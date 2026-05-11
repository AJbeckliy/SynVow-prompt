"""
图生图提示词控制器 (独立版)
"""

import base64
import hashlib
import io
import json
import pathlib
import re

import numpy as np
import requests
import urllib3
from PIL import Image

from .utils import parse_chat_response, make_headers

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_PROMPTS_DIR = pathlib.Path(__file__).resolve().parent / "prompts"
_SYSTEM_PROMPT = (_PROMPTS_DIR / "reference_image_optimizer_system.txt").read_text(encoding="utf-8")

_REFERENCE_MODE_MAP = {
    "自动判断": "auto",
    "综合参考": "full_reference",
    "只参考风格": "style_only",
    "只参考构图": "composition_only",
    "只参考色彩光影": "color_lighting_only",
    "只参考版式": "layout_only",
}


def _tensor_to_base64(tensor) -> str:
    i = 255.0 * tensor[0].cpu().numpy()
    img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))
    if img.width > 1024 or img.height > 1024:
        img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _build_user_message(reference_image, user_prompt: str, reference_mode: str, target_aspect_ratio: str, subject_image=None) -> list:
    content = []
    if subject_image is not None:
        b64_subject = _tensor_to_base64(subject_image)
        content.append({"type": "text", "text": "以下是 subject_image（主体图）："})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_subject}"}})
    b64_ref = _tensor_to_base64(reference_image)
    content.append({"type": "text", "text": "以下是 reference_image（参考图）："})
    content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_ref}"}})
    has_subject = "是" if subject_image is not None else "否"
    content.append({
        "type": "text",
        "text": (
            f"用户需求：{user_prompt}\n"
            f"是否提供 subject_image：{has_subject}\n"
            f"reference_mode：{reference_mode}\n"
            f"target_aspect_ratio：{target_aspect_ratio}"
        ),
    })
    return content


def _parse_output(raw: str):
    def extract(tag: str) -> str:
        pattern = rf"{tag}:\s*(.*?)(?=\n\w+_\w+:|$)"
        m = re.search(pattern, raw, re.DOTALL)
        return m.group(1).strip() if m else ""

    optimized_prompt = extract("optimized_prompt")
    reference_summary = extract("reference_summary")
    return optimized_prompt, reference_summary


class RHImg2ImgPromptOptimizer:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "reference_image": ("IMAGE",),
                "user_prompt": ("STRING", {"multiline": True, "default": ""}),
                "base_url": ("STRING", {"default": ""}),
                "apikey": ("STRING", {"default": ""}),
                "models_name": ("STRING", {"default": ""}),
                "reference_mode": (
                    ["自动判断", "综合参考", "只参考风格", "只参考构图", "只参考色彩光影", "只参考版式"],
                    {"default": "自动判断"},
                ),
                "target_aspect_ratio": (
                    ["auto", "1:1", "16:9", "9:16", "4:3", "3:4", "5:4", "4:5",
                     "3:2", "2:3", "3:1", "1:3", "2:1", "1:2", "21:9", "9:21"],
                    {"default": "auto"},
                ),
                "seed": ("INT", {"default": 0, "min": 0, "max": 2147483647}),
            },
            "optional": {
                "subject_image": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("optimized_prompt", "reference_summary")
    FUNCTION = "optimize"
    CATEGORY = "SynVow-prompt"
    DESCRIPTION = "图生图提示词控制器（独立版，自定义 API 地址和模型）"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        key = json.dumps({k: str(v) for k, v in kwargs.items() if k not in ("reference_image", "subject_image")}, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(key.encode()).hexdigest()

    def optimize(self, reference_image, user_prompt, base_url, apikey, models_name,
                 reference_mode, target_aspect_ratio, seed=0, subject_image=None):
        headers = make_headers(apikey)

        ref_mode_en = _REFERENCE_MODE_MAP.get(reference_mode, reference_mode)
        ratio_en = target_aspect_ratio

        has_subject = subject_image is not None
        print(f"[RH Img2Img RefOptimizer] model={models_name} mode={ref_mode_en} ratio={ratio_en} has_subject={has_subject}")

        user_content = _build_user_message(reference_image, user_prompt, ref_mode_en, ratio_en, subject_image=subject_image)

        chat_url = base_url.rstrip('/')
        payload = {
            "model": models_name,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
        }
        if seed > 0:
            payload["seed"] = seed

        res = requests.post(chat_url, headers=headers, json=payload, timeout=(30, 600), verify=False)
        try:
            res.raise_for_status()
        except requests.exceptions.HTTPError as e:
            response_text = res.text[:2000] if res.text else "<empty response>"
            raise RuntimeError(f"API request failed: HTTP {res.status_code}; response={response_text}") from e

        raw = parse_chat_response(res.json())
        if not raw or not raw.strip():
            raise RuntimeError(f"模型未返回有效内容: {str(res.json())[:200]}")

        raw = raw.strip()
        print(f"[RH Img2Img RefOptimizer] raw={raw[:300]}")

        optimized_prompt, reference_summary = _parse_output(raw)

        if not optimized_prompt:
            optimized_prompt = raw

        return (optimized_prompt, reference_summary)


NODE_CLASS_MAPPINGS = {
    "RHImg2ImgPromptOptimizer": RHImg2ImgPromptOptimizer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RHImg2ImgPromptOptimizer": "SynVow-图生图提示词控制器",
}
