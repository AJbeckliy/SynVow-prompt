"""synvow-prompts-rh 通用工具模块"""

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Dict, List

import requests

RUNNINGHUB_LLM_CHAT_URL = "https://llm.runninghub.cn/v1/chat/completions"
RUNNINGHUB_LLM_SITE_CN = "国内站 (.cn)"
RUNNINGHUB_LLM_SITE_AI = "国际站 (.ai)"
RUNNINGHUB_LLM_SITE_OPTIONS = (RUNNINGHUB_LLM_SITE_CN, RUNNINGHUB_LLM_SITE_AI)
RUNNINGHUB_LLM_SITE_CONFIG = {
    RUNNINGHUB_LLM_SITE_CN: {
        "chat_url": "https://llm.runninghub.cn/v1/chat/completions",
        "models_url": "https://llm.runninghub.cn/v1/models",
    },
    RUNNINGHUB_LLM_SITE_AI: {
        "chat_url": "https://llm.runninghub.ai/v1/chat/completions",
        "models_url": "https://llm.runninghub.ai/v1/models",
    },
}
RUNNINGHUB_LLM_MODELS_URLS = (
    RUNNINGHUB_LLM_SITE_CONFIG[RUNNINGHUB_LLM_SITE_AI]["models_url"],
    RUNNINGHUB_LLM_SITE_CONFIG[RUNNINGHUB_LLM_SITE_CN]["models_url"],
)
RUNNINGHUB_LLM_MODELS_URL = RUNNINGHUB_LLM_MODELS_URLS[0]
RUNNINGHUB_DEFAULT_MODELS = [
    "google/gemini-3.1-flash-lite-preview",
    "google/gemini-3.5-flash",
    "google/gemini-3.1-pro-preview",
    "openai/gpt-5.5",
    "glm-5.2",
]
RUNNINGHUB_DEFAULT_MODELS_BY_SITE = {
    RUNNINGHUB_LLM_SITE_CN: [
        "deepseek/deepseek-v4-flash-vision-exp",
        "glm-5v-turbo",
        "deepseek/deepseek-v4.1-flash",
        "qwen/qwen3.7-plus",
    ],
    RUNNINGHUB_LLM_SITE_AI: [
        "google/gemini-3.5-flash",
        "google/gemini-3.1-pro-preview",
        "google/gemini-3.1-flash-lite-preview",
        "openai/gpt-5.5",
        "glm-5.2",
    ],
}
MODEL_CACHE_TTL_SECONDS = 3600
RUNNINGHUB_MODEL_CACHE: Dict[str, Dict[str, Any]] = {}
RUNNINGHUB_FALLBACK_MODELS = [
    "google/gemini-3.1-flash-lite-preview",
    "google/gemini-3.5-flash",
    "google/gemini-3.1-pro-preview",
    "openai/gpt-5.5",
    "openai/gpt-5.5-pro",
    "openai/gpt-5.4-pro",
    "glm-5.2",
    "glm-5.1",
    "glm-5-turbo",
    "qwen/qwen3.7-max",
    "deepseek/deepseek-v4-pro",
]
RUNNINGHUB_FALLBACK_MODELS_BY_SITE = {
    RUNNINGHUB_LLM_SITE_CN: [
        "qwen/qwen3.7-max",
        "glm-5.2",
        "deepseek/deepseek-v4-pro",
        "glm-5.1",
        "glm-5-turbo",
    ],
    RUNNINGHUB_LLM_SITE_AI: RUNNINGHUB_FALLBACK_MODELS,
}
RUNNINGHUB_FALLBACK_VISION_MODELS_BY_SITE = {
    RUNNINGHUB_LLM_SITE_CN: [
        "deepseek/deepseek-v4-flash-vision-exp",
        "glm-5v-turbo",
        "deepseek/deepseek-v4.1-flash",
    ],
    RUNNINGHUB_LLM_SITE_AI: [
        "google/gemini-3.5-flash",
        "deepseek/deepseek-v4-flash-vision-exp",
        "glm-5v-turbo",
    ],
}


def parse_chat_response(data):
    """解析 Gemini/OpenAI 聊天响应格式，返回文本内容。"""
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
        data = data["data"]
    if "candidates" in data:
        candidates = data["candidates"]
        if candidates and "content" in candidates[0]:
            parts = candidates[0]["content"].get("parts", [])
            texts = [p.get("text", "") for p in parts if "text" in p]
            return "".join(texts)
    if "choices" in data:
        choices = data["choices"]
        if choices:
            msg = choices[0].get("message", {})
            return msg.get("content", "")
    return ""


def make_headers(apikey):
    """构建请求头。"""
    return {
        "Authorization": f"Bearer {apikey}",
        "Content-Type": "application/json",
    }


def normalize_runninghub_llm_site(site=None) -> str:
    text = str(site or "").strip().lower()
    if text in {
        "cn",
        ".cn",
        "国内",
        "国内站",
        RUNNINGHUB_LLM_SITE_CN.lower(),
        "https://llm.runninghub.cn",
        "https://llm.runninghub.cn/v1/chat/completions",
    }:
        return RUNNINGHUB_LLM_SITE_CN
    if text in {
        "ai",
        ".ai",
        "国际",
        "国际站",
        "hk",
        RUNNINGHUB_LLM_SITE_AI.lower(),
        "https://llm.runninghub.ai",
        "https://llm.runninghub.ai/v1/chat/completions",
    }:
        return RUNNINGHUB_LLM_SITE_AI
    return RUNNINGHUB_LLM_SITE_CN


def runninghub_llm_chat_url(site=None) -> str:
    normalized = normalize_runninghub_llm_site(site)
    return RUNNINGHUB_LLM_SITE_CONFIG[normalized]["chat_url"]


def runninghub_llm_site_from_url(url) -> str:
    text = str(url or "").strip().lower()
    return RUNNINGHUB_LLM_SITE_AI if "runninghub.ai" in text else RUNNINGHUB_LLM_SITE_CN


def _site_fallback_models(site=None, require_vision=False) -> List[str]:
    if site is None:
        if require_vision:
            return list(RUNNINGHUB_FALLBACK_VISION_MODELS_BY_SITE[RUNNINGHUB_LLM_SITE_AI])
        return list(RUNNINGHUB_FALLBACK_MODELS)
    normalized = normalize_runninghub_llm_site(site)
    if require_vision:
        return list(RUNNINGHUB_FALLBACK_VISION_MODELS_BY_SITE[normalized])
    return list(RUNNINGHUB_FALLBACK_MODELS_BY_SITE[normalized])


def fetch_runninghub_models(force=False, site=None, require_vision=False):
    now = time.time()
    normalized_site = normalize_runninghub_llm_site(site) if site is not None else None
    cache_key = normalized_site or "legacy"
    cache = RUNNINGHUB_MODEL_CACHE.get(cache_key, {})
    cache_field = "vision_models" if require_vision else "models"
    cached = cache.get(cache_field)
    if not force and cached and now < float(cache.get("expires_at", 0)):
        return list(cached)

    models_urls = (
        [RUNNINGHUB_LLM_SITE_CONFIG[normalized_site]["models_url"]]
        if normalized_site
        else list(RUNNINGHUB_LLM_MODELS_URLS)
    )

    last_error = None
    for models_url in models_urls:
        try:
            response = requests.get(models_url, timeout=5)
            response.raise_for_status()
            data = response.json()
            models = [
                str(item.get("id")).strip()
                for item in data.get("data", [])
                if isinstance(item, dict) and str(item.get("id", "")).strip()
            ]
            if models:
                vision_models = []
                for item in data.get("data", []):
                    if not isinstance(item, dict):
                        continue
                    model_id = str(item.get("id", "")).strip()
                    capabilities = item.get("capabilities") if isinstance(item.get("capabilities"), dict) else {}
                    input_modalities = capabilities.get("input_modalities")
                    supports_vision = (
                        capabilities.get("vision") is True
                        or capabilities.get("multimodal") is True
                        or (isinstance(input_modalities, list) and "image" in input_modalities)
                    )
                    if model_id and supports_vision:
                        vision_models.append(model_id)
                RUNNINGHUB_MODEL_CACHE[cache_key] = {
                    "models": models,
                    "vision_models": vision_models,
                    "expires_at": now + MODEL_CACHE_TTL_SECONDS,
                }
                selected_models = vision_models if require_vision else models
                if selected_models:
                    return selected_models
                last_error = RuntimeError("model endpoint returned no vision-capable models")
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        label = normalized_site or "legacy"
        print(
            f"[SynVow LLM] Failed to fetch RunningHub models for {label}, "
            f"using fallback: {type(last_error).__name__}"
        )

    return _site_fallback_models(normalized_site, require_vision=require_vision)


def default_runninghub_model(models, site=None):
    normalized_site = normalize_runninghub_llm_site(site) if site is not None else None
    preferred = RUNNINGHUB_DEFAULT_MODELS_BY_SITE.get(
        normalized_site,
        RUNNINGHUB_DEFAULT_MODELS,
    )
    for model in preferred:
        if model in models:
            return model
    fallback = _site_fallback_models(normalized_site)
    return models[0] if models else fallback[0]


def runninghub_model_union(force=False, require_vision=False) -> List[str]:
    models = []
    for site in RUNNINGHUB_LLM_SITE_OPTIONS:
        for model in fetch_runninghub_models(
            force=force,
            site=site,
            require_vision=require_vision,
        ):
            if model not in models:
                models.append(model)
    return models or list(RUNNINGHUB_FALLBACK_MODELS)


def resolve_runninghub_site_model(site, model, force=False, require_vision=False):
    normalized_site = normalize_runninghub_llm_site(site)
    models = fetch_runninghub_models(
        force=force,
        site=normalized_site,
        require_vision=require_vision,
    )
    requested = str(model or "").strip()
    if requested in models:
        return requested, False
    return default_runninghub_model(models, site=normalized_site), bool(requested)


def _read_env_file(env_path):
    result = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value:
            result[key] = value
    return result


def get_runninghub_api_key():
    for env_name in ("RUNNINGHUB_LLM_API_KEY", "RH_LLM_API_KEY"):
        api_key = (os.environ.get(env_name) or "").strip()
        if api_key:
            return api_key

    env_path = Path(__file__).resolve().parent / "config" / ".env"
    try:
        if env_path.exists():
            env_data = _read_env_file(env_path)
            for env_name in ("RUNNINGHUB_LLM_API_KEY", "RH_LLM_API_KEY"):
                api_key = (env_data.get(env_name) or "").strip()
                if api_key:
                    return api_key
    except Exception:
        pass

    try:
        from server import PromptServer
        api_key = getattr(PromptServer.instance, "shared_api_key", None)
        if api_key and isinstance(api_key, str) and api_key.strip() and api_key != "unknown":
            return api_key.strip()
    except Exception:
        pass

    for env_name in ("RH_API_KEY", "RUNNINGHUB_API_KEY"):
        api_key = (os.environ.get(env_name) or "").strip()
        if api_key:
            return api_key

    try:
        if env_path.exists():
            env_data = _read_env_file(env_path)
            for env_name in ("RH_API_KEY", "RUNNINGHUB_API_KEY"):
                api_key = (env_data.get(env_name) or "").strip()
                if api_key:
                    return api_key
    except Exception:
        pass

    return ""


def get_runninghub_openapi_key():
    """Resolve the RunningHub OpenAPI key using the official platform priority."""
    try:
        from server import PromptServer
        api_key = getattr(PromptServer.instance, "shared_api_key", None)
        if api_key and isinstance(api_key, str) and api_key.strip() and api_key != "unknown":
            return api_key.strip()
    except Exception:
        pass

    for env_name in ("RH_API_KEY", "RUNNINGHUB_API_KEY"):
        api_key = (os.environ.get(env_name) or "").strip()
        if api_key:
            return api_key

    env_path = Path(__file__).resolve().parent / "config" / ".env"
    try:
        if env_path.exists():
            env_data = _read_env_file(env_path)
            for env_name in ("RH_API_KEY", "RUNNINGHUB_API_KEY"):
                api_key = (env_data.get(env_name) or "").strip()
                if api_key:
                    return api_key
    except Exception:
        pass

    return ""


class SynVowLLMSettings:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "base_url": ("STRING", {"default": ""}),
                "apikey": ("STRING", {"default": ""}),
                "model_name": ("STRING", {"default": ""}),
            },
        }

    RETURN_TYPES = ("SYNVOW_LLM_CONFIG",)
    RETURN_NAMES = ("llm_config",)
    FUNCTION = "get_config"
    CATEGORY = "SynVow-prompt"
    DESCRIPTION = "SynVow LLM 统一配置"

    def get_config(self, base_url, apikey, model_name):
        return ({
            "base_url": base_url,
            "apikey": apikey,
            "model_name": model_name,
        },)


def resolve_llm_config(llm_config=None, base_url="", apikey="", model_name="", site=None):
    config = llm_config if isinstance(llm_config, dict) else {}

    if config:
        resolved_base_url = (config.get("base_url") or config.get("api_url") or base_url or "").strip()
        resolved_apikey = (config.get("apikey") or config.get("api_key") or apikey or "").strip()
        resolved_model = (config.get("model_name") or config.get("models_name") or model_name or "").strip()
        return resolved_base_url, resolved_apikey, resolved_model

    resolved_base_url = (base_url or runninghub_llm_chat_url(site)).strip()
    resolved_apikey = (apikey or get_runninghub_api_key()).strip()
    resolved_model = (model_name or "").strip()
    return resolved_base_url, resolved_apikey, resolved_model


try:
    from aiohttp import web
    import server

    @server.PromptServer.instance.routes.get("/synvow-prompt/runninghub-llm-models")
    async def _runninghub_llm_models(request):
        site = normalize_runninghub_llm_site(request.query.get("site"))
        force = request.query.get("force") == "1"
        require_vision = request.query.get("vision") == "1"
        loop = asyncio.get_running_loop()
        models = await loop.run_in_executor(
            None,
            fetch_runninghub_models,
            force,
            site,
            require_vision,
        )
        return web.json_response({
            "site": site,
            "models": models,
            "default": default_runninghub_model(models, site=site),
        })
except Exception:
    pass
