"""入口。带 --selftest 时只做打包自检，不弹窗。"""

from __future__ import annotations

import sys


def _selftest() -> int:
    import tempfile
    import traceback
    from pathlib import Path

    lines: list[str] = []
    ok = True

    def step(name, fn):
        nonlocal ok
        try:
            result = fn()
            lines.append(f"OK   {name}: {result}")
        except Exception:
            ok = False
            lines.append(f"FAIL {name}")
            lines.append(traceback.format_exc())

    def info():
        from app import paths

        return f"frozen={paths.is_frozen()} base={paths.base_dir()}"

    def qt():
        from PySide6 import QtCore
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        from app.ui.orb import Orb

        orb = Orb(64)
        return f"Qt {QtCore.qVersion()} orb={orb.size().width()}px"

    def vision():
        from app.vision.capture import grab

        shot = grab(max_width=640)
        return f"capture {shot.width}x{shot.height} {len(shot.jpeg) // 1024}KB"

    def ocr():
        from app.vision.ocr import OcrEngine

        engine = OcrEngine()
        engine.warmup()
        return "rapidocr ready"

    def asr():
        from app.voice.asr import WhisperASR

        engine = WhisperASR("small")
        engine.load()
        return "whisper loaded"

    def tts():
        import edge_tts  # noqa: F401
        import miniaudio  # noqa: F401
        import sounddevice as sd

        return f"out={sd.query_devices(kind='output')['name'][:24]}"

    def boot():
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        from app.config import Settings
        from app.main import AssistantApp
        from app.ui.orb import Orb

        Orb.show = lambda self: None  # 自检别真弹窗
        ctl = AssistantApp(app, Settings.load())
        combos = [h.combo for h in ctl.hotkeys]
        for listener in ctl.hotkeys:
            listener.stop()
        return f"assistant={ctl.assistant is not None} hotkeys={combos}"

    step("paths", info)
    step("qt", qt)
    step("boot", boot)
    step("vision", vision)
    step("ocr", ocr)
    step("tts", tts)
    step("asr", asr)

    target = Path(tempfile.gettempdir()) / "gameassistant_selftest.log"
    target.write_text("\n".join(lines), encoding="utf-8")
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    from app.main import main as run_app

    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
