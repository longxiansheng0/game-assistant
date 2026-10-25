"""从已安装的 DeepSeek Harness 里抽取 dsh，裁剪成可内置的 vendor/dsh。

用法：python packaging/bundle_dsh.py [DSH安装目录]
产物：vendor/dsh/（约 307MB，含 Office 组件）
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "vendor" / "dsh"

# 这些包对整个产品没用，直接不抽
DROP = (
    "@deepseek-ai/dsh-client-ui-",
    "@deepseek-ai/dsh-web-frontend",
    "@deepseek-ai/dsh-plugin-market",
    "@deepseek-ai/dsh-experimental-",
    "sherpa-onnx-win-x64",
    "@modelcontextprotocol",
)
# 不能删：ripgrep（grep 工具）、sharp（图片）、otel（删了启动慢 15 秒）、libreoffice（Office）


def find_dsh() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    for candidate in (
        Path(r"D:\APP\DeepSeek Harness"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "DeepSeek Harness",
        Path(os.environ.get("PROGRAMFILES", "")) / "DeepSeek Harness",
    ):
        if (candidate / "resources" / "app.asar").exists():
            return candidate
    raise SystemExit("找不到 DeepSeek Harness，请把安装目录作为参数传进来")


def read_header(raw: bytes) -> tuple[dict, int]:
    start = raw.find(b'{"files":')
    depth = 0
    i = start
    in_str = False
    esc = False
    while i < len(raw):
        c = raw[i : i + 1]
        if in_str:
            if esc:
                esc = False
            elif c == b"\\":
                esc = True
            elif c == b'"':
                in_str = False
        else:
            if c == b'"':
                in_str = True
            elif c == b"{":
                depth += 1
            elif c == b"}":
                depth -= 1
                if depth == 0:
                    break
        i += 1
    header = json.loads(raw[start : i + 1].decode("utf-8"))
    return header, (i + 1 + 3) // 4 * 4


def skipped(path: str) -> bool:
    parts = path.split("/")
    if len(parts) < 4:
        return False
    pkg = "/".join(parts[2:4]) if parts[2].startswith("@") else parts[2]
    return any(pkg.startswith(d) for d in DROP) or any(d in path for d in DROP)


def main() -> int:
    src = find_dsh()
    asar = src / "resources" / "app.asar"
    unpacked = src / "resources" / "app.asar.unpacked"
    print(f"源头: {src}")
    raw = asar.read_bytes()
    header, base = read_header(raw)

    if OUT.exists():
        shutil.rmtree(OUT)
    count = 0
    total = 0

    def walk(node: dict, prefix: str) -> None:
        nonlocal count, total
        for name, child in node.get("files", {}).items():
            p = f"{prefix}/{name}" if prefix else name
            if "files" in child:
                walk(child, p)
                continue
            if not p.startswith("dsh/"):
                continue
            rel = p[len("dsh/") :]
            if skipped(rel):
                continue
            dest = OUT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if child.get("unpacked"):
                s = unpacked / p
                if not s.exists():
                    continue
                dest.write_bytes(s.read_bytes())
                total += s.stat().st_size
            else:
                off = int(child["offset"])
                size = int(child["size"])
                dest.write_bytes(raw[base + off : base + off + size])
                total += size
            count += 1

    walk(header, "")
    print(f"完成: {count} 个文件, {total / 1048576:.0f} MB -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
