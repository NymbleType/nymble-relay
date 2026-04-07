# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for nymble-relay.

Produces a single-file executable per platform.
"""

import sys
from pathlib import Path

block_cipher = None
root = Path(SPECPATH)

a = Analysis(
    [str(root / "nymble_relay" / "__main__.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "config" / "config.yaml"), "config"),
    ],
    hiddenimports=[
        "nymble_relay.output.clipboard",
        "nymble_relay.output.hid",
        "nymble_relay.output.xdotool",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="nymble-relay",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
