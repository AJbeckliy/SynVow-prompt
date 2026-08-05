"""Load only the prompt modules relevant to the current request."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


_PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts" / "h3"


def _read(name: str) -> str:
    path = _PROMPT_DIR / name
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"H3 提示词资源缺失：{name}") from exc


def load_director_system_prompt(task_mode: str, content_mode: str) -> str:
    names: Iterable[str] = ("base_zh.md", f"task_{task_mode}.md", f"content_{content_mode}.md")
    modules = []
    for name in names:
        path = _PROMPT_DIR / name
        if path.exists():
            modules.append(_read(name))
    if not modules:
        raise RuntimeError("未找到 H3 系统提示词资源")
    return "\n\n".join(modules)

