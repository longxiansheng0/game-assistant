"""对话记录：一行一条 JSON，追加写，好翻也好清。"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from ..paths import data_dir


@dataclass
class Entry:
    ts: float
    game: str
    question: str
    answer: str

    @property
    def clock(self) -> str:
        return time.strftime("%m-%d %H:%M", time.localtime(self.ts))


class History:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (data_dir() / "history.jsonl")

    def add(self, game: str, question: str, answer: str) -> None:
        if not answer.strip():
            return
        entry = Entry(ts=time.time(), game=game or "", question=question or "", answer=answer)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        except OSError:
            pass

    def recent(self, limit: int = 300) -> list[Entry]:
        if not self.path.exists():
            return []
        entries: list[Entry] = []
        try:
            for line in self.path.read_text("utf-8").splitlines()[-limit:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                entries.append(
                    Entry(
                        ts=float(data.get("ts", 0)),
                        game=str(data.get("game", "")),
                        question=str(data.get("question", "")),
                        answer=str(data.get("answer", "")),
                    )
                )
        except OSError:
            return []
        return entries[::-1]  # 新的在前

    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
