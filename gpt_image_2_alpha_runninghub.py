# -*- coding: utf-8 -*-
"""RunningHub GPT-Image-2 URL-only node for transparent asset workflows."""

import hashlib
import io
import json
import re
import threading
import time
from typing import Any, Dict, List

import comfy.utils
import numpy as np
import requests
import urllib3
from PIL import Image

from .utils import get_runninghub_openapi_key, make_headers


CATEGORY = "SynVow-prompt/透明素材"
RH_API_BASE_URL_OPTIONS = [
    "https://www.runninghub.cn/openapi/v2",
    "https://www.runninghub.ai/openapi/v2",
]
RH_API_BASE_URL = RH_API_BASE_URL_OPTIONS[0]
RH_BASE_URL = RH_API_BASE_URL.rsplit("/openapi/v2", 1)[0]
RH_UPLOAD_URL = f"{RH_API_BASE_URL}/media/upload/binary"
RH_QUERY_URL = f"{RH_API_BASE_URL}/query"
POLL_INTERVAL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 900
SUBMIT_RETRY_ATTEMPTS = 2
MAX_REFERENCE_IMAGES = 8
TRANSPARENT_BACKGROUND_VALUE = "transparent"

MODEL_OPTIONS = [
    "gpt-image-2-低价通道",
    "gpt-image-2-官方",
]
MODEL_ENDPOINTS = {
    "gpt-image-2-官方": {
        "text": f"{RH_BASE_URL}/openapi/v2/rhart-image-g-2-official/text-to-image",
        "image": f"{RH_BASE_URL}/openapi/v2/rhart-image-g-2-official/image-to-image",
        "quality": True,
    },
    "gpt-image-2-低价通道": {
        "text": f"{RH_BASE_URL}/openapi/v2/rhart-image-g-2/text-to-image",
        "image": f"{RH_BASE_URL}/openapi/v2/rhart-image-g-2/image-to-image",
        "quality": False,
    },
}
MODEL_ALIASES = {
    "gpt-image-2-official": "gpt-image-2-官方",
    "gpt-image-2-1k-2605": "gpt-image-2-低价通道",
}
ASPECT_RATIOS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "2:1", "1:2", "21:9"]
RESOLUTIONS = ["1K", "2K", "4K"]
QUALITIES = ["auto", "low", "medium", "high"]

_ALPHA_CANCEL_EVENT = threading.Event()
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class AlphaPollingCancelled(RuntimeError):
    pass


def request_alpha_cancel():
    _ALPHA_CANCEL_EVENT.set()


def _raise_if_cancelled():
    if _ALPHA_CANCEL_EVENT.is_set():
        raise AlphaPollingCancelled("已取消 RH GPT-Image-2 Alpha 轮询。")
    try:
        import comfy.model_management as mm

        mm.throw_exception_if_processing_interrupted()
    except AlphaPollingCancelled:
        raise
    except Exception:
        pass


def _sleep_interruptible(seconds: float):
    deadline = time.time() + max(0.0, float(seconds))
    while time.time() < deadline:
        _raise_if_cancelled()
        time.sleep(min(0.5, max(0.0, deadline - time.time())))
    _raise_if_cancelled()


def _unpack(value):
    return value[0] if isinstance(value, list) and len(value) == 1 else value


def _normalize_model_type(model_type: str) -> str:
    text = str(model_type or "").strip()
    return MODEL_ALIASES.get(text, text if text in MODEL_ENDPOINTS else MODEL_OPTIONS[0])


def _resolve_api_key(llm_config=None) -> str:
    config = _unpack(llm_config)
    if isinstance(config, dict):
        api_key = (config.get("apikey") or config.get("api_key") or "").strip()
        if api_key:
            return api_key
    return get_runninghub_openapi_key()


def _normalize_api_base_url(api_base_url: str) -> str:
    value = str(api_base_url or "").strip().rstrip("/")
    aliases = {
        "cn": RH_API_BASE_URL_OPTIONS[0],
        "https://www.runninghub.cn": RH_API_BASE_URL_OPTIONS[0],
        "ai": RH_API_BASE_URL_OPTIONS[1],
        "https://www.runninghub.ai": RH_API_BASE_URL_OPTIONS[1],
    }
    normalized = aliases.get(value.lower(), value)
    return normalized if normalized in RH_API_BASE_URL_OPTIONS else RH_API_BASE_URL_OPTIONS[0]


def _model_endpoint_url(endpoint_info: Dict[str, Any], request_type: str, api_base_url: str) -> str:
    configured_url = str(endpoint_info[request_type])
    endpoint_path = configured_url.split("/openapi/v2/", 1)[-1].lstrip("/")
    return f"{api_base_url.rstrip('/')}/{endpoint_path}"


def _response_error_text(response, limit: int = 1000) -> str:
    try:
        text = response.text or ""
    except Exception:
        text = ""
    return text.replace("\n", " ").replace("\r", " ").strip()[:limit]


def _is_retryable_error(exc: Any) -> bool:
    text = str(exc or "").lower()
    markers = (
        "timeout",
        "too many requests",
        "rate limit",
        "temporarily",
        "excessive system load",
        "http 429",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
    )
    return any(marker in text for marker in markers)


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _collect_prompts(value) -> List[str]:
    if value is None:
        return [""]
    if isinstance(value, (list, tuple)):
        prompts = []
        for item in value:
            prompts.extend(_collect_prompts(item))
        return [prompt for prompt in prompts if prompt is not None]

    text = str(value or "").strip()
    if not text:
        return [""]
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            prompts = [str(item).strip() for item in parsed if str(item).strip()]
            return prompts or [text]
    except Exception:
        pass
    if "\n---\n" in text or "\n\n---\n\n" in text:
        pieces = re.split(r"\n\s*---\s*\n", text)
        prompts = [piece.strip() for piece in pieces if piece.strip()]
        return prompts or [text]
    return [text]


def _tensor_to_png_bytes(image, index: int = 0) -> bytes:
    tensor = image[index] if hasattr(image, "shape") and len(image.shape) == 4 else image
    if hasattr(tensor, "detach"):
        tensor = tensor.detach().cpu().numpy()
    array = np.asarray(tensor)
    array = np.clip(array * 255.0, 0, 255).astype(np.uint8)
    if array.ndim == 2:
        pil_image = Image.fromarray(array, mode="L").convert("RGBA")
    elif array.shape[-1] == 4:
        pil_image = Image.fromarray(array, mode="RGBA")
    else:
        pil_image = Image.fromarray(array[..., :3], mode="RGB").convert("RGBA")

    buffer = io.BytesIO()
    pil_image.save(buffer, format="PNG")
    return buffer.getvalue()


def _iter_image_batches(image):
    if image is None:
        return
    if isinstance(image, (list, tuple)):
        for item in image:
            yield from _iter_image_batches(item)
        return
    try:
        batch_size = int(image.shape[0]) if hasattr(image, "shape") and len(image.shape) == 4 else 1
    except Exception:
        batch_size = 1
    for index in range(batch_size):
        yield image, index


def _collect_reference_images(*images) -> List[bytes]:
    result = []
    for image in images:
        for tensor, index in _iter_image_batches(image):
            if len(result) >= MAX_REFERENCE_IMAGES:
                return result
            result.append(_tensor_to_png_bytes(tensor, index))
    return result


def _auth_headers(api_key: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _extract_urls(value: Any) -> List[str]:
    urls = []

    def visit(item):
        if item is None:
            return
        if isinstance(item, str):
            for url in re.findall(r"https?://[^\s\"'<>]+", item):
                cleaned = url.rstrip("),，。；;")
                if cleaned and cleaned not in urls:
                    urls.append(cleaned)
            return
        if isinstance(item, dict):
            for key in ("url", "imageUrl", "image_url", "download_url", "downloadUrl", "fileUrl"):
                value = item.get(key)
                if isinstance(value, str):
                    visit(value)
            for value in item.values():
                if isinstance(value, (dict, list, tuple, str)):
                    visit(value)
            return
        if isinstance(item, (list, tuple)):
            for value in item:
                visit(value)

    visit(value)
    return urls


def _extract_task_id(data: Any) -> str:
    if isinstance(data, dict):
        for key in ("taskId", "task_id", "id"):
            value = data.get(key)
            if isinstance(value, (str, int)) and str(value).strip():
                return str(value).strip()
        nested = data.get("data")
        if nested is not data:
            task_id = _extract_task_id(nested)
            if task_id:
                return task_id
        for value in data.values():
            if isinstance(value, (dict, list)):
                task_id = _extract_task_id(value)
                if task_id:
                    return task_id
    elif isinstance(data, list):
        for item in data:
            task_id = _extract_task_id(item)
            if task_id:
                return task_id
    return ""


def _upload_image(
    api_key: str,
    image_bytes: bytes,
    index: int,
    api_base_url: str = RH_API_BASE_URL,
) -> str:
    _raise_if_cancelled()
    files = {
        "file": (f"rh_gpt_image_2_ref_{index:02d}.png", image_bytes, "image/png"),
    }
    response = requests.post(
        f"{api_base_url.rstrip('/')}/media/upload/binary",
        headers=_auth_headers(api_key),
        files=files,
        timeout=(30, 180),
        verify=False,
    )
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        raise RuntimeError(f"RunningHub 参考图上传失败 HTTP {response.status_code}: {_response_error_text(response)}") from exc

    data = response.json()
    if isinstance(data, dict) and data.get("code") not in (None, 0):
        message = data.get("msg") or data.get("message") or "未知错误"
        raise RuntimeError(f"RunningHub 参考图上传失败：{message} (code={data.get('code')})")

    urls = _extract_urls(data)
    if not urls:
        raise RuntimeError(f"RunningHub 参考图上传失败，未解析到 download_url: {str(data)[:500]}")
    return urls[0]


def _upload_reference_images(
    api_key: str,
    image_bytes_list: List[bytes],
    api_base_url: str = RH_API_BASE_URL,
) -> List[str]:
    urls = []
    for index, image_bytes in enumerate(image_bytes_list, start=1):
        url = _upload_image(api_key, image_bytes, index, api_base_url)
        urls.append(url)
        print(f"[RH GPT-Image-2 Alpha] 上传参考图 {index}/{len(image_bytes_list)}: ...{url[-24:]}")
    return urls


def _build_payload(
    prompt: str,
    aspect_ratio: str,
    resolution: str,
    quality: str,
    image_urls: List[str],
    endpoint_info: Dict[str, Any],
    seed: int,
) -> Dict[str, Any]:
    payload = {
        "prompt": str(prompt or ""),
        "aspectRatio": str(aspect_ratio or "1:1"),
        "resolution": str(resolution or "1K").lower(),
        "background": TRANSPARENT_BACKGROUND_VALUE,
        "transparentBackground": True,
    }
    if image_urls:
        payload["imageUrls"] = image_urls
    if endpoint_info.get("quality"):
        payload["quality"] = "medium" if not quality or quality == "auto" else quality
    if seed > 0:
        payload["seed"] = seed % 2147483647
    return payload


def _post_json(api_key: str, url: str, payload: Dict[str, Any], timeout=(30, 180)) -> Dict[str, Any]:
    response = requests.post(url, headers=make_headers(api_key), json=payload, timeout=timeout, verify=False)
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        raise RuntimeError(f"HTTP {response.status_code}: {_response_error_text(response)}") from exc
    data = response.json()
    return data if isinstance(data, dict) else {"data": data}


def _submit_generation(api_key: str, endpoint_url: str, payload: Dict[str, Any]) -> str:
    _raise_if_cancelled()
    print(
        "[RH GPT-Image-2 Alpha] 提交: "
        f"endpoint={endpoint_url.rsplit('/', 1)[-1]} images={len(payload.get('imageUrls', []))}"
    )

    candidates = [("full", payload)]
    if "seed" in payload:
        candidates.append(("without_seed", {key: value for key, value in payload.items() if key != "seed"}))
    if "transparentBackground" in payload:
        candidates.append(("without_transparentBackground", {
            key: value for key, value in payload.items()
            if key not in {"transparentBackground", "seed"}
        }))
    if "background" in payload or "transparentBackground" in payload:
        candidates.append(("without_background_fields", {
            key: value for key, value in payload.items()
            if key not in {"background", "transparentBackground", "seed"}
        }))

    last_exc = None
    data = None
    seen = set()
    for label, candidate in candidates:
        key = json.dumps(candidate, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        try:
            data = _post_json(api_key, endpoint_url, candidate, timeout=(30, 240))
            if label != "full":
                print(f"[RH GPT-Image-2 Alpha] 兼容提交成功: {label}")
            break
        except RuntimeError as exc:
            last_exc = exc
            if label == "full":
                print(f"[RH GPT-Image-2 Alpha] 完整参数提交失败，尝试兼容重试: {exc}")
            else:
                print(f"[RH GPT-Image-2 Alpha] 兼容提交失败 {label}: {exc}")
    if data is None:
        raise last_exc or RuntimeError("RunningHub 提交失败")

    task_id = _extract_task_id(data)
    if not task_id:
        failure_text = _find_failure_text(data)
        detail = f"; detail={failure_text}" if failure_text else ""
        raise RuntimeError(f"RunningHub 提交未返回 taskId{detail}: {str(data)[:500]}")
    print(f"[RH GPT-Image-2 Alpha] taskId=...{task_id[-8:]}")
    return task_id


def _submit_with_retry(api_key: str, endpoint_url: str, payload: Dict[str, Any]) -> str:
    last_exc = None
    for attempt in range(1, SUBMIT_RETRY_ATTEMPTS + 1):
        try:
            return _submit_generation(api_key, endpoint_url, payload)
        except Exception as exc:
            last_exc = exc
            if attempt >= SUBMIT_RETRY_ATTEMPTS or not _is_retryable_error(exc):
                raise
            wait_seconds = 4 * attempt
            print(f"[RH GPT-Image-2 Alpha] 提交临时失败，{wait_seconds}s 后重试 ({attempt}/{SUBMIT_RETRY_ATTEMPTS}): {exc}")
            _sleep_interruptible(wait_seconds)
    raise last_exc


def _query_task(
    api_key: str,
    task_id: str,
    api_base_url: str = RH_API_BASE_URL,
) -> Dict[str, Any]:
    query_url = f"{api_base_url.rstrip('/')}/query"
    return _post_json(api_key, query_url, {"taskId": task_id}, timeout=(30, 120))


def _status_from_query(data: Dict[str, Any]) -> str:
    candidates = [data]
    nested = data.get("data") if isinstance(data, dict) else None
    if isinstance(nested, dict):
        candidates.insert(0, nested)
    for item in candidates:
        status = item.get("status") if isinstance(item, dict) else ""
        if status:
            return str(status).upper()
    return ""


def _results_from_query(data: Dict[str, Any]) -> Any:
    if not isinstance(data, dict):
        return None
    nested = data.get("data")
    if isinstance(nested, dict):
        for key in ("results", "result", "outputs", "output"):
            if key in nested:
                return nested[key]
    for key in ("results", "result", "outputs", "output"):
        if key in data:
            return data[key]
    return nested


def _find_failure_text(value: Any, depth: int = 0) -> str:
    if depth > 5 or value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        if text and any(token in text.lower() for token in ("error", "fail", "失败", "异常", "拒绝", "blocked")):
            return text[:1200]
        return ""
    if isinstance(value, dict):
        priority_keys = (
            "error",
            "message",
            "msg",
            "reason",
            "failReason",
            "failureReason",
            "statusMessage",
            "errmsg",
        )
        for key in priority_keys:
            text = _find_failure_text(value.get(key), depth + 1)
            if text:
                return text
        for nested in value.values():
            text = _find_failure_text(nested, depth + 1)
            if text:
                return text
    if isinstance(value, list):
        for item in value:
            text = _find_failure_text(item, depth + 1)
            if text:
                return text
    return ""


def _poll_task(
    api_key: str,
    task_id: str,
    api_base_url: str = RH_API_BASE_URL,
) -> List[str]:
    deadline = time.time() + POLL_TIMEOUT_SECONDS
    consecutive_errors = 0
    while time.time() < deadline:
        _raise_if_cancelled()
        try:
            data = _query_task(api_key, task_id, api_base_url)
            consecutive_errors = 0
        except Exception as exc:
            consecutive_errors += 1
            print(f"[RH GPT-Image-2 Alpha] 轮询异常 ({consecutive_errors}/12): ...{task_id[-8:]} {exc}")
            if consecutive_errors >= 12:
                raise
            _sleep_interruptible(POLL_INTERVAL_SECONDS)
            continue

        status = _status_from_query(data)
        results = _results_from_query(data)
        urls = _extract_urls(results)
        if urls and (not status or status in {"SUCCESS", "SUCCEEDED", "COMPLETED", "DONE"}):
            print(f"[RH GPT-Image-2 Alpha] 完成: ...{task_id[-8:]} urls={len(urls)}")
            return urls
        if status in {"SUCCESS", "SUCCEEDED", "COMPLETED", "DONE"}:
            urls = _extract_urls(data)
            if urls:
                print(f"[RH GPT-Image-2 Alpha] 完成: ...{task_id[-8:]} urls={len(urls)}")
                return urls
            raise RuntimeError(f"任务完成但未解析到图片 URL: {str(data)[:500]}")
        if status in {"FAILED", "FAILURE", "ERROR", "CANCELED", "CANCELLED"}:
            failure_text = _find_failure_text(data)
            detail = f"; detail={failure_text}" if failure_text else ""
            raise RuntimeError(f"RunningHub 任务失败 status={status}{detail}: {str(data)[:800]}")

        _sleep_interruptible(POLL_INTERVAL_SECONDS)

    raise TimeoutError(f"RunningHub 任务轮询超时: ...{task_id[-8:]}")


def _is_changed(**kwargs):
    payload = json.dumps({key: str(value) for key, value in kwargs.items()}, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


class RunningHubGptImage2Alpha_TBatch:
    FUNCTION = "process_batch"
    CATEGORY = CATEGORY
    INPUT_IS_LIST = True
    OUTPUT_IS_LIST = (False, False)
    DESCRIPTION = "RunningHub GPT-Image-2 URL-only 节点。透明素材默认使用已验证可返回真 Alpha 的低价通道。"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_type": (MODEL_OPTIONS, {"default": MODEL_OPTIONS[0]}),
                "quality": (QUALITIES, {"default": "auto"}),
                "resolution": (RESOLUTIONS, {"default": "1K"}),
                "aspect_ratio": (ASPECT_RATIOS, {"default": "1:1"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 2147483647}),
            },
            "optional": {
                "api_base_url": (
                    RH_API_BASE_URL_OPTIONS,
                    {"default": RH_API_BASE_URL_OPTIONS[0]},
                ),
                "prompts_list": ("STRING", {"forceInput": True}),
                "llm_config": ("SYNVOW_LLM_CONFIG",),
                "image1": ("IMAGE",),
                "image2": ("IMAGE",),
                "image3": ("IMAGE",),
                "image4": ("IMAGE",),
                "image5": ("IMAGE",),
                "image6": ("IMAGE",),
                "image7": ("IMAGE",),
                "image8": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("image_urls", "status")
    IS_CHANGED = staticmethod(_is_changed)

    def process_batch(
        self,
        model_type=None,
        quality=None,
        resolution=None,
        aspect_ratio=None,
        seed=None,
        api_base_url=RH_API_BASE_URL_OPTIONS[0],
        prompts_list=None,
        llm_config=None,
        image1=None,
        image2=None,
        image3=None,
        image4=None,
        image5=None,
        image6=None,
        image7=None,
        image8=None,
    ):
        _ALPHA_CANCEL_EVENT.clear()
        model = _normalize_model_type(_unpack(model_type))
        endpoint_info = MODEL_ENDPOINTS[model]
        quality = str(_unpack(quality) or "auto")
        resolution = str(_unpack(resolution) or "1K")
        aspect_ratio = str(_unpack(aspect_ratio) or "1:1")
        seed_value = _safe_int(_unpack(seed), 0)
        api_base_url = _normalize_api_base_url(_unpack(api_base_url))
        llm_config = _unpack(llm_config)
        api_key = _resolve_api_key(llm_config)
        if not api_key:
            raise RuntimeError("缺少 RunningHub API Key：请设置 RH_API_KEY/RUNNINGHUB_API_KEY，或连接 SynVow LLM Settings。")

        reference_bytes = _collect_reference_images(
            _unpack(image1),
            _unpack(image2),
            _unpack(image3),
            _unpack(image4),
            _unpack(image5),
            _unpack(image6),
            _unpack(image7),
            _unpack(image8),
        )
        reference_urls = (
            _upload_reference_images(api_key, reference_bytes, api_base_url)
            if reference_bytes
            else []
        )
        endpoint_url = _model_endpoint_url(
            endpoint_info,
            "image" if reference_urls else "text",
            api_base_url,
        )
        mode = "参考图/拆图" if reference_urls else "文生图"
        prompts = _collect_prompts(prompts_list)
        pbar = comfy.utils.ProgressBar(len(prompts))

        print(f"[RH GPT-Image-2 Alpha TBatch] {len(prompts)} 条 prompt, model={model}, mode={mode}")
        submitted = []
        for index, prompt in enumerate(prompts, start=1):
            payload = _build_payload(prompt, aspect_ratio, resolution, quality, reference_urls, endpoint_info, seed_value)
            print(
                f"[RH GPT-Image-2 Alpha] [{index}/{len(prompts)}] "
                f"prompt_chars={len(str(prompt or ''))} mode={'img2img' if reference_urls else 'text2img'}"
            )
            try:
                task_id = _submit_with_retry(api_key, endpoint_url, payload)
                submitted.append((index, task_id))
                print(f"[RH GPT-Image-2 Alpha] [{index}/{len(prompts)}] 提交成功 taskId=...{task_id[-8:]}")
            except Exception as exc:
                submitted.append((index, None))
                print(f"[RH GPT-Image-2 Alpha] [{index}/{len(prompts)}] 提交失败: {exc}")
            if index < len(prompts):
                _sleep_interruptible(1)

        image_urls = []
        failed_indexes = []
        for index, task_id in submitted:
            if not task_id:
                failed_indexes.append(index)
                pbar.update(1)
                continue
            try:
                urls = _poll_task(api_key, task_id, api_base_url)
                image_urls.extend(urls)
            except Exception as exc:
                failed_indexes.append(index)
                print(f"[RH GPT-Image-2 Alpha] [{index}/{len(prompts)}] 轮询失败: {exc}")
            finally:
                pbar.update(1)

        successful = len(image_urls)
        if successful == 0:
            raise RuntimeError(
                f"RH GPT-Image-2 Alpha 生成失败：model={model}，mode={mode}，total={len(prompts)}。"
                "请查看上方提交/轮询日志中的 HTTP 状态和服务端返回内容。"
            )

        failed_text = f"，失败序号={failed_indexes}" if failed_indexes else ""
        status = (
            f"已完成 URL {successful} 张；model={model}；mode={mode}；"
            f"api_base_url={api_base_url}；resolution={resolution}；"
            f"aspect_ratio={aspect_ratio}；quality={quality}；"
            f"background={TRANSPARENT_BACKGROUND_VALUE}(requested){failed_text}。"
            "请连接 image_urls 到 SynVow 透明PNG保存预览。"
        )
        print(f"[RH GPT-Image-2 Alpha TBatch] 完成: urls={successful}, failed={len(failed_indexes)}")
        return ("\n".join(image_urls), status)


try:
    from aiohttp import web
    import server

    @server.PromptServer.instance.routes.post("/synvow-prompt/rh-gpt-image2-alpha/cancel")
    async def _rh_gpt_image2_alpha_cancel(request):
        request_alpha_cancel()
        return web.json_response({"ok": True, "message": "RH GPT-Image-2 Alpha polling cancel requested"})
except Exception as exc:
    print(f"[RH GPT-Image-2 Alpha] 取消轮询接口注册失败: {exc}")


NODE_CLASS_MAPPINGS = {
    "RunningHubGptImage2Alpha_TBatch": RunningHubGptImage2Alpha_TBatch,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RunningHubGptImage2Alpha_TBatch": "RH GPT-Image-2 Alpha (T_batch)",
}
