# -*- coding: utf-8 -*-
"""
SynVow long-scroll e-commerce detail page workflow nodes.

This module is intentionally self-contained and only adds new nodes. It does
not modify or depend on existing SynVow node implementations.
"""

import hashlib
import json
import os
import re
import time
from copy import deepcopy

import requests
import torch
import torch.nn.functional as F

import base64
import io
import numpy as np
from PIL import Image

from .utils import (
    default_runninghub_model,
    fetch_runninghub_models,
    make_headers,
    parse_chat_response,
    resolve_llm_config,
)


CATEGORY = "SynVow-prompt/RH详情页"
PROMPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "prompts"))
RUNNINGHUB_MODELS = fetch_runninghub_models()
DEFAULT_MODEL = default_runninghub_model(RUNNINGHUB_MODELS) if RUNNINGHUB_MODELS else "gemini-3.1-flash-2606"
PAGE_STRUCTURE_CHUNK_SIZE = 2
PROMPT_BATCH_CHUNK_SIZE = 2
LONGSCROLL_NODE_VERSION = "2026-06-04-lightweight-outline-chunk2-v1"
VISIBLE_TEXT_FORBIDDEN_LABELS = {
    "FAQ",
    "FAQ/收口",
    "FAQ收口",
    "FAQ异议处理",
    "FAQ异议处理屏",
    "CTA",
    "CTA生活方式收口",
    "CTA生活方式收口屏",
    "收口",
    "收口页",
    "收口屏",
    "总结页",
    "搜索页",
    "搜索",
    "导航页",
    "导航",
    "品牌收口",
    "情感化收口",
    "场景页",
    "场景/人物",
    "人物体验场景屏",
    "卖点页",
    "功能页",
    "功能",
    "功能卖点",
    "功能主视觉屏",
    "细节",
    "细节页",
    "细节微距屏",
    "步骤",
    "步骤页",
    "步骤/使用演示",
    "参数页",
    "参数",
    "参数/信任",
    "参数信任",
    "参数信任屏",
    "信任页",
    "信任",
    "首图/核心利益",
    "核心利益",
    "模块名",
}
VISIBLE_TEXT_FORBIDDEN_PATTERN = re.compile(
    r'(visible Chinese (?:headline|subheadline|tags):\s*")'
    r'(?:FAQ|FAQ/收口|FAQ收口|FAQ异议处理|FAQ异议处理屏|CTA|CTA生活方式收口|CTA生活方式收口屏|收口|收口页|收口屏|总结页|搜索页|搜索|导航页|导航|品牌收口|情感化收口|场景页|场景/人物|卖点页|功能页|功能|细节|细节页|步骤|步骤页|步骤/使用演示|参数页|参数|参数/信任|参数信任|信任页|信任|首图/核心利益|核心利益|模块名)'
    r'(")',
    re.IGNORECASE,
)
FINAL_PROMPT_FORBIDDEN_FRAGMENT_PATTERN = re.compile(
    r'\b(?:FAQ\s*search|search\s*page|summary\s*page|navigation\s*page|search\s*UI|search\s*bar)\b|搜索页|总结页|导航页|搜索栏',
    re.IGNORECASE,
)


DEFAULT_TYPOGRAPHY_LOCK = {
    "font_family_style": "统一使用现代中文无衬线字体风格，优先接近思源黑体 / 阿里巴巴普惠体 / HarmonyOS Sans；不要书法体、宋体、手写体、英文衬线体。",
    "headline_weight": "标题统一中粗或半粗，字形干净，笔画稳定；不要每屏更换字重。",
    "body_weight": "正文统一常规字重，小字尽量减少，保持清晰可读。",
    "hierarchy": "每屏最多 3 级文字：主标题 > 副标题 > 标签/短注释；同级字号和行距保持一致。",
    "alignment": "同一屏内文字对齐方式统一，优先左对齐或居中对齐，不要混用多种对齐。",
    "spacing": "字距为 0 或自然字距，行距舒展；不要负字距、过密排版、拉伸字体。",
    "forbidden": "不要英文标题、英文参数表、乱码、花体字、过度描边、强投影、不同字体混排。",
}


MODULE_TYPE_RULES = {
    "hero": {
        "label": "首图/核心利益",
        "target": "1 屏，通常为第 01 屏",
        "allowed_archetypes": ["Hero场景首屏"],
        "notes": "建立产品第一印象、核心利益和视觉基调。",
        "screen_job": "一句话建立产品是谁、核心利益是什么、为什么值得继续看。",
        "evidence_type": "产品主视觉 + 3 个以内核心利益标签",
    },
    "scenario_person": {
        "label": "场景/人物",
        "target": "10 屏中 2-3 屏",
        "allowed_archetypes": ["人物体验场景屏", "场景矩阵屏", "Hero场景首屏", "CTA生活方式收口屏"],
        "notes": "延续首屏视觉世界，展示真实使用、生活场景、情绪利益和产品陪伴感；产品必须清晰出现或有明确关系。",
        "screen_job": "把首屏核心卖点放进更真实的生活方式场景，回答用户用起来是什么状态、为什么愿意带着它。",
        "evidence_type": "人物体验 / 生活场景 / 使用结果 / 情绪利益",
    },
    "function": {
        "label": "功能",
        "target": "10 屏中 2 屏",
        "allowed_archetypes": ["功能主视觉屏", "功能剖面 + 双细节小窗", "痛点解决合并屏"],
        "notes": "解释核心功能、效果机制、模式能力，避免只做漂亮海报。",
        "screen_job": "解释一个核心能力如何解决一个具体问题，每屏只讲一个主要功能。",
        "evidence_type": "功能演示 / 原理示意 / 模式标签 / 效果可视化",
    },
    "detail": {
        "label": "细节",
        "target": "10 屏中 1-2 屏",
        "allowed_archetypes": ["细节微距屏", "功能剖面 + 双细节小窗"],
        "notes": "展示材质、结构、按键、接口、工艺、关键部件等购买证据。",
        "screen_job": "用近距离证据证明品质、工艺、材质或结构，而不是重复功能利益。",
        "evidence_type": "微距细节 / 材质纹理 / 结构放大 / 工艺特写",
    },
    "steps": {
        "label": "步骤/使用演示",
        "target": "10 屏中 1 屏",
        "allowed_archetypes": ["使用步骤三连屏"],
        "notes": "用 3 个以内步骤说明怎么用、怎么清洗、怎么佩戴或怎么完成关键操作。",
        "screen_job": "降低使用门槛，说明用户从拿到产品到完成关键操作有多简单。",
        "evidence_type": "步骤序列 / 手部操作 / 前中后动作",
    },
    "parameter_trust": {
        "label": "参数/信任",
        "target": "10 屏中 1 屏",
        "allowed_archetypes": ["参数信任屏", "细节微距屏"],
        "notes": "集中呈现规格、材质、安全、认证、售后或包装配件，不能变成生硬白底表格。",
        "screen_job": "集中回答理性购买问题，给出规格、安全、材质、认证或售后信任。",
        "evidence_type": "参数短表 / 认证标签 / 材质说明 / 售后保障",
    },
    "faq_close": {
        "label": "FAQ/收口",
        "target": "10 屏中 1 屏",
        "allowed_archetypes": ["FAQ异议处理屏", "CTA生活方式收口屏"],
        "notes": "用简单安静的生活方式画面做情感化收束，可轻量处理 1-2 个购买异议；不要重复参数表，不要加入立即购买按钮。",
        "screen_job": "用情感化语言收束购买理由，处理最后 1-2 个轻量顾虑，留下生活向往。",
        "evidence_type": "生活方式画面 / 最终利益短句 / 轻量 FAQ / 信任短句",
    },
}


def read_text(name, fallback=""):
    path = os.path.join(PROMPTS_DIR, name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return fallback


def read_json(name, fallback):
    path = os.path.join(PROMPTS_DIR, name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return deepcopy(fallback)


def defaults():
    return read_json("longscroll_detail_defaults.json", {})


def to_json(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def load_json(value, fallback):
    try:
        return json.loads(value)
    except Exception:
        return deepcopy(fallback)


# --- Synced standalone long-scroll helper functions ---
def find_slice_item(structure, slice_id):
    wanted = str(slice_id).strip().zfill(2)
    if isinstance(structure, list):
        structure = {"items": structure}
    if not isinstance(structure, dict):
        return {}
    for key in ("items", "sections"):
        for item in structure.get(key, []):
            if str(item.get("slice_id", "")).strip().zfill(2) == wanted:
                return item
    return {}


def text_exact_to_lines(text_exact):
    if isinstance(text_exact, list):
        return [str(item).strip() for item in text_exact if str(item).strip()]
    if isinstance(text_exact, dict):
        lines = []
        for key in ("headline", "subheadline"):
            if str(text_exact.get(key, "")).strip():
                lines.append(str(text_exact.get(key)).strip())
        tags = text_exact.get("tags", [])
        if isinstance(tags, list):
            lines.extend(str(tag).strip() for tag in tags if str(tag).strip())
        elif str(tags).strip():
            lines.append(str(tags).strip())
        return lines
    text = str(text_exact or "").strip()
    return [text] if text else []


def is_forbidden_visible_label(value):
    text = str(value or "").strip()
    if not text:
        return False
    compact = re.sub(r"[\s:：｜|_-]+", "", text)
    return text in VISIBLE_TEXT_FORBIDDEN_LABELS or compact in VISIBLE_TEXT_FORBIDDEN_LABELS


def safe_visible_text_lines(text_exact, module_type=""):
    lines = [line for line in text_exact_to_lines(text_exact) if not is_forbidden_visible_label(line)]
    if str(module_type or "").strip() == "faq_close":
        lines = [line for line in lines if "FAQ" not in line.upper() and "收口" not in line]
    return lines


def fallback_visible_text_for_module(module_type):
    return {
        "hero": ["今天也要轻松一点", "把日常小事变成好心情"],
        "scenario_person": ["随手一拿，刚刚好", "通勤办公都自在"],
        "function": ["好用不止一面", "容量、便携与日常体验都在线"],
        "detail": ["看得见的用心细节", "每一处都为日常体验考虑"],
        "steps": ["三步轻松开启", "拿起、加饮、随时享用"],
        "parameter_trust": ["买得放心，用得安心", "实用配置清楚可见"],
        "faq_close": [],
    }.get(str(module_type or "").strip(), ["好看，也好用", "让日常多一点轻松感"])


def sanitize_text_exact(text_exact, module_type=""):
    lines = safe_visible_text_lines(text_exact, module_type)
    if isinstance(text_exact, dict):
        return {
            "headline": lines[0] if lines else "",
            "subheadline": lines[1] if len(lines) > 1 else "",
            "tags": lines[2:5],
        }
    return lines


def sanitize_structure_item_visible_text(item):
    if not isinstance(item, dict):
        return item
    module_type = str(item.get("module_type", "")).strip()
    item["text_exact"] = sanitize_text_exact(item.get("text_exact", {}), module_type)
    if not safe_visible_text_lines(item.get("text_exact", {}), module_type) and module_type != "faq_close":
        item["text_exact"] = sanitize_text_exact(fallback_visible_text_for_module(module_type), module_type)
    primary = item.get("primary_module")
    if isinstance(primary, dict) and is_forbidden_visible_label(primary.get("message", "")):
        safe_lines = safe_visible_text_lines(item.get("text_exact", {}), module_type)
        primary["message"] = safe_lines[0] if safe_lines else ""
    for module in item.get("secondary_modules", []) or []:
        if not isinstance(module, dict):
            continue
        message = module.get("message", "")
        if isinstance(message, list):
            module["message"] = [value for value in message if not is_forbidden_visible_label(value)]
        elif is_forbidden_visible_label(message):
            module["message"] = ""
    if module_type == "faq_close":
        item["closing_visible_text_policy"] = (
            "Do not render internal planning labels, page-type names, UI words or structural placeholders. "
            "If no meaningful closing copy is available, use a product/lifestyle closing visual with no visible text."
        )
    return item


def sanitize_final_prompt(prompt):
    text = str(prompt or "")
    text = VISIBLE_TEXT_FORBIDDEN_PATTERN.sub(r'\1\2', text)
    text = FINAL_PROMPT_FORBIDDEN_FRAGMENT_PATTERN.sub("customer-facing ecommerce detail page visual", text)
    forbidden_note = (
        "Visible text safety: render only the exact customer-facing Chinese headline, subheadline and tags provided in the Chinese typography line. "
        "Do not render any internal planning label, module name, page type, debug word, workflow word, UI/search/navigation word, or structural placeholder as visible text. "
        "If no customer-facing copy is provided for a closing screen, use a clean product or lifestyle closing image with no visible text."
    )
    if forbidden_note not in text:
        text += f"\n{forbidden_note}"
    return text


def sanitize_prompt_blueprint_context(prompt, item):
    text = str(prompt or "")
    slice_id = str(item.get("slice_id", "")).strip().zfill(2)
    module_type = str(item.get("module_type", "")).strip() or "detail"
    layout_replacement = (
        "Layout intent: Use this screen's information intent as a flexible ecommerce composition guide, "
        "not as a visible label or fixed template."
    )
    replacements = {
        "Current viewport:": f"Current viewport: Slice {slice_id}, customer-facing ecommerce detail page screen.",
        "Module role:": f"Module role: {module_type} screen; describe only visual hierarchy and commercial task, not internal labels.",
        "Layout intent:": layout_replacement,
    }
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        replaced = False
        for prefix, replacement in replacements.items():
            if stripped.startswith(prefix):
                cleaned_lines.append(replacement)
                replaced = True
                break
        if not replaced:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def prompt_has_visible_chinese_copy(prompt):
    text = str(prompt or "")
    return (
        "visible Chinese headline:" in text
        and "visible Chinese subheadline:" in text
        and "visible Chinese tags:" in text
    )


def ensure_prompt_visible_copy(prompt, item):
    module_type = str(item.get("module_type", "")).strip()
    text_lines = safe_visible_text_lines(item.get("text_exact", {}), module_type)
    if not text_lines and module_type != "faq_close":
        text_lines = fallback_visible_text_for_module(module_type)
    if not text_lines:
        return prompt
    headline = text_lines[0] if text_lines else ""
    subheadline = text_lines[1] if len(text_lines) > 1 else ""
    tags = " / ".join(text_lines[2:5])
    text = str(prompt or "").strip()
    if not prompt_has_visible_chinese_copy(text):
        text += (
            f"\nChinese typography: visible Chinese headline: \"{headline}\"; "
            f"visible Chinese subheadline: \"{subheadline}\"; "
            f"visible Chinese tags: \"{tags}\". "
            "Use clean modern Chinese sans-serif typography. These are the only visible text elements."
        )
    return text


def compact_item_for_prompt(item):
    return {
        "slice_id": item.get("slice_id", ""),
        "chapter": item.get("chapter", ""),
        "section_name": item.get("section_name", ""),
        "module_type": item.get("module_type", ""),
        "module_label": item.get("module_label", ""),
        "screen_job": item.get("screen_job", ""),
        "evidence_type": item.get("evidence_type", ""),
        "commercial_goal": item.get("commercial_goal", ""),
        "user_question": item.get("user_question", ""),
        "layout_archetype": item.get("layout_archetype", ""),
        "primary_module": item.get("primary_module", {}),
        "secondary_modules": item.get("secondary_modules", []),
        "text_exact": item.get("text_exact", []),
        "top_edge_anchor": item.get("top_edge_anchor", ""),
        "bottom_edge_anchor": item.get("bottom_edge_anchor", ""),
        "visual_continuity": item.get("visual_continuity", ""),
        "forbidden_layout": item.get("forbidden_layout", ""),
    }


def auto_outpaint_screen_task(slice_id):
    try:
        index = int(str(slice_id).strip())
    except Exception:
        index = 2

    tasks = {
        2: (
            "Auto current screen task: core selling-point bridge screen. "
            "Continue from the previous screen with a calm transition area, then introduce 2-3 key benefits of the product. "
            "Use concise Chinese copy such as a benefit headline, one short subheadline and compact labels."
        ),
        3: (
            "Auto current screen task: function/mechanism screen. "
            "Show how the product solves the main user pain point with one primary functional visual and 1-2 supporting close-ups. "
            "Keep the product or key working part clear, accurate and premium."
        ),
        4: (
            "Auto current screen task: detail close-up screen. "
            "Focus on material, structure, craftsmanship, interface, texture or key component details. "
            "Use macro photography/product close-up feeling, with sparse Chinese labels and elegant leader lines if needed."
        ),
        5: (
            "Auto current screen task: usage demonstration screen. "
            "Show the product being used naturally, or show a clear before-during-after usage flow. "
            "Avoid a complicated tutorial; keep it commercial, readable and visually connected."
        ),
        6: (
            "Auto current screen task: lifestyle scenario screen. "
            "Place the product in a real everyday scene and communicate comfort, convenience and emotional value. "
            "Use 1-2 scene vignettes at most, not a dense collage."
        ),
        7: (
            "Auto current screen task: multi-scene / companion value screen. "
            "Show the product fitting several daily moments with a rhythmic ecommerce layout. "
            "Use one main scene plus 1-2 small supporting moments, keeping visual hierarchy clear."
        ),
        8: (
            "Auto current screen task: trust and safety screen. "
            "Present quality, material, safety, durability, standard, battery, cleaning or after-sales trust points depending on the product. "
            "Use restrained icons or badges, no hard UI panel."
        ),
        9: (
            "Auto current screen task: parameter/configuration screen. "
            "Show product package, dimensions or core specifications in a clean premium layout. "
            "Keep the information light and readable, not a dense spreadsheet."
        ),
        10: (
            "Auto current screen task: emotional closing / simple FAQ screen. "
            "Use a quiet lifestyle or product still-life scene with warm Chinese copy that closes the long page. "
            "No purchase button, no QR code, no aggressive sales layout."
        ),
    }
    if index in tasks:
        return tasks[index]

    cycle = (index - 2) % 8
    fallback_order = [2, 3, 4, 5, 6, 7, 8, 10]
    return tasks[fallback_order[cycle]]


MOJIBAKE_MARKERS = (
    "锛", "鐨", "涓", "鍙", "鏂", "鏅", "闈", "缁", "鍝", "浜", "浣",
    "銆", "€", "乼", "乻", "乵", "乧", "乀", "丆", "丏",
)
# --- End synced standalone long-scroll helper functions ---

def format_template(template, **values):
    def replace(match):
        key = match.group(1)
        return str(values.get(key, match.group(0)))
    return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, template)


def stable_text_fingerprint(*parts):
    h = hashlib.sha256()
    for part in parts:
        h.update(str(part).encode("utf-8", "ignore"))
        h.update(b"\n")
    return h.hexdigest()


def image_content_signature(image):
    if image is None or not isinstance(image, torch.Tensor):
        return "none"
    try:
        tensor = image.detach().float().cpu()
        shape = tuple(tensor.shape)
        if tensor.ndim == 3:
            tensor = tensor.unsqueeze(0)
        if tensor.ndim != 4 or tensor.numel() == 0:
            return f"shape={shape}"
        first = tensor[:1]
        height = int(first.shape[1])
        width = int(first.shape[2])
        y_index = torch.linspace(0, max(0, height - 1), min(height, 32)).long()
        x_index = torch.linspace(0, max(0, width - 1), min(width, 32)).long()
        sample = first[:, y_index][:, :, x_index, :].clamp(0, 1)
        sample_u8 = (sample * 255).round().to(torch.uint8).contiguous().numpy().tobytes()
        return f"shape={shape};hash={hashlib.sha256(sample_u8).hexdigest()[:16]}"
    except Exception:
        shape = tuple(getattr(image, "shape", []))
        return "shape=" + ",".join(str(x) for x in shape)


def flatten_image_inputs(images):
    flattened = []
    if isinstance(images, torch.Tensor):
        images = [images]
    for image in images or []:
        if image is None:
            continue
        if isinstance(image, (list, tuple)):
            flattened.extend(flatten_image_inputs(image))
            continue
        if not isinstance(image, torch.Tensor):
            continue
        if image.ndim == 3:
            image = image.unsqueeze(0)
        if image.ndim != 4:
            continue
        for index in range(image.shape[0]):
            flattened.append(image[index:index + 1])
    return flattened


def resize_image_to_width(image, target_width):
    height = int(image.shape[1])
    width = int(image.shape[2])
    if width == target_width:
        return image
    target_height = max(1, int(round(height * target_width / max(1, width))))
    channels_first = image.movedim(-1, 1)
    resized = F.interpolate(channels_first, size=(target_height, target_width), mode="bilinear", align_corners=False)
    return resized.movedim(1, -1)


def mojibake_score(text):
    return sum(str(text).count(marker) for marker in MOJIBAKE_MARKERS)


def fix_mojibake_text(value):
    text = str(value)
    if mojibake_score(text) == 0:
        return text
    best = text
    best_score = mojibake_score(text)
    for encoding in ("gb18030", "gbk"):
        try:
            candidate = text.encode(encoding).decode("utf-8")
        except Exception:
            continue
        score = mojibake_score(candidate)
        if score < best_score:
            best = candidate
            best_score = score
    return best


def fix_mojibake(value):
    if isinstance(value, str):
        return fix_mojibake_text(value)
    if isinstance(value, list):
        return [fix_mojibake(item) for item in value]
    if isinstance(value, dict):
        return {key: fix_mojibake(item) for key, item in value.items()}
    return value


def extract_json_object(text):
    raw_text = str(text or "").strip()
    for prefix in ("```json", "```JSON", "```"):
        if raw_text.startswith(prefix):
            raw_text = raw_text[len(prefix):].strip()
    if raw_text.endswith("```"):
        raw_text = raw_text[:-3].strip()

    def _parse_json(candidate):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, str) and not parsed.strip() and ("{" in candidate or "[" in candidate):
                raise ValueError("JSON 顶层被解析为空字符串，继续尝试抽取对象")
            return parsed
        except Exception as json_error:
            try:
                from json_repair import repair_json
                repaired = repair_json(candidate)
                parsed = json.loads(repaired)
                if isinstance(parsed, str) and not parsed.strip() and ("{" in candidate or "[" in candidate):
                    raise ValueError("JSON 自动修复结果为空字符串")
                return parsed
            except Exception:
                raise json_error

    try:
        return _parse_json(raw_text)
    except Exception:
        pass

    object_start = raw_text.find("{")
    array_start = raw_text.find("[")
    if array_start >= 0 and (object_start < 0 or array_start < object_start):
        start = array_start
        end = raw_text.rfind("]")
    else:
        start = object_start
        end = raw_text.rfind("}")
    if start >= 0 and end > start:
        json_text = raw_text[start:end + 1]
        try:
            return _parse_json(json_text)
        except Exception as exc:
            position = getattr(exc, "pos", None)
            context = ""
            if isinstance(position, int):
                context = json_text[max(0, position - 240):position + 240]
            detail = str(exc)
            if context:
                detail = f"{detail}；附近内容：{context}"
            raise ValueError(f"大模型返回了 JSON，但格式损坏且自动修复失败：{detail}") from exc
    raise ValueError("大模型返回内容不是有效 JSON")


def call_synvow_llm(model, system_prompt, user_prompt, image_urls=None, temperature=0.3, seed=None, llm_config=None, max_tokens=4096):
    base_url, api_key, resolved_model = resolve_llm_config(llm_config, model_name=model or DEFAULT_MODEL)
    if not base_url or not api_key or not resolved_model:
        raise RuntimeError("?? LLM ?????? RunningHub/?? RH_API_KEY???? SynVow LLM Settings?")
    headers = make_headers(api_key)
    url = base_url.rstrip("/")
    user_content = [{"type": "text", "text": user_prompt}]
    for image_url in image_urls or []:
        user_content.append({"type": "image_url", "image_url": {"url": image_url}})

    payload = {
        "model": resolved_model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content if image_urls else user_prompt},
        ],
        "max_tokens": int(max_tokens or 4096),
        "temperature": temperature,
    }
    if seed is not None:
        payload["seed"] = int(seed) % 2147483647

    last_error = None
    for attempt in range(3):
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=600, verify=False)
            if res.status_code != 200:
                raise RuntimeError(f"HTTP {res.status_code}: {res.text[:500]}")
            content = parse_chat_response(res.json()) or ""
            if not content.strip():
                raise RuntimeError("RunningHub ??????????????")
            return content.strip()
        except Exception as exc:
            last_error = exc
            print(f"[SynVow-prompt LongScroll] LLM request failed ({attempt + 1}/3): {exc}")
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(
        "RunningHub LLM ??????????????? 3 ??"
        f"?????{last_error}"
    )


def tensor_to_data_url(image, index=0):
    if image is None:
        return None
    tensor = image
    try:
        if hasattr(image, "shape") and len(image.shape) == 4:
            tensor = image[index]
    except Exception:
        tensor = image
    array = 255.0 * tensor.detach().cpu().numpy()
    pil_image = Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))
    max_size = 1024
    if pil_image.width > max_size or pil_image.height > max_size:
        pil_image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    pil_image.save(buffer, format="JPEG", quality=85)
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"


def collect_uploaded_image_urls(product_images, reference_images):
    image_urls = []
    for image in list(product_images or []) + list(reference_images or []):
        if image is None:
            continue
        try:
            if hasattr(image, "shape") and len(image.shape) == 4:
                for index in range(int(image.shape[0])):
                    image_urls.append(tensor_to_data_url(image, index))
            else:
                image_urls.append(tensor_to_data_url(image, 0))
        except Exception as exc:
            print(f"[SynVow-prompt LongScroll] ??? base64 ???????{exc}")
    return [url for url in image_urls if url]

def image_input_note(product_count, reference_count):
    return (
        f"\n\n【已上传图像说明】\n"
        f"- 产品图：{product_count} 张，只用于锁定产品外观、结构、颜色、材质、品牌标识和关键部件。\n"
        f"- 参考图：{reference_count} 张，用于学习设计手法、版式节奏、视觉母题、信息组织、人物使用关系、姿态情绪和生活场景。\n"
        f"- 人物规则：如果参考图有人物，可转化为本产品适用的泛化模特、局部人物、背影、肩颈/手部使用动作或生活方式场景；不要复制具体脸、身份、服装细节或精确姿态。\n"
        f"- 严禁混用：不得把参考图里的原产品、品牌、具体文案当成本次产品；本次产品身份始终以产品图为准。"
    )


def normalize_typography_lock(style_dna):
    lock = deepcopy(DEFAULT_TYPOGRAPHY_LOCK)
    if isinstance(style_dna, dict):
        existing = style_dna.get("typography_lock")
        if isinstance(existing, dict):
            for key, value in existing.items():
                if str(value).strip():
                    lock[key] = value
        typography = str(style_dna.get("typography", "")).strip()
        if typography:
            lock["font_family_style"] = f"{lock['font_family_style']} 参考当前字体气质：{typography}"
    return lock


def ensure_typography_lock(style_dna):
    if not isinstance(style_dna, dict):
        style_dna = {}
    style_dna = deepcopy(style_dna)
    style_dna["typography_lock"] = normalize_typography_lock(style_dna)
    if not str(style_dna.get("typography", "")).strip():
        style_dna["typography"] = "现代中文无衬线字体风格，标题中粗、正文常规、标签轻量，层级统一、留白舒展。"
    return style_dna


def build_module_ratio_plan(slice_count):
    count = max(1, int(slice_count or 1))
    sequences = {
        1: ["hero"],
        2: ["hero", "faq_close"],
        3: ["hero", "function", "faq_close"],
        4: ["hero", "function", "detail", "faq_close"],
        5: ["hero", "scenario_person", "function", "detail", "faq_close"],
        6: ["hero", "scenario_person", "function", "detail", "parameter_trust", "faq_close"],
        7: ["hero", "scenario_person", "function", "detail", "steps", "parameter_trust", "faq_close"],
        8: ["hero", "scenario_person", "function", "function", "detail", "steps", "parameter_trust", "faq_close"],
        9: ["hero", "scenario_person", "function", "function", "detail", "scenario_person", "steps", "parameter_trust", "faq_close"],
        10: ["hero", "scenario_person", "function", "function", "detail", "scenario_person", "steps", "detail", "parameter_trust", "faq_close"],
    }
    sequence = list(sequences.get(min(count, 10), sequences[10]))
    extras = ["scenario_person", "detail", "function", "scenario_person", "detail", "function"]
    extra_index = 0
    while len(sequence) < count:
        sequence.insert(max(1, len(sequence) - 2), extras[extra_index % len(extras)])
        extra_index += 1

    items = []
    for index, module_type in enumerate(sequence[:count], 1):
        rule = MODULE_TYPE_RULES[module_type]
        information_density = "中-高密度"
        content_point_target = "1 个 primary_module + 2 个 secondary_modules，形成主卖点 + 证据细节 + 轻场景/利益补充"
        screen_fill_strategy = "9:21 长屏必须保持信息饱满，避免整屏只讲 1 个孤立内容点。"
        hierarchy_strategy = "每屏只有 1 个最强 headline 和 1 个主视觉焦点，辅助模块必须视觉降级。"
        composition_shift = "避免连续复用产品居中大图、周围图标卡片、底部参数条等相同组织方式。"
        if module_type == "hero":
            information_density = "中密度"
            content_point_target = "1 个强情绪主视觉 + 1 个轻量利益点 + 1 个产品身份锚点"
            screen_fill_strategy = "封面可以留白，但必须有产品身份、情绪利益和视觉锚点，不能只有单张产品图。"
            composition_shift = "封面优先高级留白、全幅氛围或产品悬浮，不要做信息卡片堆叠。"
        elif index == 2:
            information_density = "中密度"
            content_point_target = "1 个首屏卖点延续场景 + 1 个情绪利益短句 + 1 个轻量产品使用细节"
            screen_fill_strategy = "第 02 屏必须延续首屏视觉世界，做生活方式种草/卖点承接页；不要做黑白痛点对比、旧方案对比或灰暗负面场景。"
            composition_shift = "第 02 屏用全幅人物场景、户外/居家/办公自然使用或环境叙事承接首屏；产品自然出现并保持美感，禁止底部白卡、产品说明卡、三图标卡片、左右对比、黑白分屏。"
        elif index == 3:
            information_density = "高密度"
            content_point_target = "1 个 primary_module + 2-3 个 secondary_modules，形成 3-4 个清晰内容点"
            screen_fill_strategy = "第 03 屏承担首个强信息页，必须用分区、微距、标签或对比证据填满长屏。"
            hierarchy_strategy = "第 03 屏可以信息更满，但必须有 1 个最大卖点，其余 2-3 个点做小证据。"
            composition_shift = "第 03 屏必须用机制/能量流/结构剖面/局部微距证明功能，避免人物大场景和底部卡片；禁止与第 04 屏使用同角度产品大图。"
        elif index == 4:
            information_density = "中-高密度"
            content_point_target = "1 个第二功能/模式结果 + 2 个辅助证据模块，必须和第 03 屏不同"
            screen_fill_strategy = "第 04 屏承接第 03 屏但必须换表达：如果第 03 是机制剖面，第 04 就做人物使用结果、模式面板或纵向场景融合。"
            composition_shift = "第 04 屏禁止继续产品居中大特写 + 周围图标/白卡；必须使用人物佩戴结果、纵向模式序列、环境融合或斜向动线。"
        elif module_type == "scenario_person":
            information_density = "中密度"
            content_point_target = "1 个人物/生活方式主场景 + 1 个产品细节证据 + 1 个情绪利益短句"
            screen_fill_strategy = "场景页也要嵌入产品细节或利益标签，避免只有模特氛围照。"
            composition_shift = "人物页优先表现使用结果、生活方式和情绪利益；如需表达需求，只能轻量暗示，不要做黑白痛点对比、灰暗负面情绪或廉价前后对照。"
        elif module_type in ("function", "detail"):
            information_density = "中-高密度"
            content_point_target = "1 个核心功能/细节 + 2 个辅助证据模块，可合并两个相关卖点在同一屏"
            screen_fill_strategy = "功能和细节页优先做复合信息屏：一个大信息区 + 两个小证据区，而不是一屏只讲一个卖点。"
            composition_shift = "连续功能/细节页至少一屏切换为局部微距、结构剖面、斜向动线、人物使用或全幅场景融合。"
        elif module_type in ("steps", "parameter_trust"):
            information_density = "高密度"
            content_point_target = "1 个 primary_module + 2-3 个 secondary_modules，使用上下分区、纵向序列或参数/步骤组合"
            screen_fill_strategy = "步骤和参数页需要天然高信息量，可把流程、对比、参数、信任点组合在一屏。"
            composition_shift = "步骤/参数页优先竖向信息层级或连续动线，避免横版网页式左右对半。"
        elif module_type == "faq_close":
            information_density = "中密度"
            content_point_target = "1 个收尾利益主视觉 + 1-2 个 FAQ/信任/行动提示"
            screen_fill_strategy = "收尾页可以轻，但不能空；至少保留利益收束、产品露出和行动提示。"
            composition_shift = "收尾页要情感化和安静，避免再次变成参数表或信息墙。"
        items.append({
            "slice_id": str(index).zfill(2),
            "module_type": module_type,
            "module_label": rule["label"],
            "information_density": information_density,
            "content_point_target": content_point_target,
            "screen_fill_strategy": screen_fill_strategy,
            "hierarchy_strategy": hierarchy_strategy,
            "composition_shift": composition_shift,
            "allowed_archetypes": rule["allowed_archetypes"],
            "notes": rule["notes"],
            "screen_job": rule["screen_job"],
            "evidence_type": rule["evidence_type"],
        })

    summary = {}
    for item in items:
        summary[item["module_type"]] = summary.get(item["module_type"], 0) + 1
    return {
        "slice_count": count,
        "ratio_summary": {
            module_type: {
                "label": MODULE_TYPE_RULES[module_type]["label"],
                "count": summary.get(module_type, 0),
                "target": MODULE_TYPE_RULES[module_type]["target"],
            }
            for module_type in MODULE_TYPE_RULES
        },
        "items": items,
    }


def module_plan_for_slice_range(module_plan, start_id, end_id):
    selected = [
        item for item in module_plan.get("items", [])
        if start_id <= int(item.get("slice_id", "0")) <= end_id
    ]
    return {
        "slice_count": len(selected),
        "total_slice_count": module_plan.get("slice_count", 0),
        "slice_range": f"{start_id:02d}-{end_id:02d}",
        "items": selected,
    }


def compact_module_plan_summary(module_plan):
    items = []
    for item in module_plan.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        items.append({
            "slice_id": item.get("slice_id", ""),
            "module_type": item.get("module_type", ""),
            "module_label": item.get("module_label", ""),
            "density": item.get("information_density", ""),
        })
    return {
        "slice_count": module_plan.get("slice_count", len(items)),
        "items": items,
    }


def normalize_chunk_items(items, start_id, end_id):
    expected_ids = [str(i).zfill(2) for i in range(start_id, end_id + 1)]
    normalized = [deepcopy(item) for item in (items or []) if isinstance(item, dict)]
    if len(normalized) == len(expected_ids):
        seen = set()
        has_missing_or_duplicate = False
        for item in normalized:
            slice_id = str(item.get("slice_id", "")).strip().zfill(2)
            if slice_id not in expected_ids or slice_id in seen:
                has_missing_or_duplicate = True
                break
            seen.add(slice_id)
        if has_missing_or_duplicate or len(seen) != len(expected_ids):
            for item, slice_id in zip(normalized, expected_ids):
                item["slice_id"] = slice_id
    return normalized


def sort_items_by_slice_id(items):
    def sort_key(pair):
        index, item = pair
        try:
            return (0, int(str(item.get("slice_id", "")).strip()), index)
        except Exception:
            return (1, index, index)
    return [item for _, item in sorted(enumerate(items or []), key=sort_key)]


def extract_items_from_llm_result(result):
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    if not isinstance(result, dict):
        return []
    for key in ("items", "screens", "sections", "pages", "prompts", "data"):
        value = result.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = extract_items_from_llm_result(value)
            if nested:
                return nested
    return []


def normalize_llm_mapping(result, default_workflow):
    if isinstance(result, dict):
        normalized = deepcopy(result)
        if not isinstance(normalized.get("items"), list):
            normalized["items"] = extract_items_from_llm_result(result)
        return normalized
    return {
        "workflow": default_workflow,
        "items": extract_items_from_llm_result(result),
        "coerced_from": type(result).__name__,
    }


def require_llm_object(result, workflow_name):
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        return {
            "workflow": workflow_name,
            "items": [item for item in result if isinstance(item, dict)],
            "coerced_from": "list",
        }
    if isinstance(result, str):
        text = result.strip()
        if text:
            try:
                parsed = extract_json_object(text)
                if isinstance(parsed, str):
                    nested_text = parsed.strip()
                    if nested_text and nested_text != text and ("{" in nested_text or "[" in nested_text):
                        return require_llm_object(extract_json_object(nested_text), workflow_name)
                elif parsed is not result:
                    return require_llm_object(parsed, workflow_name)
            except Exception:
                pass
        preview = text[:300].replace("\n", "\\n")
        if not preview:
            preview = "<空字符串，可能是 JSON 修复器误修复或模型返回了空 JSON 字符串>"
        raise ValueError(f"大模型返回 JSON 顶层是字符串，且无法拆出对象；内容预览：{preview}")
    raise ValueError(f"大模型返回 JSON 顶层不是对象：{type(result).__name__}")


def get_narrative_section_by_id(narrative, slice_id):
    if not isinstance(narrative, dict):
        return {}
    wanted = str(slice_id).strip().zfill(2)
    for section in narrative.get("sections", []) or []:
        if isinstance(section, dict) and str(section.get("slice_id", "")).strip().zfill(2) == wanted:
            return section
    return {}


def fallback_structure_item(plan_item, narrative, index):
    slice_id = str(plan_item.get("slice_id", "") or index).zfill(2)
    section = get_narrative_section_by_id(narrative, slice_id)
    text_exact = section.get("text_exact", []) if isinstance(section, dict) else []
    module_type = str(plan_item.get("module_type", "")).strip()
    text_lines = safe_visible_text_lines(text_exact, module_type)
    if not text_lines and module_type != "faq_close":
        text_lines = fallback_visible_text_for_module(module_type)
    headline = text_lines[0] if text_lines else ""
    subheadline = text_lines[1] if len(text_lines) > 1 else ""
    allowed = plan_item.get("allowed_archetypes", []) or []
    section_name = section.get("section_name") or plan_item.get("module_label", f"第 {slice_id} 屏")
    screen_job = plan_item.get("screen_job", "") or section.get("narrative_role", "")
    main_visual = section.get("main_visual", "") or plan_item.get("notes", "")
    return {
        "slice_id": slice_id,
        "section_name": section_name,
        "module_type": module_type,
        "module_label": plan_item.get("module_label", ""),
        "layout_archetype": allowed[0] if allowed else "",
        "commercial_goal": truncate_text(section.get("narrative_role", "") or screen_job, 160),
        "user_question": f"这一屏如何证明：{headline}",
        "screen_job": screen_job,
        "evidence_type": plan_item.get("evidence_type", ""),
        "information_density": plan_item.get("information_density", ""),
        "content_point_target": plan_item.get("content_point_target", ""),
        "screen_fill_strategy": plan_item.get("screen_fill_strategy", ""),
        "hierarchy_strategy": plan_item.get("hierarchy_strategy", ""),
        "composition_shift": plan_item.get("composition_shift", ""),
        "primary_module": {
            "role": "primary",
            "message": headline,
            "visual": truncate_text(main_visual, 360),
            "area_ratio": "55-70%",
            "visual_evidence": truncate_text(section.get("composition", "") or plan_item.get("notes", ""), 260),
        },
        "secondary_modules": [
            {
                "role": "secondary",
                "message": subheadline or plan_item.get("evidence_type", ""),
                "visual": truncate_text(plan_item.get("screen_fill_strategy", "") or plan_item.get("notes", ""), 220),
                "area_ratio": "15-25%",
                "visual_evidence": truncate_text(plan_item.get("content_point_target", ""), 180),
            }
        ] if (subheadline or plan_item.get("evidence_type", "")) else [],
        "text_exact": sanitize_text_exact({
            "headline": headline,
            "subheadline": subheadline,
            "tags": text_lines[2:5],
        }, module_type),
        "top_edge_anchor": section.get("transition_in", "延续上一屏的光线、材质和空间氛围。"),
        "bottom_edge_anchor": section.get("transition_out", "为下一屏保留材质、光线或场景延展。"),
        "auto_filled": True,
    }


def fill_missing_structure_items(items, module_plan, narrative, start_id, end_id):
    normalized = [deepcopy(item) for item in (items or []) if isinstance(item, dict)]
    by_id = {
        str(item.get("slice_id", "") or index).strip().zfill(2): item
        for index, item in enumerate(normalized, 1)
    }
    plan_by_id = {
        str(item.get("slice_id", "")).strip().zfill(2): item
        for item in module_plan.get("items", []) or []
        if isinstance(item, dict)
    }
    filled = []
    for index in range(start_id, end_id + 1):
        slice_id = str(index).zfill(2)
        item = by_id.get(slice_id)
        plan_item = plan_by_id.get(slice_id)
        if item:
            if plan_item:
                fallback = fallback_structure_item(plan_item, narrative, index)
                for key, value in fallback.items():
                    if key == "auto_filled":
                        continue
                    if key not in item or item.get(key) in (None, "", [], {}):
                        item[key] = value
                if any(item.get(key) in (None, "", [], {}) for key in ("primary_module", "text_exact")):
                    item["auto_filled"] = True
            filled.append(sanitize_structure_item_visible_text(item))
            continue
        if plan_item:
            filled.append(sanitize_structure_item_visible_text(fallback_structure_item(plan_item, narrative, index)))
    return sort_items_by_slice_id(filled)


def fallback_prompt_from_structure_item(item, visual_master_spec, product_constraints, continuity_policy):
    text_exact = item.get("text_exact", {})
    text_lines = safe_visible_text_lines(text_exact, item.get("module_type", ""))
    headline = text_lines[0] if text_lines else item.get("section_name", "")
    subheadline = text_lines[1] if len(text_lines) > 1 else ""
    module_type = str(item.get("module_type", "")).strip()
    layout_intent = str(item.get("layout_archetype", "")).strip()
    module_visual_strategy = {
        "hero": "Create an appetizing premium hero scene with strong product identity, warm commercial lighting, generous negative space and a clear visual hook.",
        "scenario_person": "Create an immersive lifestyle or human scenario that extends the hero screen's selling point and desired result; keep the product naturally integrated into the scene. Avoid negative pain-point contrast, black-and-white split screens, grey problem scenes, or cheap before/after comparisons.",
        "function": "Create a clear function-benefit visualization using macro evidence, ingredient/material cues, motion flow, cutaway-like visual logic or subtle floating annotations.",
        "detail": "Create a refined detail-evidence screen with macro texture, material close-ups, craft details and premium ecommerce polish.",
        "steps": "Create a vertical 2-3 step sequence with simple visual flow, short labels and clear reading order.",
        "parameter_trust": "Create a vertical trust/parameter hierarchy with short labels, quality cues, safety/trust icons and product/material background integration.",
        "faq_close": "Create a quiet emotional closing scene with lifestyle warmth, final benefit and minimal trust notes.",
    }.get(module_type, "Create a polished premium ecommerce detail-page screen with clear hierarchy, warm lighting, product consistency and restrained information density.")
    prompt_parts = [
        "Canvas and aspect ratio: Create a single 9:21 vertical image.",
        "Reference image usage: Image 1 is the product identity reference. Infer the exact product appearance from Image 1; do not redesign or invent product details.",
        "Overall visual system: Use a warm, premium, appetizing ecommerce visual style based on the established page style. Keep palette, lighting, materials, typography and spatial atmosphere consistent with the previous screens.",
        f"Current viewport: Slice {item.get('slice_id', '')}, {item.get('section_name', '')}.",
        f"Module role: {item.get('module_type', '')} / {item.get('module_label', '')}.",
        f"Screen job and evidence: {module_visual_strategy}",
        f"Layout intent: {layout_intent}; use it as an information intent, not a fixed card template.",
        "Flexible page composition: Keep one dominant headline and one dominant visual focus. Use secondary evidence as smaller, lighter, low-contrast visual notes. Vary the composition from adjacent screens; avoid repeated white cards, centered product hero, icon rows and bottom explanation strips.",
        "Primary module: Show the main product benefit or scene clearly with a strong visual focus. If the product appears, refer only to the product from Image 1 or a product close-up based on Image 1.",
        "Secondary modules: Add only small supporting visual evidence, such as short labels, material details, ingredient cues, texture close-ups, quality icons or subtle floating notes. Keep them visually smaller and less dominant than the primary module; avoid equal-weight card collage.",
        f"Chinese typography: visible Chinese headline: \"{headline}\"; visible Chinese subheadline: \"{subheadline}\"; visible Chinese tags: \"{' / '.join(text_lines[2:5])}\". Use a clean modern Chinese sans-serif font, consistent hierarchy and relaxed spacing.",
        "Continuity policy: Keep the top and bottom edges visually compatible with adjacent screens through light, color, material texture, crumbs/particles, soft gradients or environmental continuation. Do not place important text near the edges.",
        "Important constraints: Do not render planning notes as visible text. Only the visible Chinese headline, subheadline and tags should appear in the image. No English visible text, no garbled text, no product redesign, no dense small copy, no PPT-like white card layout.",
    ]
    return sanitize_final_prompt("\n".join(part for part in prompt_parts if str(part).strip()))


def fill_missing_prompt_items(items, page_structure, target_slice_count, visual_master_spec, product_constraints, continuity_policy):
    normalized = [deepcopy(item) for item in (items or []) if isinstance(item, dict)]
    by_id = {
        str(item.get("slice_id", "") or index).strip().zfill(2): item
        for index, item in enumerate(normalized, 1)
    }
    structure_by_id = {
        str(item.get("slice_id", "")).strip().zfill(2): item
        for item in extract_items_from_llm_result(page_structure)
    }
    filled = []
    for index in range(1, target_slice_count + 1):
        slice_id = str(index).zfill(2)
        item = by_id.get(slice_id)
        structure_item = structure_by_id.get(slice_id, {})
        if item:
            if structure_item:
                for key in ("module_type", "module_label", "screen_job", "evidence_type", "layout_archetype"):
                    if not item.get(key) and structure_item.get(key):
                        item[key] = structure_item.get(key)
                if not str(item.get("prompt", "")).strip():
                    item["prompt"] = fallback_prompt_from_structure_item(
                        structure_item,
                        visual_master_spec,
                        product_constraints,
                        continuity_policy,
                    )
                    item["auto_filled"] = True
            elif not str(item.get("prompt", "")).strip():
                item["prompt"] = fallback_prompt_from_structure_item(
                    item,
                    visual_master_spec,
                    product_constraints,
                    continuity_policy,
                )
                item["auto_filled"] = True
            if str(item.get("prompt", "")).strip():
                item["prompt"] = sanitize_final_prompt(sanitize_prompt_blueprint_context(
                    ensure_prompt_visible_copy(item.get("prompt", ""), item),
                    item,
                ))
            filled.append(sanitize_structure_item_visible_text(item))
            continue
        if structure_item:
            fallback = deepcopy(structure_item)
            fallback["prompt"] = fallback_prompt_from_structure_item(
                structure_item,
                visual_master_spec,
                product_constraints,
                continuity_policy,
            )
            fallback["auto_filled"] = True
            fallback["prompt"] = sanitize_final_prompt(sanitize_prompt_blueprint_context(
                ensure_prompt_visible_copy(fallback.get("prompt", ""), fallback),
                fallback,
            ))
            filled.append(sanitize_structure_item_visible_text(fallback))
    return sort_items_by_slice_id(filled)


def enforce_module_plan_on_items(items, module_plan):
    plan_by_id = {str(item.get("slice_id", "")).zfill(2): item for item in module_plan.get("items", [])}
    warnings = []
    for index, item in enumerate(items, 1):
        slice_id = str(item.get("slice_id", "") or index).zfill(2)
        item["slice_id"] = slice_id
        plan_item = plan_by_id.get(slice_id)
        if not plan_item:
            continue
        item["module_type"] = plan_item.get("module_type", "")
        item["module_label"] = plan_item.get("module_label", "")
        item["allowed_archetypes"] = plan_item.get("allowed_archetypes", [])
        item["module_notes"] = plan_item.get("notes", "")
        item.setdefault("screen_job", plan_item.get("screen_job", ""))
        item.setdefault("evidence_type", plan_item.get("evidence_type", ""))
        item.setdefault("information_density", plan_item.get("information_density", ""))
        item.setdefault("content_point_target", plan_item.get("content_point_target", ""))
        item.setdefault("screen_fill_strategy", plan_item.get("screen_fill_strategy", ""))
        item.setdefault("hierarchy_strategy", plan_item.get("hierarchy_strategy", ""))
        item.setdefault("composition_shift", plan_item.get("composition_shift", ""))
        layout = item.get("layout_archetype", "")
        allowed = plan_item.get("allowed_archetypes", [])
        if not layout and allowed:
            item["layout_archetype"] = allowed[0]
        elif layout and allowed and layout not in allowed:
            warnings.append(f"{slice_id}:{layout} 不在 {item['module_label']} 推荐版式内")
    return warnings


def normalize_narrative_sections(sections, target_count):
    target_count = max(1, int(target_count or 1))
    module_plan = build_module_ratio_plan(target_count)
    normalized = [deepcopy(section) for section in (sections or []) if isinstance(section, dict)]
    warnings = []

    if len(normalized) != target_count:
        raise ValueError(
            f"LLM 叙事规划数量不一致：目标 {target_count} 屏，实际 {len(normalized)} 屏。"
            "已关闭自动补齐，请重新运行本节点。"
        )

    for index, section in enumerate(normalized, 1):
        section["slice_id"] = str(index).zfill(2)
        if not str(section.get("section_name", "")).strip():
            plan_item = module_plan["items"][index - 1]
            section["section_name"] = plan_item.get("module_label", f"第 {index:02d} 屏")
        if not isinstance(section.get("text_exact"), list):
            text_value = section.get("text_exact", "")
            section["text_exact"] = [str(text_value)] if str(text_value).strip() else []

    return normalized, warnings


def normalize_narrative_outline(outline, target_count):
    target_count = max(1, int(target_count or 1))
    normalized = [deepcopy(item) for item in (outline or []) if isinstance(item, dict)]
    if len(normalized) != target_count:
        raise ValueError(
            f"LLM 叙事目录数量不一致：目标 {target_count} 屏，实际 {len(normalized)} 屏。"
            "已关闭自动补齐，请重新运行本节点。"
        )
    for index, item in enumerate(normalized, 1):
        item["slice_id"] = str(index).zfill(2)
        if not str(item.get("section_name", "")).strip():
            item["section_name"] = f"第 {index:02d} 屏"
        if not str(item.get("narrative_role", "")).strip():
            item["narrative_role"] = str(item.get("key_message", "")).strip()
    return normalized


def outline_to_lightweight_sections(outline):
    sections = []
    for item in outline or []:
        if not isinstance(item, dict):
            continue
        key_message = str(item.get("key_message", "")).strip()
        section = {
            "slice_id": item.get("slice_id", ""),
            "section_name": item.get("section_name", ""),
            "narrative_role": item.get("narrative_role", "") or key_message,
            "key_message": key_message,
            "text_exact": [key_message] if key_message else [],
        }
        if str(item.get("screen_goal", "")).strip():
            section["screen_goal"] = str(item.get("screen_goal", "")).strip()
        sections.append(section)
    return sections


def truncate_text(value, max_chars=1800):
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n...[已截断，用于控制 LLM 请求体大小]"


def compact_narrative_for_page_structure(narrative, visual_master_spec):
    compact = {
        "workflow": narrative.get("workflow", "ecommerce_long_scroll_narrative"),
        "product_name": narrative.get("product_name", ""),
        "category": narrative.get("category", ""),
        "slice_count": narrative.get("slice_count", len(narrative.get("sections", []))),
        "creative_guidance": truncate_text(narrative.get("creative_guidance", ""), 320),
        "visual_style_dna": ensure_typography_lock(narrative.get("visual_style_dna", {})),
        "visual_master_spec_summary": truncate_text(
            visual_master_spec
            or narrative.get("visual_master_spec", "")
            or narrative.get("master_reference_prompt", ""),
            800,
        ),
        "sections": [],
    }
    for section in narrative.get("sections", []):
        compact["sections"].append({
            "slice_id": section.get("slice_id", ""),
            "section_name": section.get("section_name", ""),
            "narrative_role": truncate_text(section.get("narrative_role", ""), 140),
            "key_message": truncate_text(section.get("key_message", ""), 120),
            "screen_goal": truncate_text(section.get("screen_goal", ""), 120),
            "main_visual": truncate_text(section.get("main_visual", ""), 120),
            "composition": truncate_text(section.get("composition", ""), 100),
            "text_exact": section.get("text_exact", []),
            "transition_in": truncate_text(section.get("transition_in", ""), 80),
            "transition_out": truncate_text(section.get("transition_out", ""), 80),
        })
    return compact


def narrative_chunk_for_slice_range(compact_narrative, start_id, end_id):
    chunk = deepcopy(compact_narrative)
    selected = []
    for section in compact_narrative.get("sections", []):
        try:
            numeric_id = int(str(section.get("slice_id", "")).strip())
        except Exception:
            numeric_id = len(selected) + 1
        if start_id <= numeric_id <= end_id:
            selected.append(section)
    chunk["sections"] = selected or compact_narrative.get("sections", [])
    chunk["slice_count"] = len(chunk["sections"])
    chunk["total_slice_count"] = compact_narrative.get("slice_count", len(compact_narrative.get("sections", [])))
    chunk["slice_range"] = f"{start_id:02d}-{end_id:02d}"
    return chunk


def page_structure_chunk_for_slice_range(page_structure, start_id, end_id):
    page_structure = normalize_llm_mapping(page_structure, "ecommerce_long_scroll_page_structure")
    chunk = deepcopy(page_structure)
    selected = []
    for item in extract_items_from_llm_result(page_structure):
        try:
            numeric_id = int(str(item.get("slice_id", "")).strip())
        except Exception:
            numeric_id = len(selected) + 1
        if start_id <= numeric_id <= end_id:
            selected.append(item)
    chunk["items"] = selected
    chunk["slice_count"] = len(selected)
    chunk["total_slice_count"] = page_structure.get("slice_count") or len(extract_items_from_llm_result(page_structure))
    chunk["slice_range"] = f"{start_id:02d}-{end_id:02d}"
    return chunk


def compact_narrative_for_prompt_batch(narrative):
    return {
        "product_name": narrative.get("product_name", ""),
        "category": narrative.get("category", ""),
        "slice_count": narrative.get("slice_count", len(narrative.get("sections", []))),
        "visual_style_dna": ensure_typography_lock(narrative.get("visual_style_dna", {})),
        "sections": [
            {
                "slice_id": section.get("slice_id", ""),
                "section_name": section.get("section_name", ""),
                "narrative_role": truncate_text(section.get("narrative_role", ""), 180),
                "text_exact": section.get("text_exact", []),
            }
            for section in narrative.get("sections", [])
        ],
    }


def page_structure_markdown(structure):
    lines = [
        f"# {structure.get('product_name', '')} 页面结构蓝图",
        "",
        f"- 品类：{structure.get('category', '')}",
        f"- 画布：{structure.get('canvas_ratio', '9:16')}",
        "",
    ]
    style_dna = structure.get("visual_style_dna", {})
    if not isinstance(style_dna, dict):
        style_dna = ensure_typography_lock({})
    if style_dna:
        typography_lock = style_dna.get("typography_lock", {})
        if not isinstance(typography_lock, dict):
            typography_lock = DEFAULT_TYPOGRAPHY_LOCK
        lines.extend([
            "## 全局视觉 DNA",
            f"- 色彩：{style_dna.get('palette', '')}",
            f"- 光线：{style_dna.get('lighting', '')}",
            f"- 空间：{style_dna.get('space', '')}",
            f"- 材质：{style_dna.get('materials', '')}",
            f"- 字体：{style_dna.get('typography', '')}",
            f"- 字体锁：{typography_lock.get('font_family_style', '')}",
            f"- 连续母题：{style_dna.get('continuity_motif', '')}",
            "",
        ])
    for item in structure.get("items", []):
        text_exact = item.get("text_exact", {})
        primary = item.get("primary_module", {})
        lines.extend([
            f"## {item.get('slice_id', '')} {item.get('section_name', '')}",
            f"- 模块类型：{item.get('module_type', '')} / {item.get('module_label', '')}",
            f"- 版式：{item.get('layout_archetype', '')}",
            f"- 单屏职责：{item.get('screen_job', '')}",
            f"- 证据类型：{item.get('evidence_type', '')}",
            f"- 商业目标：{item.get('commercial_goal', '')}",
            f"- 用户疑问：{item.get('user_question', '')}",
            f"- 主模块：{primary.get('area_ratio', '')} / {primary.get('visual', '')} / {primary.get('message', '')}",
            f"- 文案：{text_exact.get('headline', '')} / {text_exact.get('subheadline', '')} / {'、'.join(text_exact.get('tags', []))}",
            "",
        ])
    return "\n".join(lines).strip()


def batch_prompt_text(batch):
    return "\n\n".join(
        f"===== 切片 {item.get('slice_id', '')} {item.get('section_name', '')} {item.get('layout_archetype', '')} =====\n{item.get('prompt', '')}"
        for item in batch.get("items", [])
    )


class SynVowLongScrollNarrativePlanner:
    CATEGORY = CATEGORY
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("叙事结构_JSON", "长卷视觉母版说明", "叙事结构_Markdown", "生成状态")
    FUNCTION = "plan"

    @classmethod
    def INPUT_TYPES(cls):
        values = defaults()
        return {
            "required": {
                "产品图_1": ("IMAGE",),
                "模型": (RUNNINGHUB_MODELS, {"default": DEFAULT_MODEL}),
                "产品名称": ("STRING", {"default": values.get("产品名称", "输入产品名称")}),
                "产品品类": ("STRING", {"default": values.get("产品品类", "输入产品品类")}),
                "卖点_文案_设计补充": ("STRING", {"multiline": True, "default": values.get("卖点_文案_设计补充", "")}),
                "切片数量": ("INT", {"default": 8, "min": 6, "max": 10, "step": 1}),
                "种子": ("INT", {"default": 0, "min": 0, "max": 2147483647, "control_after_generate": True}),
            },
            "optional": {
                "llm_config": ("SYNVOW_LLM_CONFIG",),
                "temperature": ("FLOAT", {"default": 0.3, "min": 0.0, "max": 1.0, "step": 0.1}),
                "产品图_2": ("IMAGE",),
                "产品图_3": ("IMAGE",),
                "产品图_4": ("IMAGE",),
                "参考图_1": ("IMAGE",),
                "参考图_2": ("IMAGE",),
                "参考图_3": ("IMAGE",),
                "参考图_4": ("IMAGE",),
            },
        }

    @classmethod
    def IS_CHANGED(cls, 产品图_1, 模型, 产品名称, 产品品类, 卖点_文案_设计补充, 切片数量, 种子,
                   llm_config=None, temperature=0.3, 产品图_2=None, 产品图_3=None, 产品图_4=None,
                   参考图_1=None, 参考图_2=None, 参考图_3=None, 参考图_4=None):
        return stable_text_fingerprint(
            LONGSCROLL_NODE_VERSION,
            模型, 产品名称, 产品品类, 卖点_文案_设计补充, 切片数量, 种子, temperature, llm_config,
            image_content_signature(产品图_1), image_content_signature(产品图_2),
            image_content_signature(产品图_3), image_content_signature(产品图_4),
            image_content_signature(参考图_1), image_content_signature(参考图_2),
            image_content_signature(参考图_3), image_content_signature(参考图_4),
        )

    def plan(self, 产品图_1, 模型, 产品名称, 产品品类, 卖点_文案_设计补充, 切片数量, 种子,
             llm_config=None, temperature=0.3, 产品图_2=None, 产品图_3=None, 产品图_4=None,
             参考图_1=None, 参考图_2=None, 参考图_3=None, 参考图_4=None):
        product_images = [产品图_1, 产品图_2, 产品图_3, 产品图_4]
        reference_images = [参考图_1, 参考图_2, 参考图_3, 参考图_4]
        product_count = sum(1 for img in product_images if img is not None)
        reference_count = sum(1 for img in reference_images if img is not None)
        try:
            image_urls = collect_uploaded_image_urls(product_images, reference_images)
            target_slice_count = int(切片数量)
            target_slice_id = str(target_slice_count).zfill(2)
            exact_count_guard = (
                f"\n\n【最终数量硬约束｜最高优先级】\n"
                f"- outline / sections 数组长度必须严格等于 {target_slice_count}。\n"
                f"- slice_id 必须从 \"01\" 连续到 \"{target_slice_id}\"。\n"
                f"- 不得少屏，不得多屏，不得跳号；不要因为模块合并而减少条目。\n"
                f"- 返回前先自检数组长度 == {target_slice_count}，不满足就继续补足独立条目后再返回。\n"
            )

            master_system_prompt = read_text(
                "longscroll_detail_narrative_master_system.txt",
                read_text("longscroll_detail_narrative_system.txt"),
            )
            master_user_prompt = format_template(
                read_text("longscroll_detail_narrative_master_user.txt"),
                product_name=产品名称,
                category=产品品类,
                creative_guidance=卖点_文案_设计补充,
                slice_count=切片数量,
            ) + image_input_note(product_count, reference_count) + exact_count_guard
            master_content = call_synvow_llm(
                模型,
                master_system_prompt,
                master_user_prompt,
                image_urls,
                temperature,
                种子,
                llm_config=llm_config,
                max_tokens=4096,
            )
            master_result = require_llm_object(
                fix_mojibake(extract_json_object(master_content)),
                "ecommerce_long_scroll_narrative_master",
            )
            style_dna = ensure_typography_lock(master_result.get("visual_style_dna", {}))
            master_result["visual_style_dna"] = style_dna
            outline_source = (
                master_result.get("outline")
                or master_result.get("section_outline")
                or master_result.get("sections")
                or master_result.get("items")
                or master_result.get("data")
                or []
            )
            outline = normalize_narrative_outline(outline_source, target_slice_count)
            visual_master_spec = master_result.get("visual_master_spec") or master_result.get("master_reference_prompt", "")
            sections, section_warnings = normalize_narrative_sections(
                outline_to_lightweight_sections(outline),
                target_slice_count,
            )
            narrative = {
                "product_name": 产品名称,
                "category": 产品品类,
                "creative_guidance": 卖点_文案_设计补充,
                "slice_count": target_slice_count,
                "visual_master_spec": visual_master_spec,
                "master_reference_prompt": master_result.get("master_reference_prompt", visual_master_spec),
                "visual_style_dna": style_dna,
                "sections": sections,
                "generation_mode": "lightweight_master_outline",
            }
            if section_warnings:
                narrative["section_warnings"] = section_warnings
            markdown = [f"# {产品名称} LLM 详情页叙事结构", ""]
            if section_warnings:
                markdown.extend(["## 数量校正", *[f"- {warning}" for warning in section_warnings], ""])
            markdown.extend([
                "## 视觉 DNA 锁定",
                f"- 色彩：{style_dna.get('palette', '')}",
                f"- 光线：{style_dna.get('lighting', '')}",
                f"- 空间/背景：{style_dna.get('space', '')}",
                f"- 材质：{style_dna.get('materials', '')}",
                f"- 字体气质：{style_dna.get('typography', '')}",
                f"- 连续母题：{style_dna.get('continuity_motif', '')}",
                "",
            ])
            for section in sections:
                markdown.extend([
                    f"## {section.get('slice_id', '')} {section.get('section_name', '')}",
                    f"- 信息任务：{section.get('narrative_role', '')}",
                    f"- 核心信息：{section.get('key_message', '')}",
                    "",
                ])
            status = f"LLM 轻量叙事规划成功：outline={len(outline)}，sections={len(sections)}"
            if section_warnings:
                status += f"，sections 已校正：{'; '.join(section_warnings)}"
            return (to_json(narrative), visual_master_spec, "\n".join(markdown).strip(), status)
        except Exception as exc:
            raise RuntimeError(f"LLM 叙事规划失败：{exc}") from exc


class SynVowLongScrollPageStructurePlanner:
    CATEGORY = CATEGORY
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("页面结构蓝图_JSON", "页面结构蓝图_Markdown", "生成状态")
    FUNCTION = "plan_structure"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "叙事结构_JSON": ("STRING", {"multiline": True, "default": ""}),
                "长卷视觉母版说明": ("STRING", {"multiline": True, "default": ""}),
                "模型": (RUNNINGHUB_MODELS, {"default": DEFAULT_MODEL}),
            },
            "optional": {
                "结构修正要求_可选": ("STRING", {"multiline": True, "default": ""}),
                "llm_config": ("SYNVOW_LLM_CONFIG",),
                "temperature": ("FLOAT", {"default": 0.25, "min": 0.0, "max": 1.0, "step": 0.1}),
                "种子": ("INT", {"default": 0, "min": 0, "max": 2147483647, "control_after_generate": True}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, 叙事结构_JSON, 长卷视觉母版说明, 模型, 结构修正要求_可选="", llm_config=None, temperature=0.25, 种子=0):
        return stable_text_fingerprint(
            叙事结构_JSON,
            长卷视觉母版说明,
            模型,
            结构修正要求_可选,
            llm_config,
            temperature,
            种子,
            LONGSCROLL_NODE_VERSION,
            PAGE_STRUCTURE_CHUNK_SIZE,
        )

    def plan_structure(self, 叙事结构_JSON, 长卷视觉母版说明, 模型, 结构修正要求_可选="", llm_config=None, temperature=0.25, 种子=0):
        narrative = load_json(叙事结构_JSON, {})
        if not isinstance(narrative, dict):
            narrative = {}
        sections = narrative.get("sections", [])
        if not sections:
            raise RuntimeError("未找到叙事结构 sections，请先连接 RH GPT-image2详情页规划。")

        target_slice_count = int(narrative.get("slice_count") or len(sections))
        module_ratio_plan = build_module_ratio_plan(target_slice_count)
        compact_narrative = compact_narrative_for_page_structure(narrative, 长卷视觉母版说明)
        compact_visual_master_spec = compact_narrative.get("visual_master_spec_summary", "")
        system_prompt = read_text("longscroll_detail_structure_system.txt")
        user_template = read_text("longscroll_detail_structure_user.txt")

        def request_chunk(start_id, end_id):
            chunk_count = end_id - start_id + 1
            chunk_narrative = narrative_chunk_for_slice_range(compact_narrative, start_id, end_id)
            chunk_module_plan = module_plan_for_slice_range(module_ratio_plan, start_id, end_id)
            chunk_instruction = (
                f"\n【分批生成要求】\n"
                f"这是完整 {target_slice_count} 屏详情页中的第 {start_id:02d}-{end_id:02d} 屏。\n"
                f"本次只输出 {chunk_count} 个 items，slice_id 必须严格为 "
                f"{', '.join(str(i).zfill(2) for i in range(start_id, end_id + 1))}。\n"
                f"每个 slice_id 必须单独输出一个 item，禁止把多个 slice_id 合并到同一个 item。\n"
                f"不要输出这个范围之外的屏幕。不要把 slice_id 重新从 01 开始编号。\n"
                f"本分批编号要求优先级最高，覆盖模板中的任何通用编号描述。\n"
            )
            user_prompt = format_template(
                user_template,
                narrative_json=to_json(chunk_narrative),
                visual_master_spec=compact_visual_master_spec,
                target_slice_count=chunk_count,
                module_ratio_plan=to_json(compact_module_plan_summary(module_ratio_plan)),
                chunk_module_plan=to_json(chunk_module_plan),
                extra_requirements=(
                    f"结构局部修正要求（可选，不作为主要卖点输入）：{truncate_text(结构修正要求_可选, 1000)}\n"
                    if str(结构修正要求_可选).strip()
                    else ""
                ) + chunk_instruction,
            )
            content = call_synvow_llm(模型, system_prompt, user_prompt, None, temperature, 种子, llm_config=llm_config)
            return fix_mojibake(extract_json_object(content))

        try:
            if target_slice_count > PAGE_STRUCTURE_CHUNK_SIZE:
                merged_items = []
                chunk_status = []
                chunk_errors = []
                for start_id in range(1, target_slice_count + 1, PAGE_STRUCTURE_CHUNK_SIZE):
                    end_id = min(target_slice_count, start_id + PAGE_STRUCTURE_CHUNK_SIZE - 1)
                    range_label = f"{start_id:02d}-{end_id:02d}"
                    expected_count = end_id - start_id + 1
                    try:
                        chunk = normalize_llm_mapping(request_chunk(start_id, end_id), "ecommerce_long_scroll_page_structure")
                        chunk_items = normalize_chunk_items(extract_items_from_llm_result(chunk), start_id, end_id)
                        if len(chunk_items) != expected_count:
                            raise ValueError(f"目标 {expected_count} 屏，实际 {len(chunk_items)} 屏")
                        merged_items.extend(chunk_items)
                        chunk_status.append(f"{range_label}:{len(chunk_items)}")
                    except Exception as chunk_exc:
                        chunk_errors.append(f"{range_label}:{chunk_exc}")
                        chunk_status.append(f"{range_label}:失败")
                        continue
                if not merged_items:
                    raise ValueError(f"所有页面结构分批均失败：{'; '.join(chunk_errors)}")
                structure = {
                    "workflow": "ecommerce_long_scroll_page_structure",
                    "canvas_ratio": "9:21",
                    "product_name": narrative.get("product_name", ""),
                    "category": narrative.get("category", ""),
                    "visual_master_spec": 长卷视觉母版说明 or narrative.get("visual_master_spec", ""),
                    "visual_style_dna": ensure_typography_lock(narrative.get("visual_style_dna", {})),
                    "module_ratio_plan": module_ratio_plan,
                    "items": merged_items,
                    "generation_mode": "chunked",
                    "chunk_status": chunk_status,
                }
                if chunk_errors:
                    structure["partial_success"] = True
                    structure["chunk_errors"] = chunk_errors
            else:
                structure = normalize_llm_mapping(request_chunk(1, target_slice_count), "ecommerce_long_scroll_page_structure")
                structure["items"] = normalize_chunk_items(extract_items_from_llm_result(structure), 1, target_slice_count)
                if len(structure["items"]) != target_slice_count:
                    raise ValueError(
                        f"页面结构数量不一致：目标 {target_slice_count} 屏，实际 {len(structure['items'])} 屏。"
                        "已关闭自动补齐，请重新运行本节点。"
                    )

            structure = normalize_llm_mapping(structure, "ecommerce_long_scroll_page_structure")
            items = sort_items_by_slice_id(extract_items_from_llm_result(structure))
            missing_ids = [
                str(index).zfill(2)
                for index in range(1, target_slice_count + 1)
                if str(index).zfill(2) not in {str(item.get("slice_id", "")).strip().zfill(2) for item in items}
            ]
            structure["items"] = items
            module_warnings = enforce_module_plan_on_items(items, module_ratio_plan)
            structure.setdefault("workflow", "ecommerce_long_scroll_page_structure")
            structure["canvas_ratio"] = "9:21"
            structure.setdefault("product_name", narrative.get("product_name", ""))
            structure.setdefault("category", narrative.get("category", ""))
            structure.setdefault("visual_master_spec", 长卷视觉母版说明 or narrative.get("visual_master_spec", ""))
            structure["visual_style_dna"] = ensure_typography_lock(structure.get("visual_style_dna") or narrative.get("visual_style_dna", {}))
            structure.setdefault("module_ratio_plan", module_ratio_plan)
            if module_warnings:
                structure["module_plan_warnings"] = module_warnings
            status = "LLM 页面结构蓝图生成成功"
            if target_slice_count > PAGE_STRUCTURE_CHUNK_SIZE:
                if structure.get("partial_success") or missing_ids:
                    status = (
                        f"LLM 页面结构蓝图部分成功：{', '.join(structure.get('chunk_status', []))}；"
                        f"目标 {target_slice_count} 屏，实际 {len(items)} 屏"
                    )
                    if missing_ids:
                        status += f"，缺失：{', '.join(missing_ids)}"
                else:
                    status = f"LLM 页面结构蓝图分批生成成功：{', '.join(structure.get('chunk_status', []))}"
            if module_warnings:
                status += f"，模块配比已写入；有 {len(module_warnings)} 个版式与模块推荐不完全一致。"
            return (to_json(structure), page_structure_markdown(structure), status)
        except Exception as exc:
            raise RuntimeError(
                f"LLM 页面结构蓝图生成失败：{exc}；"
                f"超过 {PAGE_STRUCTURE_CHUNK_SIZE} 屏已分批请求，请重新运行本节点。"
            ) from exc


class SynVowLongScrollPromptBatchBuilder:
    CATEGORY = CATEGORY
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("批量提示词_JSON", "批量提示词_文本", "提示词列表", "生成状态")
    OUTPUT_IS_LIST = (False, False, True, False)
    FUNCTION = "build"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "页面结构蓝图_JSON": ("STRING", {"multiline": True, "default": ""}),
                "长卷视觉母版说明": ("STRING", {"multiline": True, "default": ""}),
                "模型": (RUNNINGHUB_MODELS, {"default": DEFAULT_MODEL}),
            },
            "optional": {
                "叙事结构_JSON": ("STRING", {"multiline": True, "default": ""}),
                "出图提示词修正_可选": ("STRING", {"multiline": True, "default": ""}),
                "llm_config": ("SYNVOW_LLM_CONFIG",),
                "temperature": ("FLOAT", {"default": 0.25, "min": 0.0, "max": 1.0, "step": 0.1}),
                "种子": ("INT", {"default": 0, "min": 0, "max": 2147483647, "control_after_generate": True}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, 页面结构蓝图_JSON, 长卷视觉母版说明, 模型, 叙事结构_JSON="", 出图提示词修正_可选="", llm_config=None, temperature=0.25, 种子=0):
        return stable_text_fingerprint(
            页面结构蓝图_JSON,
            长卷视觉母版说明,
            模型,
            叙事结构_JSON,
            出图提示词修正_可选,
            llm_config,
            temperature,
            种子,
            LONGSCROLL_NODE_VERSION,
            PROMPT_BATCH_CHUNK_SIZE,
        )

    def build(self, 页面结构蓝图_JSON, 长卷视觉母版说明, 模型, 叙事结构_JSON="", 出图提示词修正_可选="", llm_config=None, temperature=0.25, 种子=0):
        page_structure = normalize_llm_mapping(load_json(页面结构蓝图_JSON, {}), "ecommerce_long_scroll_page_structure")
        narrative = load_json(叙事结构_JSON, {})
        if not isinstance(narrative, dict):
            narrative = {}
        use_page_structure = bool(extract_items_from_llm_result(page_structure))
        if use_page_structure:
            page_structure["items"] = sort_items_by_slice_id(extract_items_from_llm_result(page_structure))
            target_slice_count = int(len(page_structure.get("items", [])))
            module_ratio_plan = page_structure.get("module_ratio_plan") or build_module_ratio_plan(target_slice_count)
            page_structure["module_ratio_plan"] = module_ratio_plan
            if not page_structure["items"]:
                raise RuntimeError("页面结构蓝图 items 为空，请先重新运行 RH GPT-image2详情页结构。")
        elif isinstance(narrative, dict) and narrative.get("sections"):
            target_slice_count = int(narrative.get("slice_count") or len(narrative.get("sections", [])))
            module_ratio_plan = build_module_ratio_plan(target_slice_count)
            raise RuntimeError("未连接页面结构蓝图。已关闭从叙事结构自动补齐页面结构，请先运行 RH GPT-image2详情页结构。")
        else:
            raise RuntimeError("未找到页面结构蓝图 items，也未找到叙事结构 sections。请先连接 RH GPT-image2详情页结构。")

        values = defaults()
        product_constraints = "\n".join(part for part in [
            values.get("产品硬约束", ""),
            values.get("禁止项", ""),
            f"出图提示词局部修正要求（可选，不作为主要卖点输入）：{出图提示词修正_可选}" if str(出图提示词修正_可选).strip() else "",
        ] if part)
        continuity_policy = "\n".join(part for part in [
            values.get("长卷衔接规则", ""),
            "每张 9:21 切片顶部 12%-15% 承接上一张，底部 12%-15% 引出下一张；中部区域承担本屏核心信息任务。",
            "当前阶段不要强行用提示词解决无缝接缝，接缝后续用连续生成或局部处理解决。",
        ] if part)
        prompt_requirements = "\n".join(part for part in [
            values.get("优化要求", ""),
            "每屏只保留一个一级标题、一个核心画面、一个购买说服任务，辅助标签最多 3 个。",
            "默认所有可见文字使用简体中文，避免英文标题、英文参数表、英文小字和乱码。",
            "禁止把任何蓝图字段值、模块标签、章节名、页面类型、工作流调试词、UI/搜索/导航词或结构占位词作为可见文字。不要用单个模块词当标题；必须改写成消费者能读懂的利益文案。最后一屏没有明确文案时允许无文字，只做产品/生活方式氛围收尾。",
        ] if part)

        system_prompt = read_text("longscroll_detail_prompt_system.txt")
        user_template = read_text("longscroll_detail_prompt_user.txt")
        visual_master_spec = truncate_text(
            长卷视觉母版说明
            or page_structure.get("visual_master_spec", "")
            or narrative.get("visual_master_spec", "")
            or narrative.get("master_reference_prompt", ""),
            1400,
        )
        compact_narrative = compact_narrative_for_prompt_batch(narrative) if narrative else {}

        def request_chunk(start_id, end_id):
            chunk_count = end_id - start_id + 1
            chunk_page_structure = page_structure_chunk_for_slice_range(page_structure, start_id, end_id) if use_page_structure else {}
            chunk_instruction = (
                f"\n【分批生成要求】\n"
                f"这是完整 {target_slice_count} 屏详情页提示词中的第 {start_id:02d}-{end_id:02d} 屏。\n"
                f"本次只输出 {chunk_count} 个 items，slice_id 必须严格为 "
                f"{', '.join(str(i).zfill(2) for i in range(start_id, end_id + 1))}。\n"
                f"每个 slice_id 必须单独输出一个 item，禁止把多个 slice_id 合并到同一个 item。\n"
                f"不要输出这个范围之外的屏幕。不要把 slice_id 重新从 01 开始编号。\n"
                f"本分批编号要求优先级最高，覆盖模板中的任何通用编号描述。\n"
            )
            user_prompt = format_template(
                user_template,
                page_structure_json=to_json(chunk_page_structure),
                narrative_json=to_json({} if use_page_structure else compact_narrative),
                visual_master_spec=visual_master_spec,
                target_slice_count=chunk_count,
                product_constraints=product_constraints,
                continuity_policy=continuity_policy,
                prompt_requirements=prompt_requirements,
                extra_requirements=(
                    f"出图提示词局部修正要求（可选，不作为主要卖点输入）：{truncate_text(出图提示词修正_可选, 800)}\n"
                    if str(出图提示词修正_可选).strip()
                    else ""
                ) + chunk_instruction,
            )
            content = call_synvow_llm(模型, system_prompt, user_prompt, None, temperature, 种子, llm_config=llm_config)
            return fix_mojibake(extract_json_object(content))

        try:
            if target_slice_count > PROMPT_BATCH_CHUNK_SIZE:
                merged_items = []
                chunk_status = []
                chunk_errors = []
                for start_id in range(1, target_slice_count + 1, PROMPT_BATCH_CHUNK_SIZE):
                    end_id = min(target_slice_count, start_id + PROMPT_BATCH_CHUNK_SIZE - 1)
                    range_label = f"{start_id:02d}-{end_id:02d}"
                    expected_count = end_id - start_id + 1
                    try:
                        chunk = normalize_llm_mapping(request_chunk(start_id, end_id), "ecommerce_long_scroll_detail_page")
                        chunk_items = normalize_chunk_items(extract_items_from_llm_result(chunk), start_id, end_id)
                        if len(chunk_items) != expected_count:
                            raise ValueError(f"目标 {expected_count} 屏，实际 {len(chunk_items)} 屏")
                        merged_items.extend(chunk_items)
                        chunk_status.append(f"{range_label}:{len(chunk_items)}")
                    except Exception as chunk_exc:
                        chunk_errors.append(f"{range_label}:{chunk_exc}")
                        chunk_status.append(f"{range_label}:失败")
                        continue
                if not merged_items:
                    raise ValueError(f"所有批量提示词分批均失败：{'; '.join(chunk_errors)}")
                batch = {
                    "workflow": "ecommerce_long_scroll_detail_page",
                    "canvas_ratio": "9:21",
                    "items": merged_items,
                    "generation_mode": "chunked",
                    "chunk_status": chunk_status,
                }
                if chunk_errors:
                    batch["partial_success"] = True
                    batch["chunk_errors"] = chunk_errors
            else:
                batch = normalize_llm_mapping(request_chunk(1, target_slice_count), "ecommerce_long_scroll_detail_page")
                batch["items"] = normalize_chunk_items(extract_items_from_llm_result(batch), 1, target_slice_count)
                if len(batch["items"]) != target_slice_count:
                    raise ValueError(
                        f"批量提示词数量不一致：目标 {target_slice_count} 屏，实际 {len(batch['items'])} 屏。"
                        "已关闭自动补齐，请重新运行本节点。"
                    )

            batch = normalize_llm_mapping(batch, "ecommerce_long_scroll_detail_page")
            batch["canvas_ratio"] = "9:21"
            batch["items"] = sort_items_by_slice_id(extract_items_from_llm_result(batch))
            missing_ids = [
                str(index).zfill(2)
                for index in range(1, target_slice_count + 1)
                if str(index).zfill(2) not in {str(item.get("slice_id", "")).strip().zfill(2) for item in batch["items"]}
            ]
            if use_page_structure:
                structure_by_id = {
                    str(item.get("slice_id", "")).strip().zfill(2): item
                    for item in page_structure.get("items", [])
                }
                for item in batch.get("items", []):
                    slice_id = str(item.get("slice_id", "")).strip().zfill(2)
                    structure_item = structure_by_id.get(slice_id, {})
                    for key in ("module_type", "module_label", "screen_job", "evidence_type", "layout_archetype"):
                        if not item.get(key) and structure_item.get(key):
                            item[key] = structure_item.get(key)

            prompt_list = [str(item.get("prompt", "")).strip() for item in batch.get("items", [])]
            missing_prompt_ids = [
                str(item.get("slice_id", "")).strip().zfill(2)
                for item in batch.get("items", [])
                if not str(item.get("prompt", "")).strip()
            ]
            if missing_prompt_ids:
                batch["missing_prompt_ids"] = missing_prompt_ids
                batch["items"] = [
                    item for item in batch.get("items", [])
                    if str(item.get("slice_id", "")).strip().zfill(2) not in set(missing_prompt_ids)
                ]
                prompt_list = [str(item.get("prompt", "")).strip() for item in batch.get("items", [])]
            status = "LLM 批量提示词生成成功"
            if target_slice_count > PROMPT_BATCH_CHUNK_SIZE:
                if batch.get("partial_success") or missing_ids or missing_prompt_ids:
                    status = (
                        f"LLM 批量提示词部分成功：{', '.join(batch.get('chunk_status', []))}；"
                        f"目标 {target_slice_count} 屏，实际 {len(batch.get('items', []))} 屏"
                    )
                    missing_all = sorted(set(missing_ids + missing_prompt_ids))
                    if missing_all:
                        status += f"，缺失：{', '.join(missing_all)}"
                else:
                    status = f"LLM 批量提示词分批生成成功：{', '.join(batch.get('chunk_status', []))}"
            return (to_json(batch), batch_prompt_text(batch), prompt_list, status)
        except Exception as exc:
            raise RuntimeError(
                f"LLM 批量提示词生成失败：{exc}；"
                f"超过 {PROMPT_BATCH_CHUNK_SIZE} 屏已分批请求，请重新运行本节点。"
            ) from exc


class SynVowLongScrollImageListConcat:
    CATEGORY = CATEGORY
    INPUT_IS_LIST = True
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("长图", "拼接状态")
    FUNCTION = "concat"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "图像列表": ("IMAGE",),
            }
        }

    def concat(self, 图像列表):
        images = flatten_image_inputs(图像列表)
        if not images:
            blank = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return (blank, "没有收到图像列表，已输出空白占位图。")

        widths = [int(image.shape[2]) for image in images]
        target_width = widths[0]

        resized = []
        original_sizes = []
        final_sizes = []
        for index, image in enumerate(images):
            original_sizes.append(f"{index + 1:02d}:{int(image.shape[2])}x{int(image.shape[1])}")
            part = resize_image_to_width(image, target_width)
            resized.append(part)
            final_sizes.append(f"{index + 1:02d}:{int(part.shape[2])}x{int(part.shape[1])}")

        long_image = torch.cat(resized, dim=1)
        status = (
            f"按列表顺序拼接成功：{len(resized)} 张；"
            f"目标宽度 {target_width}px；"
            f"输出尺寸 {int(long_image.shape[2])}x{int(long_image.shape[1])}；"
            f"原始尺寸：{', '.join(original_sizes)}；"
            f"拼接尺寸：{', '.join(final_sizes)}"
        )
        return (long_image, status)


NODE_CLASS_MAPPINGS = {
    "SynVowPromptLongScrollNarrativePlanner": SynVowLongScrollNarrativePlanner,
    "SynVowPromptLongScrollPageStructurePlanner": SynVowLongScrollPageStructurePlanner,
    "SynVowPromptLongScrollPromptBatchBuilder": SynVowLongScrollPromptBatchBuilder,
    "SynVowPromptLongScrollImageListConcat": SynVowLongScrollImageListConcat,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SynVowPromptLongScrollNarrativePlanner": "RH GPT-image2详情页规划",
    "SynVowPromptLongScrollPageStructurePlanner": "RH GPT-image2详情页结构",
    "SynVowPromptLongScrollPromptBatchBuilder": "RH GPT-image2详情页批量提示词",
    "SynVowPromptLongScrollImageListConcat": "RH 详情页图像列表顺序拼接长图",
}
