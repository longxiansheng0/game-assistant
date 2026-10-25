"""办公任务的审计日志。

每次办公任务一行 JSON，记下：谁发起的（语音/打字）、什么权限、确认结果、
跑过哪些命令、结果如何、花了多久。出事能回溯。
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024  # 2MB 之后滚动一份 .1，别让日志无限长


@dataclass
class AuditEntry:
    ts: float
    source: str = "typed"          # voice / typed
    permission: str = ""
    workspace: str = ""
    confirm: str = ""              # not-needed / accepted / edited / cancelled / timeout
    question: str = ""
    steps: list = field(default_factory=list)
    result: str = ""
    duration: float = 0.0
    error: str = ""

    @property
    def clock(self) -> str:
        return time.strftime("%m-%d %H:%M", time.localtime(self.ts))

    @property
    def seconds(self) -> str:
        return f"{self.duration:.1f}s" if self.duration else "—"


class OfficeAudit:
    def __init__(self, path: Path) -> None:
        self.path = path

    def record(
        self,
        question: str,
        *,
        source: str = "typed",
        permission: str = "",
        workspace: str = "",
        confirm: str = "",
        steps: list | None = None,
        result: str = "",
        duration: float = 0.0,
        error: str = "",
    ) -> None:
        entry = AuditEntry(
            ts=time.time(),
            source=source,
            permission=permission,
            workspace=workspace,
            confirm=confirm,
            question=question,
            steps=steps or [],
            result=(result or "")[:4000],
            duration=duration,
            error=(error or "")[:1000],
        )
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed()
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        except OSError:
            pass  # 日志写不进去也不能影响主流程

    def recent(self, limit: int = 100) -> list[AuditEntry]:
        if not self.path.exists():
            return []
        rows: list[AuditEntry] = []
        try:
            with self.path.open("r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            return []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            known = {f for f in AuditEntry.__dataclass_fields__}
            rows.append(AuditEntry(**{k: v for k, v in data.items() if k in known}))
        rows.reverse()  # 新的在前
        return rows

    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass

    def _rotate_if_needed(self) -> None:
        try:
            if self.path.exists() and self.path.stat().st_size > MAX_BYTES:
                backup = self.path.with_suffix(".jsonl.1")
                backup.unlink(missing_ok=True)
                self.path.rename(backup)
        except OSError:
            pass
