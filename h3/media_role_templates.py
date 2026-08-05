"""Text-only reference role assembly for the unified H3 prompt director.

These helpers never inspect, decode, upload, serialize, or otherwise access
the connected video/audio payloads.  They only receive socket indices and the
roles typed by the user.
"""

from __future__ import annotations

import json
import re
from typing import Dict, Iterable, List, Optional, Tuple

from .models import PromptPlan, ValidationResult
from .prompt_renderer import render_h3_prompt_en


REFERENCE_PRIORITY_OPTIONS = ["图片身份优先", "参考视频结构优先", "用户自定义"]
_ROLE_LINE = re.compile(r"^\s*(视频|video|音频|audio)\s*_?\s*([1-3])\s*[:：]\s*(.+?)\s*$", re.IGNORECASE)


def _normalized_indices(indices: Optional[Iterable[int]], count: int) -> List[int]:
    if indices is None:
        return list(range(1, count + 1))
    return sorted({int(index) for index in indices if 1 <= int(index) <= 3})


def parse_role_lines(
    value: str,
    *,
    expected_kind: str,
    count: int,
    allowed_indices: Optional[Iterable[int]] = None,
) -> Tuple[List[Dict[str, object]], ValidationResult]:
    result = ValidationResult()
    definitions: List[Dict[str, object]] = []
    seen = set()
    valid_indices = set(_normalized_indices(allowed_indices, count))
    unnumbered_lines: List[str] = []
    for raw_line in (value or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _ROLE_LINE.match(line)
        if not match:
            unnumbered_lines.append(line)
            continue
        kind, number, roles_text = match.groups()
        normalized_kind = "video" if kind.lower() in {"视频", "video"} else "audio"
        if normalized_kind != expected_kind:
            result.add_error("media_role_kind", f"{line} 的素材类型与当前输入不符。")
            continue
        index = int(number)
        if index not in valid_indices:
            connected = ", ".join(str(item) for item in sorted(valid_indices)) or "无"
            result.add_error("media_role_index", f"{expected_kind}{index} 未连接；当前已连接编号：{connected}。")
            continue
        if index in seen:
            result.add_error("media_role_duplicate", f"{expected_kind}{index} 被重复声明。")
            continue
        seen.add(index)
        roles = [part.strip() for part in re.split(r"[,，、;；]", roles_text) if part.strip()]
        definitions.append({"id": f"{expected_kind}_{index}", "roles": roles})

    # With exactly one connected reference, there is no ambiguity: accepting a
    # natural-language role is friendlier than making the user type a redundant
    # number.  Multi-reference inputs still require numbering so roles cannot
    # accidentally be assigned to the wrong opaque audio/video socket.
    if unnumbered_lines:
        if len(valid_indices) == 1 and not definitions:
            index = next(iter(valid_indices))
            roles = [
                part.strip()
                for line in unnumbered_lines
                for part in re.split(r"[,，、;；]", line)
                if part.strip()
            ]
            definitions.append({"id": f"{expected_kind}_{index}", "roles": roles})
            result.add_warning(
                "media_role_auto_indexed",
                f"已将未编号职责自动归入已连接的 {expected_kind}{index}。",
            )
        else:
            for line in unnumbered_lines:
                result.add_error(
                    "media_role_format",
                    f"职责格式无效：{line}。接入多路素材时请使用“{expected_kind}1：职责A、职责B”。",
                )
    if valid_indices and not definitions:
        result.add_warning("media_role_missing", f"已连接 {len(valid_indices)} 个 {expected_kind} 参考，但没有填写职责描述。")
    return definitions, result.finalize()


def build_media_manifest(
    video_count: int,
    video_roles: str,
    audio_count: int,
    audio_roles: str,
    reference_priority: str,
    custom_priority_rule: str,
    strict_unmentioned_keep: bool,
    *,
    video_indices: Optional[Iterable[int]] = None,
    audio_indices: Optional[Iterable[int]] = None,
) -> Tuple[Dict[str, object], ValidationResult]:
    connected_video_indices = _normalized_indices(video_indices, video_count)
    connected_audio_indices = _normalized_indices(audio_indices, audio_count)
    videos, video_result = parse_role_lines(
        video_roles,
        expected_kind="video",
        count=len(connected_video_indices),
        allowed_indices=connected_video_indices,
    )
    audios, audio_result = parse_role_lines(
        audio_roles,
        expected_kind="audio",
        count=len(connected_audio_indices),
        allowed_indices=connected_audio_indices,
    )
    result = ValidationResult(
        errors=video_result.errors + audio_result.errors,
        warnings=video_result.warnings + audio_result.warnings,
    )
    if not 0 <= len(connected_video_indices) <= 3:
        result.add_error("video_count", "视频数量必须在 0 到 3 段之间。")
    if not 0 <= len(connected_audio_indices) <= 3:
        result.add_error("audio_count", "音频数量必须在 0 到 3 段之间。")
    if len(connected_video_indices) + len(connected_audio_indices) > 6:
        result.add_error("media_count", "视频和音频参考合计不能超过 6 个。")
    priority = (custom_priority_rule or "").strip() if reference_priority == "用户自定义" else reference_priority
    if reference_priority == "用户自定义" and not priority:
        result.add_error("reference_priority", "选择“用户自定义”时请填写优先级规则。")
    manifest: Dict[str, object] = {
        "videos": videos,
        "audios": audios,
        "connected_video_indices": connected_video_indices,
        "connected_audio_indices": connected_audio_indices,
        "reference_priority": priority,
        "strict_unmentioned_keep": bool(strict_unmentioned_keep),
        "media_analyzed": False,
        "media_sent_to_llm": False,
    }
    return manifest, result.finalize()


def render_with_media_roles(plan: PromptPlan, manifest: Dict[str, object]) -> str:
    """Render the reference layout without asserting inferred media facts."""
    prompt = render_h3_prompt_en(plan, force_reference_format=True)
    video_lines = []
    declared_video_indices = set()
    for item in manifest.get("videos", []):
        roles = ", ".join(item.get("roles", []))
        index = str(item.get("id", "")).split("_")[-1]
        declared_video_indices.add(index)
        video_lines.append(f"<Video {index}> only provides user-declared roles: {roles}.")
    for index in manifest.get("connected_video_indices", []):
        if str(index) not in declared_video_indices:
            video_lines.append(f"<Video {index}> is connected with no declared semantic role; preserve it without inferring media details.")
    audio_lines = []
    declared_audio_indices = set()
    for item in manifest.get("audios", []):
        roles = ", ".join(item.get("roles", []))
        index = str(item.get("id", "")).split("_")[-1]
        declared_audio_indices.add(index)
        audio_lines.append(f"<Audio {index}> only provides user-declared roles: {roles}.")
    for index in manifest.get("connected_audio_indices", []):
        if str(index) not in declared_audio_indices:
            audio_lines.append(f"<Audio {index}> is connected with no declared semantic role; preserve it without inferring media details.")
    priority = str(manifest.get("reference_priority", "")).strip()
    retention_parts = []
    if priority:
        retention_parts.append(f"Reference priority: {priority}.")
    if manifest.get("strict_unmentioned_keep"):
        retention_parts.append("Preserve all unmentioned content; do not infer new media details.")
    insert = " ".join(video_lines + audio_lines + retention_parts).strip()
    marker = "retention_analysis:\n"
    if insert and marker in prompt:
        prompt = prompt.replace(marker, marker + insert + "\n", 1)
    return prompt


def manifest_json(manifest: Dict[str, object]) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2)
