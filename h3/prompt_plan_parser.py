"""Defensive parsing for structured LLM responses."""

from __future__ import annotations

import json
import re
from typing import Any, Dict

from .models import PromptPlan


def clean_llm_json(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def extract_json_object(text: str) -> Dict[str, Any]:
    cleaned = clean_llm_json(text)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        if start < 0:
            raise ValueError("LLM 未返回 JSON 对象")
        decoder = json.JSONDecoder()
        try:
            value, _ = decoder.raw_decode(cleaned[start:])
        except json.JSONDecodeError as exc:
            raise ValueError("LLM 返回的 PromptPlan JSON 无法解析") from exc
    if not isinstance(value, dict):
        raise ValueError("LLM 返回的 PromptPlan 不是对象")
    return value


def parse_prompt_plan(text: str) -> PromptPlan:
    try:
        return PromptPlan.from_dict(extract_json_object(text))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"PromptPlan 解析失败：{exc}") from exc

