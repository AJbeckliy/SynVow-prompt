"""Render a validated PromptPlan into an H3-facing English prompt and Chinese review copy."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, List

from .models import PromptPlan, PromptShot
from .task_router import is_reference_mode


def _flatten_text(value: Any) -> List[str]:
    if value is None or value is False:
        return []
    if isinstance(value, (list, tuple, set)):
        return [item for child in value for item in _flatten_text(child)]
    text = str(value).strip()
    return [text] if text else []


def _dedupe(values: Iterable[object]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        for text in _flatten_text(value):
            key = " ".join(text.lower().split())
            if key and key not in seen:
                seen.add(key)
                result.append(text)
    return result


def _join(values: Iterable[object]) -> str:
    return "; ".join(_dedupe(values))


def _shot_en(shot: PromptShot, *, include_sound: bool = True) -> str:
    parts = [
        f"[Shot {shot.index}, {shot.start:.1f}-{shot.end:.1f}s]",
        shot.subject_action,
        shot.performance and f"Performance: {shot.performance}",
        shot.environment_response and f"Environment: {shot.environment_response}",
        shot.visual_detail and f"Visual: {shot.visual_detail}",
        shot.camera,
        shot.state_change,
        shot.beat_cue and f"Beat: {shot.beat_cue}",
        shot.transition_out and f"Transition: {shot.transition_out}",
        include_sound and shot.sound_instruction and f"Sound: {shot.sound_instruction}",
    ]
    return _join(parts)


def _shot_zh(shot: PromptShot) -> str:
    parts = [
        f"{shot.start:.1f}-{shot.end:.1f} 秒",
        shot.subject_action,
        shot.performance and f"表演：{shot.performance}",
        shot.environment_response and f"环境反应：{shot.environment_response}",
        shot.visual_detail and f"视觉细节：{shot.visual_detail}",
        shot.camera,
        shot.state_change,
        shot.beat_cue and f"节奏：{shot.beat_cue}",
        shot.transition_out and f"转场：{shot.transition_out}",
        shot.sound_instruction and f"声音：{shot.sound_instruction}",
    ]
    return "；".join(_flatten_text(parts))


def _image_definitions(plan: PromptPlan) -> str:
    definitions = []
    for reference in plan.image_references:
        role_text = _join(reference.roles) or "visual reference"
        feature_text = _join(reference.observed_features)
        item = f"<{reference.id.replace('_', ' ').title()}> is responsible for {role_text}"
        if feature_text:
            item += f"; keep {feature_text}"
        definitions.append(item + ".")
    definitions.extend(_subject_definitions(plan))
    return " ".join(definitions) or "No external image reference is used."


def _subject_definitions(plan: PromptPlan) -> List[str]:
    """Render optional subject locks while accepting a tolerant JSON schema."""
    definitions: List[str] = []
    for index, subject in enumerate(plan.subjects, start=1):
        if not isinstance(subject, dict):
            continue
        name = _join([subject.get("id"), subject.get("name"), subject.get("label")]) or f"Subject {index}"
        role = _join([subject.get("role"), subject.get("narrative_role")])
        identity_locks = _dedupe(
            [
                subject.get("identity_lock"),
                subject.get("must_keep"),
                subject.get("appearance"),
                subject.get("wardrobe"),
                subject.get("distinctive_features"),
            ]
        )
        continuity = _join([subject.get("continuity_rule"), subject.get("continuity")])
        if not role and not identity_locks and not continuity:
            continue
        item = f"<{name}>"
        if role:
            item += f" is {role}"
        if identity_locks:
            item += f"; keep {'; '.join(identity_locks)}"
        if continuity:
            item += f"; continuity: {continuity}"
        definitions.append(item + ".")
    return definitions


def _exact_dialogue(plan: PromptPlan) -> str:
    dialogue = (plan.exact_dialogue or "").strip()
    return f"<d>[Chinese] {dialogue}</d>" if dialogue else ""


_VISUAL_FIELDS = (
    ("creative_intent", "Creative intent"),
    ("look", "Look"),
    ("lighting", "Lighting"),
    ("palette", "Palette"),
    ("texture", "Texture"),
    ("composition", "Composition"),
    ("visual_motif", "Visual motif"),
    ("continuity_rule", "Continuity"),
)
_CAMERA_FIELDS = (
    ("camera_grammar", "Camera grammar"),
    ("performance_rule", "Performance rule"),
    ("editing_rhythm", "Editing rhythm"),
)


def _system_layer(plan: PromptPlan, fields: Iterable[tuple[str, str]]) -> str:
    visual_system = plan.visual_system if isinstance(plan.visual_system, dict) else {}
    parts = []
    for key, label in fields:
        text = _join([visual_system.get(key)])
        if text:
            parts.append(f"{label}: {text}")
    return "; ".join(parts)


def _retention_analysis(plan: PromptPlan) -> str:
    parts = _dedupe(plan.requirements.get("must_keep", []))
    if plan.subjects:
        parts.append("Keep each declared subject's identity lock, wardrobe, role, and relationship continuity across all shots")
    no_go = _dedupe([plan.requirements.get("must_not_appear", []), plan.constraints])
    if no_go:
        parts.append("No-go constraints: " + "; ".join(no_go))
    return _join(parts) or "Keep each declared reference within its assigned role."


def _sound_key(value: str) -> str:
    return " ".join(value.lower().split())


def _render_shots(plan: PromptPlan) -> str:
    """Keep repeated opaque-audio cues global instead of copying them per shot."""
    sound_keys = [_sound_key(shot.sound_instruction) for shot in plan.shots if shot.sound_instruction.strip()]
    counts = Counter(sound_keys)
    return "\n".join(
        _shot_en(
            shot,
            include_sound=not shot.sound_instruction.strip() or counts[_sound_key(shot.sound_instruction)] == 1,
        )
        for shot in plan.shots
    )


def _repeated_shot_sounds(plan: PromptPlan) -> List[str]:
    sound_values = [shot.sound_instruction for shot in plan.shots if shot.sound_instruction.strip()]
    counts = Counter(_sound_key(value) for value in sound_values)
    return _dedupe(value for value in sound_values if counts[_sound_key(value)] > 1)


def _detailed_description(plan: PromptPlan) -> str:
    parts: List[str] = []
    alignment = _frame_alignment(plan)
    if alignment:
        parts.append(alignment)
    visual_direction = _system_layer(plan, _VISUAL_FIELDS)
    if visual_direction:
        parts.append("Global visual direction:\n" + visual_direction)
    camera_grammar = _system_layer(plan, _CAMERA_FIELDS)
    if camera_grammar:
        parts.append("Camera and performance grammar:\n" + camera_grammar)
    shots = _render_shots(plan)
    if shots:
        parts.append("Timeline:\n" + shots)
    return "\n".join(parts)


def render_h3_prompt_en(plan: PromptPlan, *, force_reference_format: bool = False) -> str:
    """Render a stable structured prompt; it is output-only and does not call H3."""
    detailed_description = _detailed_description(plan)
    sound_values = _dedupe(
        [plan.sound_system.get("overall_soundscape", ""), _exact_dialogue(plan)] + _repeated_shot_sounds(plan)
    )
    if sound_values:
        soundscape = "; ".join(sound_values)
    elif any(shot.sound_instruction.strip() for shot in plan.shots):
        soundscape = "Use the shot-specific sound cues in the timeline."
    else:
        soundscape = "Use only the diegetic sound explicitly described in each shot."
    music = _text_from_mapping(plan.sound_system, "non_diegetic_music") or "No non-diegetic music unless explicitly required."
    if force_reference_format or is_reference_mode(plan.task_mode):
        return "\n".join(
            [
                "subject_definitions:",
                _image_definitions(plan),
                "summary:",
                _join(plan.requirements.get("must_appear", [])) or "Follow the requested visual goal.",
                "retention_analysis:",
                _retention_analysis(plan),
                "detailed_description:",
                detailed_description,
                "overall_soundscape:",
                soundscape,
                "non_diegetic_music:",
                music,
            ]
        ).strip()

    return "\n".join(
        [
            "integrated_multimodal_description:",
            detailed_description,
            "overall_soundscape:",
            soundscape,
            "non_diegetic_music:",
            music,
        ]
    ).strip()


def _frame_alignment(plan: PromptPlan) -> str:
    """Respect the actual connected image socket number, including sparse inputs."""
    image_numbers = [reference.id.replace("image_", "") for reference in plan.image_references]
    first = image_numbers[0] if image_numbers else "1"
    second = image_numbers[1] if len(image_numbers) > 1 else "2"
    instructions = {
        "i2va": f"Use Image {first} as the exact opening frame; describe motion evolving naturally from it.",
        "l2va": f"Use Image {first} as the exact final frame; lead the motion naturally into it.",
        "fl2va": f"Use Image {first} as the exact opening frame and Image {second} as the exact final frame; make the transition physically continuous.",
    }
    return instructions.get(plan.task_mode, "")


def _text_from_mapping(mapping: dict, key: str) -> str:
    value = mapping.get(key, "") if isinstance(mapping, dict) else ""
    return str(value).strip() if value else ""


def render_preview_zh(plan: PromptPlan) -> str:
    lines = [
        f"任务：{plan.task_mode}｜{plan.duration_seconds} 秒；{plan.aspect_ratio}",
        "创作目标：" + (_join(plan.requirements.get("must_appear", [])) or "按用户需求执行"),
    ]
    if plan.image_references:
        references = []
        for ref in plan.image_references:
            references.append(f"{ref.id}：{_join(ref.roles) or '待确认职责'}")
        lines.append("图片职责：" + "；".join(references))
    if plan.visual_system:
        visual_direction = _system_layer(plan, _VISUAL_FIELDS)
        if visual_direction:
            lines.append("全片视觉：" + visual_direction)
    lines.append("分镜：")
    lines.extend(f"- {_shot_zh(shot)}" for shot in plan.shots)
    if plan.exact_dialogue:
        lines.append(f"准确中文对白：{plan.exact_dialogue}")
    if plan.text_whitelist:
        lines.append("画面文字白名单：" + "、".join(plan.text_whitelist))
    if plan.constraints:
        lines.append("约束：" + "；".join(plan.constraints))
    return "\n".join(lines)
