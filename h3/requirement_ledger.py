"""Small deterministic requirement ledger passed to the LLM and renderers."""

from __future__ import annotations

from typing import Dict, List


def build_requirement_ledger(user_request: str, exact_dialogue: str, text_whitelist: List[str], custom_constraints: str) -> Dict[str, List[str]]:
    must_appear = [user_request.strip()] if user_request and user_request.strip() else []
    if exact_dialogue and exact_dialogue.strip():
        must_appear.append(f"Exact dialogue: {exact_dialogue.strip()}")
    if text_whitelist:
        must_appear.append("Only permitted on-screen text: " + " | ".join(text_whitelist))
    must_not_appear = [line.strip() for line in (custom_constraints or "").splitlines() if line.strip().startswith(("禁止", "不要", "不得"))]
    return {
        "must_appear": must_appear,
        "must_keep": [],
        "allowed_change": [],
        "must_not_appear": must_not_appear,
    }

