from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from .bridge import Bridge
from .lab import LabNotVisible, TouchLab, calibrate_lab, locate_viewport


def output_directory(prefix="validation"):
    return Path("artifacts") / f"{prefix}-{datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')}"


def _wait_event(lab, predicate, after, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events = [e for e in lab.snapshot() if e["host_received_at"] >= after]
        found = next((e for e in events if predicate(e)), None)
        if found:
            return found
        time.sleep(0.01)
    raise AssertionError("Expected Android pointer event was not received")


def run_validation(serial=None, server_path=None, output=None):
    output = Path(output) if output else output_directory()
    output.mkdir(parents=True, exist_ok=True)
    result = {
        "scope": "diagnostic page only; no drone control",
        "checks": {},
        "dji_app": "not tested",
        "physical_usb_disconnect": "not tested",
        "physical_rotation_fold": "not tested",
        "output": str(output.resolve()),
    }
    bridge, lab = None, None
    try:
        bridge = Bridge(serial, server_path).connect()
        result["device"] = bridge.transport.device_name
        result["scrcpy_server_sha256"] = bridge.transport.server_sha256
        lab = TouchLab(bridge.adb, output).start()
        lab.open_phone()
        frame, layout, transform = calibrate_lab(bridge, lab)
        result["frame_size"] = [frame.width, frame.height]
        result["viewport_transform"] = transform
        Image.fromarray(frame.rgb).save(output / "test-ready.png")
        print("Diagnostic page verified; starting dual-touch tests", flush=True)

        def test_input(left, right, ttl_ms=500):
            current = bridge.latest_frame()
            if current is None or time.monotonic() - current.received_at > 1:
                raise LabNotVisible("Diagnostic video is stale; refusing new input")
            try:
                locate_viewport(current, layout)
            except ValueError as exc:
                raise LabNotVisible("Diagnostic page left the screen; refusing new input") from exc
            bridge.set_sticks(left, right, ttl_ms)

        # Real Android/browser observations, not assertions against local send state.
        for _repetition in range(3):
            start = time.monotonic()
            test_input((-0.35, -0.3), (0.35, 0.3), ttl_ms=1000)
            e = _wait_event(lab, lambda e: e["kind"] == "down" and e["active"] == 2, start)
            assert e.get("pointerType") == "touch"
            time.sleep(0.1)
            downs = [e for e in lab.snapshot() if e["host_received_at"] >= start and e["kind"] == "down"]
            assert len(downs) == 2 and downs[0]["id"] != downs[1]["id"]
            left_id, right_id = downs[0]["id"], downs[1]["id"]
            start_move = time.monotonic()
            test_input((-0.35, 0.4), (0.35, 0.3), ttl_ms=1000)
            left = _wait_event(
                lab, lambda e, pid=left_id: e["kind"] == "move" and e.get("id") == pid, start_move
            )
            assert left["active"] == 2
            start_release = time.monotonic()
            test_input(None, (-0.3, -0.3), ttl_ms=1000)
            _wait_event(
                lab,
                lambda e, pid=left_id: e["kind"] == "up" and e.get("id") == pid and e["active"] == 1,
                start_release,
            )
            _wait_event(
                lab,
                lambda e, pid=right_id: e["kind"] == "move" and e.get("id") == pid and e["active"] == 1,
                start_release,
            )
            done = time.monotonic()
            bridge.release_all()
            _wait_event(lab, lambda e: e["kind"] == "up" and e["active"] == 0, done)
        result["checks"]["dual_touch_independent_move_release_3_cycles"] = "passed"

        start = time.monotonic()
        test_input((0.2, 0), (-0.2, 0), ttl_ms=200)
        _wait_event(lab, lambda e: e["kind"] == "up" and e["active"] == 0, start)
        assert not bridge.controller.active
        result["checks"]["command_expiry"] = "passed"

        # The top bar changes color on real pointer events. Timing uses ONLY Mac monotonic clocks.
        ox, oy, sx, sy = transform
        px, py = round(ox + layout["width"] * 0.5 * sx), round(oy + 36 * sy)
        latencies = []
        colors = {0: np.array([38, 54, 72]), 3: np.array([246, 185, 64])}
        for i in range(12):
            target = 3 if i % 2 == 0 else 0
            before = bridge.latest_frame().sequence
            started = time.monotonic()
            if target:
                test_input((0.25, 0), (-0.25, 0), ttl_ms=1500)
            else:
                bridge.release_all()
            while time.monotonic() - started < 1.2:
                frame = bridge.wait_frame(after=before, timeout=1.2)
                before = frame.sequence
                pixel = frame.rgb[py - 3 : py + 4, px - 3 : px + 4].mean(axis=(0, 1))
                if np.max(np.abs(pixel - colors[target])) < 35:
                    latencies.append((time.monotonic() - started) * 1000)
                    break
            else:
                raise AssertionError("Touch-to-video marker timeout")
            time.sleep(0.06)
        bridge.release_all()
        result["touch_to_decoded_video_ms"] = {
            "samples": latencies,
            "p50": float(np.percentile(latencies, 50)),
            "p95": float(np.percentile(latencies, 95)),
            "definition": "Mac command send to Android pointer marker seen in decoded video; excludes drone camera latency",
        }
        result["checks"]["touch_to_video_marker_12_samples"] = "passed"
        first = bridge.wait_frame()
        time.sleep(3)
        last = bridge.latest_frame()
        result["animated_page_fps"] = (last.sequence - first.sequence) / (last.decoded_at - first.decoded_at)
        result["checks"]["live_video"] = "passed"
        Image.fromarray(last.rgb).save(output / "test-finished.png")

        # Graceful process cleanup must be observed on Android before the transport closes.
        start = time.monotonic()
        test_input((0.1, 0), (-0.1, 0), ttl_ms=1500)
        _wait_event(lab, lambda e: e["kind"] == "down" and e["active"] == 2, start)
        start = time.monotonic()
        bridge.close()
        _wait_event(lab, lambda e: e["kind"] == "up" and e["active"] == 0, start)
        result["checks"]["graceful_close_releases_touches"] = "passed"

        # Deliberately close our video socket, not USB or someone else's adb session.
        bridge = Bridge(serial, server_path).connect()
        calibrate_lab(bridge, lab)
        bridge.transport.video.shutdown(2)
        deadline = time.monotonic() + 2
        while not bridge.error and time.monotonic() < deadline:
            time.sleep(0.01)
        assert bridge.error
        try:
            bridge.set_sticks((0.2, 0), (0, 0))
        except RuntimeError:
            pass
        else:
            raise AssertionError("Input accepted after stream failure")
        bridge.close()
        result["checks"]["video_socket_failure_blocks_input"] = "passed"
        bridge = Bridge(serial, server_path).connect()
        assert bridge.controller.sticks is None and not bridge.controller.active
        start = time.monotonic()
        time.sleep(0.7)
        assert not any(e["kind"] == "down" for e in lab.snapshot() if e["host_received_at"] >= start)
        result["checks"]["reconnect_no_command_replay"] = "passed"
        result["status"] = "passed"
    except BaseException as exc:
        result["status"] = "blocked" if isinstance(exc, LabNotVisible) else "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        if bridge:
            result["server_log"] = list(bridge.transport.logs)
            current = bridge.latest_frame()
            if current:
                Image.fromarray(current.rgb).save(output / "last-frame.png")
        raise
    finally:
        if bridge:
            bridge.close()
        if lab:
            result["event_count"] = len(lab.snapshot())
            lab.close()
        (output / "report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
    return result
