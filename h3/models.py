"""Typed data exchanged by the H3 prompt nodes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _text_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


@dataclass
class H3ImageReference:
    id: str
    roles: List[str] = field(default_factory=list)
    observed_features: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: Any, fallback_id: str) -> "H3ImageReference":
        value = value if isinstance(value, dict) else {}
        return cls(
            id=_text(value.get("id")) or fallback_id,
            roles=_text_list(value.get("roles")),
            observed_features=_text_list(value.get("observed_features")),
        )


@dataclass
class PromptShot:
    index: int
    start: float
    end: float
    camera: str = ""
    subject_action: str = ""
    performance: str = ""
    environment_response: str = ""
    visual_detail: str = ""
    beat_cue: str = ""
    state_change: str = ""
    transition_out: str = ""
    sound_instruction: str = ""

    @classmethod
    def from_dict(cls, value: Any, fallback_index: int) -> "PromptShot":
        value = value if isinstance(value, dict) else {}
        try:
            index = int(value.get("index", fallback_index))
        except (TypeError, ValueError):
            index = fallback_index
        try:
            start = float(value.get("start", 0.0))
        except (TypeError, ValueError):
            start = 0.0
        try:
            end = float(value.get("end", 0.0))
        except (TypeError, ValueError):
            end = 0.0
        return cls(
            index=index,
            start=start,
            end=end,
            camera=_text(value.get("camera")),
            subject_action=_text(value.get("subject_action", value.get("subject_actions"))),
            performance=_text(value.get("performance")),
            environment_response=_text(value.get("environment_response", value.get("environment"))),
            visual_detail=_text(value.get("visual_detail", value.get("visual_details"))),
            beat_cue=_text(value.get("beat_cue", value.get("rhythm_cue"))),
            state_change=_text(value.get("state_change")),
            transition_out=_text(value.get("transition_out")),
            sound_instruction=_text(value.get("sound_instruction")),
        )


@dataclass
class PromptPlan:
    version: str = "0.1"
    task_mode: str = "t2va"
    content_mode: str = "auto"
    duration_seconds: int = 5
    aspect_ratio: str = "16:9"
    requirements: Dict[str, List[str]] = field(default_factory=dict)
    image_references: List[H3ImageReference] = field(default_factory=list)
    subjects: List[Dict[str, Any]] = field(default_factory=list)
    shots: List[PromptShot] = field(default_factory=list)
    visual_system: Dict[str, Any] = field(default_factory=dict)
    sound_system: Dict[str, Any] = field(default_factory=dict)
    constraints: List[str] = field(default_factory=list)
    exact_dialogue: str = ""
    text_whitelist: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: Any) -> "PromptPlan":
        if not isinstance(value, dict):
            raise ValueError("PromptPlan 必须是 JSON 对象")
        requirements = value.get("requirements") if isinstance(value.get("requirements"), dict) else {}
        normalized_requirements = {
            key: _text_list(requirements.get(key))
            for key in ("must_appear", "must_keep", "allowed_change", "must_not_appear")
        }
        image_values = value.get("image_references", value.get("references", []))
        image_values = image_values if isinstance(image_values, list) else []
        shot_values = value.get("shots", [])
        shot_values = shot_values if isinstance(shot_values, list) else []
        subjects = value.get("subjects", [])
        return cls(
            version=_text(value.get("version")) or "0.1",
            task_mode=_text(value.get("task_mode")).lower() or "t2va",
            content_mode=_text(value.get("content_mode")).lower() or "auto",
            duration_seconds=int(value.get("duration_seconds", 5)),
            aspect_ratio=_text(value.get("aspect_ratio")) or "16:9",
            requirements=normalized_requirements,
            image_references=[
                H3ImageReference.from_dict(item, f"image_{index}")
                for index, item in enumerate(image_values, start=1)
            ],
            subjects=[item for item in subjects if isinstance(item, dict)] if isinstance(subjects, list) else [],
            shots=[PromptShot.from_dict(item, index) for index, item in enumerate(shot_values, start=1)],
            visual_system=value.get("visual_system", {}) if isinstance(value.get("visual_system"), dict) else {},
            sound_system=value.get("sound_system", {}) if isinstance(value.get("sound_system"), dict) else {},
            constraints=_text_list(value.get("constraints")),
            exact_dialogue=_text(value.get("exact_dialogue")),
            text_whitelist=_text_list(value.get("text_whitelist")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationIssue:
    code: str
    message: str
    severity: str = "error"

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


@dataclass
class ValidationResult:
    errors: List[ValidationIssue] = field(default_factory=list)
    warnings: List[ValidationIssue] = field(default_factory=list)
    score: int = 100

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def add_error(self, code: str, message: str) -> None:
        self.errors.append(ValidationIssue(code, message, "error"))

    def add_warning(self, code: str, message: str) -> None:
        self.warnings.append(ValidationIssue(code, message, "warning"))

    def finalize(self) -> "ValidationResult":
        self.score = max(0, 100 - len(self.errors) * 20 - len(self.warnings) * 5)
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": [item.to_dict() for item in self.errors],
            "warnings": [item.to_dict() for item in self.warnings],
            "score": self.score,
        }
