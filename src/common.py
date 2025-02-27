import sys
import os


def get_resource_path(relative_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    else:
        return os.path.join(os.path.abspath("."), relative_path)


def get_self_path():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    else:
        # 当前文件的绝对路径的上一级目录
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


CURRENT_DIR = get_self_path()
ICON_FILE = "icon.ico"
GHPROXY_URL = "ghfast.top"
SAKURA_LAUNCHER_GUI_VERSION = "v1.2.0-alpha"
DEBUG_BUILD = False

processes = []
