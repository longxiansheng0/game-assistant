import sys, json
sys.path.insert(0, ".")
from app.llm.deepseek import DeepSeekError
from app.core.agent import GameAssistant
from app.vision.capture import Capture


class FakeClient:
    """模拟：第一轮要搜索，第二轮才回答；全走流式。"""

    def __init__(self):
        self.calls = []

    def chat_stream(self, messages, tools=None, thinking=False, **_kw):
        self.calls.append(("stream", len(messages), bool(tools)))
        if tools and not any(m["role"] == "tool" for m in messages):
            yield "tool_calls", [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "search_web", "arguments": json.dumps({"query": "原神 深渊使徒 打法"})},
            }]
            return
        for t in ["弱雷，", "二阶段先清小怪。"]:
            yield "content", t

    def search(self, query, count=5, need_content=False):
        self.calls.append(("search", query))
        return [{"title": "攻略", "url": "https://example.com/a", "summary": "弱雷", "authority": 3}]

    def fetch(self, url):
        return {"title": "t", "content": "c"}


shot = Capture(jpeg=b"\xff\xd8\xff" + b"0" * 100, title="原神", process="YuanShen.exe", width=1280, height=720)
deltas, statuses = [], []
bot = GameAssistant(FakeClient())
answer = bot.ask("这boss怎么打", shot, on_status=statuses.append, on_delta=deltas.append)
print("answer:", answer)
print("chunks:", len(deltas), "->", "".join(deltas))
print("statuses:", statuses)
print("calls:", bot.client.calls)
print("history:", len(bot.history))
