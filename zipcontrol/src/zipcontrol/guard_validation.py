"""Real-device tests restricted to the marked Chrome diagnostic page."""

import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

import numpy as np

from .adb import Adb
from .astra import Astra
from .guard import GuardBridge
from .lab import TouchLab, calibrate_lab, locate_viewport
from .mission import Executor, Journal
from .validation import _wait_event, output_directory


def _error_details(exc, report, output):
    """Some exceptions (notably StopIteration and bare AssertionError) have empty str()."""
    details = str(exc).strip() or type(exc).__name__
    (output / "failure-traceback.txt").write_text(traceback.format_exc())
    return {
        "error": f"{type(exc).__name__}: {details}",
        "error_type": type(exc).__name__,
        "failed_stage": report.get("stage", "unknown"),
    }


def _wait_guard_event(guard, reason, command_id, timeout=2):
    """The control socket and HTTP telemetry can arrive in either order."""
    deadline = time.monotonic() + timeout
    with guard.condition:
        while True:
            event = next(
                (
                    e
                    for e in guard.events
                    if e.get("request_id") == 0
                    and e.get("reason") == reason
                    and e.get("command_id") == command_id
                ),
                None,
            )
            if event is not None:
                return dict(event)
            if guard.error:
                raise RuntimeError(f"Waiting for {reason} command {command_id}: {guard.error}")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(f"No Android {reason} event for command {command_id} within {timeout}s")
            guard.condition.wait(remaining)


def _wait_touch_pair(lab, after):
    second = _wait_event(lab, lambda e: e["kind"] == "down" and e["active"] == 2, after)
    page = second.get("page_id")
    first = next(
        (
            e
            for e in reversed(lab.snapshot())
            if e["kind"] == "down"
            and e.get("page_id") == page
            and e["seq"] < second["seq"]
            and e["active"] == 1
        ),
        None,
    )
    if first is None or first["id"] == second["id"]:
        raise AssertionError("Two distinct Android pointer DOWN events were not observed")
    return {"page_id": page, "ids": (first["id"], second["id"]), "seq": second["seq"]}


def _wait_pair_released(lab, pair, timeout=2):
    # Never use HTTP receipt time alone: a previous gesture's UP may be in the same batch.
    def matches(e):
        return (
            e["kind"] == "up"
            and e["active"] == 0
            and e.get("page_id") == pair["page_id"]
            and e.get("id") in pair["ids"]
            and e["seq"] > pair["seq"]
        )

    up = _wait_event(lab, matches, after=0, timeout=timeout)
    released = {
        e["id"]
        for e in lab.snapshot()
        if e["kind"] == "up"
        and e.get("page_id") == pair["page_id"]
        and pair["seq"] < e["seq"] <= up["seq"]
        and e.get("id") in pair["ids"]
    }
    if released != set(pair["ids"]):
        raise AssertionError(f"Missing UP for pointers {set(pair['ids']) - released}")
    return up


def _check_heartbeat_loss(bridge, lab, command, arm):
    arm()
    start = time.monotonic()
    ack = command((0.1, 0), (0, 0.1))
    pair = _wait_touch_pair(lab, start)
    beat = bridge.guard.heartbeat()
    release = _wait_guard_event(bridge.guard, "heartbeat_expired", ack["command_id"])
    _wait_pair_released(lab, pair)
    elapsed = release["device_time_ms"] - beat["device_time_ms"]
    if not (250 <= elapsed <= 500 and not release["armed"] and release["active"] == 0):
        raise AssertionError(
            f"Heartbeat release outside 250–500ms or still armed: elapsed={elapsed}ms, state={release}"
        )
    return {"status": "passed", "release_after_ms": elapsed, "command_id": ack["command_id"]}


def validate_guard(serial=None, server_path=None, output=None):
    output = Path(output) if output else output_directory("guard-validation")
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "scope": "Chrome diagnostic page only",
        "checks": {},
        "physical_usb_disconnect": "not tested",
        "physical_rotation": "not tested",
        "actual_flight": "not tested",
    }
    lab = bridge = None
    try:
        report["stage"] = "open_diagnostic_page"
        lab = TouchLab(Adb(serial), output).start()
        lab.open_phone()
        bridge = GuardBridge(serial, server_path).connect()
        frame, layout, transform = calibrate_lab(bridge, lab)
        report["device"] = bridge.adb.serial
        report["server_sha256"] = bridge.transport.server_sha256
        report["guard"] = bridge.guard.request("hello")

        def arm():
            locate_viewport(bridge.latest_frame(), layout)
            bridge.arm("com.android.chrome")

        def command(left, right, ttl=1000):
            locate_viewport(bridge.latest_frame(), layout)
            return bridge.set_sticks(left, right, ttl)

        def hold(seconds):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                bridge.guard.heartbeat()
                if bridge.guard.snapshot().get("expires_at_ms"):
                    bridge.guard.update()
                time.sleep(0.05)

        print("Diagnostic page verified; guarded pointer tests", flush=True)
        ox, oy, sx, sy = transform

        def check_full_radius(mode):
            full_radius = []
            for axis in range(4):
                for sign in (-1, 1):
                    arm()
                    start = time.monotonic()
                    xy = [0.0, 0.0]
                    xy[axis % 2] = float(sign)
                    selected = axis // 2
                    requested = (tuple(xy), None) if selected == 0 else (None, tuple(xy))
                    send = bridge.set_manual_sticks if mode == "manual" else bridge.set_sticks
                    ack = send(*requested, ttl_ms=500)
                    assert ack["command_mode"] == mode and ack["active"] == 1, (
                        f"{mode} command did not select one pointer: {ack}"
                    )
                    down = _wait_event(lab, lambda e: e["kind"] == "down" and e["active"] == 1, start)
                    hold(0.18)
                    px, py = bridge.controller.sticks[selected].target(xy)
                    tx, ty = (px - ox) / sx, (py - oy) / sy
                    page_id = down.get("page_id")
                    _wait_event(
                        lab,
                        lambda e, pid=down["id"], page=page_id, x=tx, y=ty: (
                            e["kind"] == "move"
                            and e.get("id") == pid
                            and e.get("page_id") == page
                            and abs(e["x"] - x) < 2
                            and abs(e["y"] - y) < 2
                            and e["active"] == 1
                        ),
                        start,
                    )
                    gesture_downs = [
                        e for e in lab.snapshot() if e["host_received_at"] >= start and e["kind"] == "down"
                    ]
                    assert len(gesture_downs) == 1, f"{mode} axis also touched the unused stick"
                    bridge.release_all()
                    _wait_pair_released(
                        lab, {"ids": (down["id"],), "seq": down["seq"], "page_id": down.get("page_id")}
                    )
                    full_radius.append(
                        {"axis": axis, "sign": sign, "target_video_px": [px, py], "observed": "passed"}
                    )
            return {"status": "passed", "directions": full_radius}

        for mode in ("manual", "ai"):
            report["stage"] = f"{mode}_full_radius_single_pointer"
            report["checks"][f"{mode}_full_radius_8_directions"] = check_full_radius(mode)

        report["stage"] = "manual_lifetime_and_ai_magnitude_limits"
        for op, duration, magnitude in (
            ("manual_command", 501, 1.0),
            ("manual_command", 500, 1.01),
            ("command", 500, 1.01),
        ):
            arm()
            try:
                bridge.guard.request(
                    op,
                    epoch=bridge.guard.status["epoch"],
                    command_id=bridge.guard.command_id + 1,
                    targets=[[magnitude, 0], None],
                    valid_for_ms=duration,
                )
                raise AssertionError(f"Out-of-bounds {op} accepted: {duration}ms, {magnitude}")
            except RuntimeError as exc:
                if not any(reason in str(exc) for reason in ("id or duration", "stick magnitude limit")):
                    raise
            assert not bridge.guard.snapshot()["armed"] and bridge.guard.snapshot()["active"] == 0, (
                "Rejected command did not disarm"
            )
        report["checks"]["manual_lifetime_and_ai_magnitude_limits"] = "passed"

        report["stage"] = "continuous_independent_contacts_3_cycles"
        for _cycle in range(3):
            arm()
            start = time.monotonic()
            command((0.15, 0), (0, -0.15))
            _wait_event(lab, lambda e: e["kind"] == "down" and e["active"] == 2, start)
            hold(0.2)
            command((-0.15, 0), (0, -0.15))
            hold(0.2)
            downs = [e for e in lab.snapshot() if e["host_received_at"] >= start and e["kind"] == "down"]
            assert len(downs) == 2 and downs[0]["id"] != downs[1]["id"], (
                "Expected two distinct pointer DOWN events"
            )
            left, right = downs[0]["id"], downs[1]["id"]
            moves = [e for e in lab.snapshot() if e["host_received_at"] >= start and e["kind"] == "move"]
            assert (
                max(e["x"] for e in moves if e["id"] == left) - min(e["x"] for e in moves if e["id"] == left)
                > 3
            ), "Left pointer did not move independently by more than 3 CSS pixels"
            before = time.monotonic()
            command(None, (0, 0.15))
            _wait_event(
                lab, lambda e, pid=left: e["kind"] == "up" and e["id"] == pid and e["active"] == 1, before
            )
            hold(0.15)
            _wait_event(
                lab, lambda e, pid=right: e["kind"] == "move" and e["id"] == pid and e["active"] == 1, before
            )
            before = time.monotonic()
            bridge.release_all()
            _wait_event(lab, lambda e: e["kind"] == "up" and e["active"] == 0, before)
        report["checks"]["continuous_independent_contacts_3_cycles"] = "passed"

        report["stage"] = "device_command_expiry_with_heartbeat"
        arm()
        start = time.monotonic()
        ack = command((1.0, 0), (0, 1.0), 200)
        pair = _wait_touch_pair(lab, start)
        hold(0.4)  # heartbeat must NOT extend the 200ms action
        release = _wait_guard_event(bridge.guard, "command_expired", ack["command_id"])
        up = _wait_pair_released(lab, pair)
        lateness = release["device_time_ms"] - ack["expires_at_ms"]
        assert 0 <= lateness <= 100, f"200ms command release lateness: {lateness}ms; expected 0–100ms"
        report["checks"]["device_command_expiry_with_heartbeat"] = {
            "status": "passed",
            "lateness_ms": lateness,
            "android_up_t": up["t"],
        }

        # The hard deadline is device-owned, including full-radius input with heartbeats/updates.
        report["stage"] = "device_two_second_expiry"
        arm()
        start = time.monotonic()
        ack = command((1.0, 0), (0, 1.0), 2000)
        pair = _wait_touch_pair(lab, start)
        hold(2.2)
        release = _wait_guard_event(bridge.guard, "command_expired", ack["command_id"])
        up = _wait_pair_released(lab, pair)
        lateness = release["device_time_ms"] - ack["expires_at_ms"]
        assert 0 <= lateness <= 100, f"2s command release lateness: {lateness}ms; expected 0–100ms"
        report["checks"]["device_two_second_expiry"] = {
            "status": "passed",
            "lateness_ms": lateness,
            "android_up_t": up["t"],
        }

        report["stage"] = "over_two_second_command_rejected"
        arm()
        start = time.monotonic()
        command((0.1, 0), (0, 0.1))
        pair = _wait_touch_pair(lab, start)
        try:
            bridge.guard.request(
                "command",
                epoch=bridge.guard.status["epoch"],
                command_id=bridge.guard.command_id + 1,
                targets=[[0.1, 0], [0, 0.1]],
                valid_for_ms=2001,
            )
            raise AssertionError("Over-two-second command accepted")
        except RuntimeError as exc:
            if "id or duration" not in str(exc):
                raise
        assert bridge.guard.snapshot()["active"] == 0 and not bridge.guard.snapshot()["armed"], (
            "Rejected duration did not disarm/release"
        )
        _wait_pair_released(lab, pair)
        report["checks"]["over_two_second_command_rejected"] = "passed"

        report["stage"] = "heartbeat_loss"
        report["checks"]["heartbeat_loss"] = _check_heartbeat_loss(bridge, lab, command, arm)

        report["stage"] = "duplicate_command_disarms"
        arm()
        start = time.monotonic()
        command((0.1, 0), (0, 0.1))
        pair = _wait_touch_pair(lab, start)
        try:
            bridge.guard.request(
                "command",
                epoch=bridge.guard.status["epoch"],
                command_id=bridge.guard.command_id,
                targets=[[0.1, 0], [0, 0.1]],
                valid_for_ms=1000,
            )
            raise AssertionError("Duplicate accepted")
        except RuntimeError as exc:
            if "id or duration" not in str(exc):
                raise
        assert bridge.guard.snapshot()["active"] == 0 and not bridge.guard.snapshot()["armed"], (
            "Duplicate command did not disarm/release"
        )
        _wait_pair_released(lab, pair)
        report["checks"]["duplicate_command_disarms"] = "passed"
        report["stage"] = "phone_home_disarms"
        arm()
        start = time.monotonic()
        command((0.1, 0), (0, 0.1))
        bridge.adb.run("shell", "input", "keyevent", "KEYCODE_HOME")
        limit = time.monotonic() + 2
        while bridge.guard.snapshot()["armed"] and time.monotonic() < limit:
            time.sleep(0.01)
        status = bridge.guard.snapshot()
        assert not status["armed"] and status["active"] == 0, f"Home did not release: {status}"
        assert status["reason"] in ("foreground_changed", "foreground_unavailable"), (
            f"Unexpected Home stop: {status}"
        )
        report["checks"]["phone_home_disarms"] = {"status": "passed", "guard_reason": status["reason"]}
        report["stage"] = "restore_diagnostic_page"
        lab.open_phone()
        calibrate_lab(bridge, lab)
        time.sleep(0.15)
        saved_sticks = bridge.controller.sticks
        # EOF closes only this test's control channel; lab and video session remain owned here.
        report["stage"] = "control_eof_releases"
        arm()
        start = time.monotonic()
        command((0.1, 0), (0, 0.1))
        pair = _wait_touch_pair(lab, start)
        bridge.transport.control.shutdown(2)
        _wait_pair_released(lab, pair)
        report["checks"]["control_eof_releases"] = "passed"
        guard_events = list(bridge.guard.events)
        bridge.close()

        # Child owns its own adb/server. SIGKILL must not rely on Python finally cleanup.
        report["stage"] = "host_SIGKILL"
        code = """import json,time,sys
from zipcontrol.guard import GuardBridge
from zipcontrol.control import Stick
b=GuardBridge(sys.argv[1],sys.argv[2]).connect()
f=b.latest_frame(); s=json.loads(sys.argv[3]); b.calibrate(Stick(**s[0]),Stick(**s[1]),f)
b.arm("com.android.chrome"); b.set_sticks((.1,0),(0,.1),1000); b.guard.heartbeat()
print(json.dumps({"state":"holding", "port":b.transport.port, "abstract":b.transport.abstract, "remote":b.transport.remote, "remote_log":b.transport.remote_log}),flush=True)
time.sleep(10)
"""
        from dataclasses import asdict

        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                code,
                bridge.adb.serial,
                str(bridge.transport.server_path),
                json.dumps([asdict(s) for s in saved_sticks]),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        owned = None
        try:
            import select

            if not select.select([child.stdout], [], [], 10)[0]:
                raise RuntimeError("Child did not reach test input")
            owned = json.loads(child.stdout.readline())
            assert owned["state"] == "holding", f"Child not holding: {owned}"
            start = time.monotonic()
            child.kill()
            child.wait(timeout=3)
            up = _wait_event(lab, lambda e: e["kind"] == "up" and e["active"] == 0, start)
            assert up["host_received_at"] - start <= 0.5, (
                f"SIGKILL release exceeded 500ms: {up['host_received_at'] - start}s"
            )
            report["checks"]["host_SIGKILL"] = {
                "status": "passed",
                "host_observed_release_ms": (up["host_received_at"] - start) * 1000,
            }
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            if owned:
                # SIGKILL skips the child's Python cleanup; remove only its reported session.
                listing = bridge.adb.run("forward", "--list")
                expected = f"{bridge.adb.serial} tcp:{owned['port']} localabstract:{owned['abstract']}"
                if expected in listing.splitlines():
                    bridge.adb.run("forward", "--remove", f"tcp:{owned['port']}")
                bridge.adb.run("shell", "rm", "-f", owned["remote"], owned["remote_log"])
        report["stage"] = "reconnect_no_replay"
        bridge = GuardBridge(serial, server_path).connect()
        assert not bridge.guard.snapshot()["armed"] and bridge.guard.snapshot()["active"] == 0, (
            "Reconnected server armed or touching"
        )
        report["checks"]["reconnect_no_replay"] = "passed"
        first = bridge.latest_frame()
        time.sleep(2)
        last = bridge.latest_frame()
        report["fps"] = (last.sequence - first.sequence) / (last.decoded_at - first.decoded_at)
        report.update(status="passed", stage="complete")
    except Exception as exc:
        report.update(status="failed", **_error_details(exc, report, output))
        if lab:
            report["diagnostic_page"] = lab.diagnostics()
        if bridge and bridge.latest_frame():
            from PIL import Image

            Image.fromarray(bridge.latest_frame().rgb).save(output / "failure.png")
    finally:
        if bridge:
            events = locals().get("guard_events", []) + (bridge.guard.events if bridge.guard else [])
            (output / "guard-events.json").write_text(json.dumps(events, indent=2))
            bridge.close()
            report["server_logs"] = list(bridge.transport.logs)
        if lab:
            lab.close()
        (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
    if report.get("status") == "passed":
        from .readiness import record

        record(bridge, "guard", output / "report.json")
    return report


def benchmark_astra(serial=None, server_path=None, output=None, count=20):
    output = Path(output) if output else output_directory("astra-benchmark")
    journal = Journal(output)
    provider = Astra()
    results = []
    try:
        with GuardBridge(serial, server_path) as bridge:
            from .camera import CameraStore, camera_rect

            frame = bridge.latest_frame()
            roi = CameraStore().load(bridge.adb.serial, frame.width, frame.height)
            camera_rect(roi, frame.width, frame.height)
            executor = Executor(bridge, False, None, journal, camera_roi=roi)
            executor.running = True
            executor.epoch = bridge.latest_frame().epoch
            previous = None
            for i in range(count):
                obs = executor.observe(
                    "Describe a useful next handheld camera viewpoint from this camera image."
                )
                journal.observation(obs)
                started = time.monotonic()
                try:
                    decision = provider.decide(obs, previous)
                    result = {
                        "sample": i + 1,
                        "status": "valid",
                        "name": decision.name,
                        "latency_ms": decision.latency * 1000,
                        "usage": decision.usage,
                        "reason": decision.arguments.get("reason", ""),
                    }
                except Exception as exc:
                    result = {
                        "sample": i + 1,
                        "status": "error",
                        "latency_ms": (time.monotonic() - started) * 1000,
                        "error": str(exc),
                    }
                results.append(result)
                journal.event("benchmark", **result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
                previous = obs
                if result["status"] == "error" and any(
                    s in result["error"] for s in ("HTTP 401", "HTTP 403", "HTTP 404")
                ):
                    break
            assert not bridge.guard.snapshot()["armed"] and not bridge.guard.snapshot()["active"]
    finally:
        provider.close()
    latencies = [r["latency_ms"] for r in results if r["status"] == "valid"]
    report = {
        "requested": count,
        "status": "passed" if len(results) == count and len(latencies) == count else "incomplete",
        "samples": results,
        "mode": "observation_only_camera_crop",
        "valid_fraction": len(latencies) / max(1, len(results)),
        "touches_sent": 0,
        "p50_ms": float(np.percentile(latencies, 50)) if latencies else None,
        "p95_ms": float(np.percentile(latencies, 95)) if latencies else None,
        "under_1s_fraction": sum(x <= 1000 for x in latencies) / max(1, len(latencies)),
        "stale_discard_fraction": None,
        "stale_discard_note": "not measurable without motion; covered by executor tests",
        "actual_flight": "not tested",
    }
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def validate_usb(serial=None, server_path=None, output=None):
    """Operator unplugs/replugs; offline browser events are replayed after ADB reverse recovery."""
    output = Path(output) if output else output_directory("physical-usb")
    output.mkdir(parents=True, exist_ok=True)
    report = {"scope": "Chrome diagnostic page only", "status": "waiting", "actual_flight": "not tested"}
    bridge = lab = None
    try:
        report["stage"] = "open_diagnostic_page"
        lab = TouchLab(Adb(serial), output).start()
        lab.open_phone()
        bridge = GuardBridge(serial, server_path).connect()
        _, layout, _ = calibrate_lab(bridge, lab)
        report["stage"] = "wait_for_physical_disconnect"
        bridge.arm("com.android.chrome")
        began = time.monotonic()
        bridge.set_sticks((1.0, 0), (0, 1.0), 2000)
        report["command_mode"] = "ai"
        report["command_lease_ms"] = 2000
        _wait_event(lab, lambda e: e["kind"] == "down" and e["active"] == 2, began)
        last_command = time.monotonic()
        direction = 1
        print(
            "READY: Chrome Touch Lab에서 2 TOUCHES를 확인하고 USB를 뽑은 뒤 2초 후 다시 연결하세요. 60초 대기합니다.",
            flush=True,
        )
        disconnected = False
        while time.monotonic() - began < 60:
            try:
                locate_viewport(bridge.latest_frame(), layout)
                if time.monotonic() - last_command >= 0.1:
                    direction *= -1
                    bridge.set_sticks((direction, 0), (0, direction), 2000)
                    last_command = time.monotonic()
                bridge.guard.heartbeat()
                bridge.guard.update()
                time.sleep(0.05)
            except (RuntimeError, OSError, EOFError, TimeoutError):
                devices = subprocess.check_output([bridge.adb.executable, "devices"], text=True)
                if not any(
                    line.split()[:2] == [bridge.adb.serial, "device"] for line in devices.splitlines()
                ):
                    disconnected = True
                    break
                raise
        if not disconnected:
            raise TimeoutError("Physical USB removal not observed; test not completed")
        print("USB 분리 확인. 다시 연결을 기다립니다…", flush=True)
        report["stage"] = "wait_for_reconnect"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            devices = subprocess.check_output([bridge.adb.executable, "devices"], text=True)
            if any(line.split()[:2] == [bridge.adb.serial, "device"] for line in devices.splitlines()):
                break
            time.sleep(0.2)
        else:
            raise TimeoutError("USB did not reconnect")
        report["stage"] = "recover_offline_events"
        lab.ensure_reverse()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            events = [
                e
                for e in lab.snapshot()
                if e["host_received_at"] >= began and e["kind"] in ("down", "move", "up", "cancel")
            ]
            if events and events[-1]["kind"] in ("up", "cancel") and events[-1]["active"] == 0:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("No offline Android release event recovered")
        final = events[-1]
        # Release injects centered MOVE immediately before UP; exclude these center events.
        motion = [e for e in events if e["kind"] == "move" and e["active"] == 2]
        # Two centered moves precede the first UP. The earlier move reflects held input.
        before_release = [e for e in motion if e["t"] < final["t"] - 5]
        if not before_release:
            raise AssertionError("Insufficient pre-disconnect movement evidence")
        gap = final["t"] - before_release[-1]["t"]
        report["phone_pointer_release_gap_ms"] = gap
        if not 0 <= gap <= 500:
            raise AssertionError(f"Pointer release observed, but timing bound failed: {gap:.1f}ms")
        report.update(
            status="passed",
            phone_pointer_release_gap_ms=gap,
            offline_final_event=final,
            timing_definition="Browser monotonic time from last non-release MOVE to final UP; conservative heartbeat-loss proxy",
        )
        bridge.close()
        bridge = GuardBridge(serial, server_path).connect()
        assert not bridge.guard.snapshot()["armed"] and bridge.guard.snapshot()["active"] == 0, (
            "USB reconnect replayed input or stayed armed"
        )
        report["reconnect_no_replay"] = "passed"
        report["stage"] = "complete"
    except Exception as exc:
        report.update(status="incomplete", **_error_details(exc, report, output))
        if lab:
            report["diagnostic_page"] = lab.diagnostics()
    finally:
        if bridge:
            bridge.close()
            report["server_logs"] = list(bridge.transport.logs)
        if lab:
            lab.close()
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if report.get("status") == "passed":
        from .readiness import record

        record(bridge, "physical_usb", output / "report.json")
    return report
