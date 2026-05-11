"""synvow-prompts-rh 通用工具模块"""


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
