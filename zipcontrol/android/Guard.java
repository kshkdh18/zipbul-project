package com.genymobile.scrcpy.control;

import android.content.ComponentName;
import android.os.IBinder;
import android.os.SystemClock;
import android.view.MotionEvent;
import com.genymobile.scrcpy.model.Position;
import org.json.JSONArray;
import org.json.JSONObject;
import java.lang.reflect.Method;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/** Device-side owner of both fingers. Network reads never own the expiry timer. */
public final class Guard {
    public static final String PROTOCOL = "jipbul-guard-4";
    private final Controller controller;
    private final DeviceMessageSender sender;
    private final ScheduledExecutorService timer = Executors.newSingleThreadScheduledExecutor();
    private final ScheduledExecutorService monitor = Executors.newSingleThreadScheduledExecutor();
    private volatile String foreground = "";
    private volatile String monitorError = "starting";
    private volatile boolean locked = true;
    private volatile long monitorAt;
    private boolean armed;
    private boolean closed;
    private long epoch;
    private long commandId;
    private String commandMode = "none";
    private long expires;
    private long heartbeat;
    private int width, height;
    private String allowed = "";
    private String reason = "disarmed";
    private boolean injectionOk = true;
    private final boolean[] active = new boolean[2];
    private double[][] sticks;
    private double[][] origin = new double[][] {new double[2], new double[2]};
    private double[][] target = new double[][] {new double[2], new double[2]};
    private double[][] current = new double[][] {new double[2], new double[2]};
    private long changedAt;

    Guard(Controller controller, DeviceMessageSender sender) {
        this.controller = controller;
        this.sender = sender;
        monitor.scheduleWithFixedDelay(this::pollForeground, 0, 100, TimeUnit.MILLISECONDS);
        timer.scheduleAtFixedRate(this::tick, 0, 10, TimeUnit.MILLISECONDS);
    }

    private static Object service(String name, String type) throws Exception {
        Object binder = Class.forName("android.os.ServiceManager").getMethod("getService", String.class).invoke(null, name);
        return Class.forName(type + "$Stub").getMethod("asInterface", IBinder.class).invoke(null, binder);
    }

    private void pollForeground() {
        try {
            Object tasks = service("activity_task", "android.app.IActivityTaskManager");
            Object task = tasks.getClass().getMethod("getFocusedRootTaskInfo").invoke(tasks);
            ComponentName top = (ComponentName) task.getClass().getField("topActivity").get(task);
            Object windows = service("window", "android.view.IWindowManager");
            Method isLocked = windows.getClass().getMethod("isKeyguardLocked");
            boolean newLocked = (boolean) isLocked.invoke(windows);
            String newForeground = top == null ? "" : top.getPackageName();
            synchronized (this) {
                foreground = newForeground;
                locked = newLocked;
                monitorError = "";
                monitorAt = SystemClock.uptimeMillis();
                if (armed && !permitted()) stop("foreground_changed", true);
            }
        } catch (Throwable exc) {
            monitorError = exc.getClass().getSimpleName();
            synchronized (this) { if (armed) stop("monitor_failed", true); }
        }
    }

    private boolean permitted() {
        return monitorError.isEmpty() && !locked && !allowed.isEmpty() && allowed.equals(foreground)
            && SystemClock.uptimeMillis() - monitorAt <= 300;
    }

    synchronized void geometry(int w, int h) {
        stop("geometry_changed", true); // old mapper still installed, so old contacts can be released
        width = w;
        height = h;
        epoch++;
        sticks = null;
    }

    private boolean inject(int side, int action, double x, double y) {
        boolean ok = controller.injectGuardTouch(action, side + 1,
            new Position((int) Math.round(x), (int) Math.round(y), width, height),
            action == MotionEvent.ACTION_UP ? 0 : 1);
        injectionOk &= ok;
        return ok;
    }

    private void release(int side) {
        if (active[side] && sticks != null) {
            // Always attempt UP even if centering fails.
            try { inject(side, MotionEvent.ACTION_MOVE, sticks[side][0], sticks[side][1]); }
            finally { inject(side, MotionEvent.ACTION_UP, sticks[side][0], sticks[side][1]); }
        }
        active[side] = false;
        current[side] = new double[2];
    }

    private void stop(String why, boolean disarm) {
        try { release(0); } finally { release(1); }
        expires = 0;
        if (disarm) armed = false;
        reason = why;
        emit(0, true, why);
    }

    private synchronized void tick() {
        if (closed || !armed) return;
        try {
            long now = SystemClock.uptimeMillis();
            if (!permitted()) { stop("foreground_unavailable", true); return; }
            if (now - heartbeat >= 300) { stop("heartbeat_expired", true); return; }
            if (expires != 0 && now >= expires) { stop("command_expired", false); return; }
        } catch (Throwable exc) {
            armed = false;
            reason = "injection_failed";
            injectionOk = false;
            try { stop(reason, true); } catch (Throwable ignored) { }
        }
    }

    private void update() {
        long now = SystemClock.uptimeMillis();
        double blend = Math.min(1, (now - changedAt) / 100.0);
        for (int i = 0; i < 2; i++) {
            if (target[i] == null) { release(i); continue; }
            if (!active[i]) {
                // Track attempted DOWN too, so failed injection still receives an UP attempt.
                active[i] = true;
                if (!inject(i, MotionEvent.ACTION_DOWN, sticks[i][0], sticks[i][1])) throw new IllegalStateException("DOWN failed");
            }
            current[i] = new double[] {origin[i][0] + (target[i][0] - origin[i][0]) * blend,
                origin[i][1] + (target[i][1] - origin[i][1]) * blend};
            if (!inject(i, MotionEvent.ACTION_MOVE, sticks[i][0] + current[i][0] * sticks[i][2],
                sticks[i][1] + current[i][1] * sticks[i][2])) throw new IllegalStateException("MOVE failed");
        }
    }

    private static double number(JSONArray a, int i) throws Exception {
        Object value = a.get(i);
        if (!(value instanceof Number)) throw new IllegalArgumentException("number required");
        double n = ((Number) value).doubleValue();
        if (Double.isNaN(n) || Double.isInfinite(n)) throw new IllegalArgumentException("finite required");
        return n;
    }

    private static long integer(JSONObject o, String key) throws Exception {
        Object value = o.get(key);
        if (!(value instanceof Integer || value instanceof Long)) throw new IllegalArgumentException("integer required");
        return ((Number) value).longValue();
    }

    synchronized void accept(String text) {
        long request = 0;
        try {
            JSONObject o = new JSONObject(text);
            request = integer(o, "request_id");
            String op = o.getString("op");
            tick(); // expiry wins over a late command or heartbeat
            if (op.equals("hello")) { emit(request, true, "hello"); return; }
            if (op.equals("stop") || op.equals("release")) {
                stop(op, op.equals("stop")); emit(request, injectionOk, op); return;
            }
            if (closed) throw new IllegalStateException("closed");
            if (op.equals("arm")) {
                stop("rearm", true);
                if (!injectionOk) throw new IllegalStateException("previous injection failed; reconnect and verify physical touch state");
                if (integer(o, "epoch") != epoch || width == 0) throw new IllegalArgumentException("geometry mismatch");
                allowed = o.getString("package");
                if (!(allowed.equals("dji.go.v5") || allowed.equals("com.android.chrome"))) throw new IllegalArgumentException("package");
                if (!permitted()) throw new IllegalStateException("foreground monitor unavailable or wrong app");
                JSONArray cal = o.getJSONArray("sticks");
                if (cal.length() != 2) throw new IllegalArgumentException("two sticks required");
                double[][] next = new double[2][3];
                for (int i = 0; i < 2; i++) {
                    JSONArray s = cal.getJSONArray(i);
                    if (s.length() != 3) throw new IllegalArgumentException("calibration");
                    for (int j = 0; j < 3; j++) next[i][j] = number(s, j);
                    double x = next[i][0], y = next[i][1], r = next[i][2];
                    if (r < 2 || x-r < 0 || y-r < 0 || x+r >= width || y+r >= height) throw new IllegalArgumentException("bounds");
                }
                sticks = next;
                heartbeat = SystemClock.uptimeMillis();
                injectionOk = true;
                armed = true;
                reason = "armed";
            } else {
                if (!armed || !permitted()) throw new IllegalStateException("not armed");
                if (integer(o, "epoch") != epoch) throw new IllegalArgumentException("stale epoch");
                if (op.equals("heartbeat")) {
                    heartbeat = SystemClock.uptimeMillis(); // never changes expires
                } else if (op.equals("command") || op.equals("manual_command")) {
                    boolean manual = op.equals("manual_command");
                    long id = integer(o, "command_id"), duration = integer(o, "valid_for_ms");
                    if (id <= commandId || duration < 100 || duration > (manual ? 500 : 2000)) throw new IllegalArgumentException("id or duration");
                    JSONArray values = o.getJSONArray("targets");
                    if (values.length() != 2) throw new IllegalArgumentException("targets");
                    double[][] next = new double[2][];
                    for (int i = 0; i < 2; i++) {
                        if (values.isNull(i)) continue;
                        JSONArray a = values.getJSONArray(i);
                        if (a.length() != 2) throw new IllegalArgumentException("xy");
                        next[i] = new double[] {number(a, 0), number(a, 1)};
                        if (Math.hypot(next[i][0], next[i][1]) > 1.0000001) throw new IllegalArgumentException("stick magnitude limit");
                    }
                    commandId = id;
                    commandMode = manual ? "manual" : "ai";
                    origin = new double[][] {current[0].clone(), current[1].clone()};
                    target = next;
                    changedAt = SystemClock.uptimeMillis();
                    expires = changedAt + duration;
                    reason = "command";
                    update();
                } else if (op.equals("update")) {
                    if (integer(o, "command_id") != commandId) throw new IllegalArgumentException("stale update");
                    if (expires != 0) update(); // expiry is an ordinary result, never a renewal
                } else throw new IllegalArgumentException("unknown operation");
            }
            emit(request, injectionOk, reason);
        } catch (Throwable exc) {
            try { stop("rejected", true); } catch (Throwable ignored) { injectionOk = false; }
            emit(request, false, exc.getMessage() == null ? exc.getClass().getSimpleName() : exc.getMessage());
        }
    }

    synchronized void close() {
        if (closed) return;
        stop("closed", true);
        closed = true;
        timer.shutdownNow();
        monitor.shutdownNow();
    }

    private void emit(long request, boolean ok, String message) {
        try {
            JSONObject status = new JSONObject();
            status.put("protocol", PROTOCOL).put("request_id", request).put("ok", ok)
                .put("reason", message).put("armed", armed).put("epoch", epoch)
                .put("width", width).put("height", height).put("active", (active[0]?1:0)+(active[1]?1:0))
                .put("command_id", commandId).put("command_mode", commandMode).put("expires_at_ms", expires)
                .put("device_time_ms", SystemClock.uptimeMillis()).put("injection_ok", injectionOk)
                .put("foreground", foreground).put("locked", locked).put("monitor_error", monitorError)
                .put("monitor_age_ms", SystemClock.uptimeMillis() - monitorAt);
            sender.send(DeviceMessage.createGuard(status.toString()));
        } catch (Exception ignored) { }
    }
}
