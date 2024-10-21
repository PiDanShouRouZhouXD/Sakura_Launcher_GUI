default: run

build:
  cd src/native && xmake
  cp src/native/build/windows/x64/release/native.dll ./

run: build
  python main.py

dist: build
  pyinstaller -F main.py \
    --icon=icon.png \
    --add-data "icon.png:." \
    --add-data "cloudflared-windows-amd64.exe:." \
    --add-data "native.dll:." \
    -w \
    --hidden-import=tiktoken_ext.openai_public \
    --hidden-import=tiktoken_ext \
    --hidden-import=PySide6 \
    --hidden-import=PySide6.QtCore \
    --hidden-import=PySide6.QtGui \
    --hidden-import=qfluentwidgets \
    --hidden-import=aiohttp \
    --hidden-import=certifi \
    --hidden-import=ssl \
    --clean
