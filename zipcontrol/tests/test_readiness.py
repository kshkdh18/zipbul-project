import json
from types import SimpleNamespace

from zipcontrol.control import Stick
from zipcontrol.guard import GuardBridge
from zipcontrol.readiness import record


def test_diagnostic_records_are_optional_and_do_not_gate_arm(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = []
    bridge = object.__new__(GuardBridge)
    bridge.error = None
    bridge.adb = SimpleNamespace(serial="A")
    bridge.transport = SimpleNamespace(server_sha256="new-build")
    bridge.controller = SimpleNamespace(sticks=(Stick(20, 20, 5), Stick(70, 20, 5)), size=(100, 100))
    bridge.guard = SimpleNamespace(arm=lambda *args: calls.append(args) or {"width": 100, "height": 100})
    bridge.arm()
    assert len(calls) == 1 and not (tmp_path / ".runtime").exists()
    path = tmp_path / "diagnostics.json"
    record(bridge, "guard", tmp_path / "report.json", path)
    assert json.loads(path.read_text())["checks"]["guard"]
    bridge.transport.server_sha256 = "another-build"
    bridge.arm()
    assert len(calls) == 2
