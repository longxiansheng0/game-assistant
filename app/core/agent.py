"""编排：画面 + 问题 -> 判断要不要查攻略 -> 流式回答。"""

from __future__ import annotations

import json
from typing import Any, Callable

from ..llm.deepseek import DeepSeekClient, DeepSeekError, image_block
from ..vision.capture import Capture

SYSTEM_PROMPT = """你是「小助手」，常驻在玩家桌面上，替正在打游戏的人答疑。

玩家刚截了一帧屏幕给你。你要结合画面和他的问题，给出立刻能用的答案。

规矩：
1. 他在游戏里，没耐心看长文。先给结论（一句话），需要时再补最多三条要点。
2. 游戏的具体数值、位置、机制、掉落、配装，你可能记错或过时。没把握就调用 search_web 查，查询词里带上游戏名。
3. 查不到就直说"这个我没查到确切说法"，然后给个方向，不要编。
4. 玩家的问题常常极短（"这怎么打""这啥""卡住了"），要结合截图推断他指的是什么。
5. 不要复述截图内容——他自己看得见。直接给判断。
6. 画面上那个发光的小球是助手自己的悬浮窗，忽略它。
6. 中文，口语，不要标题、不要 emoji、不要长篇大论。"""

DEFAULT_QUESTION = "看看我现在什么情况，下一步该干嘛？"

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "联网搜索游戏攻略、机制说明、道具位置等。不确定时先搜。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索词，务必带上游戏名"},
                    "count": {"type": "integer", "description": "返回条数 1-10，默认 5"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_page",
            "description": "读取指定网页的正文。搜索摘要不够详细时再用。",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "http(s) 链接"}},
                "required": ["url"],
            },
        },
    },
]


class GameAssistant:
    def __init__(
        self,
        client: DeepSeekClient,
        max_tool_rounds: int = 2,
        allow_search: bool = True,
        think: bool = False,
    ) -> None:
        self.client = client
        self.max_tool_rounds = max_tool_rounds
        self.allow_search = allow_search
        self.think = think
        self.history: list[dict[str, Any]] = []

    # ---------- 对外 ----------

    def ask(
        self,
        question: str,
        shot: Capture,
        on_status: Callable[[str], None] | None = None,
        on_delta: Callable[[str], None] | None = None,
        ocr_text: str = "",
    ) -> str:
        status = on_status or (lambda _s: None)
        delta = on_delta or (lambda _s: None)
        question = (question or "").strip() or DEFAULT_QUESTION

        messages = self._build_messages(question, shot, ocr_text)
        max_rounds = self.max_tool_rounds if self.allow_search else 0

        # 全程流式：模型一边想一边吐字，需要查资料就先吐 tool_calls，查完接着答
        for round_idx in range(max_rounds + 1):
            use_tools = round_idx < max_rounds
            if round_idx == 0:
                status("看看画面…")

            parts: list[str] = []
            calls: list[dict[str, Any]] | None = None
            speaking = False

            for kind, payload in self.client.chat_stream(
                messages, tools=TOOLS if use_tools else None, thinking=self.think
            ):
                if kind == "content":
                    if not speaking:
                        speaking = True
                        status("")
                    parts.append(payload)
                    delta(payload)
                elif kind == "tool_calls":
                    calls = payload

            if calls:
                text = "".join(parts).strip()
                messages.append({"role": "assistant", "content": text, "tool_calls": calls})
                for call in calls:
                    fn = call.get("function", {})
                    status(_status_text(fn))
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id", ""),
                            "content": self._run_tool(fn),
                        }
                    )
                continue

            answer = "".join(parts).strip()
            if answer:
                self._remember(question, answer)
                return answer

        raise DeepSeekError("这次没拿到回答，重试一下")

    def reset(self) -> None:
        self.history.clear()

    # ---------- 内部 ----------

    def _build_messages(
        self, question: str, shot: Capture, ocr_text: str = ""
    ) -> list[dict[str, Any]]:
        game = shot.game_name or "未知游戏"
        context = (
            f"【当前画面】\n"
            f"游戏：{game}\n"
            f"窗口标题：{shot.title or '(未知)'}\n"
            f"截图尺寸：{shot.width}x{shot.height}\n"
        )
        if ocr_text:
            context += (
                "\n【屏幕上的文字】（OCR 识别，可能有错字，遇到关键名词以它为准）\n"
                f"{ocr_text}\n"
            )
        context += f"\n【玩家的问题】\n{question}"
        user = {
            "role": "user",
            "content": [{"type": "text", "text": context}, image_block(shot.jpeg)],
        }
        return [{"role": "system", "content": SYSTEM_PROMPT}, *self.history[-6:], user]

    def _run_tool(self, fn: dict[str, Any]) -> str:
        name = fn.get("name", "")
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        try:
            if name == "search_web":
                results = self.client.search(
                    str(args.get("query", ""))[:128], count=int(args.get("count", 5) or 5)
                )
                digest = [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "summary": (r.get("summary") or r.get("snippet") or "")[:600],
                        "authority": r.get("authority"),
                    }
                    for r in results[:5]
                ]
                return json.dumps({"results": digest}, ensure_ascii=False)
            if name == "read_page":
                page = self.client.fetch(str(args.get("url", "")))
                return json.dumps(
                    {
                        "title": page.get("title", ""),
                        "content": (page.get("content") or "")[:5000],
                    },
                    ensure_ascii=False,
                )
            return json.dumps({"error": f"未知工具 {name}"}, ensure_ascii=False)
        except DeepSeekError as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    def _remember(self, question: str, answer: str) -> None:
        self.history.append({"role": "user", "content": question})
        self.history.append({"role": "assistant", "content": answer})
        del self.history[:-6]


def _status_text(fn: dict[str, Any]) -> str:
    if fn.get("name") == "search_web":
        try:
            q = json.loads(fn.get("arguments") or "{}").get("query", "")
        except json.JSONDecodeError:
            q = ""
        return f"查攻略：{q}" if q else "查攻略…"
    return "读网页…"
