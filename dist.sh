pyinstaller -n main -F main.py -w \
    --icon=icon.ico \
    --add-data "icon.ico:." \
    --add-data "cloudflared-windows-amd64.exe:." \
    --hidden-import=tiktoken_ext.openai_public \
    --hidden-import=tiktoken_ext \
    --hidden-import=PySide6 \
    --hidden-import=PySide6.QtCore \
    --hidden-import=PySide6.QtGui \
    --hidden-import=qfluentwidgets \
    --clean
