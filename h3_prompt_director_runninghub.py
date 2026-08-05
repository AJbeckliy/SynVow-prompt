"""RunningHub-backed, prompt-only MiniMax H3 multi-reference director.

The node is intentionally self-contained inside SynVow-prompt.  Images are
sent to the selected vision LLM; VIDEO and AUDIO inputs remain opaque and only
their numbered connections plus user-authored roles are disclosed to the LLM.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import time
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np
import requests
import urllib3
from PIL import Image

from .h3 import (
    duration_engine,
    media_role_templates,
    prompt_loader,
    prompt_plan_parser,
    prompt_renderer,
    requirement_ledger,
    task_router,
    validators,
)
from .h3.models import H3ImageReference, PromptPlan, ValidationResult
from .utils import (
    default_runninghub_model,
    fetch_runninghub_models,
    get_runninghub_api_key,
    make_headers,
    parse_chat_response,
)


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

RUNNINGHUB_LLM_DOMAIN_OPTIONS = [
    "自动（优先 .ai，失败回退 .cn）",
    "RunningHub .ai",
    "RunningHub .cn",
]
RUNNINGHUB_LLM_ENDPOINTS = {
    "RunningHub .ai": "https://llm.runninghub.ai/v1/chat/completions",
    "RunningHub .cn": "https://llm.runninghub.cn/v1/chat/completions",
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


def _image_cache_fingerprint(value: Any) -> Any:
    """Hash image pixels because image pixels are part of the LLM request."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [_image_cache_fingerprint(item) for item in value]
    try:
        tensor = value.detach().cpu() if hasattr(value, "detach") else value
        array = np.ascontiguousarray(tensor.numpy() if hasattr(tensor, "numpy") else np.asarray(tensor))
        digest = hashlib.sha256()
        digest.update(str(array.dtype).encode("utf-8"))
        digest.update(str(tuple(array.shape)).encode("utf-8"))
        digest.update(array.tobytes())
        return {"shape": list(array.shape), "dtype": str(array.dtype), "sha256": digest.hexdigest()}
    except Exception:
        return {"unhashable_image": type(value).__name__, "force_reexecute": time.time_ns()}


def _director_input_hash(inputs: Dict[str, Any]) -> str:
    cache_inputs: Dict[str, Any] = {}
    for key, value in sorted(inputs.items()):
        if key.startswith("图片_"):
            cache_inputs[key] = _image_cache_fingerprint(value)
        elif key.startswith("视频_") or key.startswith("音频_"):
            # Do not inspect opaque media payloads; only connection state counts.
            cache_inputs[key] = {"connected": value is not None}
        else:
            cache_inputs[key] = _json_safe(value)
    raw = json.dumps(cache_inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _tensor_to_data_urls(value: Any) -> List[str]:
    if value is None:
        return []
    tensor = value.detach().cpu() if hasattr(value, "detach") else value
    array = np.asarray(tensor.numpy() if hasattr(tensor, "numpy") else tensor)
    if array.ndim == 3:
        frames = [array]
    elif array.ndim == 4:
        frames = [array[index] for index in range(array.shape[0])]
    else:
        raise ValueError(f"图片输入维度无效：{tuple(array.shape)}")

    urls: List[str] = []
    for frame in frames:
        if frame.ndim == 2:
            image_array = np.clip(frame, 0, 255).astype(np.uint8)
            image = Image.fromarray(image_array, mode="L").convert("RGB")
        else:
            image_array = frame[..., :3]
            if np.issubdtype(image_array.dtype, np.floating):
                image_array = np.clip(image_array * 255.0, 0, 255).astype(np.uint8)
            else:
                image_array = np.clip(image_array, 0, 255).astype(np.uint8)
            image = Image.fromarray(image_array, mode="RGB")
        if max(image.size) > 1280:
            image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        urls.append(f"data:image/jpeg;base64,{encoded}")
    return urls


def _split_whitelist(value: str) -> List[str]:
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def _empty_manifest() -> Dict[str, object]:
    return {
        "videos": [],
        "audios": [],
        "connected_video_indices": [],
        "connected_audio_indices": [],
        "reference_priority": "图片身份优先",
        "strict_unmentioned_keep": True,
        "media_analyzed": False,
        "media_sent_to_llm": False,
    }


def _error_result(message: str) -> Tuple[str, str, str, str, str, str]:
    result = ValidationResult()
    result.add_error("director", message)
    result.finalize()
    return "", "", "", media_role_templates.manifest_json(_empty_manifest()), _json(result.to_dict()), _json({"error": message})


def _unpack_config(value: Any) -> Dict[str, Any]:
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    return value if isinstance(value, dict) else {}


def _resolve_chat_targets(model: str, domain: str, llm_config: Any) -> Tuple[List[str], str, str, str]:
    config = _unpack_config(llm_config)
    configured_url = str(config.get("base_url") or config.get("api_url") or "").strip()
    configured_key = str(config.get("apikey") or config.get("api_key") or "").strip()
    configured_model = str(config.get("model_name") or config.get("models_name") or "").strip()
    api_key = configured_key or get_runninghub_api_key()
    resolved_model = configured_model or str(model or "").strip()
    if not api_key:
        raise RuntimeError("缺少 RunningHub LLM API Key：请设置 RUNNINGHUB_LLM_API_KEY/RH_LLM_API_KEY，或连接 SynVow LLM Settings。")
    if not resolved_model:
        raise RuntimeError("缺少 LLM 模型。")
    if configured_url:
        return [configured_url.rstrip("/")], api_key, resolved_model, "SynVow LLM Settings"
    if domain == "RunningHub .ai":
        targets = [RUNNINGHUB_LLM_ENDPOINTS["RunningHub .ai"]]
    elif domain == "RunningHub .cn":
        targets = [RUNNINGHUB_LLM_ENDPOINTS["RunningHub .cn"]]
    else:
        targets = [RUNNINGHUB_LLM_ENDPOINTS["RunningHub .ai"], RUNNINGHUB_LLM_ENDPOINTS["RunningHub .cn"]]
    return targets, api_key, resolved_model, domain


def _chat_completion(
    model: str,
    system_prompt: str,
    user_prompt: str,
    image_urls: Sequence[str],
    seed: int,
    domain: str,
    llm_config: Any,
    *,
    temperature: float,
) -> Tuple[str, str]:
    targets, api_key, resolved_model, route_label = _resolve_chat_targets(model, domain, llm_config)
    user_content: Any = user_prompt
    if image_urls:
        user_content = [{"type": "text", "text": user_prompt}]
        for image_url in image_urls:
            user_content.append({"type": "image_url", "image_url": {"url": image_url}})
    payload = {
        "model": resolved_model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 4096,
        "temperature": float(temperature),
    }
    if int(seed or 0) > 0:
        payload["seed"] = int(seed) % 2147483647

    last_error: Exception | None = None
    for target in targets:
        try:
            response = requests.post(
                target,
                headers=make_headers(api_key),
                json=payload,
                timeout=(30, 180),
                verify=False,
            )
            if response.status_code != 200:
                raise RuntimeError(f"RunningHub LLM HTTP {response.status_code}: {response.text[:1000]}")
            content = parse_chat_response(response.json()) or ""
            if not content.strip():
                raise RuntimeError("RunningHub LLM 未返回有效文本。")
            return content.strip(), target if route_label != "SynVow LLM Settings" else route_label
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"RunningHub LLM 请求失败：{last_error}")


class RunningHubH3MultiReferencePromptDirector:
    """Create and validate one MiniMax H3 prompt using a RunningHub LLM."""

    @classmethod
    def INPUT_TYPES(cls):
        models = fetch_runninghub_models()
        default_model = default_runninghub_model(models)
        optional: Dict[str, tuple] = {"llm_config": ("SYNVOW_LLM_CONFIG",)}
        for index in range(1, 10):
            optional[f"图片_{index}"] = ("IMAGE",)
        for index in range(1, 4):
            optional[f"视频_{index}"] = ("VIDEO",)
        for index in range(1, 4):
            optional[f"音频_{index}"] = ("AUDIO",)
        optional.update(
            {
                "图片职责说明": ("STRING", {"multiline": True, "default": ""}),
                "视频职责说明": ("STRING", {"multiline": True, "default": ""}),
                "音频职责说明": ("STRING", {"multiline": True, "default": ""}),
                "精确中文对白": ("STRING", {"multiline": True, "default": ""}),
                "画面文字白名单": ("STRING", {"multiline": True, "default": ""}),
                "其他创作约束": ("STRING", {"multiline": True, "default": ""}),
            }
        )
        return {
            "required": {
                "模型": (models, {"default": default_model}),
                "RunningHub LLM 域名": (RUNNINGHUB_LLM_DOMAIN_OPTIONS, {"default": RUNNINGHUB_LLM_DOMAIN_OPTIONS[0]}),
                "创作需求": ("STRING", {"multiline": True, "default": "一位成年人舞者在雨后的霓虹街头完成一段有力量感的舞蹈。"}),
                "任务模式": (task_router.TASK_MODE_OPTIONS, {"default": "自动判断"}),
                "内容类型": (task_router.CONTENT_MODE_OPTIONS, {"default": "自动判断"}),
                "时长（秒）": ("INT", {"default": 10, "min": 4, "max": 15, "step": 1}),
                "画幅比例": (task_router.ASPECT_RATIO_OPTIONS, {"default": "16:9"}),
                "运动强度": (task_router.MOTION_OPTIONS, {"default": "标准"}),
                "镜头结构": (task_router.SHOT_OPTIONS, {"default": "自动判断"}),
                "输出格式": (task_router.OUTPUT_FORMAT_OPTIONS, {"default": "官方英文结构化+中文预览"}),
                "参考优先级": (media_role_templates.REFERENCE_PRIORITY_OPTIONS, {"default": "图片身份优先"}),
                "自定义优先级规则": ("STRING", {"multiline": False, "default": ""}),
                "未声明内容保持": ("BOOLEAN", {"default": True}),
                "严格校验": ("BOOLEAN", {"default": True}),
                "随机种子": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 0xFFFFFFFFFFFFFFFF,
                        "control_after_generate": True,
                        "tooltip": "固定输入与固定种子会复用结果；改变输入或种子才会重新请求 LLM。",
                    },
                ),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("H3 英文提示词", "中文导演预览", "提示词方案 JSON", "媒体连接清单 JSON", "校验报告", "调试信息")
    FUNCTION = "generate"
    CATEGORY = "SynVow-prompt/H3 视频提示词"
    DESCRIPTION = "单节点 H3 视频提示词导演。图片发送给 RunningHub LLM；视频和音频只使用编号与职责文本。"

    @classmethod
    def IS_CHANGED(cls, **inputs: Any) -> str:
        return _director_input_hash(inputs)

    @staticmethod
    def _connected_slots(kwargs: Dict[str, Any], prefix: str, maximum: int) -> List[Tuple[int, Any]]:
        return [(index, kwargs[f"{prefix}_{index}"]) for index in range(1, maximum + 1) if kwargs.get(f"{prefix}_{index}") is not None]

    @staticmethod
    def _slot_indices(slots: Sequence[Tuple[int, Any]]) -> List[int]:
        return [index for index, _ in slots]

    @staticmethod
    def _upload_images(image_slots: Sequence[Tuple[int, Any]]) -> List[str]:
        urls: List[str] = []
        for index, image in image_slots:
            image_urls = _tensor_to_data_urls(image)
            if len(image_urls) != 1:
                raise ValueError(f"图片_{index} 必须只包含一张图片；请将批量图片拆分到图片_1 至图片_9 插口。")
            urls.extend(image_urls)
        if len(urls) > 9:
            raise ValueError("连接图片总数不能超过 9 张。")
        return urls

    @staticmethod
    def _build_user_prompt(
        user_request: str,
        task_mode: str,
        content_mode: str,
        duration_seconds: int,
        aspect_ratio: str,
        motion_intensity: str,
        shot_structure: str,
        image_indices: Sequence[int],
        image_roles: str,
        media_manifest: Dict[str, object],
        exact_dialogue: str,
        text_whitelist: List[str],
        custom_constraints: str,
    ) -> str:
        ledger = requirement_ledger.build_requirement_ledger(user_request, exact_dialogue, text_whitelist, custom_constraints)
        budget = duration_engine.duration_budget(content_mode, duration_seconds)
        image_ids = [f"image_{index}" for index in image_indices]
        media_inventory = {
            "connected_image_ids": image_ids,
            "connected_video_ids": [f"video_{index}" for index in media_manifest["connected_video_indices"]],
            "connected_audio_ids": [f"audio_{index}" for index in media_manifest["connected_audio_indices"]],
            "user_declared_video_roles": media_manifest["videos"],
            "user_declared_audio_roles": media_manifest["audios"],
            "reference_priority": media_manifest["reference_priority"],
            "video_audio_policy": "Video/audio payloads are unavailable to you. Do not claim to see, hear, transcribe, summarize, or infer their contents. Use only the numbered connections and user-declared roles.",
        }
        return "\n".join(
            [
                "Create one PromptPlan JSON using the required schema.",
                f"User request (Chinese): {user_request.strip()}",
                f"Locked task_mode: {task_mode}",
                f"Locked content_mode: {content_mode}",
                f"Locked duration_seconds: {duration_seconds}",
                f"Locked aspect_ratio: {aspect_ratio}",
                f"Motion intensity: {motion_intensity}; shot structure: {shot_structure}",
                f"Connected image ids; the supplied image payload order follows this exact list: {_json(image_ids)}.",
                "User-specified image roles (take precedence when present):\n" + (image_roles.strip() or "None."),
                "Text-only reference inventory. This is metadata, not media analysis:\n" + _json(media_inventory),
                "Exact Chinese dialogue; preserve byte-for-byte in exact_dialogue:\n" + (exact_dialogue.strip() or "None."),
                "On-screen text whitelist; preserve each item exactly:\n" + (_json(text_whitelist) if text_whitelist else "[]"),
                "Custom constraints:\n" + (custom_constraints.strip() or "None."),
                "Requirement ledger:\n" + _json(ledger),
                "Duration pacing budget:\n" + _json(budget),
                "Return JSON only.",
            ]
        )

    @staticmethod
    def _apply_locked_ui_values(
        plan: PromptPlan,
        *,
        task_mode: str,
        content_mode: str,
        duration_seconds: int,
        aspect_ratio: str,
        user_request: str,
        exact_dialogue: str,
        whitelist: List[str],
        custom_constraints: str,
        image_indices: Sequence[int],
    ) -> PromptPlan:
        plan.task_mode = task_mode
        plan.content_mode = content_mode
        plan.duration_seconds = int(duration_seconds)
        plan.aspect_ratio = aspect_ratio
        plan.exact_dialogue = exact_dialogue
        plan.text_whitelist = whitelist
        if not plan.requirements.get("must_appear"):
            plan.requirements = requirement_ledger.build_requirement_ledger(user_request, exact_dialogue, whitelist, custom_constraints)
        if not plan.image_references and image_indices:
            plan.image_references = [H3ImageReference(id=f"image_{index}", roles=["visual reference"]) for index in image_indices]
        return plan

    @staticmethod
    def _invalid_output(
        validation: ValidationResult,
        manifest: Dict[str, object],
        debug: Dict[str, object],
        plan: PromptPlan | None = None,
    ) -> Tuple[str, str, str, str, str, str]:
        plan_json = _json(plan.to_dict()) if plan else ""
        return "", "", plan_json, media_role_templates.manifest_json(manifest), _json(validation.to_dict()), _json(debug)

    def generate(self, **inputs: Any) -> Tuple[str, str, str, str, str, str]:
        model = str(inputs.get("模型") or "")
        domain = str(inputs.get("RunningHub LLM 域名") or RUNNINGHUB_LLM_DOMAIN_OPTIONS[0])
        user_request = str(inputs.get("创作需求") or "")
        requested_task = str(inputs.get("任务模式") or "自动判断")
        requested_content = str(inputs.get("内容类型") or "自动判断")
        duration_seconds = int(inputs.get("时长（秒）") or 10)
        aspect_ratio = str(inputs.get("画幅比例") or "16:9")
        motion_intensity = str(inputs.get("运动强度") or "标准")
        shot_structure = str(inputs.get("镜头结构") or "自动判断")
        output_format = str(inputs.get("输出格式") or "官方英文结构化+中文预览")
        reference_priority = str(inputs.get("参考优先级") or "图片身份优先")
        custom_priority_rule = str(inputs.get("自定义优先级规则") or "")
        strict_unmentioned_keep = bool(inputs.get("未声明内容保持", True))
        strict_mode = bool(inputs.get("严格校验", True))
        seed = int(inputs.get("随机种子") or 0)
        if not user_request.strip():
            return _error_result("请填写创作需求。")

        image_slots = self._connected_slots(inputs, "图片", 9)
        video_slots = self._connected_slots(inputs, "视频", 3)
        audio_slots = self._connected_slots(inputs, "音频", 3)
        image_indices = self._slot_indices(image_slots)
        video_indices = self._slot_indices(video_slots)
        audio_indices = self._slot_indices(audio_slots)
        task_mode, routing_warnings = task_router.normalize_task_mode(requested_task, len(image_slots), len(video_slots), len(audio_slots))
        content_mode = task_router.normalize_content_mode(requested_content, user_request)
        manifest, media_validation = media_role_templates.build_media_manifest(
            len(video_slots),
            str(inputs.get("视频职责说明") or ""),
            len(audio_slots),
            str(inputs.get("音频职责说明") or ""),
            reference_priority,
            custom_priority_rule,
            strict_unmentioned_keep,
            video_indices=video_indices,
            audio_indices=audio_indices,
        )
        input_validation = validators.validate_media_contract(
            image_count=len(image_slots),
            video_count=len(video_slots),
            audio_count=len(audio_slots),
            task_mode=task_mode,
        )
        validation = validators.merge_results(input_validation, media_validation)
        for warning in routing_warnings:
            validation.add_warning("task_route", warning)
        validation.finalize()
        debug: Dict[str, object] = {
            "model": model,
            "domain": domain,
            "connected_image_indices": image_indices,
            "connected_video_indices": video_indices,
            "connected_audio_indices": audio_indices,
            "llm_media": "text_and_images_only; video_audio_connection_metadata_only",
            "video_audio_payload_accessed": False,
            "seed": seed,
        }
        if validation.errors:
            return self._invalid_output(validation, manifest, debug)

        exact_dialogue = str(inputs.get("精确中文对白") or "").strip()
        whitelist = _split_whitelist(str(inputs.get("画面文字白名单") or ""))
        image_roles = str(inputs.get("图片职责说明") or "")
        custom_constraints = str(inputs.get("其他创作约束") or "")
        llm_config = inputs.get("llm_config")
        try:
            image_urls = self._upload_images(image_slots)
            system_prompt = prompt_loader.load_director_system_prompt(task_mode, content_mode)
            user_prompt = self._build_user_prompt(
                user_request,
                task_mode,
                content_mode,
                duration_seconds,
                aspect_ratio,
                motion_intensity,
                shot_structure,
                image_indices,
                image_roles,
                manifest,
                exact_dialogue,
                whitelist,
                custom_constraints,
            )
            raw_plan, route = _chat_completion(model, system_prompt, user_prompt, image_urls, seed, domain, llm_config, temperature=0.25)
            debug["llm_endpoint"] = route
        except Exception as exc:
            return _error_result(str(exc))

        try:
            plan = prompt_plan_parser.parse_prompt_plan(raw_plan)
            debug["format_repair_attempted"] = False
        except ValueError:
            try:
                repair_prompt = "\n".join(
                    [
                        "The previous response was not valid PromptPlan JSON.",
                        "Return the same requested plan as one strict JSON object only. Do not add prose or Markdown.",
                        "Original request:\n" + user_prompt,
                    ]
                )
                raw_plan, route = _chat_completion(model, system_prompt, repair_prompt, image_urls, seed, domain, llm_config, temperature=0.0)
                plan = prompt_plan_parser.parse_prompt_plan(raw_plan)
                debug["llm_endpoint"] = route
                debug["format_repair_attempted"] = True
            except Exception as exc:
                return _error_result(str(exc))

        plan = self._apply_locked_ui_values(
            plan,
            task_mode=task_mode,
            content_mode=content_mode,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
            user_request=user_request,
            exact_dialogue=exact_dialogue,
            whitelist=whitelist,
            custom_constraints=custom_constraints,
            image_indices=image_indices,
        )
        plan_validation = validators.validate_prompt_plan(
            plan,
            image_count=len(image_slots),
            video_count=len(video_slots),
            audio_count=len(audio_slots),
            image_indices=image_indices,
            task_mode=task_mode,
            strict_mode=strict_mode,
        )
        validation = validators.merge_results(media_validation, plan_validation)
        for warning in routing_warnings:
            validation.add_warning("task_route", warning)
        validation.finalize()
        debug["validation_repair_attempted"] = False
        if validation.errors:
            return self._invalid_output(validation, manifest, debug, plan)

        has_reference_layout = bool(image_slots or video_slots or audio_slots)
        english = media_role_templates.render_with_media_roles(plan, manifest) if has_reference_layout else prompt_renderer.render_h3_prompt_en(plan)
        preview = prompt_renderer.render_preview_zh(plan)
        final_validation = validators.merge_results(validation, validators.validate_rendered_prompt(english, text_whitelist=whitelist))
        if strict_mode and not final_validation.is_valid:
            return self._invalid_output(final_validation, manifest, debug, plan)
        if output_format == "仅官方英文结构化":
            preview = ""
        elif output_format == "仅中文导演预览":
            english = ""
        return (
            english,
            preview,
            _json(plan.to_dict()),
            media_role_templates.manifest_json(manifest),
            _json(final_validation.to_dict()),
            _json(debug),
        )


NODE_CLASS_MAPPINGS = {"RunningHubH3MultiReferencePromptDirector": RunningHubH3MultiReferencePromptDirector}
NODE_DISPLAY_NAME_MAPPINGS = {"RunningHubH3MultiReferencePromptDirector": "SynVow H3 多参考提示词导演（RunningHub）"}
