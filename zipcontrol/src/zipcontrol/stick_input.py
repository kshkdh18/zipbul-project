"""Map model directions to the drag radius explicitly selected by the operator."""

import math

from .guard import targets


def drag_fraction(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0.05 <= value <= 1.0
    ):
        raise ValueError("드래그 크기는 보정 반경의 5~100%여야 합니다.")
    return float(value)


def directed_targets(left, right, strength=1.0):
    """Preserve null/neutral and direction, applying the selected radius to nonzero vectors."""
    strength = drag_fraction(strength)
    result = []
    for xy in targets(left, right):
        if xy is None:
            result.append(None)
        else:
            magnitude = math.hypot(*xy)
            result.append([v / magnitude * strength for v in xy] if magnitude else [0.0, 0.0])
    return result
