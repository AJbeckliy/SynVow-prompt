import base64
import io
import json
import os
import re

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

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROMPTS_DIR = os.path.join(_CURRENT_DIR, "prompts")


def _load_prompt(filename):
    prompt_file = os.path.join(_PROMPTS_DIR, filename)
    try:
        with open(prompt_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as exc:
        print(f"[Banana Ecommerce V3] Failed to load prompt {filename}: {exc}")
        return None


def _load_system_prompt():
    prompt = _load_prompt("banana_ecommerce_system_prompt.txt")
    if prompt is None:
        prompt = _load_prompt("banana_ecommerce_default_prompt.txt")
    if prompt is None:
        raise FileNotFoundError("Missing banana ecommerce prompt files in prompts/.")
    return prompt


def _tensor_to_data_url(image, index=0):
    img_tensor = image
    if hasattr(image, "shape") and len(image.shape) == 4:
        img_tensor = image[index]

    arr = 255.0 * img_tensor.cpu().numpy()
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    if img.width > 1024 or img.height > 1024:
        img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def _collect_images(images, max_images):
    data_urls = []
    for image in images:
        if image is None or len(data_urls) >= max_images:
            continue
        try:
            if hasattr(image, "shape") and len(image.shape) == 4:
                for idx in range(int(image.shape[0])):
                    if len(data_urls) >= max_images:
                        break
                    data_urls.append(_tensor_to_data_url(image, idx))
            else:
                data_urls.append(_tensor_to_data_url(image, 0))
        except Exception as exc:
            print(f"[Banana Ecommerce V3] Image conversion failed: {exc}")
    return data_urls


class BananaEcommercePromptGeneratorV3:
    @classmethod
    def INPUT_TYPES(cls):
        models = fetch_runninghub_models()
        return {
            "required": {
                "model": (models, {"default": default_runninghub_model(models)}),
                "product_type": ("STRING", {"multiline": False, "default": "美妆粉底液"}),
                "selling_points": ("STRING", {"multiline": True, "default": "持久显色、自动避障"}),
                "design_style": (
                    [
                        "简约 Ins 风",
                        "高级奢华",
                        "科技感",
                        "清新自然",
                        "国潮风",
                        "活泼撞色",
                        "极简工业风",
                        "梦幻唯美",
                        "亚马逊风格",
                    ],
                    {"default": "简约 Ins 风"},
                ),
                "scene_preference": (
                    [
                        "混合（以使用场景为主）",
                        "生活方式使用场景（人物/手部交互）",
                        "棚拍干净背景（不复刻参考图背景）",
                    ],
                    {"default": "混合（以使用场景为主）"},
                ),
                "output_language": (
                    ["中文 (Chinese)", "English", "自动检测 (Auto)"],
                    {"default": "自动检测 (Auto)"},
                ),
                "seed": ("INT", {"default": 0, "min": 0, "max": 2147483647}),
                "prompt_count": ("INT", {"default": 5, "min": 1, "max": 20, "forceInput": False}),
            },
            "optional": {
                "llm_config": ("SYNVOW_LLM_CONFIG",),
                "product_image_1": ("IMAGE",),
                "product_image_2": ("IMAGE",),
                "product_image_3": ("IMAGE",),
                "product_image_4": ("IMAGE",),
                "product_image_5": ("IMAGE",),
                "product_image_6": ("IMAGE",),
                "product_image_7": ("IMAGE",),
                "product_image_8": ("IMAGE",),
                "ref_image_1": ("IMAGE",),
                "ref_image_2": ("IMAGE",),
                "ref_image_3": ("IMAGE",),
                "ref_image_4": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("STRING", "INT", "STRING")
    RETURN_NAMES = ("prompts_list", "prompts_count", "debug_info")
    OUTPUT_IS_LIST = (True, False, False)
    FUNCTION = "generate_prompts_with_vision"
    CATEGORY = "SynVow-prompt"

    def _parse_response_to_prompts_list(self, response_text):
        cleaned = (response_text or "").strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            result = json.loads(cleaned)
            if isinstance(result, list):
                return [self._extract_prompt_text(item) for item in result]
        except Exception:
            pass

        parts = [p.strip() for p in re.split(r"\n\s*\n\s*\n+", response_text or "") if p.strip()]
        return parts if len(parts) > 1 else [response_text or ""]

    def _extract_prompt_text(self, item):
        if isinstance(item, dict):
            prompt = item.get("prompt")
            return prompt if isinstance(prompt, str) else json.dumps(item, ensure_ascii=False)
        return str(item).replace("\\n", "\n")

    def _build_image_section(self, product_count, ref_count):
        if not product_count and not ref_count:
            return ""

        product_block = ""
        if product_count:
            product_block = f"""
【产品参考图】共 {product_count} 张，编号：产品参考图1 ~ 产品参考图{product_count}
  - 仅用于：锁定产品的形状、轮廓、颜色、材质、logo、细节纹理，所有屏必须保持产品外观完全一致。
  - 必须做到：抠出产品主体，丢弃原图背景，为每屏重建全新场景与镜头。
  - 严格禁止：从产品参考图中提取任何背景色调、氛围、排版或光影风格。"""

        ref_block = ""
        if ref_count:
            ref_block = f"""
【风格参考图】共 {ref_count} 张，编号：风格参考图1 ~ 风格参考图{ref_count}
  - 仅用于：提取视觉风格，包括色调配色、背景氛围、光影风格、排版结构、构图节奏。
  - 必须先分析参考图的具体色调、背景氛围、光影、排版和构图，再把这些具体描述写入每屏提示词。
  - 严格禁止：从风格参考图中提取或描述任何产品形状、产品细节、人物身份或品牌信息。
  - 严格禁止：把风格参考图的产品或人物当作本次产品的参考外观。"""

        return f"\n[图片分组说明 - 严格区分，禁止混用]{product_block}{ref_block}\n"

    def _build_user_request(
        self,
        product_type,
        selling_points,
        design_style,
        scene_preference,
        output_language,
        prompt_count,
        product_count,
        ref_count,
    ):
        if output_language == "中文 (Chinese)":
            lang_instruction = "请使用中文生成所有提示词内容。"
        elif output_language == "English":
            lang_instruction = "Please generate all prompt content in English."
        else:
            lang_instruction = "请根据用户输入语言自动选择输出语言。"

        if scene_preference == "生活方式使用场景（人物/手部交互）":
            scene_instruction = (
                "每一屏都必须是全新设计的生活方式/使用场景画面，画面中必须有人物或手部与产品交互，"
                "并且必须有真实场景背景；禁止白底棚拍、白底平铺、俯拍平铺、证件照式正面商品图。"
            )
        elif scene_preference == "棚拍干净背景（不复刻参考图背景）":
            scene_instruction = (
                "每一屏都必须是全新设计的棚拍画面，禁止复刻参考图的原背景与道具；"
                "允许少量手部交互特写表现使用。"
            )
        else:
            scene_instruction = (
                "以全新设计的使用场景为主，优先有人物/手部交互和真实环境背景，"
                "少量屏幕可用干净棚拍用于参数或结构说明；禁止把参考图背景当作必须复刻的场景。"
            )

        image_section = self._build_image_section(product_count, ref_count)
        return f"""
请为以下产品设计 {{COUNT}} 屏详情页提示词：
1. 产品类型: {product_type}
2. 核心卖点: {selling_points}
3. 设计风格: {design_style}
4. 场景偏好: {scene_preference}（必须遵守：{scene_instruction}）
5. 输出语言要求: {lang_instruction}
{image_section}
重要：每个元素是纯字符串，不要包装成 JSON 对象，不要出现 prompt、consistency_id 等字段名，不要输出任何解释文字。

请严格输出 JSON 字符串列表 (List[str])，列表长度必须严格等于 {{COUNT}}。
每个元素对应一屏，字符串内部允许换行。不要输出 Markdown、不要代码块、不要额外解释。
"""

    def call_llm_vision(self, base_url, apikey, model, system_prompt, user_prompt, product_images, ref_images, seed=None):
        content = [{"type": "text", "text": user_prompt}]
        for idx, image_url in enumerate(product_images, 1):
            content.append({"type": "text", "text": f"产品参考图{idx}："})
            content.append({"type": "image_url", "image_url": {"url": image_url}})
        for idx, image_url in enumerate(ref_images, 1):
            content.append({"type": "text", "text": f"风格参考图{idx}："})
            content.append({"type": "image_url", "image_url": {"url": image_url}})

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            "max_tokens": 4096,
            "temperature": 0.7,
            "stream": False,
        }
        if seed is not None:
            payload["seed"] = seed % 2147483647

        response = requests.post(
            base_url.rstrip("/"),
            headers=make_headers(apikey),
            json=payload,
            timeout=(30, 600),
            verify=False,
        )
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            body = response.text[:2000] if response.text else "<empty response>"
            if response.status_code == 401 and "only SHARED" in body:
                raise RuntimeError(
                    "RunningHub LLM 认证失败：当前账号/API Key 不是 LLM 网关接受的 SHARED/enterprise key。"
                    "请换用支持 LLM 的 RunningHub 企业/共享 Key，或连接 SynVow LLM Settings 使用第三方接口。"
                ) from exc
            raise RuntimeError(f"API request failed: HTTP {response.status_code}; response={body}") from exc

        raw = parse_chat_response(response.json())
        if not raw or not raw.strip():
            raise RuntimeError(f"模型未返回有效内容: {str(response.json())[:200]}")
        return raw.strip()

    def generate_prompts_with_vision(
        self,
        model,
        product_type,
        selling_points,
        design_style,
        scene_preference,
        output_language,
        seed,
        prompt_count,
        llm_config=None,
        product_image_1=None,
        product_image_2=None,
        product_image_3=None,
        product_image_4=None,
        product_image_5=None,
        product_image_6=None,
        product_image_7=None,
        product_image_8=None,
        ref_image_1=None,
        ref_image_2=None,
        ref_image_3=None,
        ref_image_4=None,
    ):
        base_url, apikey, model_name = resolve_llm_config(llm_config, model_name=model)
        if not base_url or not apikey or not model_name:
            raise RuntimeError("缺少 LLM 配置：请登录 RunningHub/设置 RH_API_KEY，或连接 SynVow LLM Settings。")

        target_count = max(1, min(20, int(prompt_count)))
        product_images = _collect_images(
            [
                product_image_1,
                product_image_2,
                product_image_3,
                product_image_4,
                product_image_5,
                product_image_6,
                product_image_7,
                product_image_8,
            ],
            max_images=8,
        )
        ref_images = _collect_images([ref_image_1, ref_image_2, ref_image_3, ref_image_4], max_images=4)

        system_prompt = _load_system_prompt()
        user_prompt = self._build_user_request(
            product_type,
            selling_points,
            design_style,
            scene_preference,
            output_language,
            target_count,
            len(product_images),
            len(ref_images),
        )

        collected = []
        raw_responses = []
        attempts = []
        max_per_call = 6
        call_idx = 0
        last_error = None

        while len(collected) < target_count and call_idx < 30:
            request_n = min(target_count - len(collected), max_per_call)
            batch_prompt = user_prompt.replace("{COUNT}", str(request_n))
            if collected:
                batch_prompt += f"\n\n补充要求：这是续写生成。请生成新的 {request_n} 屏，不要重复之前的内容与角度。"

            try:
                raw = self.call_llm_vision(
                    base_url,
                    apikey,
                    model_name,
                    system_prompt,
                    batch_prompt,
                    product_images,
                    ref_images,
                    seed + call_idx if seed is not None else None,
                )
                raw_responses.append(raw)
                batch = self._parse_response_to_prompts_list(raw)
                collected.extend([item for item in batch if str(item).strip()])
                attempts.append({"call": call_idx + 1, "requested": request_n, "parsed": len(batch)})
            except Exception as exc:
                last_error = str(exc)
                attempts.append({"call": call_idx + 1, "requested": request_n, "error": last_error})
                break
            call_idx += 1

        if len(collected) < target_count:
            collected.extend([f"[GENERATION_FAILED] {last_error or 'Unable to generate enough prompts.'}"] * (target_count - len(collected)))
        collected = collected[:target_count]

        debug_info = {
            "model": model_name,
            "base_url": base_url,
            "product_image_count": len(product_images),
            "style_reference_image_count": len(ref_images),
            "attempts": attempts,
        }
        if raw_responses:
            debug_info["raw_response"] = raw_responses[-1]
        if last_error:
            debug_info["error"] = last_error

        return (collected, len(collected), json.dumps(debug_info, ensure_ascii=False))


NODE_CLASS_MAPPINGS = {
    "BananaEcommercePromptGeneratorV3": BananaEcommercePromptGeneratorV3,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "BananaEcommercePromptGeneratorV3": "香蕉电商详情页提示词生成器V3-带参考图",
}
