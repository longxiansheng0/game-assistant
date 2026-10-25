"""内置 DSH 的调用桥。

子进程跑 vendor 里的 node + dsh，读它的 NDJSON 事件流，翻译成一行行中文。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


@dataclass
class Step:
    kind: str          # tool / result / note / final
    text: str
    ok: bool = True


class DshBridge:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.node = root / "vendor" / "node" / "node.exe"
        self._proc: subprocess.Popen | None = None
        self.cli = (
            root
            / "vendor"
            / "dsh"
            / "node_modules"
            / "@deepseek-ai"
            / "dsh-desktop-host"
            / "lib"
            / "cli.js"
        )

    @property
    def available(self) -> bool:
        return self.node.exists() and self.cli.exists()

    def version(self) -> str:
        if not self.available:
            return ""
        try:
            out = subprocess.run(
                [str(self.node), str(self.cli), "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                creationflags=CREATE_NO_WINDOW,
            )
            return (out.stdout or "").strip().splitlines()[0]
        except Exception:
            return ""

    def run(
        self,
        task: str,
        cwd: Path,
        on_step: Callable[[Step], None],
        api_key: str,
        permission: str = "workspace-write",
        timeout: int = 180,
        should_stop: Callable[[], bool] | None = None,
    ) -> str:
        if not self.available:
            raise RuntimeError("内置执行组件不完整（vendor 缺失）")

        cwd.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["DEEPSEEK_API_KEY"] = api_key
        env["DSH_HOME"] = str(self.root / "data" / "dsh_home")
        env["DSH_PERMISSION_MODE"] = permission

        errors = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(
            [str(self.node), str(self.cli), "headless", "--json", task],
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=CREATE_NO_WINDOW,
        )

        self._proc = proc
        started = time.time()
        final = ""
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                if should_stop and should_stop():
                    _kill(proc)
                    raise TimeoutError("已停止")
                if time.time() - started > timeout:
                    _kill(proc)
                    raise TimeoutError(f"超时（{timeout} 秒）")

                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                step = _describe(event)
                if step is None:
                    continue
                if step.kind == "final":
                    final = step.text
                on_step(step)
        finally:
            self._proc = None
            code = proc.wait(timeout=10)
            if code != 0 and not final:
                errors.seek(0)
                detail = errors.read()[-400:].strip()
                errors.close()
                raise RuntimeError(detail or f"执行组件退出码 {code}")
            errors.close()
        return final


    def cancel(self) -> None:
        """从别的线程叫停：杀掉进程树，阻塞中的 readline 会立刻返回。"""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            _kill(proc)


def _kill(proc: subprocess.Popen) -> None:
    try:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        proc.kill()


def _describe(event: dict) -> Step | None:
    kind = event.get("type")
    if kind == "tool_call":
        tool = str(event.get("tool") or "")
        data = event.get("input") or {}
        detail = ""
        for key in ("command", "query", "pattern", "path", "file_path", "url", "description"):
            if isinstance(data.get(key), str) and data[key]:
                detail = data[key]
                break
        if not detail:
            detail = json.dumps(data, ensure_ascii=False)[:60]
        detail = " ".join(detail.split())[:90]
        return Step("tool", f"{tool} · {detail}" if detail else tool)
    if kind == "tool_result":
        ok = event.get("status") == "completed"
        return Step("result", "完成" if ok else "这一步失败了", ok)
    if kind == "final":
        return Step("final", str(event.get("text") or ""))
    return None
