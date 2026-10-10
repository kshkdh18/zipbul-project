"""Semantic Decisions choices and the sole enum-to-stick adapter."""

from dataclasses import dataclass

from .flight_profile import AXES, DEFAULT_AXES
from .i18n import message as m
from .i18n import translate

MOVEMENTS = {
    "YAW_LEFT": ("yaw", -1, m("왼쪽으로 회전")),
    "YAW_RIGHT": ("yaw", 1, m("오른쪽으로 회전")),
    "ASCEND": ("vertical", 1, m("위로 이동")),
    "DESCEND": ("vertical", -1, m("아래로 이동")),
    "MOVE_LEFT": ("lateral", -1, m("왼쪽으로 이동")),
    "MOVE_RIGHT": ("lateral", 1, m("오른쪽으로 이동")),
    "FORWARD": ("forward", 1, m("앞으로 이동")),
    "BACKWARD": ("forward", -1, m("뒤로 이동")),
}
ACTION_DESCRIPTIONS = {
    "YAW_LEFT": "Rotate the CAMERA to its LEFT. Fixed scene objects shift RIGHT in the image. "
    "Use for a target LEFT of the image center when centering the view.",
    "YAW_RIGHT": "Rotate the CAMERA to its RIGHT. Fixed scene objects shift LEFT in the image. "
    "Use for a target RIGHT of the image center when centering the view.",
    "ASCEND": "Move the CAMERA UP. Fixed scene objects shift DOWN. Use for a target ABOVE center.",
    "DESCEND": "Move the CAMERA DOWN. Fixed scene objects shift UP. Use for a target BELOW center.",
    "MOVE_LEFT": "Translate the CAMERA sideways to its LEFT, without turning. Scene objects shift RIGHT.",
    "MOVE_RIGHT": "Translate the CAMERA sideways to its RIGHT, without turning. Scene objects shift LEFT.",
    "FORWARD": "Translate the CAMERA FORWARD along its heading, approaching what it faces; objects grow larger.",
    "BACKWARD": "Translate the CAMERA BACKWARD along its heading, away from what it faces; objects get smaller.",
}
STATUS_ACTIONS = {
    "WAIT": "Release and reobserve ONLY if the current image is temporarily unusable (e.g. motion blur), "
    "or a just-executed action needs time for the person to respond. If a useful direction is clear, choose it. "
    "Identical images with no executed action do not require waiting.",
    "SUBGOAL_DONE": "The current image satisfies the current subgoal's visual completion criteria.",
    "REPLAN": "Release input and ask Astra for another approach: the subgoal is unsuitable, "
    "the scene changed materially, or repeated attempts show no useful progress. "
    "An unchanged image while the person follows guidance alone is not a reason to replan.",
}


def text_field(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError("Invalid plan text")
    return value.strip()


@dataclass(frozen=True)
class Subgoal:
    goal: str
    completion_criteria: str
    allowed_actions: tuple[str, ...]
    reason: str

    def __post_init__(self):
        for value in (self.goal, self.completion_criteria, self.reason):
            text_field(value)
        if (
            not isinstance(self.allowed_actions, (tuple, list))
            or not self.allowed_actions
            or any(not isinstance(a, str) or a not in MOVEMENTS for a in self.allowed_actions)
            or len(set(self.allowed_actions)) != len(self.allowed_actions)
        ):
            raise ValueError("Invalid allowed movement actions")

    @classmethod
    def direct(cls, goal, language="ko"):
        return cls(
            goal, translate(m("최신 영상에서 사용자의 목표가 달성됨"), language), tuple(MOVEMENTS), goal
        )


class ActionAdapter:
    @staticmethod
    def command(action, observation_id, subgoal, axes=DEFAULT_AXES, language="ko"):
        if action not in subgoal.allowed_actions or action not in MOVEMENTS:
            raise ValueError("Action is not an allowed movement")
        if (
            len(axes) != 4
            or any(
                len(a) != 2 or a[0] not in AXES or type(a[1]) is not int or a[1] not in (-1, 1) for a in axes
            )
            or sorted(a[0] for a in axes) != sorted(AXES)
        ):
            raise ValueError("Invalid axis mapping")
        axis, sign, label = MOVEMENTS[action]
        values = [sign * direction if name == axis else 0 for name, direction in axes]
        left, right = values[:2], values[2:]
        return {
            "left_xy": left if any(left) else None,
            "right_xy": right if any(right) else None,
            "valid_for_ms": 2000,
            "observation_id": observation_id,
            "reason": f"{translate(label, language)} · {subgoal.goal}"[:2000],
        }
