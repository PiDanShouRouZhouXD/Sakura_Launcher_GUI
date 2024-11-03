# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('icon.ico', '.'), ('data.json', '.')],
    hiddenimports=['tiktoken_ext.openai_public', 'tiktoken_ext', 'PySide6', 'PySide6.QtCore', 'PySide6.QtGui', 'qfluentwidgets'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
exclude_prefix = [
   'PySide6\\opengl32sw.dll',
    'PySide6\\Qt6Pdf.dll',
    'PySide6\\Qt6Network.dll',
    'PySide6\\QtNetwork.pyd',
    'PySide6\\Qt6VirtualKeyboard.dll',
    'PySide6\\Qt6Qml.dll',
    'PySide6\\Qt6Quick.dll',
    'PySide6\\Qt6OpenGL.dll',
    'PySide6\\Qt6QmlModels.dll',
    'PySide6\\translations',
    'Pythonwin',
]
def should_include(t):
    return not any(t[0].startswith(prefix) for prefix in exclude_prefix)
a.binaries = list(filter(should_include, a.binaries))
a.datas = list(filter(should_include, a.datas))

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='main',
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
    icon=['icon.ico'],
)
