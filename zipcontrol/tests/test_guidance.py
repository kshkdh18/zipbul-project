import base64
import io
import json
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from test_mission import LiveFrames, executor

from zipcontrol.actions import MOVEMENTS, STATUS_ACTIONS, ActionAdapter, Subgoal
from zipcontrol.astra import Decision
from zipcontrol.execution import CommandStream
from zipcontrol.flight_profile import DEFAULT_AXES
from zipcontrol.guidance import GuidanceMission
from zipcontrol.luna import ActionChoice, LunaDecider, parse_choice
from zipcontrol.planning import AstraPlanner, parse_plan
from zipcontrol.simulation import Simulation, semantic_axes


def plan(goal="상자 중앙 정렬", actions=("YAW_LEFT", "YAW_RIGHT")):
    return Decision(
        "set_subgoal",
        {
            "goal": goal,
            "completion_criteria": "상자가 화면 중앙에 보임",
            "allowed_actions": list(actions),
            "reason": "상자를 살펴봅니다",
        },
    )


def choice(action):
    return ActionChoice(action, 0.4, {action: 1}, latency=0.01)


class Sequence:
    def __init__(self, *items):
        self.items = iter(items)
        self.seen = []
        self.closed = False

    def decide(self, obs, previous):
        self.seen.append((time.monotonic(), obs, previous))
        item = next(self.items)
        if isinstance(item, Exception):
            raise item
        return item(obs) if callable(item) else item

    def close(self):
        self.closed = True


def mission(tmp_path, luna, planner=None, **kwargs):
    return GuidanceMission(
        LiveFrames(),
        luna,
        planner or Sequence(),
        "상자를 중앙에 맞춰",
        camera_roi=[0, 0, 120, 40],
        output=tmp_path,
        **kwargs,
    )


@pytest.mark.parametrize("action", MOVEMENTS)
@pytest.mark.parametrize(
    "axes",
    [
        DEFAULT_AXES,
        tuple((a, -s) for a, s in DEFAULT_AXES),
        (DEFAULT_AXES[2], DEFAULT_AXES[3], DEFAULT_AXES[0], DEFAULT_AXES[1]),
    ],
)
def test_enum_android_arrows_simulation_match_for_all_axis_mappings(tmp_path, action, axes):
    b, runner = executor(tmp_path)
    b.profile.axes = axes
    stream = runner.stream = CommandStream(clock=lambda: b.now)
    runner.drag_strength = 0.55
    observation = runner.observe("goal")
    command = ActionAdapter.command(action, observation.id, Subgoal.direct("goal"), axes)
    runner.submit(observation, command, source="luna_decisions")
    event = stream.drain()[0]
    semantic, sign, label = MOVEMENTS[action]
    actual = semantic_axes(event)
    assert actual[semantic] == pytest.approx(sign * 0.55)
    assert all(value == 0 for key, value in actual.items() if key != semantic)
    assert b.calls[-1][1:3] == (
        list(event.left) if event.left else None,
        list(event.right) if event.right else None,
    )
    assert event.deadline == runner.deadline
    assert (event.left is None) != (event.right is None)
    sim = Simulation()
    sim.consume(event)
    sim.advance(b.now + 1)
    assert sim.label == label and sim.show_arrows
    position = {
        "yaw": ((sim.yaw + 180) % 360 - 180) / 45,
        "vertical": sim.y,
        "lateral": sim.x,
        "forward": -sim.z,
    }
    assert position[semantic] == pytest.approx(sign * 0.55)


def response(action="YAW_RIGHT", *, kind="choice", name="next_action"):
    options = ["YAW_LEFT", "YAW_RIGHT", *STATUS_ACTIONS]
    return SimpleNamespace(
        answers=[
            SimpleNamespace(
                type=kind,
                name=name,
                choice=action,
                confidence=0.8,
                probabilities=[
                    SimpleNamespace(value=a, probability=1.0 if a == action else 0.0) for a in options
                ],
            )
        ],
        usage=None,
    )


@pytest.mark.parametrize("provider_type", [AstraPlanner, LunaDecider])
def test_both_providers_send_only_current_and_previous_crop(tmp_path, provider_type):
    b, runner = executor(tmp_path, False)
    original = b.latest_frame()
    original.rgb[:] = (255, 0, 0)
    original.rgb[20:70, 30:100] = (0, 200, 0)
    b.latest_frame = lambda: original
    runner.camera_roi = [30, 20, 70, 50]
    previous, current = runner.observe("goal"), runner.observe("goal")
    current.metadata["current_subgoal"] = plan().arguments
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        if provider_type is LunaDecider:
            return response()
        return SimpleNamespace(
            status="completed",
            id="planner-test",
            usage=None,
            output=[
                SimpleNamespace(
                    type="function_call", name="set_subgoal", arguments=json.dumps(plan().arguments)
                )
            ],
        )

    provider = provider_type(
        SimpleNamespace(responses=SimpleNamespace(create=create), decisions=SimpleNamespace(create=create))
    )
    provider.decide(current, previous)
    images = [c for c in requests[0]["input"][0]["content"] if c["type"] == "input_image"]
    assert len(images) == 2
    for item in images:
        pixels = np.asarray(Image.open(io.BytesIO(base64.b64decode(item["image_url"].split(",")[1]))))
        assert pixels.shape == (50, 70, 3)
        assert pixels[:, :, 0].max() < 10 and pixels[:, :, 1].min() > 190
    if provider_type is LunaDecider:
        assert requests[0]["model"] == "gpt-6-luna"
        assert len(requests[0]["questions"]) == 1
        assert {o["value"] for o in requests[0]["questions"][0]["choices"]} == {
            "YAW_LEFT",
            "YAW_RIGHT",
            *STATUS_ACTIONS,
        }
    else:
        assert {t["name"] for t in requests[0]["tools"]} == {"set_subgoal", "finish", "need_operator"}


@pytest.mark.parametrize(
    "bad",
    [
        response("FORWARD"),
        response(kind="refusal"),
        response(name="wrong"),
        response(action=True),
        SimpleNamespace(answers=[]),
    ],
)
def test_invalid_luna_response_never_becomes_command(bad):
    with pytest.raises((ValueError, RuntimeError)):
        parse_choice(bad, ["YAW_LEFT", "YAW_RIGHT", *STATUS_ACTIONS])


def test_planner_cannot_command_or_authorize_unknown_actions():
    with pytest.raises(ValueError):
        parse_plan("command_sticks", {})
    bad = plan().arguments
    bad["allowed_actions"] = ["TAKEOFF"]
    with pytest.raises(ValueError):
        parse_plan("set_subgoal", bad)


def test_hierarchy_continuous_control_done_review_and_overall_verification(tmp_path):
    planner = Sequence(
        plan(),
        plan("옆을 살펴보기", ("MOVE_RIGHT",)),
        *[Decision("finish", {"evidence": "모든 목표 확인"})] * 3,
    )
    luna = Sequence(
        choice("YAW_RIGHT"),
        choice("YAW_LEFT"),
        choice("SUBGOAL_DONE"),
        choice("MOVE_RIGHT"),
        choice("SUBGOAL_DONE"),
    )
    stream = CommandStream()
    m = mission(tmp_path, luna, planner, live=True, stream=stream)
    m.start()
    m.thread.join(6)
    assert m.state == "completed", m.message
    assert m.executor.submissions == 3 and m.executor.continuous_updates == 1
    assert m.verifications == 2 and len(m.completed_subgoals) == 1
    assert len(planner.seen) == 5 and len(luna.seen) == 5
    assert luna.seen[0][1].frame.sequence > planner.seen[0][1].frame.sequence
    assert luna.seen[1][1].metadata["continuous_hold_ms"] >= 190
    assert all(b[0] - a[0] >= 0.19 for a, b in zip(luna.seen, luna.seen[1:], strict=False))
    events = stream.drain()
    assert len([e for e in events if e.kind == "command"]) == 3
    assert events[-1].kind == "stop"
    report = m.report()
    assert report["model_metrics"]["astra"]["calls"] == 5
    assert report["model_metrics"]["luna"]["calls"] == 5


def test_direct_replan_enters_astra_without_operator_takeover(tmp_path):
    luna = Sequence(choice("REPLAN"), choice("FORWARD"), RuntimeError("test finished"))
    planner = Sequence(plan("앞으로 살펴보기", ("FORWARD",)))
    m = mission(tmp_path, luna, planner, mode="direct", live=True)
    m.start()
    m.thread.join(3)
    assert m.mode == "hierarchical" and m.executor.submissions == 1
    assert planner.seen[0][1].metadata["planning_trigger"] == "REPLAN"
    assert planner.seen[0][1].metadata["current_command"] is None
    assert "need_operator" not in m.message


def test_direct_done_requires_two_new_images_and_failed_verification_cannot_move(tmp_path):
    luna = Sequence(
        choice("SUBGOAL_DONE"),
        choice("FORWARD"),
        choice("SUBGOAL_DONE"),
        choice("SUBGOAL_DONE"),
        choice("SUBGOAL_DONE"),
    )
    m = mission(tmp_path, luna, mode="direct", live=True)
    m.start()
    m.thread.join(4)
    assert m.state == "completed" and m.executor.submissions == 0
    assert luna.seen[-1][0] - luna.seen[-2][0] >= 0.5
    assert luna.seen[-2][0] - luna.seen[-3][0] >= 0.5
    assert len({o.frame.sequence for _, o, _ in luna.seen}) == 5


@pytest.mark.parametrize("stage", ["astra", "luna"])
def test_region_change_discards_inflight_plan_or_action_and_clears_previous(tmp_path, stage):
    entered, deliver = threading.Event(), threading.Event()

    def delayed(obs):
        entered.set()
        deliver.wait(2)
        return plan() if stage == "astra" else choice("YAW_RIGHT")

    planner = Sequence(delayed if stage == "astra" else plan(), plan(), RuntimeError("done"))
    luna = Sequence(delayed if stage == "luna" else RuntimeError("done"), RuntimeError("done"))
    m = mission(tmp_path, luna, planner, live=True)
    m.start()
    assert entered.wait(1)
    m.set_camera_roi(None)
    m.set_camera_roi([10, 10, 70, 40])
    deliver.set()
    m.thread.join(3)
    assert not m.busy and m.discarded == 1 and m.executor.submissions == 0
    assert planner.seen[-1][2] is None
    assert planner.seen[-1][1].frame.width == 70


def test_slow_luna_is_discarded_and_latest_observation_can_continue(tmp_path, monkeypatch):
    import zipcontrol.guidance as module

    monkeypatch.setattr(module, "MAX_LUNA_OBSERVATION_AGE_S", 0.03)

    def slow(obs):
        time.sleep(0.05)
        return choice("FORWARD")

    luna = Sequence(slow, choice("FORWARD"), RuntimeError("done"))
    m = mission(tmp_path, luna, mode="direct", live=True)
    m.start()
    m.thread.join(2)
    assert m.discarded == 1 and m.executor.submissions == 1


def test_stop_discards_pending_luna_and_no_other_request_starts(tmp_path):
    entered, deliver = threading.Event(), threading.Event()

    def delayed(obs):
        entered.set()
        deliver.wait(1)
        return choice("FORWARD")

    luna = Sequence(delayed)
    m = mission(tmp_path, luna, mode="direct", live=True)
    m.start()
    assert entered.wait(1)
    m.stop()
    deliver.set()
    m.thread.join(2)
    assert m.executor.submissions == 0 and len(luna.seen) == 1


def test_observation_only_and_api_failure_release_without_fallback(tmp_path):
    luna = Sequence(choice("FORWARD"), RuntimeError("refusal"))
    stream = CommandStream()
    m = mission(tmp_path, luna, mode="direct", stream=stream)
    m.start()
    m.thread.join(2)
    assert m.state == "paused" and m.executor.submissions == 1
    assert not m.executor.bridge.calls
    assert not [e for e in stream.drain() if e.kind == "command"]
    assert not m.planner.seen


def test_old_plan_and_session_are_rejected_even_with_executor_generation_intact(tmp_path):
    m = mission(tmp_path, Sequence(), mode="direct")
    m.executor.running = True
    m.executor.epoch = 1
    obs = m._observation()
    m.plan_version += 1
    assert m._discard_reason(obs, "luna") == "previous_plan"
    m.plan_version -= 1
    m.session_id = "new-session"
    assert m._discard_reason(obs, "luna") == "previous_session"
