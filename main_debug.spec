# -*- mode: python ; coding: utf-8 -*-
import sys

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
# 平台特定的排除项
if sys.platform == 'win32':
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
else:
    exclude_prefix = [
        'PySide6/Qt6Pdf',
        'PySide6/Qt6Network',
        'PySide6/QtNetwork',
        'PySide6/Qt6VirtualKeyboard',
        'PySide6/Qt6Qml',
        'PySide6/Qt6Quick',
        'PySide6/Qt6OpenGL',
        'PySide6/Qt6QmlModels',
        'PySide6/translations',
    ]
def should_include(t):
    return not any(t[0].startswith(prefix) for prefix in exclude_prefix)
a.binaries = list(filter(should_include, a.binaries))
a.datas = list(filter(should_include, a.datas))

pyz = PYZ(a.pure)

if sys.platform == 'win32':
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name='main_debug',
        debug=True,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=['icon.ico'],
    )
elif sys.platform == 'darwin':
    exe = EXE(
        pyz,
        a.scripts,
        [],  # 不包含二进制文件
        exclude_binaries=True,
        name='SakuraLauncher_debug',
        debug=True,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=True,
        argv_emulation=True,
    )
    
    app = BUNDLE(
        exe,
        a.binaries,
        a.datas,
        name='SakuraLauncher_debug.app',
        icon='icon.ico',
        bundle_identifier='com.sakura.launcher',
        info_plist={
            'NSHighResolutionCapable': True,
            'LSBackgroundOnly': False,
            'CFBundleDisplayName': 'SakuraLauncher_debug',
        }
    )