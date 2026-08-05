"""UI values and deterministic task-mode routing for the H3 prompt node."""

from __future__ import annotations

from typing import Dict, List, Tuple


TASK_MODE_LABELS: Dict[str, str] = {
    "自动判断": "auto",
    "文生视频": "t2va",
    "首帧图生视频": "i2va",
    "尾帧图生视频": "l2va",
    "首尾帧图生视频": "fl2va",
    "多图片参考生成": "image_reference",
    "多参考视频（图/视频/音频）": "multimodal_reference",
}
CONTENT_MODE_LABELS: Dict[str, str] = {
    "自动判断": "auto",
    "文戏对白": "dialogue",
    "武戏打斗": "action",
    "电商广告": "ecommerce",
    "数字人口播": "digital_human",
    "舞蹈大动态": "dance",
    "一镜到底": "one_take",
    "变身特效": "transformation",
    "动画风格化": "animation",
    "九宫格分镜": "storyboard",
}
CONTENT_MODE_LABELS["音乐 MV / 情绪短片"] = "music_video"

TASK_MODE_OPTIONS: List[str] = list(TASK_MODE_LABELS)
CONTENT_MODE_OPTIONS: List[str] = list(CONTENT_MODE_LABELS)
ASPECT_RATIO_OPTIONS = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"]
MOTION_OPTIONS = ["克制", "标准", "高动态", "极限动态"]
SHOT_OPTIONS = ["自动判断", "单镜头", "多镜头", "一镜到底"]
OUTPUT_FORMAT_OPTIONS = ["官方英文结构化+中文预览", "仅官方英文结构化", "仅中文导演预览"]


def normalize_task_mode(
    value: str,
    image_count: int,
    video_count: int = 0,
    audio_count: int = 0,
) -> Tuple[str, List[str]]:
    """Resolve auto mode without inspecting any video or audio payload."""
    requested = TASK_MODE_LABELS.get(value, str(value or "auto").lower())
    warnings: List[str] = []
    has_non_image_reference = bool(video_count or audio_count)
    if requested == "auto":
        if has_non_image_reference:
            return "multimodal_reference", warnings
        if image_count == 0:
            return "t2va", warnings
        if image_count == 1:
            return "i2va", warnings
        return "image_reference", warnings

    if requested == "t2va" and (image_count or has_non_image_reference):
        warnings.append("文生视频模式连接了参考素材；节点仍会保留该模式，但会把已连接的素材编号和职责写入提示词。")
    if requested == "image_reference" and has_non_image_reference:
        warnings.append("多图片参考模式连接了视频或音频；如要让任务语义更清晰，可选择“多参考视频（图/视频/音频）”。")
    return requested, warnings


def normalize_content_mode(value: str, user_request: str = "") -> str:
    requested = CONTENT_MODE_LABELS.get(value, str(value or "auto").lower())
    if requested != "auto":
        return requested
    request = str(user_request or "").lower()
    if any(keyword in request for keyword in ("mv", "音乐视频", "音乐短片", "情绪短片", "music video")):
        return "music_video"
    return "auto"


def frame_requirements(task_mode: str) -> Tuple[int, int]:
    if task_mode in {"i2va", "l2va"}:
        return 1, 1
    if task_mode == "fl2va":
        return 2, 2
    if task_mode == "image_reference":
        return 1, 9
    if task_mode == "multimodal_reference":
        return 0, 9
    return 0, 9


def is_reference_mode(task_mode: str) -> bool:
    return task_mode in {"image_reference", "multimodal_reference"}
