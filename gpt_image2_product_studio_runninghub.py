"""RunningHub GPT-Image-2 six-in-one product image studio node."""

import base64
import io
import math
from pathlib import Path

import numpy as np
import requests
import torch
import torch.nn.functional as F
import urllib3
from PIL import Image

from .gpt_image_2_alpha_runninghub import (
    _ALPHA_CANCEL_EVENT,
    ASPECT_RATIOS,
    MODEL_ENDPOINTS,
    MODEL_OPTIONS,
    RH_API_BASE_URL_OPTIONS,
    _collect_reference_images,
    _model_endpoint_url,
    _normalize_api_base_url,
    _poll_task,
    _resolve_api_key,
    _submit_with_retry,
    _upload_reference_images,
)
from .utils import (
    RUNNINGHUB_LLM_CHAT_URL,
    default_runninghub_model,
    fetch_runninghub_models,
    make_headers,
    parse_chat_response,
)


CATEGORY = "SynVow-prompt/产品图像"

MODE_PRODUCT_REFINE = "产品精修"
MODE_SCENE_COMPOSITE = "产品融入场景"
MODE_CLARITY_RESTORE = "模糊图片高清"
MODE_OBJECT_REMOVE = "移除物品"
MODE_ADD_LIGHT_EFFECT = "增加光效"
MODE_OUTPAINT = "扩图"
LEGACY_MODE_CYBER_LIGHT = "赛博科技光效"

MODES = [
    MODE_PRODUCT_REFINE,
    MODE_SCENE_COMPOSITE,
    MODE_CLARITY_RESTORE,
    MODE_OBJECT_REMOVE,
    MODE_ADD_LIGHT_EFFECT,
    MODE_OUTPAINT,
]

_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
_PROMPT_FILES = {
    MODE_PRODUCT_REFINE: "gpt_image2_product_refine.txt",
    MODE_SCENE_COMPOSITE: "gpt_image2_scene_composite.txt",
    MODE_CLARITY_RESTORE: "gpt_image2_clarity_restore.txt",
    MODE_OBJECT_REMOVE: "gpt_image2_object_remove.txt",
    MODE_ADD_LIGHT_EFFECT: "gpt_image2_add_light_effect.txt",
    MODE_OUTPAINT: "gpt_image2_outpaint.txt",
}
_LLM_PROMPT_FILE = "gpt_image2_product_studio_llm_enhancer.txt"
_LLM_OFF = "关闭"
_RATIOS = ["auto"] + list(ASPECT_RATIOS)
_QUALITIES = ["auto", "low", "medium", "high"]
_RESOLUTIONS = ["1K", "2K", "4K"]

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _normalize_mode(mode):
    text = str(mode or MODE_PRODUCT_REFINE).strip()
    return MODE_ADD_LIGHT_EFFECT if text == LEGACY_MODE_CYBER_LIGHT else text


def _read_prompt(filename, label):
    path = _PROMPT_DIR / filename
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise FileNotFoundError(f"{label}读取失败：{path}") from exc
    if not text:
        raise ValueError(f"{label}为空：{path}")
    return text


def build_product_studio_prompt(mode, extra_instructions="", has_reference=False, has_mask=False):
    mode = _normalize_mode(mode)
    if mode not in _PROMPT_FILES:
        raise ValueError(f"不支持的场景模式：{mode}")
    if mode == MODE_SCENE_COMPOSITE and not has_reference:
        raise ValueError("“产品融入场景”必须连接 reference_image 作为目标场景图。")
    extra = str(extra_instructions or "").strip()
    if mode == MODE_OBJECT_REMOVE and not extra and not has_mask:
        raise ValueError("“移除物品”请连接 mask，或描述要移除的对象、位置或特征。")
    if mode == MODE_ADD_LIGHT_EFFECT and not has_mask:
        raise ValueError("“增加光效”请连接 mask，并涂抹需要增加功能特效的区域。")

    prompt = _read_prompt(_PROMPT_FILES[mode], "提示词文件")
    if extra:
        prompt += (
            "\n\nAdditional request:\n"
            + extra
            + "\nFollow this request only where it does not conflict with the preservation constraints above."
        )
    return prompt


def _llm_models_input():
    models = list(dict.fromkeys(fetch_runninghub_models()))
    default = default_runninghub_model(models)
    if _LLM_OFF not in models:
        models.append(_LLM_OFF)
    return models, {"default": default}


def _strip_prompt_wrapper(text):
    prompt = str(text or "").strip()
    if prompt.startswith("```"):
        line_end = prompt.find("\n")
        prompt = prompt[line_end + 1:] if line_end >= 0 else ""
        if prompt.rstrip().endswith("```"):
            prompt = prompt.rstrip()[:-3]
    for prefix in ("Final prompt:", "Final Prompt:", "Enhanced prompt:", "Enhanced Prompt:"):
        if prompt.startswith(prefix):
            prompt = prompt[len(prefix):].lstrip()
            break
    return prompt.strip()


def _tensor_to_data_url(image):
    tensor = image[0] if image.ndim == 4 else image
    array = np.clip(tensor.detach().cpu().numpy() * 255.0, 0, 255).astype(np.uint8)
    if array.ndim == 2:
        pil_image = Image.fromarray(array, mode="L").convert("RGB")
    else:
        pil_image = Image.fromarray(array[..., :3], mode="RGB")
    if max(pil_image.size) > 1280:
        pil_image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    pil_image.save(buffer, format="JPEG", quality=88)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _llm_image_roles(mode, has_mask, has_reference):
    roles = ["Image 1: the original source image that must be preserved."]
    if has_mask:
        if mode == MODE_OUTPAINT:
            roles.append(
                "Image 2: the aligned outpainting guide; white is boundary-connected blank canvas "
                "to fill and black is protected."
            )
        else:
            roles.append(
                "Image 2: the aligned selection guide; white is selected and black is protected."
            )
    if has_reference:
        roles.append(
            f"Image {len(roles) + 1}: optional reference image, used only as allowed by the base prompt."
        )
    return roles


def _enhance_prompt_with_llm(
    api_key,
    llm_model,
    mode,
    base_prompt,
    extra_instructions,
    image,
    mask_guide=None,
    reference_image=None,
    seed=0,
):
    images = [image]
    if mask_guide is not None:
        images.append(mask_guide)
    has_reference = reference_image is not None and mode != MODE_OBJECT_REMOVE
    if has_reference:
        images.append(reference_image)

    roles = _llm_image_roles(mode, mask_guide is not None, has_reference)
    user_text = (
        f"Mode: {mode}\n"
        f"Additional request: {str(extra_instructions or '').strip() or '(none; infer the best edit from the images)'}\n\n"
        "Image roles:\n- "
        + "\n- ".join(roles)
        + "\n\nBase GPT-Image-2 prompt to preserve and improve:\n"
        + base_prompt
    )
    content = [{"type": "text", "text": user_text}]
    for index, item in enumerate(images, start=1):
        content.append({"type": "text", "text": f"Image {index}:"})
        content.append({"type": "image_url", "image_url": {"url": _tensor_to_data_url(item)}})

    payload = {
        "model": llm_model,
        "messages": [
            {
                "role": "system",
                "content": _read_prompt(_LLM_PROMPT_FILE, "LLM 提示词文件"),
            },
            {"role": "user", "content": content},
        ],
        "max_tokens": 2600,
        "temperature": 0.2,
        "stream": False,
    }
    if int(seed or 0) > 0:
        payload["seed"] = int(seed) % 2147483647

    print(f"[RH ProductStudio] LLM 分析中 mode={mode} model={llm_model}")
    response = requests.post(
        RUNNINGHUB_LLM_CHAT_URL,
        headers=make_headers(api_key),
        json=payload,
        timeout=(30, 600),
        verify=False,
    )
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        body = response.text[:1200] if response.text else "<empty response>"
        raise RuntimeError(f"RunningHub LLM HTTP {response.status_code}: {body}") from exc
    enhanced = _strip_prompt_wrapper(parse_chat_response(response.json()))
    if len(enhanced) < 80:
        raise RuntimeError(f"LLM 返回内容无效或过短：{enhanced[:160]}")
    return enhanced


def _mask_to_guide_image(mask, target_image=None):
    if mask is None:
        return None
    if mask.ndim == 2:
        mask = mask.unsqueeze(0)
    elif mask.ndim == 4 and mask.shape[-1] == 1:
        mask = mask[..., 0]
    elif mask.ndim == 4 and mask.shape[1] == 1:
        mask = mask[:, 0]
    if mask.ndim != 3:
        raise ValueError(f"mask 格式不正确，期望 [B,H,W]，实际为 {tuple(mask.shape)}")
    mask = mask.detach().float().clamp(0.0, 1.0)
    if float(mask.max().item()) <= 0.001:
        return None
    if target_image is not None:
        target_size = (int(target_image.shape[-3]), int(target_image.shape[-2]))
        if tuple(mask.shape[-2:]) != target_size:
            mask = F.interpolate(
                mask.unsqueeze(1), size=target_size, mode="bilinear", align_corners=False
            ).squeeze(1)
    mask = (mask > 0.05).float()
    return mask.unsqueeze(-1).repeat(1, 1, 1, 3)


def _connected_white_region(candidate, strict_white):
    try:
        import cv2

        _, labels = cv2.connectedComponents(candidate.astype(np.uint8), connectivity=4)
        border_labels = np.unique(
            np.concatenate((labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]))
        )
        strict_labels = np.unique(labels[strict_white])
        selected_labels = np.intersect1d(border_labels, strict_labels)
        return np.isin(labels, selected_labels[selected_labels != 0])
    except ImportError:
        from collections import deque

        height, width = candidate.shape
        selected = np.zeros_like(candidate, dtype=bool)
        queue = deque()
        edge_points = (
            [(0, x) for x in range(width)]
            + [(height - 1, x) for x in range(width)]
            + [(y, 0) for y in range(1, height - 1)]
            + [(y, width - 1) for y in range(1, height - 1)]
        )
        for y, x in edge_points:
            if strict_white[y, x] and candidate[y, x] and not selected[y, x]:
                selected[y, x] = True
                queue.append((y, x))
        while queue:
            y, x = queue.popleft()
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < height and 0 <= nx < width:
                    if candidate[ny, nx] and not selected[ny, nx]:
                        selected[ny, nx] = True
                        queue.append((ny, nx))
        return selected


def _make_boundary_white_mask(image):
    if image.ndim == 3:
        image = image.unsqueeze(0)
    if image.ndim != 4 or image.shape[-1] < 3:
        raise ValueError(f"image 格式不正确，期望 [B,H,W,C]，实际为 {tuple(image.shape)}")
    source = image.detach().float().clamp(0.0, 1.0)
    masks = []
    coverages = []
    for batch_index in range(int(source.shape[0])):
        rgb = source[batch_index, ..., :3].cpu().numpy()
        channel_min = rgb.min(axis=2)
        channel_range = rgb.max(axis=2) - channel_min
        candidate = (channel_min >= 0.975) & (channel_range <= 0.025)
        strict_white = (channel_min >= 0.995) & (channel_range <= 0.008)
        selected = _connected_white_region(candidate, strict_white)
        coverage = float(selected.mean())
        if coverage < 0.002:
            raise ValueError(
                "“扩图”没有检测到与画布边缘相连的 #ffffff 区域，请先将扩充边界填为纯白。"
            )
        if coverage > 0.95:
            raise ValueError("“扩图”检测到的白色区域超过画面 95%，请检查输入图。")
        masks.append(selected.astype(np.float32))
        coverages.append(coverage)
    mask = source.new_tensor(np.stack(masks, axis=0))
    return mask.unsqueeze(-1).repeat(1, 1, 1, 3), sum(coverages) / len(coverages)


def _make_removal_overlay(image, mask_guide):
    source = image.unsqueeze(0) if image.ndim == 3 else image
    source = source.detach().float().clamp(0.0, 1.0)
    mask = mask_guide[..., :1].to(device=source.device, dtype=source.dtype)
    if mask.shape[0] == 1 and source.shape[0] > 1:
        mask = mask.expand(source.shape[0], -1, -1, -1)
    if mask.shape[0] != source.shape[0]:
        raise ValueError(f"image 与 mask 批次数量不一致：{source.shape[0]} / {mask.shape[0]}")
    magenta = source.new_tensor((1.0, 0.0, 0.85)).view(1, 1, 1, 3)
    return source * (1.0 - mask * 0.82) + magenta * (mask * 0.82)


def _closest_aspect_ratio(image):
    height, width = (
        (int(image.shape[1]), int(image.shape[2]))
        if image.ndim == 4
        else (int(image.shape[0]), int(image.shape[1]))
    )
    source_ratio = width / max(height, 1)
    return min(
        ASPECT_RATIOS,
        key=lambda ratio: abs(
            math.log((int(ratio.split(":")[0]) / int(ratio.split(":")[1])) / source_ratio)
        ),
    )


def _build_generation_payload(prompt, aspect_ratio, resolution, quality, image_urls, model, seed):
    payload = {
        "prompt": str(prompt or ""),
        "aspectRatio": str(aspect_ratio),
        "resolution": str(resolution).lower(),
    }
    if image_urls:
        payload["imageUrls"] = image_urls
    if MODEL_ENDPOINTS[model].get("quality"):
        payload["quality"] = "medium" if quality == "auto" else quality
    if int(seed or 0) > 0:
        payload["seed"] = int(seed) % 2147483647
    return payload


def _download_image_tensor(url):
    response = requests.get(url, timeout=(30, 180), verify=False)
    response.raise_for_status()
    image = Image.open(io.BytesIO(response.content)).convert("RGB")
    array = np.asarray(image).astype(np.float32) / 255.0
    return torch.from_numpy(array).unsqueeze(0)


def _download_images(urls):
    tensors = []
    for url in urls:
        try:
            tensors.append(_download_image_tensor(url))
        except Exception as exc:
            print(f"[RH ProductStudio] 下载结果失败：{exc}")
    if not tensors:
        raise RuntimeError("RunningHub 已返回任务结果，但没有可下载的有效图片。")
    first_size = tensors[0].shape[1:3]
    normalized = [
        tensor
        if tensor.shape[1:3] == first_size
        else F.interpolate(
            tensor.permute(0, 3, 1, 2), size=first_size, mode="bilinear", align_corners=False
        ).permute(0, 2, 3, 1)
        for tensor in tensors
    ]
    return torch.cat(normalized, dim=0)


def _raise_friendly_rh_error(exc):
    """Translate RunningHub account-tier failures into an actionable node error."""
    text = str(exc or "")
    lowered = text.lower()
    if (
        "1014" in text
        or "enterprise-shared" in lowered
        or "standard model api is restricted" in lowered
        or "标准模型api仅限企业级" in lowered
    ):
        raise RuntimeError(
            "RunningHub Key 类型不支持：当前 Key 可以上传图片，但不能调用标准模型 API。"
            "RH GPT-Image-2 产品六合一需要 Enterprise-Shared（企业共享）API Key；"
            "请更换支持标准模型 API 的企业共享 Key 后重试。"
        ) from exc
    raise exc


class RunningHubGptImage2ProductStudio:
    FUNCTION = "generate"
    CATEGORY = CATEGORY
    DESCRIPTION = "RunningHub GPT-Image-2 产品六合一：精修、场景、高清、移除、功能特效与扩图。"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "mode": (MODES, {"default": MODE_PRODUCT_REFINE}),
                "model_type": (MODEL_OPTIONS, {"default": MODEL_OPTIONS[0]}),
                "quality": (_QUALITIES, {"default": "auto"}),
                "resolution": (_RESOLUTIONS, {"default": "1K"}),
                "aspect_ratio": (_RATIOS, {"default": "auto"}),
                "seed": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 2147483647,
                        "control_after_generate": True,
                    },
                ),
                "llm_model": _llm_models_input(),
            },
            "optional": {
                "api_base_url": (
                    RH_API_BASE_URL_OPTIONS,
                    {"default": RH_API_BASE_URL_OPTIONS[0]},
                ),
                "reference_image": ("IMAGE",),
                "mask": ("MASK",),
                "extra_instructions": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "placeholder": "可选：摆放位置、移除目标、功能特效偏好或扩图环境",
                    },
                ),
                "llm_config": ("SYNVOW_LLM_CONFIG",),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("images", "final_prompt", "status")

    def generate(
        self,
        image,
        mode,
        model_type,
        quality,
        resolution,
        aspect_ratio,
        seed,
        llm_model,
        api_base_url=RH_API_BASE_URL_OPTIONS[0],
        reference_image=None,
        mask=None,
        extra_instructions="",
        llm_config=None,
    ):
        _ALPHA_CANCEL_EVENT.clear()
        if image is None:
            raise ValueError("请连接主输入图片 image。")
        mode = _normalize_mode(mode)
        model = model_type if model_type in MODEL_ENDPOINTS else MODEL_OPTIONS[0]
        api_base_url = _normalize_api_base_url(api_base_url)
        ratio = _closest_aspect_ratio(image) if aspect_ratio == "auto" else aspect_ratio
        mask_guide = None
        outpaint_coverage = None
        if mode == MODE_OUTPAINT:
            mask_guide, outpaint_coverage = _make_boundary_white_mask(image)
        elif mode in (MODE_OBJECT_REMOVE, MODE_ADD_LIGHT_EFFECT):
            mask_guide = _mask_to_guide_image(mask, image)

        base_prompt = build_product_studio_prompt(
            mode,
            extra_instructions,
            has_reference=reference_image is not None,
            has_mask=mask_guide is not None,
        )
        api_key = _resolve_api_key(llm_config)
        if not api_key:
            raise RuntimeError(
                "缺少 RunningHub API Key：请设置 RH_API_KEY/RUNNINGHUB_API_KEY，"
                "或连接 SynVow LLM Settings。"
            )

        final_prompt = base_prompt
        llm_status = "off"
        if llm_model != _LLM_OFF:
            try:
                final_prompt = _enhance_prompt_with_llm(
                    api_key,
                    llm_model,
                    mode,
                    base_prompt,
                    extra_instructions,
                    image,
                    mask_guide=mask_guide,
                    reference_image=reference_image,
                    seed=seed,
                )
                llm_status = llm_model
            except Exception as exc:
                llm_status = f"fallback({llm_model})"
                print(f"[RH ProductStudio] LLM 增强失败，回退本地模板：{exc}")

        if mode == MODE_OBJECT_REMOVE and mask_guide is not None:
            request_images = [_make_removal_overlay(image, mask_guide), mask_guide]
        else:
            request_images = [image]
            if mask_guide is not None:
                request_images.append(mask_guide)
        if reference_image is not None and mode != MODE_OBJECT_REMOVE:
            request_images.append(reference_image)

        reference_bytes = _collect_reference_images(*request_images)
        reference_urls = _upload_reference_images(api_key, reference_bytes, api_base_url)
        endpoint_info = MODEL_ENDPOINTS[model]
        endpoint_url = _model_endpoint_url(endpoint_info, "image", api_base_url)
        payload = _build_generation_payload(
            final_prompt, ratio, resolution, quality, reference_urls, model, seed
        )
        print(
            f"[RH ProductStudio] 提交 mode={mode} model={model} "
            f"images={len(reference_urls)} ratio={ratio}"
        )
        try:
            task_id = _submit_with_retry(api_key, endpoint_url, payload)
        except Exception as exc:
            _raise_friendly_rh_error(exc)
        image_urls = _poll_task(api_key, task_id, api_base_url)
        output = _download_images(image_urls)

        mask_status = "yes" if mask_guide is not None else "no"
        coverage = (
            f" white_area={outpaint_coverage:.1%}" if outpaint_coverage is not None else ""
        )
        status = (
            f"已完成 mode={mode} model={model} api_base_url={api_base_url} ratio={ratio} "
            f"resolution={resolution} quality={quality} seed={seed} "
            f"mask={mask_status} llm={llm_status}{coverage}"
        )
        return output, final_prompt, status


NODE_CLASS_MAPPINGS = {
    "RunningHubGptImage2ProductStudio": RunningHubGptImage2ProductStudio,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RunningHubGptImage2ProductStudio": "RH GPT-Image-2 产品六合一",
}
