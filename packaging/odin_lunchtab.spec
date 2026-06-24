# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

project_root = Path(SPECPATH).resolve().parent
datas = [
    (str(project_root / "assets" / "app.ico"), "assets"),
    (str(project_root / "assets" / "app.png"), "assets"),
]
datas += copy_metadata("odin-lunchtab")

a = Analysis(
    [str(project_root / "src" / "odin_lunchtab" / "gui.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[],
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
    [],
    exclude_binaries=True,
    name="OdinLunchtab",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "assets" / "app.ico"),
    version=str(project_root / "build" / "version_info.txt"),
    uac_admin=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="OdinLunchtab",
)
