from __future__ import annotations

import json
import secrets
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

from .adb import Adb
from .control import Stick


class LabNotVisible(TimeoutError):
    """User must make the diagnostic page visible before a hardware test can run."""


class TouchLab:
    """Loopback-only diagnostic page. Accepts event telemetry, never control commands."""

    def __init__(self, adb: Adb, output: Path | None = None):
        self.adb, self.output = adb, output
        self.token = secrets.token_urlsafe(24)
        self.events = deque(maxlen=20000)
        self.lock = threading.Lock()
        self.layout = None
        self.server = None
        self.phone_port = None
        self._log = None
        self.expected_load = None
        self.page_requests = 0
        self.launch_attempts = 0
        self.reverse_repairs = 0
        self.setup_error = None

    def start(self):
        owner = self
        html = files("zipcontrol").joinpath("touch_test.html").read_bytes()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def authorized(self):
                return parse_qs(urlparse(self.path).query).get("token") == [owner.token]

            def do_GET(self):
                if not self.authorized() or urlparse(self.path).path != "/touch-test":
                    self.send_error(404)
                    return
                with owner.lock:
                    load = parse_qs(urlparse(self.path).query).get("load", [None])[0]
                    if owner.expected_load is None or load == owner.expected_load:
                        owner.page_requests += 1
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(html)

            def do_POST(self):
                if not self.authorized() or urlparse(self.path).path != "/events":
                    self.send_error(403)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 256_000:
                        raise ValueError("Bad length")
                    events = json.loads(self.rfile.read(length))
                    if not isinstance(events, list) or len(events) > 500:
                        raise ValueError("Bad batch")
                    with owner.lock:
                        for event in events:
                            if not isinstance(event, dict):
                                raise ValueError("Bad event")
                            if (
                                owner.expected_load is not None
                                and event.get("load_id") != owner.expected_load
                            ):
                                continue  # An old tab's delayed batch cannot ready a new diagnostic session.
                            event["host_received_at"] = time.monotonic()
                            owner.events.append(event)
                            if event.get("kind") in ("ready", "status"):
                                owner.layout = event
                            if owner._log:
                                owner._log.write(json.dumps(event) + "\n")
                        if owner._log:
                            owner._log.flush()
                except (ValueError, TypeError, KeyError):
                    self.send_error(400)
                    return
                self.send_response(204)
                self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        if self.output:
            self.output.mkdir(parents=True, exist_ok=True)
            self._log = (self.output / "touch-events.jsonl").open("w")
        threading.Thread(target=self.server.serve_forever, name="touch-lab", daemon=True).start()
        try:
            self.phone_port = int(
                self.adb.run("reverse", "--no-rebind", "tcp:0", f"tcp:{self.server.server_port}")
            )
            self.ensure_reverse()
        except BaseException:
            self.close()
            raise
        return self

    def ensure_reverse(self):
        """Repair a missing own mapping; never replace a mapping owned by another session."""
        expected = [f"tcp:{self.phone_port}", f"tcp:{self.server.server_port}"]
        listing = self.adb.run("reverse", "--list", timeout=2)
        pairs = [line.split()[-2:] for line in listing.splitlines()]
        if expected in pairs:
            return
        if any(pair and pair[0] == expected[0] for pair in pairs):
            raise RuntimeError(
                f"Diagnostic port {expected[0]} is bound to another destination; not replacing it"
            )
        self.adb.run("reverse", "--no-rebind", *expected, timeout=2)
        self.reverse_repairs += 1
        listing = self.adb.run("reverse", "--list", timeout=2)
        if not any(line.split()[-2:] == expected for line in listing.splitlines()):
            raise RuntimeError("Diagnostic ADB reverse mapping disappeared during setup")

    def open_phone(self, timeout=20):
        with self.lock:
            self.layout = None
            self.expected_load = secrets.token_hex(6)
            self.page_requests = 0
            self.launch_attempts = 0
            self.setup_error = None
        deadline = time.monotonic() + timeout
        url = f"http://127.0.0.1:{self.phone_port}/touch-test?token={self.token}&load={self.expected_load}"
        time.sleep(0.3)
        # ADB reverse can be installed before the first Chrome navigation succeeds.
        # Retry only our diagnostic URL, and require an actual browser ready event.
        # The attempt query avoids Chrome retaining a failed cached navigation.
        for attempt in range(3):
            self.launch_attempts += 1
            try:
                self.ensure_reverse()
                self.adb.run(
                    "shell",
                    "am",
                    "start",
                    "--user",
                    "0",
                    "-a",
                    "android.intent.action.VIEW",
                    "-d",
                    f"'{url}&attempt={attempt}'",
                    "com.android.chrome",
                    timeout=max(0.1, min(6, deadline - time.monotonic())),
                )
                self.setup_error = None
            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                # A launch command can report failure even though Chrome handles the URL.
                # Only the matching page's telemetry confirms success.
                self.setup_error = str(exc)
            try:
                remaining = max(0.01, deadline - time.monotonic())
                self.wait_ready(timeout=remaining if attempt == 2 else min(4, remaining))
                time.sleep(0.3)
                return
            except LabNotVisible:
                if attempt == 2 or time.monotonic() >= deadline:
                    detail = (
                        "Chrome did not request this session's URL"
                        if self.page_requests == 0
                        else "Page requested, but matching ready telemetry was not received"
                    )
                    if self.setup_error:
                        detail += "; ADB setup error: " + self.setup_error
                    raise LabNotVisible(
                        f"{detail}; unlock the phone and retry. Old tabs do not count (RUN {self.expected_load[:6]})"
                    ) from None

    def diagnostics(self):
        with self.lock:
            result = {
                "run": self.expected_load,
                "launch_attempts": self.launch_attempts,
                "page_requests": self.page_requests,
                "ready_received": self.layout is not None,
                "events_received": len(self.events),
                "reverse_repairs": self.reverse_repairs,
            }
            if self.setup_error:
                result["setup_error"] = self.setup_error
        try:
            listing = self.adb.run("reverse", "--list", timeout=2)
            expected = [f"tcp:{self.phone_port}", f"tcp:{self.server.server_port}"]
            result["reverse_mapping_present"] = any(
                line.split()[-2:] == expected for line in listing.splitlines()
            )
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            result["reverse_error"] = str(exc)
        return result

    def snapshot(self):
        with self.lock:
            return list(self.events)

    def wait_ready(self, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if self.layout:
                    return dict(self.layout)
            time.sleep(0.05)
        raise LabNotVisible("Touch test page not ready; unlock phone and open Chrome")

    def close(self):
        if self.phone_port:
            try:
                listing = self.adb.run("reverse", "--list", timeout=2)
                pair = [f"tcp:{self.phone_port}", f"tcp:{self.server.server_port}"]
                if any(line.split()[-2:] == pair for line in listing.splitlines()):
                    self.adb.run("reverse", "--remove", f"tcp:{self.phone_port}", timeout=2)
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
            self.phone_port = None
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        with self.lock:
            if self._log:
                self._log.close()
                self._log = None


def locate_viewport(frame, layout):
    """Locate all four diagnostic markers; never infer DJI controls from these pixels."""
    rgb = frame.rgb
    mask = (rgb[:, :, 0] > 190) & (rgb[:, :, 1] < 75) & (rgb[:, :, 2] > 190)
    ys, xs = np.where(mask)
    if len(xs) < 80:
        raise ValueError("Diagnostic fiducials not visible")
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    if x1 - x0 < frame.width * 0.5 or y1 - y0 < frame.height * 0.4:
        raise ValueError("Incomplete diagnostic fiducials")
    for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
        if np.count_nonzero(mask[max(0, y - 15) : y + 16, max(0, x - 15) : x + 16]) < 15:
            raise ValueError("Missing corner marker")
    sx = (x1 - x0 + 1) / (layout["width"] - 24)
    sy = (y1 - y0 + 1) / (layout["height"] - 24)
    return float(x0 - 12 * sx), float(y0 - 12 * sy), float(sx), float(sy)


def calibrate_lab(bridge, lab, timeout=10):
    layout = lab.wait_ready(timeout)
    deadline = time.monotonic() + timeout
    sequence = 0
    while time.monotonic() < deadline:
        try:
            frame = bridge.wait_frame(after=sequence, timeout=min(2, max(0.01, deadline - time.monotonic())))
        except TimeoutError:
            continue
        sequence = frame.sequence
        try:
            transform = locate_viewport(frame, layout)
        except ValueError:
            continue
        ox, oy, sx, sy = transform
        radius = layout["radius"] * min(sx, sy)
        sticks = [Stick(ox + x * sx, oy + y * sy, radius) for x, y in (layout["left"], layout["right"])]
        bridge.calibrate(*sticks, frame)
        return frame, layout, transform
    raise LabNotVisible(
        "Diagnostic page is not visible. Unlock the phone and open Touch Lab; no touch was sent"
    )
