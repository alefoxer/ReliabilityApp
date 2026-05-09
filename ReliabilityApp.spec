# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files


hiddenimports = [
    "docx",
    "docx.enum.text",
    "docx.shared",
    "openpyxl",
    "openpyxl.drawing.image",
    "openpyxl.styles",
    "openpyxl.utils",
    "PIL.Image",
    "yaml",
]

datas = [
    ("resources", "resources"),
    ("examples", "examples"),
    ("app/demo/db_modules.json", "app/demo"),
    ("docs", "docs"),
]
datas += collect_data_files("docx")
datas += collect_data_files("openpyxl")
datas += collect_data_files("PIL")


a = Analysis(
    ["app/main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "IPython",
        "PIL.ImageTk",
        "PySide6",
        "anyio",
        "dask",
        "fsspec",
        "gradio",
        "librosa",
        "llvmlite",
        "numba",
        "pandas",
        "pydantic",
        "pytest",
        "scipy",
        "sklearn",
        "soundfile",
        "sqlalchemy",
        "tensorflow",
        "torch",
        "transformers",
        "uvicorn",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ReliabilityApp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="resources/app_icon.ico",
)
