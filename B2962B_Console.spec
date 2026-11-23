# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

root = Path(SPECPATH).resolve()
local_packages = root / '.packages'

a = Analysis(
    [str(root / 'b2962b_desktop.pyw')],
    pathex=[str(local_packages)] if local_packages.is_dir() else [],
    hiddenimports=['pyvisa.ctwrapper.highlevel'],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='B2962B_Console',
    upx=False,
    console=False,
)
