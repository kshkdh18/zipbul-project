"""One typed choice from the Decisions API, without generated control arguments."""

import math
import os
import time
from dataclasses import dataclass

from dotenv import dotenv_values
from openai import OpenAI

from .actions import ACTION_DESCRIPTIONS, STATUS_ACTIONS
from .astra import observation_content
from .planning import CONTEXT

LUNA_SYSTEM = (
    CONTEXT
    + """
Choose exactly one next_action to advance current_subgoal, using its completion_criteria.
Actions move the CAMERA, not the target object. For view-centering prefer YAW over sideways translation:
target to RIGHT of center -> YAW_RIGHT; target to LEFT -> YAW_LEFT.
Target ABOVE center -> ASCEND; target BELOW center -> DESCEND. Center means the IMAGE midpoint.
For a centering goal, first locate the target relative to BOTH image midlines. If it is horizontally
centered, do NOT choose YAW_LEFT or YAW_RIGHT: correct vertical offset with ASCEND or DESCEND.
If it is centered on both axes, choose SUBGOAL_DONE. Do not rotate merely because yaw is listed first.
If there is both horizontal and vertical offset, correct the larger relative offset first.
For an exploration subgoal follow its allowed actions instead of this centering preference.
The overall goal is context, not permission to bypass the current subgoal.
Use CURRENT image for the decision; compare the previous image and executed actions if provided.
Consider current sticks and continuous_hold_ms; a new action updates the current input.
WAIT releases input and keeps observing. SUBGOAL_DONE needs visible evidence of the completion criteria.
REPLAN asks Astra for another approach, not human takeover. Choose from the supplied actions only.
During completion_verification assess completion afresh; if incomplete choose an appropriate action.
"""
)


@dataclass(frozen=True)
class ActionChoice:
    action: str
    confidence: float
    probabilities: dict
    latency: float = 0
    usage: dict | None = None
    response_id: str = ""


def parse_choice(response, allowed):
    if len(response.answers) != 1:
        raise ValueError("Exactly one Decisions answer required")
    answer = response.answers[0]
    if answer.type == "refusal":
        raise RuntimeError("Luna Decisions가 판단을 거부했습니다.")
    if answer.type != "choice" or answer.name != "next_action":
        raise ValueError("Unexpected Decisions answer type/name")
    if not isinstance(answer.choice, str) or answer.choice not in allowed:
        raise ValueError("Luna selected an action outside the allowed set")
    values = [answer.confidence, *(p.probability for p in answer.probabilities)]
    if any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1 for v in values):
        raise ValueError("Invalid Decisions probability")
    options = [p.value for p in answer.probabilities]
    if (
        any(not isinstance(v, str) for v in options)
        or len(set(options)) != len(options)
        or set(options) != set(allowed)
    ):
        raise ValueError("Invalid Decisions probability options")
    return answer.choice, float(answer.confidence), {p.value: p.probability for p in answer.probabilities}


class LunaDecider:
    model = "gpt-6-luna"

    def __init__(self, client=None):
        key = os.getenv("OPENAI_API_KEY") or dotenv_values(".env.local").get("OPENAI_API_KEY")
        if client is None and not key:
            raise RuntimeError("OPENAI_API_KEY를 환경변수 또는 .env.local에 설정하세요.")
        self.client = client or OpenAI(api_key=key, timeout=15, max_retries=0)

    def decide(self, observation, previous=None):
        content = observation_content(observation, previous)
        subgoal = observation.metadata["current_subgoal"]
        allowed = list(subgoal["allowed_actions"]) + list(STATUS_ACTIONS)
        choices = [
            {"value": action, "description": ACTION_DESCRIPTIONS[action]}
            for action in subgoal["allowed_actions"]
        ]
        choices.extend(
            {"value": action, "description": description} for action, description in STATUS_ACTIONS.items()
        )
        started = time.monotonic()
        try:
            response = self.client.decisions.create(
                model=self.model,
                input=[{"role": "user", "content": content}],
                questions=[
                    {"name": "next_action", "type": "choice", "instructions": LUNA_SYSTEM, "choices": choices}
                ],
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            raise RuntimeError(
                f"OpenAI {type(exc).__name__}" + (f" (HTTP {status})" if status else "")
            ) from None
        latency = time.monotonic() - started
        if latency > 15:
            raise TimeoutError("Luna response exceeded 15 seconds")
        action, confidence, probabilities = parse_choice(response, allowed)
        usage = response.usage.model_dump() if response.usage else {}
        return ActionChoice(
            action, confidence, probabilities, latency, usage, getattr(response, "_request_id", "") or ""
        )

    def close(self):
        self.client.close()
