# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.win32.versioninfo import (VSVersionInfo, FixedFileInfo,
    StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct)
from pathlib import Path
import runpy

root = Path(SPECPATH)
meta = runpy.run_path(str(root / 'source' / 'appmeta.py'))
version_tuple = tuple(map(int, meta['VERSION'].split('.'))) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_tuple, prodvers=version_tuple, mask=0x3f,
        flags=0, OS=0x40004, fileType=0x1, subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable('040904B0', [
        StringStruct('CompanyName', 'Mayank Nandgowle'),
        StringStruct('FileDescription', meta['PRODUCT']),
        StringStruct('FileVersion', meta['VERSION']),
        StringStruct('ProductName', meta['PRODUCT']),
        StringStruct('ProductVersion', meta['VERSION']),
        StringStruct('OriginalFilename', 'TitleVisionAssistant.exe')])]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])])])

datas = []
binaries = []
hiddenimports = []
tmp_ret = collect_all('playwright')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('tzdata')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    [str(root / 'source' / 'app.py')],
    pathex=[],
    binaries=binaries,
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
    [],
    exclude_binaries=True,
    name='TitleVisionAssistant',
    version=version_info,
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='TitleVisionAssistant',
)
