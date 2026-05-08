# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


hiddenimports = []
hiddenimports += collect_submodules("docx")
hiddenimports += collect_submodules("openpyxl")
hiddenimports += collect_submodules("PIL")

datas = [
    ("resources/app_icon.ico", "resources"),
    ("resources/app_icon.png", "resources"),
    ("examples/imported/sne_emrtu_project.json", "examples/imported"),
    ("examples/imported/simple_series_project.yaml", "examples/imported"),
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
    excludes=[],
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
