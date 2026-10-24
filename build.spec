# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：单目录（onedir），不压 UPX。

单文件版每次启动都要解压 1GB 的东西，十几秒起步，不值得。
"""

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

datas = []
datas += collect_data_files("rapidocr_onnxruntime")   # det/rec/cls 的 onnx 模型
datas += collect_data_files("faster_whisper")         # silero vad 权重
datas += collect_data_files("miniaudio")              # 可能没有，没有就算了

binaries = []
binaries += collect_dynamic_libs("ctranslate2")
binaries += collect_dynamic_libs("onnxruntime")
binaries += collect_dynamic_libs("sounddevice")

hiddenimports = [
    "faster_whisper",
    "ctranslate2",
    "onnxruntime",
    "av",
    "tokenizers",
    "sounddevice",
    "_sounddevice",
    "miniaudio",
    "mss",
    "edge_tts",
    "httpx",
    "httpcore",
    "PIL.Image",
    "cv2",
    "pyclipper",
    "shapely",
    "numpy",
    "huggingface_hub",
]
hiddenimports += collect_submodules("rapidocr_onnxruntime")

excludes = [
    "tkinter",
    "matplotlib",
    "pandas",
    "scipy",
    "IPython",
    "jupyter",
    "pytest",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.Qt3DCore",
    "PySide6.QtMultimedia",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtPdf",
    "PySide6.QtSql",
    "PySide6.QtTest",
]

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GameAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/app.ico",
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="GameAssistant",
)
