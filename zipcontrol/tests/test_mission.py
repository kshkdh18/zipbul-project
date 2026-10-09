import json
import threading
import time
from dataclasses import asdict
from types import SimpleNamespace

import numpy as np
import pytest

from zipcontrol.astra import Astra, Decision, parse_decision
from zipcontrol.bridge import Frame
from zipcontrol.control import Stick
from zipcontrol.flight_profile import DEFAULT_AXES, FlightProfile, FlightProfileStore, anchor
from zipcontrol.guard import targets
from zipcontrol.mission import Executor, Journal, Mission


class Rig:
    def __init__(self):
        self.now = 100.0
        self.sequence = 1
        self.epoch = 1
        self.error = None
        self.transport = SimpleNamespace(server_sha256="fake")
        self.controller = SimpleNamespace(sticks=(Stick(30, 70, 10), Stick(90, 70, 10)))
        self.calls = []
        self.guard = self
        self.armed = False
        self.profile = SimpleNamespace(
            validate=lambda: None,
            matches=lambda *args: True,
            visible=lambda f: True,
            axes=DEFAULT_AXES,
            camera=[0, 0, 120, 40],
        )

    def latest_frame(self):
        return Frame(
            np.zeros((100, 120, 3), dtype=np.uint8), self.sequence, self.now, self.now, 0, self.epoch
        )

    def wait_frame(self, after, timeout):
        self.sequence += 1
        return self.latest_frame()

    def arm(self, package):
        self.armed = True
        self.calls.append(("arm", package))

    def heartbeat(self):
        self.calls.append(("heartbeat",))

    def command(self, left, right, duration):
        self.calls.append(("command", left, right, duration))
        return {"expires_at_ms": int(self.now * 1000) + duration, "device_time_ms": int(self.now * 1000)}

    def release(self, disarm=False):
        if disarm:
            self.armed = False
        self.calls.append(("release", disarm))
        return {"active": 0}

    def update(self):
        self.calls.append(("update",))

    def snapshot(self):
        return {"armed": self.armed, "expires_at_ms": 99999999}


def executor(tmp_path, live=True):
    b = Rig()
    e = Executor(b, live, b.profile, Journal(tmp_path), clock=lambda: b.now, camera_roi=[0, 0, 120, 40])
    e.running = True
    e.started = b.now
    e.epoch = b.epoch
    b.armed = True
    return b, e


def args(observation, ttl=1000):
    return {
        "left_xy": [0.1, 0],
        "right_xy": [0, -0.1],
        "valid_for_ms": ttl,
        "observation_id": observation.id,
        "reason": "adjust",
    }


def test_expiry_invalidates_pending_inference_and_heartbeat_does_not_renew(tmp_path):
    b, e = executor(tmp_path)
    first = e.observe("center target")
    e.submit(first, args(first, 100))
    pending = e.observe("center target")
    b.now += 0.12
    e.tick()
    assert e.running and e.command is None and e.generation > pending.generation
    assert ("release", False) in b.calls
    before = len([c for c in b.calls if c[0] == "command"])
    with pytest.raises(ValueError):
        e.submit(pending, args(pending))
    assert len([c for c in b.calls if c[0] == "command"]) == before
    fresh = e.observe("center target")
    e.submit(fresh, args(fresh))
    assert e.command


def test_stop_discards_late_command_and_requires_new_start(tmp_path):
    b, e = executor(tmp_path)
    observation = e.observe("goal")
    e.stop("user_paused")
    with pytest.raises(ValueError):
        e.submit(observation, args(observation))
    assert not e.running and not b.armed and not any(c[0] == "command" for c in b.calls)


def test_duplicate_observation_cannot_extend_a_command(tmp_path):
    b, e = executor(tmp_path)
    observation = e.observe("goal")
    e.submit(observation, args(observation))
    with pytest.raises(ValueError):
        e.submit(observation, args(observation))
    assert len([c for c in b.calls if c[0] == "command"]) == 1


def test_continuous_update_does_not_release_contacts(tmp_path):
    b, e = executor(tmp_path)
    for _ in range(2):
        o = e.observe("goal")
        e.submit(o, args(o))
        b.now += 0.1
    assert e.continuous_updates == 1
    assert not any(c[0] == "release" for c in b.calls)


def test_two_second_ai_command_survives_one_second_and_expires_at_two(tmp_path):
    b, e = executor(tmp_path)
    o = e.observe("goal")
    command = args(o, 2000)
    parse_decision("command_sticks", command)
    e.submit(o, command)
    b.now += 1.2
    e.tick()
    assert e.command is not None
    b.now += 0.81
    e.tick()
    assert e.command is None and e.expirations == 1 and e.running


@pytest.mark.parametrize("fault", ["geometry", "stale", "android"])
def test_control_stops_for_local_faults(tmp_path, fault):
    b, e = executor(tmp_path)
    o = e.observe("goal")
    e.submit(o, args(o))
    if fault == "geometry":
        b.epoch += 1
    elif fault == "stale":
        frame = b.latest_frame()
        b.latest_frame = lambda: frame
        b.now += 0.6
    elif fault == "ui":
        e.require_ui = True
        e.ui_heartbeat = b.now - 0.6
    elif fault == "mission_timeout":
        b.now += 300
    elif fault == "android":
        b.armed = False
    elif fault == "layout":
        e.profile.visible = lambda f: False
    e.tick()
    assert not e.running and ("release", True) in b.calls


def test_observe_only_proposes_but_never_arms_or_touches(tmp_path):
    b, e = executor(tmp_path, False)
    o = e.observe("goal")
    e.submit(o, args(o))
    e.stop()
    assert b.calls == []


@pytest.mark.parametrize("axis", range(4))
@pytest.mark.parametrize("sign", [-1, 1])
def test_ai_small_direction_reaches_selected_full_radius_and_logs_both(tmp_path, axis, sign):
    b, e = executor(tmp_path)
    o = e.observe("inspect")
    requested = args(o, 1500)
    xy = [0.0, 0.0]
    xy[axis % 2] = 0.12 * sign
    requested["left_xy"] = xy if axis < 2 else None
    requested["right_xy"] = xy if axis >= 2 else None
    e.submit(o, requested)
    sent = next(c for c in b.calls if c[0] == "command")
    expected = [0.0, 0.0]
    expected[axis % 2] = float(sign)
    assert sent[1:3] == ((expected, None) if axis < 2 else (None, expected))
    assert sent[3] == 1500  # magnitude changes do not extend the command lease
    assert xy[axis % 2] == 0.12 * sign  # preserve the model's original request
    record = [r for r in e.journal.history if r["kind"] == "executed"][-1]
    assert record["requested_command"] == requested
    assert record["operator_drag_fraction"] == 1.0
    assert e.observe("inspect").metadata["current_command"] == record["command"]
    assert o.metadata["operator_drag_fraction"] == 1.0
    stick = b.controller.sticks[axis // 2]
    point = stick.target(expected)
    assert point[axis % 2] == (stick.x if axis % 2 == 0 else stick.y) + sign * stick.radius


@pytest.mark.parametrize("strength", [0.05, 0.5, 1.0])
def test_ai_selected_size_preserves_diagonal_direction_neutral_and_partial_release(tmp_path, strength):
    b, e = executor(tmp_path)
    e.drag_strength = strength
    o = e.observe("inspect")
    request = {**args(o), "left_xy": [0.06, -0.08], "right_xy": [0, 0]}
    e.submit(o, request)
    assert e.command["left_xy"] == pytest.approx([0.6 * strength, -0.8 * strength])
    assert e.command["right_xy"] == [0, 0]
    assert o.metadata["operator_drag_fraction"] == strength
    o = e.observe("inspect")
    e.submit(o, {**request, "observation_id": o.id, "left_xy": None})
    assert e.command["left_xy"] is None and e.command["right_xy"] == [0, 0]


@pytest.mark.parametrize("strength", [0, 0.04, 1.01, float("nan"), float("inf"), True, "1"])
def test_invalid_ai_drag_size_rejected_before_arming(tmp_path, strength):
    b = Rig()
    with pytest.raises(ValueError):
        Executor(b, True, None, Journal(tmp_path), drag_strength=strength)
    assert b.calls == []


@pytest.mark.parametrize("xy", [[float("nan"), 0], [True, 0], [1, 1], [".1", 0], [0.1]])
def test_invalid_sticks_fail_before_transport(xy):
    with pytest.raises(ValueError):
        targets(xy, [0, 0])


@pytest.mark.parametrize(
    "change", [{"valid_for_ms": 2001}, {"valid_for_ms": True}, {"unexpected": 1}, {"observation_id": ""}]
)
def test_function_validation_rejects_bad_model_output(change):
    arguments = {
        "left_xy": [0, 0],
        "right_xy": [0, 0],
        "valid_for_ms": 100,
        "observation_id": "o",
        "reason": "test",
        **change,
    }
    with pytest.raises(ValueError):
        parse_decision("command_sticks", arguments)


def test_provider_uses_astra_and_does_not_expose_exception_secrets():
    def fail(**kwargs):
        assert kwargs["model"] == "gpt-6-astra"
        assert kwargs["parallel_tool_calls"] is False
        raise RuntimeError("secret-api-key-example")

    client = SimpleNamespace(responses=SimpleNamespace(create=fail))
    p = Astra(client=client)
    b = Rig()
    o = SimpleNamespace(id="o", frame=b.latest_frame(), metadata={"camera_only": True})
    with pytest.raises(RuntimeError, match="OpenAI RuntimeError") as error:
        p.decide(o)
    assert "secret-api-key" not in str(error.value)


class LiveFrames(Rig):
    def latest_frame(self):
        self.now = time.monotonic()
        self.sequence += 1
        return super().latest_frame()


class Provider:
    def __init__(self, decisions):
        self.decisions = iter(decisions)
        self.seen = []

    def decide(self, observation, previous):
        self.seen.append((time.monotonic(), observation))
        item = next(self.decisions)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        pass


def test_finish_requires_two_new_observations_at_least_half_second_apart(tmp_path):
    provider = Provider([Decision("finish", {"evidence": "target centered"})] * 3)
    mission = Mission(LiveFrames(), provider, "center", output=tmp_path, camera_roi=[0, 0, 120, 40])
    mission.start()
    mission.thread.join(4)
    assert mission.state == "completed" and mission.verifications == 2
    assert len(provider.seen) == 3
    assert provider.seen[1][0] - provider.seen[0][0] >= 0.5
    assert provider.seen[2][0] - provider.seen[1][0] >= 0.5
    assert all(o.metadata["completion_verification"] for _, o in provider.seen[1:])


def test_api_error_pauses_and_does_not_retry(tmp_path):
    provider = Provider([RuntimeError("API unavailable")])
    mission = Mission(LiveFrames(), provider, "goal", output=tmp_path, camera_roi=[0, 0, 120, 40])
    mission.start()
    mission.thread.join(2)
    assert mission.state == "paused" and len(provider.seen) == 1


@pytest.mark.parametrize("live", [False, True])
def test_reobserve_continues_but_explicit_operator_request_releases_and_pauses(tmp_path, live):
    class InspectThenMove:
        def __init__(self):
            self.seen = []

        def decide(self, observation, previous):
            self.seen.append(observation)
            step = len(self.seen)
            if step in (1, 3):
                return Decision("command_sticks", args(observation, 2000))
            if step == 2:
                return Decision("observe", {})
            return Decision("need_operator", {"reason": "Flight control UI unavailable"})

        def close(self):
            pass

    bridge = LiveFrames()
    provider = InspectThenMove()
    mission = Mission(
        bridge, provider, "inspect another approach", live=live, output=tmp_path, camera_roi=[0, 0, 120, 40]
    )
    mission.start()
    mission.thread.join(2)
    assert not mission.busy
    assert mission.state == "paused" and not mission.executor.running
    assert mission.message == "need_operator: Flight control UI unavailable"
    assert mission.executor.submissions == 2 and len(provider.seen) == 4
    # observe ends the old input, then a new observation can authorize another command.
    assert provider.seen[2].generation > provider.seen[1].generation
    assert provider.seen[2].metadata["current_command"] is None
    records = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    requests = [record for record in records if record["kind"] == "operator_request"]
    assert len(requests) == 1 and requests[0]["source"] == "model"
    if live:
        relevant = [call for call in bridge.calls if call[0] in ("command", "release")]
        assert [call[0] for call in relevant] == ["command", "release", "command", "release"]
        assert relevant[1] == ("release", False) and relevant[-1] == ("release", True)
        assert not bridge.armed
    else:
        assert bridge.calls == []


def test_api_hard_timeout_is_independent_of_http_progress(tmp_path, monkeypatch):
    import zipcontrol.mission as module

    monkeypatch.setattr(module, "API_TIMEOUT_S", 0.08)
    finish = threading.Event()

    class Slow:
        def decide(self, observation, previous):
            finish.wait(1)
            return Decision("finish", {"evidence": "late"})

        def close(self):
            finish.set()

    mission = Mission(LiveFrames(), Slow(), "goal", output=tmp_path, camera_roi=[0, 0, 120, 40])
    mission.start()
    mission.thread.join(1)
    assert mission.state == "paused" and mission.api_timeouts == 1
    assert mission.executor.submissions == 0


def test_model_reply_after_user_stop_never_executes(tmp_path):
    entered, finish = threading.Event(), threading.Event()

    class Delayed:
        def decide(self, o, previous):
            entered.set()
            finish.wait(2)
            return Decision("command_sticks", args(o))

        def close(self):
            finish.set()

    bridge = LiveFrames()
    mission = Mission(bridge, Delayed(), "goal", output=tmp_path, camera_roi=[0, 0, 120, 40])
    mission.start()
    assert entered.wait(1)
    mission.stop("user_paused")
    mission.thread.join(2)
    assert mission.executor.submissions == 0 and not bridge.calls


def test_flight_profile_roundtrip_layout_mismatch_and_geometry(tmp_path):
    b = Rig()
    f = b.latest_frame()
    s = b.controller.sticks
    p = FlightProfile(
        "a",
        120,
        100,
        [asdict(x) for x in s],
        [["yaw", 1], ["vertical", -1], ["lateral", 1], ["forward", -1]],
        [0, 0, 120, 40],
        [anchor(f, x) for x in s],
        True,
    )
    store = FlightProfileStore(tmp_path)
    store.save(p)
    loaded = store.load("a", 120, 100)
    assert loaded == p and store.load("b", 120, 100) is None
    changed = Frame(np.full((100, 120, 3), 255, dtype=np.uint8), 1, 0, 0, 0, 1)
    assert not loaded.visible(changed)
    p.axes[1] = ["yaw", 1]
    with pytest.raises(ValueError):
        store.save(p)


def test_live_start_without_profile_uses_defaults_without_layout_gate(tmp_path, monkeypatch):
    b = Rig()

    def forbidden_save(*args):
        raise AssertionError("Starting without a profile must not create a saved/verified profile")

    monkeypatch.setattr(FlightProfileStore, "save", forbidden_save)
    e = Executor(b, True, None, Journal(tmp_path), clock=lambda: b.now, camera_roi=[0, 0, 120, 40])
    try:
        e.start()
        assert e.running and ("arm", "dji.go.v5") in b.calls
        assert e.profile is None and e.layout is None
        observation = e.observe("inspect the scene")
        assert observation.metadata["axis_mapping_screen_lx_ly_rx_ry"] == [list(a) for a in DEFAULT_AXES]
        assert observation.metadata["axis_mapping_source"] == "default"
        assert observation.metadata["axis_mapping_verified"] is False
        assert observation.metadata["camera_roi"] == [0, 0, 120, 40]
        assert observation.metadata["camera_roi_source"] == "cropped"
        e.submit(observation, args(observation, 2000))
        assert any(c[0] == "command" for c in b.calls)
    finally:
        e.stop()
        if e.thread:
            e.thread.join(1)


def test_no_profile_still_requires_current_lr_coordinates_for_live_input(tmp_path):
    b = Rig()
    b.controller.sticks = None
    e = Executor(b, True, None, Journal(tmp_path), clock=lambda: b.now, camera_roi=[0, 0, 120, 40])
    with pytest.raises(ValueError, match="L/R"):
        e.start()
    assert not any(c[0] == "arm" for c in b.calls)


def test_observation_mode_transmits_default_mapping_and_selected_roi_without_profile(tmp_path):
    b = Rig()
    selected = [0, 0, 120, 40]
    e = Executor(b, False, None, Journal(tmp_path), clock=lambda: b.now, camera_roi=selected)
    payloads = []

    def create(**kwargs):
        import json

        payloads.append(json.loads(kwargs["input"][0]["content"][0]["text"]))
        return SimpleNamespace(
            status="completed",
            id="mock",
            usage=None,
            output=[SimpleNamespace(type="function_call", name="observe", arguments="{}")],
        )

    try:
        e.start()
        provider = Astra(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
        provider.decide(e.observe("look around"))
        assert payloads[0]["axis_mapping_screen_lx_ly_rx_ry"] == [list(a) for a in DEFAULT_AXES]
        assert payloads[0]["axis_mapping_source"] == "default"
        assert payloads[0]["camera_roi"] == selected
        assert b.calls == []
    finally:
        e.stop()
        if e.thread:
            e.thread.join(1)


def test_optional_unverified_axes_can_be_used_with_selected_camera(tmp_path):
    b = Rig()
    profile = FlightProfile.capture_layout(b.latest_frame(), b.controller.sticks)
    profile.serial = "phone"
    profile.axes[0] = ["yaw", -1]
    store = FlightProfileStore(tmp_path / "settings")
    store.save(profile)
    loaded = store.load("phone", 120, 100)
    assert loaded.verified is False and loaded.camera is None
    e = Executor(b, True, loaded, Journal(tmp_path / "run"), clock=lambda: b.now, camera_roi=[0, 0, 120, 40])
    try:
        # Old saved appearance is optional metadata, not a start prerequisite.
        loaded.anchors = [[255] * len(a) for a in loaded.anchors]
        e.start()
        assert e.running
        assert e.observe("goal").metadata["axis_mapping_screen_lx_ly_rx_ry"][0] == ["yaw", -1]
        assert e.layout is None
    finally:
        e.stop()
        if e.thread:
            e.thread.join(1)


def test_layout_pixels_focus_and_five_minutes_do_not_stop_mission(tmp_path):
    b = Rig()
    e = Executor(b, True, None, Journal(tmp_path), clock=lambda: b.now, camera_roi=[0, 0, 120, 40])
    try:
        e.start()
        original = b.latest_frame()
        b.latest_frame = lambda: Frame(np.full_like(original.rgb, 255), 2, b.now, b.now, 0, b.epoch)
        b.now += 301
        e.require_ui = True
        e.ui_heartbeat = 0
        e.tick()
        assert e.running
    finally:
        e.stop()
        if e.thread:
            e.thread.join(1)
