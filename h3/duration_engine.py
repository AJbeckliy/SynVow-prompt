"""Duration profiles are data-driven so prompt modules stay free of duplicates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


_PROFILE_PATH = Path(__file__).resolve().parent.parent / "prompts" / "h3" / "duration_profiles.json"


def load_duration_profiles() -> Dict[str, Dict[str, Dict[str, float]]]:
    with _PROFILE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _interpolate(left: float, right: float, factor: float) -> float:
    return round(left + (right - left) * factor, 2)


def duration_budget(content_mode: str, duration_seconds: int) -> Dict[str, Any]:
    """Return the nearest/interpolated pacing profile for an integer 4--15s clip."""
    if not isinstance(duration_seconds, int) or not 4 <= duration_seconds <= 15:
        raise ValueError("时长必须是 4 到 15 的整数")
    profiles = load_duration_profiles()
    mode = content_mode if content_mode in profiles else "default"
    anchors = sorted(int(key) for key in profiles[mode])
    if duration_seconds < anchors[0]:
        # The first calibrated profile is 5s.  Four-second clips scale down
        # its pacing budget instead of being rejected or silently rounded up.
        factor = duration_seconds / anchors[0]
        result: Dict[str, Any] = {"duration_seconds": duration_seconds, "interpolated_from": [anchors[0]]}
        for key, value in profiles[mode][str(anchors[0])].items():
            if isinstance(value, list):
                lower = value[0] * factor
                upper = value[1] * factor
                if key in {"shot_count", "action_count"}:
                    lower, upper = max(1, round(lower)), max(1, round(upper))
                else:
                    lower, upper = round(lower, 2), round(upper, 2)
                result[key] = [lower, upper]
            else:
                result[key] = round(float(value) * factor, 2)
        return result
    if duration_seconds in anchors:
        return {"duration_seconds": duration_seconds, **profiles[mode][str(duration_seconds)]}
    lower = max(anchor for anchor in anchors if anchor < duration_seconds)
    upper = min(anchor for anchor in anchors if anchor > duration_seconds)
    factor = (duration_seconds - lower) / (upper - lower)
    result: Dict[str, Any] = {"duration_seconds": duration_seconds, "interpolated_from": [lower, upper]}
    for key, left_value in profiles[mode][str(lower)].items():
        right_value = profiles[mode][str(upper)][key]
        if isinstance(left_value, list):
            result[key] = [
                _interpolate(float(left_value[0]), float(right_value[0]), factor),
                _interpolate(float(left_value[1]), float(right_value[1]), factor),
            ]
        else:
            result[key] = _interpolate(float(left_value), float(right_value), factor)
    return result
