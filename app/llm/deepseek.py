"""DeepSeek 客户端。

一个 key 打通三件事：
  - 对话（deepseek-flash，支持读图）
  - 流式输出（最终回答边生成边显示）
  - 联网搜索 / 网页抓取（官方 /v1/tools/* 接口，查攻略用）
"""

from __future__ import annotations

import json
from typing import Any, Iterator

import httpx


class DeepSeekError(RuntimeError):
    pass


class DeepSeekClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-flash",
        timeout: float = 90.0,
    ) -> None:
        if not api_key:
            raise DeepSeekError("没有配置 DeepSeek API Key")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    # ---------- 基础设施 ----------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            resp = httpx.post(url, headers=self._headers(), json=payload, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise DeepSeekError(f"网络异常：{exc}") from exc
        if resp.status_code != 200:
            raise DeepSeekError(_explain(resp.status_code, resp.text))
        return resp.json()

    # ---------- 对话 ----------

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        thinking: bool = False,
        reasoning_effort: str = "high",
        max_tokens: int = 1200,
    ) -> dict[str, Any]:
        """非流式一轮，用来决定要不要搜索。"""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "thinking": {"type": "enabled" if thinking else "disabled"},
        }
        if thinking:
            payload["reasoning_effort"] = reasoning_effort
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        data = self._post("/chat/completions", payload)
        return data["choices"][0]["message"]

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        thinking: bool = False,
        reasoning_effort: str = "high",
        max_tokens: int = 1200,
    ) -> Iterator[tuple[str, Any]]:
        """流式返回 (类型, 内容)：content / reasoning 是文本，tool_calls 是整轮结束后的一次性列表。"""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "max_tokens": max_tokens,
            "thinking": {"type": "enabled" if thinking else "disabled"},
        }
        if thinking:
            payload["reasoning_effort"] = reasoning_effort
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        pending: dict[int, dict[str, Any]] = {}

        url = f"{self.base_url}/chat/completions"
        try:
            with httpx.stream(
                "POST", url, headers=self._headers(), json=payload, timeout=self.timeout
            ) as resp:
                if resp.status_code != 200:
                    resp.read()
                    raise DeepSeekError(_explain(resp.status_code, resp.text))
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    if delta.get("reasoning_content"):
                        yield "reasoning", delta["reasoning_content"]
                    if delta.get("content"):
                        yield "content", delta["content"]
                    for piece in delta.get("tool_calls") or []:
                        idx = piece.get("index", 0)
                        slot = pending.setdefault(
                            idx,
                            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                        )
                        if piece.get("id"):
                            slot["id"] = piece["id"]
                        fn = piece.get("function") or {}
                        if fn.get("name"):
                            slot["function"]["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["function"]["arguments"] += fn["arguments"]
        except httpx.HTTPError as exc:
            raise DeepSeekError(f"网络异常：{exc}") from exc

        if pending:
            yield "tool_calls", [pending[k] for k in sorted(pending)]

    # ---------- 联网工具 ----------

    def search(self, query: str, count: int = 5, need_content: bool = False) -> list[dict[str, Any]]:
        data = self._post(
            "/v1/tools/search",
            {"query": query[:128], "count": max(1, min(20, count)), "need_content": need_content},
        )
        return data.get("results", []) or []

    def fetch(self, url: str) -> dict[str, Any]:
        return self._post("/v1/tools/fetch", {"url": url})


def image_block(jpeg_bytes: bytes, detail: str = "high") -> dict[str, Any]:
    """把截图包成 DeepSeek 能吃的 image_url 内容块。"""
    import base64

    b64 = base64.b64encode(jpeg_bytes).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": detail},
    }


def _explain(status: int, body: str) -> str:
    snippet = (body or "").strip()[:300]
    if status == 401:
        return "API Key 无效或已过期（401）"
    if status == 402:
        return "账户余额不足（402）"
    if status == 429:
        return "请求太频繁，被限流了（429）"
    if status >= 500:
        return f"DeepSeek 服务端出错（{status}），稍后再试"
    return f"请求失败（{status}）：{snippet}"
