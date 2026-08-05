"""Offline mechanical checks for H3 prompt plans and rendered prompts."""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence

from .models import PromptPlan, ValidationResult
from .task_router import ASPECT_RATIO_OPTIONS, frame_requirements


MAX_PROMPT_CHARS = 7000
TIMELINE_TOLERANCE = 0.05
_PLACEHOLDER = re.compile(r"\{\{.+?\}\}|\b(?:TODO|TBD)\b", re.IGNORECASE)


def _integer_duration(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 4 <= value <= 15


def _source_indices(indices: Optional[Sequence[int]], count: int, maximum: int) -> List[int]:
    if indices is None:
        return list(range(1, count + 1))
    return sorted({int(index) for index in indices if 1 <= int(index) <= maximum})


def validate_media_contract(
    *,
    image_count: int = 0,
    video_count: int = 0,
    audio_count: int = 0,
    task_mode: str = "t2va",
) -> ValidationResult:
    """Validate connection counts only; never access the connected payloads."""
    result = ValidationResult()
    if not 0 <= image_count <= 9:
        result.add_error("image_count", "图片数量必须在 0 到 9 张之间。")
    if not 0 <= video_count <= 3:
        result.add_error("video_count", "视频数量必须在 0 到 3 段之间。")
    if not 0 <= audio_count <= 3:
        result.add_error("audio_count", "音频数量必须在 0 到 3 段之间。")
    if image_count + video_count + audio_count > 12:
        result.add_error("media_total", "图片、视频和音频合计不能超过 12 个参考素材。")
    minimum, maximum = frame_requirements(task_mode)
    if not minimum <= image_count <= maximum:
        result.add_error("task_frames", f"{task_mode} 需要 {minimum} 到 {maximum} 张图片，当前为 {image_count} 张。")
    if audio_count and not (image_count or video_count):
        result.add_error("audio_only", "音频不能单独作为参考素材。")
    return result.finalize()


def validate_prompt_plan(
    plan: PromptPlan,
    *,
    image_count: int = 0,
    video_count: int = 0,
    audio_count: int = 0,
    image_indices: Optional[Sequence[int]] = None,
    task_mode: Optional[str] = None,
    strict_mode: bool = True,
) -> ValidationResult:
    result = ValidationResult()
    mode = task_mode or plan.task_mode
    if not _integer_duration(plan.duration_seconds):
        result.add_error("duration", "时长必须是 4 到 15 秒的整数。")
    if plan.aspect_ratio not in ASPECT_RATIO_OPTIONS:
        result.add_error("aspect_ratio", "画幅必须是受支持的标准比例。")
    media_result = validate_media_contract(
        image_count=image_count,
        video_count=video_count,
        audio_count=audio_count,
        task_mode=mode,
    )
    result.errors.extend(media_result.errors)
    result.warnings.extend(media_result.warnings)

    expected_start = 0.0
    if not plan.shots:
        result.add_error("timeline_empty", "PromptPlan 必须至少包含一个时间段。")
    for position, shot in enumerate(plan.shots, start=1):
        if shot.end <= shot.start:
            result.add_error("timeline_order", f"镜头 {position} 的结束时间必须晚于开始时间。")
        if abs(shot.start - expected_start) > TIMELINE_TOLERANCE:
            issue = "timeline_gap" if shot.start > expected_start else "timeline_overlap"
            result.add_error(issue, f"镜头 {position} 的时间轴不连续。")
        expected_start = shot.end
    if plan.shots and abs(expected_start - plan.duration_seconds) > TIMELINE_TOLERANCE:
        result.add_error("timeline_boundary", "时间轴必须覆盖且仅覆盖目标时长。")

    valid_image_ids = {f"image_{index}" for index in _source_indices(image_indices, image_count, 9)}
    for reference in plan.image_references:
        if reference.id not in valid_image_ids:
            result.add_error("image_reference", f"引用的图片编号不存在：{reference.id}。")
        if not reference.roles:
            result.add_warning("image_role", f"{reference.id} 没有明确参考职责。")
    if mode == "one_take" or plan.content_mode == "one_take":
        all_transitions = " ".join(shot.transition_out.lower() for shot in plan.shots)
        if any(marker in all_transitions for marker in ("cut", "hard cut", "切镜", "硬切")):
            result.add_error("one_take_cut", "一镜到底不能包含硬切或切镜。")
    combined = " ".join(
        f"{shot.camera} {shot.subject_action} {shot.state_change}".lower() for shot in plan.shots
    )
    if "static" in combined and any(marker in combined for marker in ("orbit", "aerial", "drone", "环绕", "航拍")):
        result.add_error("camera_conflict", "固定机位不能同时要求环绕、航拍或大范围跟随。")
    if plan.content_mode == "action":
        for shot in plan.shots:
            action_text = f"{shot.subject_action} {shot.state_change}".strip()
            if action_text and not shot.state_change:
                result.add_warning("action_feedback", f"镜头 {shot.index} 的动作缺少明确的结果或受力反馈。")
    if strict_mode and not plan.requirements.get("must_appear"):
        result.add_warning("requirements", "未记录明确的必须出现需求，可能降低可控性。")
    return result.finalize()


def validate_rendered_prompt(prompt: str, *, text_whitelist: Optional[Iterable[str]] = None) -> ValidationResult:
    result = ValidationResult()
    content = (prompt or "").strip()
    if not content:
        result.add_error("prompt_empty", "提示词不能为空。")
        return result.finalize()
    if len(content) > MAX_PROMPT_CHARS:
        result.add_error("prompt_length", f"提示词超过 {MAX_PROMPT_CHARS} 字符限制。")
    if _PLACEHOLDER.search(content):
        result.add_error("placeholder", "提示词仍包含 TODO 或模板占位符。")
    whitelist = [item for item in (text_whitelist or []) if item]
    if whitelist:
        quoted_chinese = re.findall(r'"([^"\n]+)"', content)
        unexpected = [value for value in quoted_chinese if any("\u4e00" <= char <= "\u9fff" for char in value) and value not in whitelist]
        if unexpected:
            result.add_warning("text_whitelist", "发现不在文字白名单中的中文引号文本。")
    return result.finalize()


def merge_results(*results: ValidationResult) -> ValidationResult:
    merged = ValidationResult()
    for item in results:
        merged.errors.extend(item.errors)
        merged.warnings.extend(item.warnings)
    return merged.finalize()
