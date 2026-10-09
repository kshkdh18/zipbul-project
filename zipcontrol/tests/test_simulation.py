import math
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_manual import Bridge
from test_mission import args, executor

from zipcontrol.execution import CommandStream, ExecutionEvent, execute_command
from zipcontrol.manual import ManualHold
from zipcontrol.simulation import Simulation, semantic_axes


def event(left=None, right=None, duration=1, at=0, command_id=1):
    return ExecutionEvent("command", command_id, at, at + duration, left, right)


@pytest.mark.parametrize(
    "left,right,axis,sign,label",
    [
        ((-1, 0), None, "yaw", -1, "왼쪽으로 회전"),
        ((1, 0), None, "yaw", 1, "오른쪽으로 회전"),
        ((0, -1), None, "y", 1, "위로 이동"),
        ((0, 1), None, "y", -1, "아래로 이동"),
        (None, (-1, 0), "x", -1, "왼쪽으로 이동"),
        (None, (1, 0), "x", 1, "오른쪽으로 이동"),
        (None, (0, -1), "z", -1, "앞으로 이동"),
        (None, (0, 1), "z", 1, "뒤로 이동"),
    ],
)
def test_eight_directions_and_arrows_match(left, right, axis, sign, label):
    sim = Simulation()
    sim.consume(event(left, right))
    assert sim.label == label and sim.show_arrows
    sim.advance(1)
    expected = (sign * 45) % 360 if axis == "yaw" else sign
    assert getattr(sim, axis) == pytest.approx(expected)
    assert sim.deadline == 0 and sim.state == "다음 판단 중" and sim.show_arrows


def test_yaw_then_forward_uses_drone_heading_and_does_not_drift_after_expiry():
    sim = Simulation()
    sim.consume(event((1, 0), duration=2))
    sim.consume(event(right=(0, -1), at=2, command_id=2))
    sim.advance(3)
    assert sim.yaw == pytest.approx(90) and sim.x == pytest.approx(1) and sim.z == pytest.approx(0)
    position = (sim.x, sim.y, sim.z)
    sim.advance(30)
    assert (sim.x, sim.y, sim.z) == position
    sim.consume(ExecutionEvent("stop", 2, 30))
    assert not sim.show_arrows


def test_diagonal_combined_axes_custom_mapping_and_duplicate_are_consistent():
    sim = Simulation()
    cmd = event((0, -0.5), (math.sqrt(0.5), -math.sqrt(0.5)))
    sim.consume(cmd)
    sim.advance(0.5)
    sim.consume(cmd)
    sim.advance(1)
    assert sim.x == pytest.approx(math.sqrt(0.5))
    assert sim.z == pytest.approx(-math.sqrt(0.5))
    assert sim.y == pytest.approx(0.5)
    custom = replace(cmd, axes=(("yaw", -1), ("vertical", 1), ("forward", 1), ("lateral", -1)))
    assert semantic_axes(custom)["vertical"] == -0.5


def test_failed_android_command_never_emits_simulation_event():
    stream = CommandStream()
    bridge = SimpleNamespace(guard=SimpleNamespace(command=lambda *args: {"ok": False}))
    with pytest.raises(RuntimeError):
        execute_command(bridge, (1, 0), None, 500, stream=stream)
    assert stream.drain() == []


def test_ai_common_event_uses_final_scaled_vectors_and_release(tmp_path):
    bridge, runner = executor(tmp_path)
    stream = CommandStream(clock=lambda: bridge.now)
    runner.stream = stream
    runner.drag_strength = 0.5
    obs = runner.observe("target")
    runner.submit(obs, args(obs))
    cmd = stream.drain()[0]
    assert cmd.left == (0.5, 0) and cmd.right == (0, -0.5) and cmd.valid_for_ms == 1000
    assert bridge.calls[-1][1:3] == ([0.5, 0], [0, -0.5])
    with pytest.raises(ValueError):
        runner.submit(obs, args(obs))
    assert stream.drain() == []
    runner.stop()
    assert stream.drain()[0].kind == "stop"


def test_manual_common_event_and_observation_only_no_motion(tmp_path):
    bridge = Bridge()
    stream = CommandStream()
    hold = ManualHold(bridge, 3, -1, stream=stream)
    assert hold.begin() and hold.tick()
    cmd = stream.drain()[0]
    assert cmd.source == "manual" and cmd.right == (0, -1) and cmd.valid_for_ms == 500
    hold.stop()
    assert stream.drain()[-1].kind == "stop"
    _, runner = executor(tmp_path, False)
    runner.stream = stream
    obs = runner.observe("target")
    runner.submit(obs, args(obs))
    assert not stream.drain()


def test_delayed_ack_does_not_extend_original_expiry():
    now = [1.0]
    stream = CommandStream(clock=lambda: now[0])
    cmd = stream.accepted(
        (1, 0), None, 500, {"expires_at_ms": 500, "device_time_ms": 0}, "ai", "test", event().axes, sent_at=0
    )
    assert cmd.deadline == 0.5
    sim = Simulation()
    sim.consume(cmd)
    sim.advance(2)
    assert sim.yaw == 0


@pytest.mark.parametrize("fault", ["video", "android", "geometry", "release_error"])
def test_execution_fault_clears_visual_motion_and_arrows(tmp_path, fault):
    bridge, runner = executor(tmp_path)
    stream = CommandStream(clock=lambda: bridge.now)
    runner.stream = stream
    obs = runner.observe("target")
    runner.submit(obs, args(obs, 100))
    sim = Simulation()
    sim.consume(stream.drain()[0])
    if fault == "video":
        bridge.error = "disconnected"
    elif fault == "android":
        bridge.armed = False
    elif fault == "geometry":
        bridge.epoch += 1
    else:

        def fail(*args):
            raise RuntimeError("release failed")

        bridge.release = fail
        bridge.now += 0.2
    runner.tick()
    for message in stream.drain():
        sim.consume(message)
    assert not runner.running and not sim.show_arrows and sim.deadline == 0
