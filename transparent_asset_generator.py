# -*- coding: utf-8 -*-
"""
SynVow transparent asset prompt generator.

This module only adds new ComfyUI nodes. It reuses the existing SynVow auth and
LLM client, but leaves image generation to the existing GPT-Image-2 nodes.
"""

import hashlib
import base64
import io
import json
import os
import re
from typing import Any, Dict, List, Tuple

import numpy as np
import requests
import urllib3
from PIL import Image

from .utils import (
    default_runninghub_model,
    fetch_runninghub_models,
    make_headers,
    parse_chat_response,
    resolve_llm_config,
)


CATEGORY = "SynVow-prompt/透明素材"
NODE_VERSION = "2026-07-01-transparent-assets-prompts-only-v9"
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


SCENE_PRESETS = _config_list("scene_presets", ["通用透明素材", "电商素材包"])
PLANNER_MODES = _config_list("planner_modes", ["自动规划(LLM)", "规则预设(不调用LLM)"])
ASSET_COUNTS = _config_list("asset_counts", ["1", "2", "4", "6", "8", "12"])
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
DEFAULT_STYLE_STRENGTH = _default_option("style_strength", STYLE_STRENGTHS, "标准")
DEFAULT_COMPLEXITY = _default_option("complexity", COMPLEXITIES, "适中")
GENERIC_SCENE = "通用透明素材"
LAYOUT_SPLIT_SCENE = "参考图分层拆图"
LAYOUT_SPLIT_LAYER_NAMES = [
    "文字/Logo层",
    "主体/人物/产品层",
    "背景层",
    "装饰元素层",
    "光影氛围层",
    "其他可复用元素层",
]


def _unpack(value):
    return value[0] if isinstance(value, list) else value


def _safe_int(value, default=1):
    try:
        return int(str(value).strip())
    except Exception:
        return default


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


def _layout_split_fallback_items(count: int, custom_prompt: str = "") -> List[Dict[str, str]]:
    style_direction = _style_direction_from_custom_prompt(LAYOUT_SPLIT_SCENE, custom_prompt, count)
    names = LAYOUT_SPLIT_LAYER_NAMES[:max(1, min(count, len(LAYOUT_SPLIT_LAYER_NAMES)))]
    result = []
    for name in names:
        result.append({
            "name": name,
            "description": name,
            "prompt": _single_custom_item_prompt(LAYOUT_SPLIT_SCENE, name, style_direction, []),
        })
    return result


def _fallback_items(scene: str, count: int, custom_prompt: str = "") -> List[Dict[str, str]]:
    if scene == GENERIC_SCENE:
        base = custom_prompt.strip() or "transparent design asset"
        result = []
        for index in range(1, count + 1):
            subject = base if count == 1 else f"{base}, variation {index}"
            result.append({
                "name": f"通用透明素材_{index:02d}",
                "description": subject,
                "prompt": _single_custom_item_prompt(scene, subject, "", []),
            })
        return result
    if scene == LAYOUT_SPLIT_SCENE:
        return _layout_split_fallback_items(count, custom_prompt)

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
                "prompt": _single_custom_item_prompt(scene, item_name, style_direction, other_names),
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
            "prompt": _single_custom_item_prompt(scene, name, style_direction, []),
        })
    return result


def _extract_custom_item_names(scene: str, custom_prompt: str, count: int) -> List[str]:
    text = str(custom_prompt or "").strip()
    if not text or scene == GENERIC_SCENE:
        return []

    match = re.search(r"(?:包含|包括|含有|分别是|需要|拆出|提取|:|：)(.+)", text)
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


def _layout_split_item_prompt(item_name: str, style_direction: str) -> str:
    style_text = f" User split instruction: {style_direction}." if style_direction else ""
    common = (
        "Use the connected reference image as the only source of truth. "
        "Do not invent new props, mascots, icons, food, stickers, text, or unrelated design assets. "
        "Preserve the reference image's visual identity, placement logic, color relationship, and commercial poster style."
    )
    if "文字" in item_name or "Logo" in item_name or "logo" in item_name.lower():
        return (
            "Recreate only the visible text, typography, logo marks, brand marks, numbers, and small written labels from the reference image "
            "as one transparent overlay layer. Preserve their approximate shapes, colors, positions, scale relationships, and hierarchy. "
            "Do not include the person, product, background, decorative props, shadows, or scene surfaces. Visible text is allowed for this layer. "
            f"{common}{style_text}"
        )
    if any(word in item_name for word in ("主体", "人物", "产品", "主角")):
        return (
            "Recreate only the main foreground subject layer from the reference image: the primary person/IP/character and the main held or displayed product if present. "
            "Preserve pose, crop, silhouette, clothing/product shape, and the relationship between person and product. "
            "Do not include text/logo, background walls/floor, decorative stickers, floating props, or unrelated objects. "
            f"{common}{style_text}"
        )
    if "背景" in item_name:
        return (
            "Recreate only the background layer from the reference image as a clean full-frame background plate. "
            "Preserve the main background colors, gradients, wall/floor planes, lighting direction, and broad composition. "
            "Remove the person, product, text/logo, foreground stickers, mascots, decorative props, and floating elements. "
            "The background layer may be opaque and rectangular; do not add new objects. "
            f"{common}{style_text}"
        )
    if any(word in item_name for word in ("装饰", "元素", "光影", "氛围", "其他")):
        return (
            "Recreate only the visible decorative foreground elements from the reference image as one transparent overlay layer. "
            "This can include existing stickers, mascots, props, sparkles, drops, ribbons, light accents, badges, or small decoration elements that are actually visible in the reference. "
            "Do not include text/logo, the main person, main product, or background plate. Do not add new decorations that are not in the reference. "
            f"{common}{style_text}"
        )
    return (
        f"Recreate only the {item_name} from the reference image as a separate design layer. "
        f"{common}{style_text}"
    )


def _single_custom_item_prompt(scene: str, item_name: str, style_direction: str, other_names: List[str]) -> str:
    style_text = f" Style direction: {style_direction}." if style_direction else ""
    one_asset_rule = (
        "This prompt is for the current asset only. "
        "The output canvas must contain exactly one object only."
    )
    if scene == LAYOUT_SPLIT_SCENE:
        return _layout_split_item_prompt(item_name, style_direction)
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
        return (
            f"Generate exactly one simple original cartoon mascot/emote sticker asset: {item_name}. "
            f"{one_asset_rule} Use one non-real-person mascot head, bust, or simple rounded character with one clear expression or gesture. "
            "If a reference image is provided, convert it into one consistent original chibi sticker character; "
            "preserve only general hair, face and color cues, not a photoreal portrait. "
            f"{CHARACTER_STICKER_CONSISTENCY_LOCK} "
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


def _enforce_single_asset_prompt(scene: str, name: str, prompt: str, custom_prompt: str, count: int) -> str:
    style_direction = _style_direction_from_custom_prompt(scene, custom_prompt, count)
    single_prompt = _single_custom_item_prompt(scene, name, style_direction, [])
    if scene == LAYOUT_SPLIT_SCENE:
        return single_prompt
    raw_prompt = re.sub(r"\s+", " ", str(prompt or "")).strip()
    if not raw_prompt or _prompt_mentions_multi_asset(raw_prompt):
        return single_prompt
    return (
        f"{single_prompt} Preserve only relevant single-object visual details from planner: "
        f"{raw_prompt}. Ignore any wording that implies a pack, sheet, grid, multiple objects, "
        f"complete layout, poster, UI screen, or scene."
    )


def _normalize_items(value: Any, count: int, scene: str, custom_prompt: str = "") -> List[Dict[str, str]]:
    if scene == LAYOUT_SPLIT_SCENE:
        return _layout_split_fallback_items(count, custom_prompt)

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
                "prompt": _enforce_single_asset_prompt(scene, name, prompt, custom_prompt, count),
            })

    if len(normalized) < count:
        fallback = _fallback_items(scene, count, custom_prompt)
        normalized.extend(fallback[len(normalized):count])
    return normalized[:count]


def _planner_system_prompt() -> str:
    return str(PROMPT_CONFIG.get(
        "planner_system_prompt",
        "You are a transparent PNG asset planner. Return strict JSON only with items.",
    ))


def _tensor_to_data_url(image, index: int = 0) -> str:
    tensor = image[index] if hasattr(image, "shape") and len(image.shape) == 4 else image
    if hasattr(tensor, "detach"):
        tensor = tensor.detach().cpu().numpy()
    array = np.asarray(tensor)
    array = np.clip(array * 255.0, 0, 255).astype(np.uint8)
    if array.ndim == 2:
        pil_image = Image.fromarray(array, mode="L").convert("RGB")
    elif array.shape[-1] == 4:
        pil_image = Image.fromarray(array, mode="RGBA").convert("RGB")
    else:
        pil_image = Image.fromarray(array[..., :3], mode="RGB")

    buffer = io.BytesIO()
    pil_image.save(buffer, format="JPEG", quality=92)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _image_to_data_urls(image, max_images: int = 8) -> List[str]:
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


def _chat_completion(
    llm_model: str,
    system_prompt: str,
    user_prompt: str,
    image_urls: List[str] = None,
    temperature: float = 0.35,
    max_tokens: int = 3500,
    timeout: int = 240,
    seed: int = None,
    llm_config=None,
) -> str:
    base_url, apikey, model_name = resolve_llm_config(llm_config, model_name=llm_model)
    if not base_url or not apikey or not model_name:
        raise RuntimeError("缺少 LLM 配置：请登录 RunningHub/设置 RH_API_KEY，或连接 SynVow LLM Settings。")

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
    if seed is not None:
        payload["seed"] = int(seed) % 2147483647

    response = requests.post(
        base_url.rstrip("/"),
        headers=make_headers(apikey),
        json=payload,
        timeout=(30, timeout),
        verify=False,
    )
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        body = response.text[:2000] if response.text else "<empty response>"
        print(f"[TransparentAssetPrompts] RunningHub LLM HTTP {response.status_code} url={response.url}")
        print(f"[TransparentAssetPrompts] response={body}")
        if response.status_code == 401 and "only SHARED" in body:
            raise RuntimeError(
                "RunningHub LLM 认证失败：当前账号/API Key 不是 LLM 网关接受的 SHARED/enterprise key。"
                "请换用支持 LLM 的 RunningHub 企业/共享 Key，或连接 SynVow LLM Settings 使用第三方接口。"
            ) from exc
        raise RuntimeError(f"RunningHub LLM 请求失败: HTTP {response.status_code}; response={body}") from exc

    raw = parse_chat_response(response.json())
    if not raw or not raw.strip():
        raise RuntimeError(f"模型未返回有效内容: {str(response.json())[:300]}")
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
    seed: int = None,
    llm_config=None,
) -> Tuple[List[Dict[str, str]], str, str]:
    image_urls: List[str] = []
    if product_image is not None:
        image_urls.extend(_image_to_data_urls(product_image))
    if style_image is not None:
        image_urls.extend(_image_to_data_urls(style_image))

    user_payload = {
        "scene_preset": scene,
        "asset_count": count,
        "scene_strategy": SCENE_HINTS.get(scene, ""),
        "user_direction": custom_prompt or "",
        "style_strength": style_strength,
        "visual_complexity": complexity,
        "reference_images": {
            "product_or_ip_reference": product_image is not None,
            "style_reference": style_image is not None,
        },
        "requirements": _config_list("planner_requirements", [
            "Plan exactly asset_count items.",
            "Each item must be reusable as a transparent PNG component.",
            "The whole pack must share one consistent visual style.",
            "Do not plan full posters, full ecommerce main images, or full UI screens.",
        ]),
    }
    content = _chat_completion(
        llm_model,
        _planner_system_prompt(),
        json.dumps(user_payload, ensure_ascii=False),
        image_urls=image_urls,
        temperature=0.35,
        max_tokens=3500,
        timeout=240,
        seed=seed,
        llm_config=llm_config,
    )
    parsed = _extract_json_object(content)
    return _normalize_items(parsed, count, scene, custom_prompt), content, _normalize_style_prompt(parsed)


def _style_lock(scene: str, style_strength: str, complexity: str, custom_prompt: str, count: int = 0) -> str:
    strength_map = _config_dict("style_strength_map")
    complexity_map = _config_dict("complexity_map")
    style_direction = _style_direction_from_custom_prompt(scene, custom_prompt, count)
    return (
        f"Shared visual style: {SCENE_HINTS.get(scene, '')} "
        f"Style strength: {strength_map.get(style_strength, style_strength)}. "
        f"Complexity: {complexity_map.get(complexity, complexity)}. "
        f"User direction: {style_direction or 'follow the scene preset'}."
    )


def _compose_style_lock(base_style: str, planner_style_prompt: str) -> str:
    base_style = str(base_style or "").strip()
    planner_style_prompt = str(planner_style_prompt or "").strip()
    if not planner_style_prompt:
        return base_style
    return (
        f"{base_style}\n"
        f"Global style prompt generated by planner, apply identically to every output: {planner_style_prompt}\n"
        "Do not reinterpret or vary this global style prompt between assets; only change the requested asset subject, expression, gesture or function."
    )


def _scene_generation_rules(scene: str) -> str:
    rules = _config_dict("scene_generation_rules")
    return str(rules.get(scene) or rules.get(GENERIC_SCENE) or "Generate one transparent reusable asset.")


def _transparent_constraints_for_item(scene: str, item_name: str) -> str:
    if scene != LAYOUT_SPLIT_SCENE:
        return TRANSPARENT_CONSTRAINTS
    name = str(item_name or "")
    if "背景" in name:
        return (
            "Layer constraints: output the background layer only. A full-frame opaque or semi-opaque rectangular background plate is allowed. "
            "Do not include text, logo, person, product, foreground decoration, stickers, mascots, or checkerboard/fake transparency."
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


def _build_generation_prompt(
    scene: str,
    item: Dict[str, str],
    style_lock: str,
    index: int,
    count: int,
) -> str:
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
        "style_lock": style_lock,
        "scene_rule": _scene_generation_rules(scene),
        "transparent_constraints": _transparent_constraints_for_item(scene, item.get("name", "")),
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
        llm_models = fetch_runninghub_models()
        return {
            "required": {
                "scene_preset": (SCENE_PRESETS, {"default": DEFAULT_SCENE}),
                "planner_mode": (PLANNER_MODES, {"default": DEFAULT_PLANNER_MODE}),
                "asset_count": (ASSET_COUNTS, {"default": DEFAULT_ASSET_COUNT}),
                "custom_prompt": ("STRING", {"multiline": True, "default": ""}),
                "model": (llm_models, {"default": default_runninghub_model(llm_models)}),
                "style_strength": (STYLE_STRENGTHS, {"default": DEFAULT_STYLE_STRENGTH}),
                "complexity": (COMPLEXITIES, {"default": DEFAULT_COMPLEXITY}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 2147483647}),
            },
            "optional": {
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
        style_strength,
        complexity,
        seed,
        llm_config=None,
        product_or_reference_image=None,
        style_reference_image=None,
    ):
        scene = _unpack(scene_preset) or DEFAULT_SCENE
        planner_mode = _unpack(planner_mode) or DEFAULT_PLANNER_MODE
        count = _safe_int(_unpack(asset_count), _safe_int(DEFAULT_ASSET_COUNT, 6))
        custom_prompt = str(_unpack(custom_prompt) or "").strip()
        llm_model = _unpack(model) or default_runninghub_model(fetch_runninghub_models())
        style_strength = _unpack(style_strength) or DEFAULT_STYLE_STRENGTH
        complexity = _unpack(complexity) or DEFAULT_COMPLEXITY
        seed = _safe_int(_unpack(seed), 0)
        llm_config = _unpack(llm_config)
        product_or_reference_image = _unpack(product_or_reference_image)
        style_reference_image = _unpack(style_reference_image)

        if scene == GENERIC_SCENE and not custom_prompt:
            raise RuntimeError("通用透明素材模式需要填写 custom_prompt。")

        llm_debug = ""
        planner_style_prompt = ""
        if scene == LAYOUT_SPLIT_SCENE:
            items = _fallback_items(scene, count, custom_prompt)
            plan_source = "layer_preset"
        elif scene == GENERIC_SCENE or planner_mode == "规则预设(不调用LLM)":
            items = _fallback_items(scene, count, custom_prompt)
            plan_source = "rule"
        else:
            try:
                items, llm_debug, planner_style_prompt = _plan_with_llm(
                    scene,
                    count,
                    custom_prompt,
                    style_strength,
                    complexity,
                    llm_model,
                    product_or_reference_image,
                    style_reference_image,
                    seed,
                    llm_config,
                )
                plan_source = f"llm:{llm_model}"
            except Exception as exc:
                print(f"[TransparentAssetPrompts] LLM 规划失败，使用规则预设: {exc}")
                items = _fallback_items(scene, count, custom_prompt)
                plan_source = f"rule_fallback:{exc}"

        base_style = _style_lock(scene, style_strength, complexity, custom_prompt, count)
        style = _compose_style_lock(base_style, planner_style_prompt)
        prompts = [
            _build_generation_prompt(scene, item, style, index, len(items))
            for index, item in enumerate(items, start=1)
        ]

        plan = {
            "scene_preset": scene,
            "planner_mode": planner_mode,
            "plan_source": plan_source,
            "prompt_config_path": PROMPT_CONFIG_PATH,
            "asset_count": len(items),
            "style_strength": style_strength,
            "complexity": complexity,
            "style_prompt_source": "llm" if planner_style_prompt else "rule",
            "style_prompt": planner_style_prompt or base_style,
            "items": [
                {
                    "index": index,
                    "name": item.get("name", ""),
                    "description": item.get("description", ""),
                    "planner_prompt": item.get("prompt", ""),
                    "generation_prompt": prompts[index - 1],
                }
                for index, item in enumerate(items, start=1)
            ],
        }
        if llm_debug:
            plan["llm_raw_response"] = llm_debug

        status = (
            f"透明素材提示词生成完成：scene={scene}，规划={plan_source}，"
            f"输出 {len(prompts)} 条提示词。可直接连接到 RH GPT-Image-2 Alpha (T_batch) 的 prompts_list。"
        )
        return (
            prompts,
            json.dumps(plan, ensure_ascii=False, indent=2),
            _plain_prompt_text(items, prompts),
            status,
        )


NODE_CLASS_MAPPINGS = {
    "SynVowPromptTransparentAssetPromptGenerator": SynVowTransparentAssetPromptGenerator,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SynVowPromptTransparentAssetPromptGenerator": "SynVow 透明素材提示词生成器 (RH)",
}
