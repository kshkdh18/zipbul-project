from __future__ import annotations

import hashlib
import secrets
import shlex
import shutil
import socket
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from .protocol import VERSION, read_exact


class Adb:
    def __init__(self, serial: str | None = None):
        self.executable = shutil.which("adb")
        if not self.executable:
            raise RuntimeError("adb not found; install Android platform-tools")
        listing = subprocess.check_output([self.executable, "devices"], text=True)
        ready = [
            line.split()[0]
            for line in listing.splitlines()[1:]
            if len(line.split()) >= 2 and line.split()[1] == "device"
        ]
        if serial is None:
            if len(ready) != 1:
                raise RuntimeError("Connect one authorized USB device, or specify --serial")
            serial = ready[0]
        if serial not in ready:
            raise RuntimeError(f"Device {serial} is absent or unauthorized")
        self.serial = serial

    def command(self, *args: str) -> list[str]:
        return [self.executable, "-s", self.serial, *args]

    def run(self, *args: str, timeout: float = 12) -> str:
        result = subprocess.run(self.command(*args), capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError(f"adb {' '.join(args)}: {result.stderr.strip() or result.stdout.strip()}")
        return result.stdout.strip()


class Transport:
    """Owns only its random SCID, pushed jar, host process, and adb forward."""

    def __init__(self, adb: Adb, server_path: str | None = None, guarded: bool = False):
        self.adb = adb
        self.scid = secrets.randbelow(0x7FFFFFFF)
        self.abstract = f"scrcpy_{self.scid:08x}"
        self.remote = f"/data/local/tmp/jipbul-{self.scid:08x}.jar"
        self.server_path = server_path
        self.guarded = guarded
        self.port: int | None = None
        self.process: subprocess.Popen | None = None
        self.device_pid: int | None = None
        self.remote_log = f"/data/local/tmp/jipbul-{self.scid:08x}.log"
        self.video: socket.socket | None = None
        self.control: socket.socket | None = None
        self.logs: deque[str] = deque(maxlen=100)
        self.device_name = ""
        self.server_sha256 = ""

    def start(self, max_size: int = 1280, max_fps: int = 30):
        import json

        binary = shutil.which("scrcpy")
        if not binary:
            raise RuntimeError("scrcpy 4.1 must be installed")
        version = subprocess.check_output([binary, "--version"], text=True).splitlines()[0].split()[1]
        if not self.guarded and version != VERSION:
            raise RuntimeError(f"Protocol requires scrcpy {VERSION}, installed {version}")
        candidates = (
            [Path(self.server_path)]
            if self.server_path
            else [
                Path(binary).resolve().parent.parent / "share/scrcpy/scrcpy-server",
                Path(binary).parent.parent / "share/scrcpy/scrcpy-server",
            ]
        )
        server = next((p for p in candidates if p.is_file()), None)
        if not server:
            raise RuntimeError("scrcpy-server not found; use --server-path")
        self.server_sha256 = hashlib.sha256(server.read_bytes()).hexdigest()
        server_version = VERSION
        if self.guarded:
            manifest = json.loads(server.with_name("manifest.json").read_text())
            server_version = "4.1-jipbul-guard-4"
            if (
                manifest.get("version") != server_version
                or manifest.get("protocol") != "jipbul-guard-4"
                or manifest.get("sha256") != self.server_sha256
                or manifest.get("upstream_commit") != "2926c06c5dc3064ae6d8db706f1a98a37cfcf3f0"
            ):
                raise RuntimeError("Guard server manifest/checksum mismatch; rebuild android/build.py")
        try:
            self.adb.run("push", str(server), self.remote)
            self.port = int(self.adb.run("forward", "tcp:0", f"localabstract:{self.abstract}"))
            args = [
                "shell",
                f"CLASSPATH={self.remote}",
                "app_process",
                "/",
                "com.genymobile.scrcpy.Server",
                server_version,
                f"scid={self.scid:08x}",
                "tunnel_forward=true",
                "audio=false",
                "control=true",
                "cleanup=false",
                "clipboard_autosync=false",
                "power_on=false",
                "video_codec=h264",
                f"max_size={max_size}",
                f"max_fps={max_fps}",
                "video_bit_rate=4000000",
                "log_level=info",
            ]
            if self.guarded:
                # ADB shell's process group may receive SIGHUP when USB disappears.
                # The device watchdog must survive that shell to inject the final UP.
                launch = shlex.join(["/system/bin/setsid", "/system/bin/nohup", "/system/bin/env", *args[1:]])
                launch += f" >{shlex.quote(self.remote_log)} 2>&1 </dev/null & jipbul_pid=$!; echo $jipbul_pid; wait $jipbul_pid"
                self.process = subprocess.Popen(
                    self.adb.command("shell", "sh", "-c", shlex.quote(launch)),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                import select

                if not select.select([self.process.stdout], [], [], 5)[0]:
                    raise TimeoutError("Guard launcher did not return its PID")
                self.device_pid = int(self.process.stdout.readline().strip())
                threading.Thread(target=self._read_logs, daemon=True).start()
            else:
                self.process = subprocess.Popen(
                    self.adb.command(*args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
                )
                threading.Thread(target=self._read_logs, daemon=True).start()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if self.process and self.process.poll() is not None:
                    raise RuntimeError("scrcpy server exited: " + "\n".join(self.logs))
                probe = None
                try:
                    probe = socket.create_connection(("127.0.0.1", self.port), timeout=0.5)
                    if read_exact(probe, 1) != b"\x00":
                        raise RuntimeError("Bad scrcpy handshake")
                    self.video = probe
                    break
                except (OSError, EOFError):
                    if probe:
                        probe.close()
                    time.sleep(0.1)
            if not self.video:
                if self.guarded:
                    self.logs.extend(self.adb.run("shell", "cat", self.remote_log).splitlines())
                raise RuntimeError("scrcpy handshake timeout: " + "\n".join(self.logs))
            self.control = socket.create_connection(("127.0.0.1", self.port), timeout=2)
            self.control.settimeout(0.3)
            self.video.settimeout(5)
            self.device_name = read_exact(self.video, 64).split(b"\0", 1)[0].decode("utf8", "replace")
            codec = read_exact(self.video, 4)
            if codec != b"h264":
                raise RuntimeError(f"Expected h264 codec; got {codec!r}")
            self.video.settimeout(None)
        except BaseException:
            self.close()
            raise

    def _read_logs(self):
        for line in self.process.stdout:
            self.logs.append(line.rstrip())

    def close(self):
        if self.guarded:
            try:
                self.logs.extend(self.adb.run("shell", "cat", self.remote_log, timeout=2).splitlines())
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
        for sock in (self.video, self.control):
            if sock:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()
        self.video = self.control = None
        if self.device_pid:
            try:
                # PID reuse must never let us kill another application's process.
                cmdline = self.adb.run("shell", "cat", f"/proc/{self.device_pid}/cmdline", timeout=2)
                if "com.genymobile.scrcpy.Server" in cmdline and f"scid={self.scid:08x}" in cmdline:
                    self.adb.run("shell", "kill", "-TERM", str(self.device_pid), timeout=2)
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
            self.device_pid = None
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            self.process = None
        if self.port:
            try:
                listing = self.adb.run("forward", "--list", timeout=2)
                owned = f"{self.adb.serial} tcp:{self.port} localabstract:{self.abstract}"
                if owned in listing.splitlines():
                    self.adb.run("forward", "--remove", f"tcp:{self.port}", timeout=2)
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
            self.port = None
        try:
            self.adb.run("shell", "rm", "-f", self.remote, self.remote_log, timeout=2)
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
