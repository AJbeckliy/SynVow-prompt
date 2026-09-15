# -*- coding: utf-8 -*-
"""
SynVow transparent asset prompt generator.

This module only adds new ComfyUI nodes. It reuses the existing SynVow auth and
LLM client, but leaves image generation to the existing GPT-Image-2 nodes.
"""

import base64
import hashlib
import io
import json
import math
import os
import re
from typing import Any, Dict, List, Tuple

import numpy as np
import requests
import urllib3
from PIL import Image

from .utils import (
    RUNNINGHUB_LLM_SITE_CN,
    RUNNINGHUB_LLM_SITE_OPTIONS,
    default_runninghub_model,
    fetch_runninghub_models,
    make_headers,
    normalize_runninghub_llm_site,
    parse_chat_response,
    resolve_llm_config,
    resolve_runninghub_site_model,
    runninghub_model_union,
)


CATEGORY = "SynVow-prompt/透明素材"
NODE_VERSION = "2026-09-15-rh-site-aware-layer-split-v18"
PROMPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "prompts"))
PROMPT_CONFIG_PATH = os.path.join(PROMPTS_DIR, "transparent_asset_generator_prompts.json")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
CHARACTER_STICKER_CONSISTENCY_LOCK = (
    "Treat this as one coherent sticker pack of the same original character. "
    "Keep identical character identity, chibi head/bust proportions, face shape, eye rendering style, "
    "hair color, hair length, hair parting, skin tone, line thickness, sticker outline/border, material, "
    "lighting, camera angle and level of detail across all outputs. "
    "Only the expression, small gesture or small prop may change. "
    "Do not switch between 2D anime, 3D toy, semi-realistic portrait, flat vector, different eye styles "
    "or different rendering materials."
)
STYLE_REFERENCE_PRIORITY_LOCK = (
    "Style reference image priority: when a style_reference_image is provided, it is the highest-priority "
    "source for the art direction. Extract and follow its line quality, stroke thickness, edge roughness, "
    "shape language, color palette, fill method, texture, material, detail density, camera/perspective, "
    "lighting, shadow behavior, and overall rendering style. Use the product_or_reference_image only for "
    "subject identity, content, or layer structure. Do not let the scene preset, internal scene defaults, "
    "or default sticker/icon style override the style reference. Do not copy the style reference subject "
    "unless the user explicitly asks for that subject."
)


def _load_prompt_config() -> Dict[str, Any]:
    try:
        with open(PROMPT_CONFIG_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"[TransparentAssetPrompts] 提示词配置读取失败，使用最小兜底配置: {exc}")
        return {}


PROMPT_CONFIG = _load_prompt_config()


def _config_list(key: str, fallback: List[str]) -> List[str]:
    value = PROMPT_CONFIG.get(key)
    return value if isinstance(value, list) and value else fallback


def _config_dict(key: str, fallback: Dict[str, Any] = None) -> Dict[str, Any]:
    value = PROMPT_CONFIG.get(key)
    return value if isinstance(value, dict) else (fallback or {})


def _default_option(key: str, options: List[str], fallback: str) -> str:
    defaults = _config_dict("defaults")
    value = str(defaults.get(key, fallback))
    return value if value in options else (options[0] if options else fallback)


def _default_planner_model(models: List[str], site=None) -> str:
    preferred = (
        "google/gemini-3.5-flash",
        "google/gemini-3.1-pro-preview",
        "qwen/qwen3.7-max",
        "glm-5.2",
    )
    return next(
        (model for model in preferred if model in models),
        default_runninghub_model(models, site=site),
    )


SCENE_PRESETS = _config_list("scene_presets", ["通用透明素材", "电商素材包"])
PLANNER_MODES = _config_list("planner_modes", ["自动规划(LLM)", "规则预设(不调用LLM)"])
ASSET_COUNTS = _config_list("asset_counts", ["1", "2", "4", "6", "8", "12"])
LAYER_COUNTS = _config_list("layer_counts", ["2", "3", "4", "5", "6"])
STYLE_STRENGTHS = _config_list("style_strengths", ["保守", "标准", "丰富", "高表现"])
COMPLEXITIES = _config_list("complexities", ["简洁", "适中", "丰富"])

SCENE_HINTS = _config_dict("scene_hints")
FALLBACK_ITEMS = _config_dict("fallback_items")
TRANSPARENT_CONSTRAINTS = str(PROMPT_CONFIG.get(
    "transparent_constraints",
    "Transparent PNG asset, true transparent background, alpha channel, isolated subject, no scene background, no checkerboard, no transparency preview canvas, clean edge. Do not draw or simulate transparency.",
))

DEFAULT_SCENE = _default_option("scene_preset", SCENE_PRESETS, "电商素材包")
DEFAULT_PLANNER_MODE = _default_option("planner_mode", PLANNER_MODES, "自动规划(LLM)")
DEFAULT_ASSET_COUNT = _default_option("asset_count", ASSET_COUNTS, "6")
DEFAULT_LAYER_COUNT = _default_option("layer_count", LAYER_COUNTS, "4")
DEFAULT_STYLE_STRENGTH = _default_option("style_strength", STYLE_STRENGTHS, "标准")
DEFAULT_COMPLEXITY = _default_option("complexity", COMPLEXITIES, "适中")
GENERIC_SCENE = "通用透明素材"
LAYOUT_SPLIT_SCENE = "参考图分层拆图"
LAYOUT_SPLIT_SLOTS = [
    {
        "slot_id": "background",
        "name": "背景层",
        "purpose": "完整不透明背景；移除所有前景内容并仅补全被遮挡的背景区域",
    },
    {
        "slot_id": "subject_product",
        "name": "主体/人物/产品层",
        "purpose": "主要人物、角色、动物、产品或核心主体",
    },
    {
        "slot_id": "text_logo",
        "name": "文字/Logo层",
        "purpose": "所有可见文字、标题、数字、品牌标记、产品标记和Logo",
    },
    {
        "slot_id": "decorations",
        "name": "装饰元素层",
        "purpose": "图中真实存在的装饰物、贴纸、道具、飞溅、粒子和前景图形",
    },
    {
        "slot_id": "lighting_atmosphere",
        "name": "光影氛围层",
        "purpose": "可独立叠加的光束、辉光、雾、光斑和氛围效果",
    },
    {
        "slot_id": "other_reusable",
        "name": "其他可复用元素层",
        "purpose": "未归入前五层但在原图中真实存在的其他可复用元素",
    },
]


def _selected_layout_slots(count: int) -> List[Dict[str, str]]:
    return LAYOUT_SPLIT_SLOTS[:max(2, min(int(count), len(LAYOUT_SPLIT_SLOTS)))]


def _auto_style_controls(scene: str) -> Tuple[str, str]:
    defaults = {
        LAYOUT_SPLIT_SCENE: ("保守", "丰富"),
        GENERIC_SCENE: ("标准", "适中"),
        "电商素材包": ("保守", "丰富"),
        "UI图标套装": ("标准", "适中"),
        "人物/IP贴纸": ("保守", "适中"),
        "周边贴纸素材": ("标准", "适中"),
        "游戏道具素材": ("高表现", "丰富"),
        "节日活动素材": ("标准", "丰富"),
    }
    style_strength, complexity = defaults.get(scene, (DEFAULT_STYLE_STRENGTH, DEFAULT_COMPLEXITY))
    if style_strength not in STYLE_STRENGTHS:
        style_strength = DEFAULT_STYLE_STRENGTH
    if complexity not in COMPLEXITIES:
        complexity = DEFAULT_COMPLEXITY
    return style_strength, complexity


def _unpack(value):
    return value[0] if isinstance(value, list) else value


def _safe_int(value, default=1):
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _is_rule_planner_mode(value: Any) -> bool:
    text = str(value or "")
    return ("规则" in text and "不调用" in text) or ("rule" in text.lower() and "llm" in text.lower())


def _stable_fingerprint(**kwargs):
    payload = {key: str(value) for key, value in kwargs.items()}
    payload["node_version"] = NODE_VERSION
    payload["prompt_config_path"] = PROMPT_CONFIG_PATH
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _extract_json_object(text: str) -> Any:
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except Exception:
        pass

    candidates = []
    if "[" in raw and "]" in raw:
        candidates.append(raw[raw.find("["): raw.rfind("]") + 1])
    if "{" in raw and "}" in raw:
        candidates.append(raw[raw.find("{"): raw.rfind("}") + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except Exception:
            continue
    raise ValueError(f"无法解析 LLM 返回的 JSON: {raw[:500]}")


def _normalize_style_prompt(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    for key in ("style_prompt", "global_style_prompt", "style_lock", "shared_style"):
        text = value.get(key)
        if isinstance(text, str) and text.strip():
            cleaned = re.sub(r"\s+", " ", text).strip()
            return cleaned[:1600]
    return ""


def _normalize_source_image_description(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    keys = (
        "source_image_description",
        "reference_image_description",
        "full_image_description",
        "image_description",
        "visual_description",
    )
    for key in keys:
        text = value.get(key)
        if isinstance(text, str) and text.strip():
            cleaned = re.sub(r"\s+", " ", text).strip()
            return cleaned[:2400]
    return ""


def _source_canvas_metadata(image: Any) -> Dict[str, Any]:
    image = _unpack(image)
    shape = getattr(image, "shape", None)
    if shape is None or len(shape) < 3:
        return {}
    height = int(shape[-3])
    width = int(shape[-2])
    if width <= 0 or height <= 0:
        return {}
    divisor = math.gcd(width, height)
    return {
        "width": width,
        "height": height,
        "aspect_ratio": f"{width // divisor}:{height // divisor}",
        "coordinate_system": "normalized_top_left_origin",
    }


def _normalize_unit_values(value: Any, length: int) -> List[float]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        return []
    result = []
    for item in value:
        try:
            result.append(round(max(0.0, min(1.0, float(item))), 4))
        except (TypeError, ValueError):
            return []
    return result


def _normalize_edge_names(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    aliases = {
        "left": "left", "right": "right", "top": "top", "bottom": "bottom",
        "左": "left", "右": "right", "上": "top", "下": "bottom",
    }
    result = []
    for item in value:
        edge = aliases.get(str(item).strip().lower())
        if edge and edge not in result:
            result.append(edge)
    return result


def _normalize_region(value: Any, index: int) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    bbox = _normalize_unit_values(
        value.get("bbox_normalized") or value.get("bbox") or value.get("bounding_box"), 4,
    )
    center = _normalize_unit_values(value.get("center_normalized") or value.get("center"), 2)
    size = _normalize_unit_values(value.get("size_normalized") or value.get("size"), 2)
    if bbox and bbox[2] > bbox[0] and bbox[3] > bbox[1]:
        if not center:
            center = [round((bbox[0] + bbox[2]) / 2, 4), round((bbox[1] + bbox[3]) / 2, 4)]
        if not size:
            size = [round(bbox[2] - bbox[0], 4), round(bbox[3] - bbox[1], 4)]
    else:
        bbox = []
    result = {
        "label": str(value.get("label") or value.get("name") or f"region_{index:02d}").strip(),
        "bbox_normalized": bbox,
        "center_normalized": center,
        "size_normalized": size,
        "touches_edges": _normalize_edge_names(value.get("touches_edges")),
        "visible_state": re.sub(r"\s+", " ", str(value.get("visible_state") or "")).strip()[:300],
        "occlusion": re.sub(
            r"\s+", " ", str(value.get("occlusion") or value.get("occluded_by") or ""),
        ).strip()[:500],
    }
    return result if bbox else {}


def _normalize_layer_geometry(item: Any) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    raw = item.get("geometry") if isinstance(item.get("geometry"), dict) else item
    bbox = _normalize_unit_values(
        raw.get("layer_bbox_normalized") or raw.get("bbox_normalized") or raw.get("bbox"), 4,
    )
    center = _normalize_unit_values(raw.get("center_normalized") or raw.get("center"), 2)
    size = _normalize_unit_values(raw.get("size_normalized") or raw.get("size"), 2)
    if bbox and bbox[2] > bbox[0] and bbox[3] > bbox[1]:
        if not center:
            center = [round((bbox[0] + bbox[2]) / 2, 4), round((bbox[1] + bbox[3]) / 2, 4)]
        if not size:
            size = [round(bbox[2] - bbox[0], 4), round(bbox[3] - bbox[1], 4)]
    else:
        bbox = []
    regions_source = raw.get("regions") if isinstance(raw.get("regions"), list) else []
    regions = [
        region
        for index, value in enumerate(regions_source[:8], start=1)
        if (region := _normalize_region(value, index))
    ]
    return {
        "layer_bbox_normalized": bbox,
        "center_normalized": center,
        "size_normalized": size,
        "touches_edges": _normalize_edge_names(raw.get("touches_edges")),
        "placement_summary": re.sub(r"\s+", " ", str(raw.get("placement_summary") or "")).strip()[:800],
        "occlusion_relationships": re.sub(
            r"\s+", " ", str(raw.get("occlusion_relationships") or raw.get("occlusion") or ""),
        ).strip()[:1000],
        "regions": regions,
    }


def _reference_image_role_notes(product_image=None, style_image=None) -> List[str]:
    notes: List[str] = []
    image_index = 1
    if product_image is not None:
        notes.append(
            f"Image {image_index}: product_or_reference_image. Use this image only for subject identity, "
            "content, visible layers, product/person structure, or source objects."
        )
        image_index += 1
    if style_image is not None:
        notes.append(
            f"Image {image_index}: style_reference_image. This image has the highest priority for art direction. "
            "Extract line quality, stroke thickness, edge roughness, shape language, palette, fill method, "
            "texture, material, detail density, perspective, lighting and shadow behavior. Apply this extracted "
            "style to every planned asset while changing only the requested subject/expression/gesture/function."
        )
    return notes


def _layout_split_fallback_items(count: int, custom_prompt: str = "", suppress_style: bool = False) -> List[Dict[str, str]]:
    style_direction = _style_direction_from_custom_prompt(LAYOUT_SPLIT_SCENE, custom_prompt, count)
    slots = _selected_layout_slots(count)
    names = [slot["name"] for slot in slots]
    result = []
    for slot in slots:
        name = slot["name"]
        other_names = [other_name for other_name in names if other_name != name]
        result.append({
            "slot_id": slot["slot_id"],
            "name": name,
            "description": slot["purpose"],
            "prompt": _single_custom_item_prompt(
                LAYOUT_SPLIT_SCENE,
                name,
                style_direction,
                other_names,
                suppress_style=suppress_style,
            ),
            "geometry": {},
        })
    return result


def _fallback_items(scene: str, count: int, custom_prompt: str = "", suppress_style: bool = False) -> List[Dict[str, str]]:
    if scene == GENERIC_SCENE:
        base = custom_prompt.strip() or "transparent design asset"
        result = []
        for index in range(1, count + 1):
            subject = base if count == 1 else f"{base}, variation {index}"
            result.append({
                "name": f"通用透明素材_{index:02d}",
                "description": subject,
                "prompt": _single_custom_item_prompt(scene, subject, "", [], suppress_style=suppress_style),
            })
        return result
    if scene == LAYOUT_SPLIT_SCENE:
        return _layout_split_fallback_items(count, custom_prompt, suppress_style=suppress_style)

    custom_names = _extract_custom_item_names(scene, custom_prompt, count)
    if custom_names:
        item_names = [_scene_item_name(scene, name) for name in custom_names[:count]]
        style_direction = _style_direction_from_custom_prompt(scene, custom_prompt, count)
        result = []
        for item_name in item_names:
            other_names = [name for name in item_names if name != item_name]
            result.append({
                "name": item_name,
                "description": item_name,
                "prompt": _single_custom_item_prompt(scene, item_name, style_direction, other_names, suppress_style=suppress_style),
            })
        if len(result) >= count:
            return result[:count]

    names = FALLBACK_ITEMS.get(scene) or FALLBACK_ITEMS.get(DEFAULT_SCENE) or ["transparent design asset"]
    style_direction = _style_direction_from_custom_prompt(scene, custom_prompt, count)
    result = []
    for index in range(count):
        name = _scene_item_name(scene, str(names[index % len(names)]))
        result.append({
            "name": name,
            "description": name,
            "prompt": _single_custom_item_prompt(scene, name, style_direction, [], suppress_style=suppress_style),
        })
    return result


def _extract_custom_item_names(scene: str, custom_prompt: str, count: int) -> List[str]:
    text = str(custom_prompt or "").strip()
    if not text or scene == GENERIC_SCENE:
        return []

    match = re.search(r"(?:包含|包括|含有|要有|分别是|需要|拆出|提取|:|：)(.+)", text)
    if match:
        source = match.group(1)
    else:
        source = _implicit_item_list_source(text, count)
        if not source:
            return []

    pieces = re.split(r"[、,，;；\n]+", source)
    names = []
    for piece in pieces:
        token = re.split(r"(?:统一|同一|整体|风格|透明PNG|透明素材|适合|用于|不要)", piece.strip())[0].strip()
        token = re.sub(r"^(?:和|以及|及|与)", "", token).strip()
        token = re.sub(r"(?:图标|素材|贴纸|元素|道具)$", "", token).strip() or piece.strip()
        if not token:
            continue
        if len(token) > 16:
            continue
        if any(word in token for word in ("统一", "风格", "透明", "素材包", "套装")):
            continue
        if token not in names:
            names.append(token)
        if len(names) >= count:
            break
    return names


def _implicit_item_list_source(text: str, count: int) -> str:
    parts = re.split(r"[，,：:]", str(text or ""), maxsplit=1)
    if len(parts) < 2:
        return ""
    suffix = parts[1].strip()
    pieces = [piece.strip() for piece in re.split(r"[、,，;；\n]+", suffix) if piece.strip()]
    if len(pieces) < min(max(count, 2), 2):
        return ""
    meaningful = [
        piece for piece in pieces
        if not any(word in piece for word in ("统一", "风格", "透明PNG", "透明素材", "素材包", "套装"))
    ]
    return suffix if len(meaningful) >= 2 else ""


def _looks_like_item_token(scene: str, value: str) -> bool:
    token = str(value or "").strip()
    if not token or len(token) > 18:
        return False
    style_markers = (
        "统一", "同一", "整体", "风格", "透明PNG", "透明素材", "素材包", "套装",
    )
    if any(word in token for word in style_markers):
        return False
    scene_keywords = {
        "电商素材包": ("标签", "底板", "箭头", "粒子", "光环", "水滴", "胶囊", "元素", "道具", "装饰", "高光", "碎片"),
        "参考图分层拆图": ("文字", "Logo", "主体", "人物", "产品", "背景", "装饰", "元素", "光影", "氛围", "层"),
        "UI图标套装": ("图标", "生成", "编辑", "上传", "下载", "收藏", "设置", "搜索", "首页", "订单", "支付", "用户", "数据"),
        "人物/IP贴纸": ("贴纸", "表情", "动作", "挥手", "点赞", "比心", "疑问", "开心", "角色"),
        "周边贴纸素材": ("贴纸", "徽章", "冰箱贴", "手账", "封口贴", "立牌", "图案", "装饰"),
        "游戏道具素材": ("金币", "宝箱", "药水", "水晶", "武器", "护盾", "技能", "卡牌", "挂件", "奖励", "道具"),
        "节日活动素材": ("礼盒", "彩带", "优惠券", "倒计时", "角标", "金币", "烟花", "爆炸贴", "标签", "徽章"),
    }
    keywords = scene_keywords.get(scene, ())
    if any(word in token for word in keywords):
        return True
    style_descriptors = (
        "电商", "主图", "科技", "高端", "可爱", "蓝紫", "蓝色", "紫色", "红色", "金色",
        "清透", "轻拟物", "3D", "扁平", "手绘", "写实", "赛博", "奇幻", "春节", "双11",
    )
    if any(word in token for word in style_descriptors):
        return False
    return len(token) <= 8


def _scene_item_name(scene: str, name: str) -> str:
    clean = str(name or "").strip()
    if scene == LAYOUT_SPLIT_SCENE:
        return clean if clean.endswith("层") else f"{clean}层"
    if scene == "UI图标套装":
        return clean if clean.endswith("图标") else f"{clean}图标"
    if scene == "游戏道具素材":
        return clean if clean.endswith(("图标", "道具", "素材")) else f"{clean}道具图标"
    if scene in ("人物/IP贴纸", "周边贴纸素材"):
        return clean if clean.endswith("贴纸") else f"{clean}贴纸"
    if scene == "节日活动素材":
        return clean if clean.endswith(("元素", "素材", "贴纸", "标签", "底板")) else f"{clean}元素"
    return clean if clean.endswith(("素材", "元素", "标签", "底板", "图标")) else f"{clean}素材"


_UI_ICON_ENGLISH_HINTS = {
    "生成": "AI generation sparkle or magic-wand symbol",
    "编辑": "pencil edit symbol",
    "上传": "upward arrow upload symbol",
    "下载": "downward arrow download symbol",
    "收藏": "favorite heart or star symbol",
    "设置": "settings gear symbol",
    "搜索": "magnifying glass search symbol",
    "首页": "home symbol",
    "消息": "message bubble symbol",
    "订单": "order document symbol",
    "支付": "payment card symbol",
    "数据": "analytics chart symbol",
    "商品": "product box symbol",
    "用户": "user profile symbol",
    "客服": "customer service headset symbol",
    "物流": "delivery truck symbol",
}


_UI_ICON_SYMBOL_LOCKS = {
    "上传": (
        "Use one upward arrow rising from a simple tray or cloud base. "
        "Do not use a downward arrow or download tray."
    ),
    "下载": (
        "Use one downward arrow entering a simple tray or inbox. "
        "Do not use an upward arrow, cloud upload symbol, or extra mini icons."
    ),
}


def _style_direction_from_custom_prompt(scene: str, custom_prompt: str, count: int = 0) -> str:
    text = str(custom_prompt or "").strip()
    if not text:
        return ""
    if scene in (GENERIC_SCENE, LAYOUT_SPLIT_SCENE):
        return text

    text = re.sub(
        r"(?:包含|包括|含有|分别是|需要|拆出|提取)[^。；;]*?"
        r"(?=(?:，|,)?(?:统一|同一|整体|保持|风格|蓝|紫|红|金|科技|可爱|高端|简洁|轻拟物|3D|扁平|手绘|写实)|[。；;]|$)",
        "",
        text,
    )
    implicit_source = _implicit_item_list_source(text, count or 2)
    if implicit_source:
        style_prefix_parts = re.split(r"[，,：:]", text, maxsplit=1)
        style_prefix = style_prefix_parts[0].strip() if len(style_prefix_parts) > 1 else ""
        segments = [seg.strip() for seg in re.split(r"[、,，;；\n]+", text) if seg.strip()]
        kept = []
        for seg in segments:
            if style_prefix and seg == style_prefix:
                kept.append(seg)
                continue
            if not _looks_like_item_token(scene, seg):
                kept.append(seg)
        if not kept and style_prefix:
            kept.append(style_prefix)
        text = "，".join(kept)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[，,]\s*[，,]+", "，", text)
    text = text.strip("，,。；; ")
    return text or str(custom_prompt or "").strip()


def _ui_icon_subject(item_name: str) -> str:
    label = str(item_name or "").strip()
    base = label[:-2] if label.endswith("图标") else label
    hint = _UI_ICON_ENGLISH_HINTS.get(base)
    return f"{label} ({hint})" if hint else label


def _ui_icon_symbol_lock(item_name: str) -> str:
    label = str(item_name or "").strip()
    base = label[:-2] if label.endswith("图标") else label
    return _UI_ICON_SYMBOL_LOCKS.get(base, "")


def _layout_split_item_prompt(item_name: str, style_direction: str, other_names: List[str] = None) -> str:
    style_text = f" User split instruction: {style_direction}." if style_direction else ""
    common = (
        "Use the connected reference image as the only source of truth. "
        "Separate the requested visible content in place; do not redraw, redesign, repaint, upscale, stylize, simplify, enhance, or invent anything. "
        "Do not add new props, mascots, icons, food, stickers, text, logos, background, decorations, or unrelated design assets. "
        "Keep the original full-canvas coordinates, element position, element scale, crop relationship, pixel appearance, color, sharpness, material texture, lighting direction, shadows, and visible detail unchanged."
    )
    other_names = other_names or []
    has_separate_light_layer = any("光影" in name or "氛围" in name for name in other_names)
    if "前景综合" in item_name:
        return (
            "Extract every visible non-background foreground element from the reference image as one transparent overlay layer, including the main subject/person/product, visible text and logos, decorations, foreground effects, and their visible shadows. "
            "Preserve their original overlap, position, scale, and appearance. Exclude only the background plate and do not reconstruct hidden content. "
            f"{common}{style_text}"
        )
    if "装饰" in item_name and any(word in item_name for word in ("主体", "人物", "产品", "主角")):
        return (
            "Extract the main visible subject/person/product together with all visible non-text decorative foreground elements as one transparent overlay layer. "
            "Preserve their original overlap, position, scale, materials, lighting, and shadows. Exclude text, logos, and the background plate. Do not invent or complete hidden content. "
            f"{common}{style_text}"
        )
    if "文字" in item_name or "Logo" in item_name or "logo" in item_name.lower():
        return (
            "Separate only the original visible text, typography, logo marks, brand marks, numbers, and small written labels from the reference image "
            "as one transparent overlay layer. Preserve their exact visible shapes, colors, positions, scale relationships, sharpness, and hierarchy without regenerating the typography. "
            "Do not include the person, product, background, decorative props, shadows, or scene surfaces. Visible text is allowed for this layer. "
            f"{common}{style_text}"
        )
    if any(word in item_name for word in ("主体", "人物", "产品", "主角")):
        return (
            "Separate only the existing main foreground subject layer in place from the reference image: the primary person/IP/character and the main held or displayed product if present. "
            "Preserve pose, crop, silhouette, clothing/product shape, and the relationship between person and product. "
            "Do not include text/logo, background walls/floor, decorative stickers, floating props, or unrelated objects. "
            f"{common}{style_text}"
        )
    if "背景" in item_name:
        return (
            "Reconstruct one complete clean background plate from the reference image, keeping the original full canvas, camera perspective, wall/floor geometry, lighting direction, texture, and composition. "
            "Remove every foreground person, product, text/logo, decoration, prop, and effect, then naturally inpaint the areas they previously covered by continuing the surrounding background structure. "
            "The result must be a full-frame opaque rectangular background with no transparent holes, missing patches, circular crop, remnants, silhouettes, or duplicated foreground objects. Do not add unrelated objects. "
            f"{common}{style_text}"
        )
    if "光影" in item_name or "氛围" in item_name:
        return (
            "Extract only visible atmospheric overlay effects from the reference image, such as existing glow, light rays, bloom, mist, particles, or floating illumination. "
            "Do not include ordinary object lighting, object shadows, text, logos, the main subject, products, physical decorations, or background. "
            "If no separable atmospheric overlay exists, output an empty transparent layer. "
            f"{common}{style_text}"
        )
    if "其他" in item_name:
        return (
            "Extract only remaining visible reusable foreground elements that do not belong to the background, main subject/product, text/logo, decoration, or atmospheric-light layers. "
            "Do not duplicate content assigned to another layer. If no such remaining element exists, output an empty transparent layer. "
            f"{common}{style_text}"
        )
    if "装饰" in item_name or "元素" in item_name:
        light_exclusion = (
            " Exclude glow, light rays, bloom, mist, and atmospheric particles because they belong to the separately requested light/atmosphere layer."
            if has_separate_light_layer else ""
        )
        return (
            "Separate only the existing visible decorative foreground elements in place from the reference image as one transparent overlay layer. "
            "Include only real decorative graphics, effects, light accents, splashes, particles, stickers, badges, or small foreground elements that are explicitly visible in the reference image. "
            "If the source image has no visible decorative foreground elements, output an empty transparent layer. "
            "Do not include text/logo, the main person, main product, background plate, or any guessed decoration. "
            f"{light_exclusion} {common}{style_text}"
        )
    return (
        f"Recreate only the {item_name} from the reference image as a separate design layer. "
        f"{common}{style_text}"
    )


def _single_custom_item_prompt(
    scene: str,
    item_name: str,
    style_direction: str,
    other_names: List[str],
    suppress_style: bool = False,
) -> str:
    style_text = f" Style direction: {style_direction}." if style_direction and not suppress_style else ""
    one_asset_rule = (
        "This prompt is for the current asset only. "
        "The output canvas must contain exactly one object only."
    )
    if scene == LAYOUT_SPLIT_SCENE:
        return _layout_split_item_prompt(item_name, style_direction, other_names)
    if scene == "UI图标套装":
        symbol_lock = _ui_icon_symbol_lock(item_name)
        symbol_text = f" {symbol_lock}" if symbol_lock else ""
        return (
            f"Generate exactly one standalone UI icon: {_ui_icon_subject(item_name)}. "
            f"{one_asset_rule} Only this single symbol, no icon sheet, no icon grid, no small icon cluster, no extra icons."
            f"{symbol_text}{style_text}"
        )
    if scene == "电商素材包":
        return f"Generate exactly one standalone ecommerce overlay asset: {item_name}. {one_asset_rule} No ecommerce poster, no product main image, no layout, no asset sheet, no extra props.{style_text}"
    if scene == "游戏道具素材":
        return f"Generate exactly one standalone game asset icon: {item_name}. {one_asset_rule} Only this single prop or item, no inventory grid, no item sheet, no full game scene.{style_text}"
    if scene == "人物/IP贴纸":
        if suppress_style:
            return (
                f"Generate exactly one character/emote sticker asset: {item_name}. "
                f"{one_asset_rule} Use the subject/reference image only for broad identity and content cues. "
                "Use the style_reference_image as the only source for visual style; do not add any written style assumptions. "
                "Show one clear requested expression, gesture, or small prop only. "
                "Avoid realistic human likeness, celebrity likeness, photoreal face, complex full-body anatomy, detailed hands, multiple characters, "
                "sticker sheet, multiple poses in one image, or mockup scene."
            )
        return (
            f"Generate exactly one original character/emote sticker asset: {item_name}. "
            f"{one_asset_rule} Use one bust, head, simplified mascot, or simple character with one clear expression or gesture. "
            "If a subject reference image is provided, preserve only the broad identity cues needed by the user. "
            "When a style reference image is provided, the style reference controls the rendering style completely, including whether the result is monochrome, flat, rough, minimal, hand-drawn, or non-chibi. "
            "Do not force anime eyes, chibi proportions, colorful hair, skin-tone rendering, glossy material, gradients, or cute-Q details when they conflict with the style reference. "
            "Keep character consistency across outputs by preserving the same simplified face structure, silhouette, line weight, camera angle and detail level. "
            "Avoid realistic human likeness, celebrity likeness, photoreal face, complex full-body anatomy, detailed hands, multiple characters, "
            "sticker sheet, multiple poses in one image, or mockup scene."
            f"{style_text}"
        )
    if scene == "周边贴纸素材":
        return f"Generate exactly one standalone merchandise sticker asset: {item_name}. {one_asset_rule} Only this single sticker or merchandise artwork, no sticker sheet, no product mockup scene.{style_text}"
    if scene == "节日活动素材":
        return f"Generate exactly one standalone holiday campaign asset: {item_name}. {one_asset_rule} Only this single reusable element, no element sheet, no complete poster, no layout, no other campaign elements.{style_text}"
    return f"Generate exactly one standalone transparent asset: {item_name}. {one_asset_rule} Only this single reusable element, no asset sheet, no complete design layout.{style_text}"


_MULTI_ASSET_PROMPT_HINTS = (
    "asset sheet", "icon sheet", "sticker sheet", "item sheet", "contact sheet",
    "icon grid", "item grid", "grid of", "nine-grid", "9-grid", "3x3",
    "collage", "collection", "multiple", "many", "several", "various",
    "set of icons", "icon set", "sticker set", "asset pack", "all icons", "all items",
    "full poster", "poster layout", "main image layout", "ui screen", "full interface",
    "九宫格", "宫格", "网格", "拼图", "合集", "集合", "整套", "全套", "一整套",
    "图标套装", "图标组", "图标表", "贴纸套装", "贴纸表", "素材包", "素材表",
    "道具栏", "多个", "多张", "多种", "一组", "成套", "包含", "包括",
)


def _prompt_mentions_multi_asset(prompt: str) -> bool:
    text = str(prompt or "")
    lower = text.lower()
    return any(hint in lower for hint in _MULTI_ASSET_PROMPT_HINTS)


def _enforce_single_asset_prompt(
    scene: str,
    name: str,
    prompt: str,
    custom_prompt: str,
    count: int,
    suppress_style: bool = False,
) -> str:
    style_direction = _style_direction_from_custom_prompt(scene, custom_prompt, count)
    single_prompt = _single_custom_item_prompt(scene, name, style_direction, [], suppress_style=suppress_style)
    raw_prompt = re.sub(r"\s+", " ", str(prompt or "")).strip()
    if scene == LAYOUT_SPLIT_SCENE:
        if not raw_prompt:
            return single_prompt
        return (
            f"{raw_prompt}. "
            "Use the connected reference image and source_image_description as the only source of truth. "
            "Reconstruct only this requested visible layer. Do not add standard category examples, decorative guesses, or elements that are not explicitly visible in the reference image. "
            "Exclude all other layers from this output."
        )
    if suppress_style:
        return single_prompt
    if not raw_prompt or _prompt_mentions_multi_asset(raw_prompt):
        return single_prompt
    return (
        f"{single_prompt} Preserve only relevant single-object visual details from planner: "
        f"{raw_prompt}. Ignore any wording that implies a pack, sheet, grid, multiple objects, "
        f"complete layout, poster, UI screen, or scene."
    )


def _normalize_items(value: Any, count: int, scene: str, custom_prompt: str = "", suppress_style: bool = False) -> List[Dict[str, str]]:
    if isinstance(value, dict):
        items = value.get("items", [])
    elif isinstance(value, list):
        items = value
    else:
        items = []

    normalized = []
    for index, item in enumerate(items[:count], start=1):
        if isinstance(item, str):
            name = item.strip()
            description = item.strip()
            prompt = item.strip()
        elif isinstance(item, dict):
            name = str(item.get("name") or item.get("title") or f"asset_{index:02d}").strip()
            description = str(item.get("description") or item.get("usage") or name).strip()
            prompt = str(item.get("prompt") or item.get("image_prompt") or description or name).strip()
        else:
            continue
        if prompt:
            normalized.append({
                "name": name,
                "description": description,
                "prompt": _enforce_single_asset_prompt(scene, name, prompt, custom_prompt, count, suppress_style=suppress_style),
                "geometry": _normalize_layer_geometry(item) if scene == LAYOUT_SPLIT_SCENE else {},
            })

    if len(normalized) < count:
        fallback = _fallback_items(scene, count, custom_prompt, suppress_style=suppress_style)
        normalized.extend(fallback[len(normalized):count])
    return normalized[:count]


def _normalize_layout_split_slots(
    value: Any,
    count: int,
    custom_prompt: str = "",
    suppress_style: bool = False,
) -> List[Dict[str, Any]]:
    selected_slots = _selected_layout_slots(count)
    if isinstance(value, dict):
        raw_items = value.get("slots") if isinstance(value.get("slots"), list) else value.get("items", [])
    else:
        raw_items = value if isinstance(value, list) else []

    by_slot_id = {}
    by_name = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        slot_id = str(item.get("slot_id") or "").strip()
        name = str(item.get("name") or item.get("layer_name") or "").strip()
        if slot_id and slot_id not in by_slot_id:
            by_slot_id[slot_id] = item
        if name and name not in by_name:
            by_name[name] = item

    fallback_by_id = {
        item["slot_id"]: item
        for item in _layout_split_fallback_items(count, custom_prompt, suppress_style=suppress_style)
    }
    normalized = []
    for slot in selected_slots:
        candidate = by_slot_id.get(slot["slot_id"]) or by_name.get(slot["name"])
        if not isinstance(candidate, dict):
            normalized.append(fallback_by_id[slot["slot_id"]])
            continue
        description = str(
            candidate.get("description")
            or candidate.get("content_summary")
            or candidate.get("visible_content")
            or slot["purpose"]
        ).strip()
        visible_content = str(candidate.get("visible_content") or description).strip()
        edit_instruction = str(candidate.get("edit_instruction") or candidate.get("prompt") or "").strip()
        prompt = str(
            candidate.get("prompt")
            or edit_instruction
            or visible_content
            or description
        ).strip()
        normalized.append({
            "slot_id": slot["slot_id"],
            "name": slot["name"],
            "description": description,
            "visible_content": visible_content,
            "edit_instruction": edit_instruction,
            "prompt": _enforce_single_asset_prompt(
                LAYOUT_SPLIT_SCENE,
                slot["name"],
                prompt,
                custom_prompt,
                count,
                suppress_style=suppress_style,
            ),
            "geometry": _normalize_layer_geometry(candidate),
        })
    return normalized


def _planner_system_prompt(scene: str = "") -> str:
    if scene == LAYOUT_SPLIT_SCENE:
        return (
            "Analyze the reference image and fill the supplied fixed slots. Return one-line strict JSON only; no markdown or commentary. "
            "Return exactly: {source_image_description:string,slots:[{slot_id:string,visible_content:string,"
            "bbox_normalized:[x1,y1,x2,y2],touches_edges:[left|right|top|bottom],"
            "regions:[{label:string,bbox_normalized:[x1,y1,x2,y2]}]}]}. "
            "Keep every supplied slot_id exactly once and in order. Coordinates use the full source canvas, top-left origin, range 0 to 1. "
            "Use [0,0,1,1] for background. Keep the description under 60 words and each visible_content under 30 words. "
            "Use at most 6 regions per slot and group repeated small elements. For an absent slot use visible_content='empty transparent layer', "
            "bbox_normalized=[] and regions=[]. Describe only visible source content."
        )
    base = str(PROMPT_CONFIG.get(
        "planner_system_prompt",
        "You are a transparent PNG asset planner. Return strict JSON only with items.",
    ))
    return base


def _tensor_to_data_url(image, index: int = 0) -> str:
    tensor = image[index] if hasattr(image, "shape") and len(image.shape) == 4 else image
    if hasattr(tensor, "detach"):
        tensor = tensor.detach().cpu().numpy()
    array = np.asarray(tensor)
    array = np.clip(array * 255.0, 0, 255).astype(np.uint8)
    if array.ndim == 2:
        pil_image = Image.fromarray(array, mode="L").convert("RGB")
    else:
        pil_image = Image.fromarray(array[..., :3], mode="RGB")
    if max(pil_image.size) > 1600:
        pil_image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    pil_image.save(buffer, format="JPEG", quality=92)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def image_to_data_urls(image, max_images: int = 8) -> List[str]:
    if image is None:
        return []
    try:
        batch_size = int(image.shape[0]) if hasattr(image, "shape") and len(image.shape) == 4 else 1
    except Exception:
        batch_size = 1
    urls = []
    for index in range(min(batch_size, max_images)):
        try:
            urls.append(_tensor_to_data_url(image, index))
        except Exception as exc:
            print(f"[TransparentAssetPrompts] 参考图转 data URL 失败: {exc}")
    return urls


def _runninghub_chat_completion(
    llm_model: str,
    system_prompt: str,
    user_prompt: str,
    image_urls: List[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 2000,
    timeout: int = 240,
    llm_site=RUNNINGHUB_LLM_SITE_CN,
    llm_config=None,
) -> str:
    base_url, api_key, model_name = resolve_llm_config(
        llm_config,
        model_name=llm_model,
        site=llm_site,
    )
    if not base_url or not api_key or not model_name:
        raise RuntimeError(
            "缺少LLM配置：请设置RunningHub共享API Key，或连接SynVow LLM Settings。"
        )

    content = user_prompt
    if image_urls:
        content = [{"type": "text", "text": user_prompt}]
        for index, image_url in enumerate(image_urls, start=1):
            content.append({"type": "text", "text": f"参考图{index}："})
            content.append({"type": "image_url", "image_url": {"url": image_url}})

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        "stream": False,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }
    response = requests.post(
        base_url.rstrip("/"),
        headers=make_headers(api_key),
        json=payload,
        timeout=(30, timeout),
        verify=False,
    )
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        body = response.text[:2000] if response.text else "<empty response>"
        if response.status_code == 401 and "only shared" in body.lower():
            raise RuntimeError(
                "RunningHub LLM认证失败：当前Key不是LLM网关接受的SHARED/enterprise Key。"
            ) from exc
        raise RuntimeError(
            f"RunningHub LLM请求失败：site={llm_site}，HTTP {response.status_code}，response={body}"
        ) from exc

    data = response.json()
    raw = parse_chat_response(data)
    if not raw or not raw.strip():
        raise RuntimeError(f"模型未返回有效内容: {str(data)[:300]}")
    return raw.strip()


def _plan_with_llm(
    scene: str,
    count: int,
    custom_prompt: str,
    style_strength: str,
    complexity: str,
    llm_model: str,
    product_image=None,
    style_image=None,
    llm_site=RUNNINGHUB_LLM_SITE_CN,
    llm_config=None,
) -> Tuple[List[Dict[str, Any]], str, str, str, Dict[str, Any]]:
    image_urls: List[str] = []
    if product_image is not None:
        image_urls.extend(image_to_data_urls(product_image))
    if style_image is not None:
        image_urls.extend(image_to_data_urls(style_image))

    source_canvas = _source_canvas_metadata(product_image)
    user_payload = {
        "scene_preset": scene,
        "scene_strategy": SCENE_HINTS.get(scene, ""),
        "user_direction": custom_prompt or "",
        "auto_scene_rendering_strategy": {
            "fidelity": style_strength,
            "detail": complexity,
            "source": "scene_preset_auto_default",
        },
        "reference_images": {
            "product_or_ip_reference": product_image is not None,
            "style_reference": style_image is not None,
        },
        "reference_image_role_notes": _reference_image_role_notes(product_image, style_image),
        "source_image_description_required": product_image is not None,
        "source_image_analysis_workflow": (
            "If product_or_ip_reference is true, first write source_image_description as a faithful full-scene visual description of the connected reference image before planning layers or assets. "
            "Describe the real visible content, composition, camera angle, subject pose, silhouette, materials, surface texture, lighting direction, shadows, color relationships, text/logo placement, background structure, edge relationships, and image quality. "
            "For reference layer split mode, every item prompt must use this source_image_description as the source of truth and then specify the exact layer to reconstruct. Do not plan or describe objects that are not visible in the reference image."
        ),
        "style_reference_priority": (
            "If style_reference is true, the style_reference_image is the highest-priority art-direction source. "
            "The returned style_prompt must explicitly describe the style reference image's linework, palette, "
            "fill/texture/material, detail density, camera/perspective, lighting, shadow behavior and shape language. "
            "Scene preset and internal scene defaults are secondary controls and must not override the style reference."
            if style_image is not None else ""
        ),
        "requirements": _config_list("planner_requirements", [
            "Plan exactly asset_count items.",
            "Each item must be reusable as a transparent PNG component.",
            "The whole pack must share one consistent visual style.",
            "Do not plan full posters, full ecommerce main images, or full UI screens.",
        ]),
    }
    if scene == LAYOUT_SPLIT_SCENE:
        selected_slots = _selected_layout_slots(count)
        user_payload.pop("auto_scene_rendering_strategy", None)
        user_payload.pop("style_reference_priority", None)
        user_payload["layer_count"] = count
        user_payload["source_canvas"] = source_canvas
        user_payload["slots"] = selected_slots
        user_payload["source_image_analysis_workflow"] = (
            "Analyze the input image once, then fill each supplied slot exactly once. Identify only visible source content, "
            "measure its full-canvas normalized geometry, and describe what the image edit should extract or remove."
        )
        user_payload["geometry_requirements"] = (
            "Return only layer and region bounding boxes in normalized full-canvas coordinates."
        )
        user_payload["requirements"] = [
            "Return the supplied slot_id values exactly once and in the supplied order.",
            "Do not create additional slots and do not rename or merge slots.",
            "Use the input image as the only source of visual facts.",
            "Return an empty regions list when a selected slot has no visible source content.",
            "Do not write a global style prompt for layer separation.",
        ]
    else:
        user_payload["asset_count"] = count
    content = _runninghub_chat_completion(
        llm_model,
        _planner_system_prompt(scene),
        json.dumps(user_payload, ensure_ascii=False),
        image_urls=image_urls,
        temperature=0.2,
        max_tokens=2000,
        timeout=240,
        llm_site=llm_site,
        llm_config=llm_config,
    )
    parsed = _extract_json_object(content)
    normalized_items = (
        _normalize_layout_split_slots(
            parsed,
            count,
            custom_prompt,
            suppress_style=style_image is not None,
        )
        if scene == LAYOUT_SPLIT_SCENE
        else _normalize_items(parsed, count, scene, custom_prompt, suppress_style=style_image is not None)
    )
    return (
        normalized_items,
        content,
        "" if scene == LAYOUT_SPLIT_SCENE else _normalize_style_prompt(parsed),
        _normalize_source_image_description(parsed),
        source_canvas,
    )


def _explicit_style_override(custom_prompt: str) -> str:
    text = str(custom_prompt or "").lower()
    has_monochrome = any(token in text for token in ("黑白", "单色", "monochrome", "black and white", "black-and-white"))
    has_line_style = any(token in text for token in ("粗线", "粗线条", "线稿", "简笔", "极简", "minimal", "line art", "bold line"))
    if has_monochrome or has_line_style:
        parts = []
        if has_monochrome:
            parts.append(
                "Hard user style lock: use a black-and-white or monochrome palette only, with no skin-tone fill, no colored hair, no colorful clothing, no blush color, and no decorative color accents."
            )
        if has_line_style:
            parts.append(
                "Hard user style lock: use bold simple line-art, minimal flat shapes, low detail density, rough hand-drawn edges if appropriate, and no gradients, glossy rendering, 3D volume, anime eye detail, or cute-Q polished finish."
            )
        return " ".join(parts)
    return ""


def _style_lock(scene: str, style_strength: str, complexity: str, custom_prompt: str, count: int = 0) -> str:
    strength_map = _config_dict("style_strength_map")
    complexity_map = _config_dict("complexity_map")
    style_direction = _style_direction_from_custom_prompt(scene, custom_prompt, count)
    explicit_override = _explicit_style_override(custom_prompt)
    rendering_hint = " ".join(
        part for part in (
            strength_map.get(style_strength, style_strength),
            complexity_map.get(complexity, complexity),
        ) if part
    )
    base = (
        f"Shared visual style: {SCENE_HINTS.get(scene, '')} "
        f"Scene rendering strategy: {rendering_hint}. "
        f"User direction: {style_direction or 'follow the scene preset'}."
    )
    return f"{base} {explicit_override}".strip()


def _compose_style_lock(
    base_style: str,
    planner_style_prompt: str,
    has_style_reference: bool = False,
    reference_role_notes: List[str] = None,
) -> str:
    base_style = str(base_style or "").strip()
    planner_style_prompt = str(planner_style_prompt or "").strip()
    if has_style_reference:
        parts = [
            "Style pass-through mode: a style_reference_image is connected. Ignore all written preset styles, internal scene defaults, default character/icon/sticker styles, and LLM-generated style descriptions. Use the connected style_reference_image as the only visual style source."
        ]
        parts.append(STYLE_REFERENCE_PRIORITY_LOCK)
        if reference_role_notes:
            parts.append(
                "When reference images are attached to the image generation request, interpret them in this role order: "
                + " ".join(str(note).strip() for note in reference_role_notes if str(note).strip())
            )
        parts.append(
            "Subject/product reference images are content-only. The style reference image controls all linework, palette, fill, material, texture, detail density, perspective, lighting and shadow behavior."
        )
        return "\n".join(part for part in parts if part)
    parts = [base_style] if base_style else []
    if planner_style_prompt:
        parts.append(f"Global style prompt generated by planner, apply identically to every output: {planner_style_prompt}")
        parts.append(
            "Do not reinterpret or vary this global style prompt between assets; only change the requested asset subject, expression, gesture or function."
        )
    return "\n".join(part for part in parts if part)


def _scene_generation_rules(scene: str, style_pass_through: bool = False) -> str:
    if scene == LAYOUT_SPLIT_SCENE:
        return (
            "Reference layer split mode. Follow the requested layer grouping exactly; it may contain 2 to 6 layers rather than a fixed four-layer scheme. "
            "Use the connected source image as the only visual truth. Keep the source canvas aspect ratio, normalized coordinate system, crop, element positions, relative scale, and stacking relationships. "
            "Perform an in-place alpha layer separation on the full source canvas, not a new isolated-object composition. Every retained element must keep the same normalized bounding box, x/y coordinates, size, crop relationship, and distance to all four canvas edges as in the source image. "
            "Do not redraw, redesign, restyle, center, zoom, shrink, enlarge, reframe, rotate, make a circular or oval crop, or move retained elements. Return the final RGBA PNG directly and treat its alpha channel as final. Foreground layers must use real alpha transparency outside retained elements. The background layer is the exception: it must be one complete opaque clean plate with removed foreground areas naturally inpainted."
        )
    if style_pass_through:
        if scene == "人物/IP贴纸":
            return (
                "One character/emote sticker asset only. One output must contain one subject with one requested expression, gesture or small prop only. "
                "Use subject/reference image for broad identity and content only. Do not define or add any written visual style; follow the style_reference_image exclusively. "
                "No realistic human likeness, celebrity likeness, multiple characters, sticker sheet, contact sheet, multiple poses, background scene, or text unless the user requested a blank sign."
            )
        return (
            "One reusable transparent asset only. One output must contain exactly one requested subject/object only. "
            "Do not define or add any written visual style; follow the style_reference_image exclusively. "
            "No asset sheet, grid, contact sheet, collage, full poster, UI screen, full scene, extra objects, or visible text unless explicitly requested."
        )
    rules = _config_dict("scene_generation_rules")
    return str(rules.get(scene) or rules.get(GENERIC_SCENE) or "Generate one transparent reusable asset.")


def _transparent_constraints_for_item(scene: str, item_name: str) -> str:
    if scene != LAYOUT_SPLIT_SCENE:
        return TRANSPARENT_CONSTRAINTS
    name = str(item_name or "")
    if "前景综合" in name:
        return (
            "Layer constraints: output one transparent overlay containing every visible non-background element, including the main subject/product, text/logo, decorations, effects, and visible foreground shadows. "
            "Exclude only the background pixels. Keep all retained content at its source coordinates and do not omit text/logo."
        )
    if "背景" in name:
        return (
            "Layer constraints: output a complete full-canvas opaque background plate. Remove text, logo, person, product, foreground decoration, and effects, and naturally reconstruct the background behind them. "
            "No transparent holes, black gaps, circular masks, incomplete patches, foreground remnants, checkerboard, or fake transparency."
        )
    if "文字" in name or "Logo" in name or "logo" in name.lower():
        return (
            "Layer constraints: output a transparent PNG overlay with real alpha outside the text/logo marks. "
            "Visible typography, numbers, brand marks, and logo shapes from the reference are allowed. "
            "Do not include person, product, background, foreground props, decorations, checkerboard, or fake transparency."
        )
    return (
        "Layer constraints: output a transparent PNG overlay with real alpha outside this foreground layer. "
        "Keep only the requested layer content from the reference image. Do not include text/logo, background plate, unrelated objects, checkerboard, or fake transparency."
    )


def _source_image_context_for_prompt(scene: str, source_image_description: str) -> str:
    text = re.sub(r"\s+", " ", str(source_image_description or "")).strip()
    if not text:
        return ""
    if scene == LAYOUT_SPLIT_SCENE:
        return (
            "Source image full visual description. Treat this as the source of truth for layer reconstruction: "
            f"{text}"
        )
    return f"Reference image visual description: {text}"


def _compact_prompt_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[:max(1, limit - 3)].rstrip(" ,.;:") + "..."


def _compact_bbox(value: Any) -> str:
    if not isinstance(value, list) or len(value) != 4:
        return ""
    return "[" + ",".join(f"{float(number):.3f}".rstrip("0").rstrip(".") for number in value) + "]"


def _layer_geometry_context(item: Dict[str, Any], source_canvas: Dict[str, Any], limit: int = 220) -> str:
    geometry = item.get("geometry") if isinstance(item.get("geometry"), dict) else {}
    if not source_canvas:
        return ""
    parts = [f"Full-canvas source aspect {source_canvas.get('aspect_ratio')}"]
    bbox = geometry.get("layer_bbox_normalized")
    if bbox:
        parts.append(f"bbox={_compact_bbox(bbox)}")
    if geometry.get("touches_edges"):
        parts.append("edges=" + ",".join(geometry["touches_edges"]))
    regions = geometry.get("regions") if isinstance(geometry.get("regions"), list) else []
    for region in regions:
        label = _compact_prompt_text(region.get("label"), 16)
        token = f"{label}{_compact_bbox(region.get('bbox_normalized'))}"
        candidate = "; ".join(parts + ["regions=" + token])
        if len(candidate) > limit:
            break
        if parts and parts[-1].startswith("regions="):
            parts[-1] += "," + token
        else:
            parts.append("regions=" + token)
    return "; ".join(parts) + "."


def _build_layout_split_generation_prompt(
    item: Dict[str, Any],
    source_image_description: str,
    source_canvas: Dict[str, Any],
) -> str:
    del source_image_description
    slot_id = str(item.get("slot_id") or "")
    name = str(item.get("name") or "")
    details = _compact_prompt_text(
        item.get("visible_content") or item.get("description") or item.get("prompt") or name,
        60,
    )
    geometry = _layer_geometry_context(item, source_canvas)

    if slot_id == "background":
        remove_content = _compact_prompt_text(item.get("remove_content"), 140)
        prompt = (
            f"[Layer: background] Edit in place. Remove only: {remove_content or 'all listed foreground layers'}. "
            "Do not change anything else. Inpaint only exposed pixels from adjacent background. "
            f"{geometry} Preserve all visible background pixels, camera, perspective, geometry, lighting, color, texture and sharpness. "
            "Output a full-canvas opaque PNG; no remnants, additions, text, logos or checkerboard."
        )
    else:
        prompt = (
            f"[Layer: {slot_id}] Edit the input image in place. Keep only {name}: {details}. {geometry} "
            "Make every other pixel transparent. Preserve the retained pixels' exact source position, scale, proportions, perspective, crop, "
            "colors, texture, lighting and sharpness. Output a full-canvas PNG with clean alpha edges and no halos. "
            "Do not center, resize, move, redraw, restyle, add shadows or include other layers."
        )
        if slot_id == "text_logo":
            prompt = (
                f"[Layer: {slot_id}] Edit the input image in place. Keep only {name}: {_compact_prompt_text(details, 45)}. {geometry} "
                "Make every other pixel transparent. Preserve exact wording, line breaks, typography, logo geometry, source position, scale, color and sharpness. "
                "Output a full-canvas PNG with clean alpha edges and no halos. "
                "Do not redraw, approximate, center, resize, move, restyle or include other layers."
            )
        if not details or "empty transparent" in details.lower():
            prompt = (
                f"Edit the input image. The {name} has no visible source content. {geometry} "
                "Output one empty full-canvas transparent PNG. Do not invent any element."
            )
    return _compact_prompt_text(prompt, 500)


def _is_text_logo_layer_item(item: Dict[str, str]) -> bool:
    layer_text = " ".join(
        str(item.get(key, "") or "")
        for key in ("name", "layer", "layer_name", "split_layer")
    ).lower()
    return any(
        token in layer_text
        for token in ("文字", "文案", "标题", "logo", "标志", "typography", "text", "brand mark")
    )


def _style_lock_for_item(scene: str, item: Dict[str, str], style_lock: str) -> str:
    if scene == LAYOUT_SPLIT_SCENE:
        if not _is_text_logo_layer_item(item):
            return (
                "Source-fidelity layer extraction mode: do not apply any new visual style, rendering strategy, material treatment, lighting, color grading, detail enhancement, or scene aesthetics. "
                "Preserve the connected source image appearance and coordinates only."
            )
        return (
            "Text/logo in-place separation mode: preserve the exact visible typography and logo pixels from the reference image without redrawing them. "
            "Keep the original text content, line breaks, x/y coordinates, alignment, scale, font weight, color, sharpness, and logo mark geometry unchanged. "
            "Do not apply photography, fur, product material, lighting, texture, depth of field, or scene-rendering style to this text/logo layer. "
            "Output only the original flat text/logo marks on real alpha transparency; do not soften, recolor, restyle, regenerate, or approximate them."
        )
    return style_lock


def _build_generation_prompt(
    scene: str,
    item: Dict[str, str],
    style_lock: str,
    index: int,
    count: int,
    style_pass_through: bool = False,
    source_image_description: str = "",
    source_canvas: Dict[str, Any] = None,
) -> str:
    if scene == LAYOUT_SPLIT_SCENE:
        return _build_layout_split_generation_prompt(
            item,
            source_image_description,
            source_canvas or {},
        )
    template_key = "layout_split_generation_prompt_template" if scene == LAYOUT_SPLIT_SCENE else "generation_prompt_template"
    template = PROMPT_CONFIG.get(template_key)
    if isinstance(template, str):
        lines = template.splitlines()
    elif isinstance(template, list):
        lines = [str(line) for line in template]
    else:
        lines = [
            "Asset {index} of {count}: {item_prompt}",
            "Asset name: {item_name}",
            "{style_lock}",
            "{scene_rule}",
            "{transparent_constraints}",
            "Output only the isolated subject on real alpha transparency. Do not visualize transparency as a checkerboard, gray-white grid, preview canvas, background, frame, canvas texture, floor shadow, watermark, signature, or extra objects.",
        ]

    context = {
        "index": index,
        "count": count,
        "item_prompt": item.get("prompt", "").strip(),
        "item_name": item.get("name", "").strip(),
        "style_lock": _style_lock_for_item(scene, item, style_lock),
        "source_image_context": _source_image_context_for_prompt(scene, source_image_description),
        "scene_rule": _scene_generation_rules(scene, style_pass_through=style_pass_through),
        "transparent_constraints": _transparent_constraints_for_item(scene, item.get("name", "")),
        "layer_geometry": _layer_geometry_context(item, source_canvas or {}),
    }
    rendered = []
    for line in lines:
        try:
            value = line.format(**context)
        except Exception:
            value = line
        value = str(value).strip()
        if value:
            rendered.append(value)
    geometry_text = context["layer_geometry"]
    if scene == LAYOUT_SPLIT_SCENE and geometry_text and geometry_text not in rendered:
        rendered.insert(min(2, len(rendered)), geometry_text)
    return "\n".join(rendered)


def _plain_prompt_text(items: List[Dict[str, str]], prompts: List[str]) -> str:
    blocks = []
    for index, (item, prompt) in enumerate(zip(items, prompts), start=1):
        blocks.append(
            f"{index:02d}. {item.get('name', '')}\n"
            f"{item.get('description', '')}\n"
            f"{prompt}"
        )
    return "\n\n---\n\n".join(blocks)


class SynVowTransparentAssetPromptGenerator:
    FUNCTION = "generate"
    CATEGORY = CATEGORY
    INPUT_IS_LIST = True
    OUTPUT_IS_LIST = (True, False, False, False)

    @classmethod
    def INPUT_TYPES(cls):
        llm_models = runninghub_model_union(require_vision=True)
        cn_models = fetch_runninghub_models(
            site=RUNNINGHUB_LLM_SITE_CN,
            require_vision=True,
        )
        return {
            "required": {
                "scene_preset": (SCENE_PRESETS, {"default": DEFAULT_SCENE}),
                "planner_mode": (PLANNER_MODES, {"default": DEFAULT_PLANNER_MODE}),
                "asset_count": (ASSET_COUNTS, {"default": DEFAULT_ASSET_COUNT}),
                "layer_count": (LAYER_COUNTS, {"default": DEFAULT_LAYER_COUNT}),
                "custom_prompt": ("STRING", {"multiline": True, "default": ""}),
                "model": (
                    llm_models,
                    {"default": _default_planner_model(cn_models, RUNNINGHUB_LLM_SITE_CN)},
                ),
                "seed": ("INT", {"default": 0, "min": 0, "max": 2147483647}),
            },
            "optional": {
                "llm_site": (
                    RUNNINGHUB_LLM_SITE_OPTIONS,
                    {"default": RUNNINGHUB_LLM_SITE_CN},
                ),
                "llm_config": ("SYNVOW_LLM_CONFIG",),
                "product_or_reference_image": ("IMAGE",),
                "style_reference_image": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = (
        "prompts_list",
        "asset_plan_json",
        "prompts_text",
        "status",
    )

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return _stable_fingerprint(**kwargs)

    def generate(
        self,
        scene_preset,
        planner_mode,
        asset_count,
        custom_prompt,
        model,
        seed,
        layer_count=DEFAULT_LAYER_COUNT,
        llm_site=RUNNINGHUB_LLM_SITE_CN,
        llm_config=None,
        product_or_reference_image=None,
        style_reference_image=None,
        **_legacy_inputs,
    ):
        scene = _unpack(scene_preset) or DEFAULT_SCENE
        planner_mode = _unpack(planner_mode) or DEFAULT_PLANNER_MODE
        asset_count = _safe_int(_unpack(asset_count), _safe_int(DEFAULT_ASSET_COUNT, 6))
        layer_count = _safe_int(_unpack(layer_count), _safe_int(DEFAULT_LAYER_COUNT, 4))
        count = max(2, min(layer_count, 6)) if scene == LAYOUT_SPLIT_SCENE else asset_count
        custom_prompt = str(_unpack(custom_prompt) or "").strip()
        llm_site = normalize_runninghub_llm_site(_unpack(llm_site))
        llm_config = _unpack(llm_config)
        requested_llm_model = str(_unpack(model) or "").strip()
        rule_planning = (
            (scene == LAYOUT_SPLIT_SCENE and _is_rule_planner_mode(planner_mode))
            or scene == GENERIC_SCENE
            or _is_rule_planner_mode(planner_mode)
        )
        configured_model = ""
        if isinstance(llm_config, dict):
            configured_model = str(
                llm_config.get("model_name") or llm_config.get("models_name") or ""
            ).strip()
        if rule_planning:
            llm_model = configured_model or requested_llm_model
            model_fallback = False
        elif configured_model:
            llm_model = configured_model
            model_fallback = False
        else:
            llm_model, model_fallback = resolve_runninghub_site_model(
                llm_site,
                requested_llm_model,
                require_vision=True,
            )
        product_or_reference_image = _unpack(product_or_reference_image)
        style_reference_image = _unpack(style_reference_image)
        if scene == LAYOUT_SPLIT_SCENE:
            style_reference_image = None
        style_pass_through = style_reference_image is not None
        style_strength, complexity = _auto_style_controls(scene)

        if scene == GENERIC_SCENE and not custom_prompt:
            raise RuntimeError("通用透明素材模式需要填写 custom_prompt。")

        llm_debug = ""
        planner_style_prompt = ""
        source_image_description = ""
        source_canvas = _source_canvas_metadata(product_or_reference_image) if scene == LAYOUT_SPLIT_SCENE else {}
        if rule_planning:
            items = _fallback_items(scene, count, custom_prompt, suppress_style=style_pass_through)
            plan_source = "layer_preset" if scene == LAYOUT_SPLIT_SCENE else "rule"
        else:
            try:
                items, llm_debug, planner_style_prompt, source_image_description, source_canvas = _plan_with_llm(
                    scene,
                    count,
                    custom_prompt,
                    style_strength,
                    complexity,
                    llm_model,
                    product_or_reference_image,
                    style_reference_image,
                    llm_site,
                    llm_config,
                )
                plan_source = f"llm:{llm_site}:{llm_model}"
            except Exception as exc:
                print(f"[TransparentAssetPrompts] LLM 规划失败，使用规则预设: {exc}")
                items = _fallback_items(scene, count, custom_prompt, suppress_style=style_pass_through)
                plan_source = f"rule_fallback:{exc}"

        base_style = _style_lock(scene, style_strength, complexity, custom_prompt, count)
        reference_role_notes = _reference_image_role_notes(product_or_reference_image, style_reference_image)
        style = (
            ""
            if scene == LAYOUT_SPLIT_SCENE
            else _compose_style_lock(base_style, planner_style_prompt, style_pass_through, reference_role_notes)
        )
        if scene == LAYOUT_SPLIT_SCENE and items:
            remove_content = "; ".join(
                str(item.get("visible_content") or item.get("description") or "").strip()
                for item in items
                if item.get("slot_id") != "background"
            )
            items[0]["remove_content"] = remove_content
        prompts = [
            _build_generation_prompt(
                scene,
                item,
                style,
                index,
                len(items),
                style_pass_through=style_pass_through,
                source_image_description=source_image_description,
                source_canvas=source_canvas,
            )
            for index, item in enumerate(items, start=1)
        ]

        plan = {
            "scene_preset": scene,
            "planner_mode": planner_mode,
            "plan_source": plan_source,
            "llm_site": llm_site,
            "llm_model_requested": requested_llm_model,
            "llm_model_resolved": llm_model,
            "llm_model_fallback": model_fallback,
            "prompt_config_path": PROMPT_CONFIG_PATH,
            "asset_count": None if scene == LAYOUT_SPLIT_SCENE else len(items),
            "layer_count": len(items) if scene == LAYOUT_SPLIT_SCENE else None,
            "scene_rendering_strategy": {
                "fidelity": style_strength,
                "detail": complexity,
                "source": "scene_preset_auto_default",
            },
            "style_prompt_source": "none_for_reference_layer_split" if scene == LAYOUT_SPLIT_SCENE else ("image_reference_pass_through" if style_pass_through else ("llm" if planner_style_prompt else "rule")),
            "style_prompt": "" if scene == LAYOUT_SPLIT_SCENE else ("connected style_reference_image only" if style_pass_through else (planner_style_prompt or base_style)),
            "style_prompt_ignored_due_to_reference_image": planner_style_prompt if style_pass_through and planner_style_prompt else "",
            "style_reference_image_used": style_reference_image is not None,
            "reference_image_role_notes": reference_role_notes,
            "source_image_description": source_image_description,
            "source_canvas": source_canvas,
            "slot_order": [item.get("slot_id", "") for item in items],
            "layer_order_bottom_to_top": [
                slot_id
                for slot_id in (
                    "background",
                    "subject_product",
                    "decorations",
                    "lighting_atmosphere",
                    "other_reusable",
                    "text_logo",
                )
                if slot_id in {item.get("slot_id", "") for item in items}
            ],
            "items": [
                {
                    "index": index,
                    "key": item.get("slot_id", ""),
                    "slot_id": item.get("slot_id", ""),
                    "name": item.get("name", ""),
                    "description": item.get("description", ""),
                    "visible_content": item.get("visible_content", ""),
                    "edit_instruction": item.get("edit_instruction", ""),
                    "planner_prompt": item.get("prompt", ""),
                    "geometry": item.get("geometry", {}),
                    "generation_prompt": prompts[index - 1],
                }
                for index, item in enumerate(items, start=1)
            ],
        }
        if llm_debug:
            plan["llm_raw_response"] = llm_debug

        status = (
            f"透明素材提示词生成完成：scene={scene}，规划={plan_source}，"
            f"输出 {len(prompts)} 条提示词。可连接到后续RunningHub GPT Image 2.5生成节点。"
        )
        if model_fallback:
            status += (
                f" 所选模型 {requested_llm_model or '<empty>'} 不属于 {llm_site}，"
                f"已改用 {llm_model}。"
            )
        return (
            prompts,
            json.dumps(plan, ensure_ascii=False, indent=2),
            _plain_prompt_text(items, prompts),
            status,
        )


NODE_CLASS_MAPPINGS = {
    "SynVowTransparentAssetPromptGenerator": SynVowTransparentAssetPromptGenerator,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SynVowTransparentAssetPromptGenerator": "SynVow 透明素材提示词生成器",
}
