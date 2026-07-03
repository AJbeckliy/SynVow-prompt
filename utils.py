"""synvow-prompts-rh 通用工具模块"""

import os
import time
from pathlib import Path

import requests

RUNNINGHUB_LLM_CHAT_URL = "https://llm.runninghub.cn/v1/chat/completions"
RUNNINGHUB_LLM_MODELS_URLS = (
    "https://llm.runninghub.ai/v1/models",
    "https://llm.runninghub.cn/v1/models",
)
RUNNINGHUB_LLM_MODELS_URL = RUNNINGHUB_LLM_MODELS_URLS[0]
RUNNINGHUB_DEFAULT_MODELS = [
    "google/gemini-3.1-flash-lite-preview",
    "google/gemini-3.5-flash",
    "google/gemini-3.1-pro-preview",
    "openai/gpt-5.5",
    "glm-5.2",
]
MODEL_CACHE_TTL_SECONDS = 3600
RUNNINGHUB_MODEL_CACHE = {"expires_at": 0.0, "models": None}
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


def fetch_runninghub_models(force=False):
    now = time.time()
    cached = RUNNINGHUB_MODEL_CACHE.get("models")
    if not force and cached and now < float(RUNNINGHUB_MODEL_CACHE.get("expires_at", 0)):
        return list(cached)

    last_error = None
    for models_url in RUNNINGHUB_LLM_MODELS_URLS:
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
                RUNNINGHUB_MODEL_CACHE["models"] = models
                RUNNINGHUB_MODEL_CACHE["expires_at"] = now + MODEL_CACHE_TTL_SECONDS
                return models
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        print(f"[SynVow LLM] Failed to fetch RunningHub models, using fallback: {type(last_error).__name__}")

    return list(RUNNINGHUB_FALLBACK_MODELS)


def default_runninghub_model(models):
    for model in RUNNINGHUB_DEFAULT_MODELS:
        if model in models:
            return model
    return models[0] if models else RUNNINGHUB_FALLBACK_MODELS[0]


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


def resolve_llm_config(llm_config=None, base_url="", apikey="", model_name=""):
    config = llm_config if isinstance(llm_config, dict) else {}

    if config:
        resolved_base_url = (config.get("base_url") or config.get("api_url") or base_url or "").strip()
        resolved_apikey = (config.get("apikey") or config.get("api_key") or apikey or "").strip()
        resolved_model = (config.get("model_name") or config.get("models_name") or model_name or "").strip()
        return resolved_base_url, resolved_apikey, resolved_model

    resolved_base_url = (base_url or RUNNINGHUB_LLM_CHAT_URL).strip()
    resolved_apikey = (apikey or get_runninghub_api_key()).strip()
    resolved_model = (model_name or "").strip()
    return resolved_base_url, resolved_apikey, resolved_model
