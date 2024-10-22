import json
from PySide6.QtCore import QObject, Signal

from .common import CONFIG_FILE


class Setting(QObject):
    llamacpp_path = ""
    model_search_paths = ""
    model_sort_option = "修改时间"
    remember_window_state = False
    remember_advanced_state = False
    no_gpu_ability_check = False
    window_geometry = None
    advanced_state = False

    llamacpp_path_changed = Signal(str)
    model_search_paths_changed = Signal(str)
    model_sort_option_changed = Signal(str)
    remember_window_state_changed = Signal(bool)
    remember_advanced_state_changed = Signal(bool)
    no_gpu_ability_check_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._load_settings()

        for sig in [
            self.llamacpp_path_changed,
            self.model_search_paths_changed,
            self.model_sort_option_changed,
            self.remember_window_state_changed,
            self.remember_advanced_state_changed,
        ]:
            sig.connect(lambda: self.save_settings())

    def set_value(self, name: str, value):
        self.__setattr__(name, value)
        self.__getattribute__(name + "_changed").emit(value)

    def _read_settings(self):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            return {}

    def _write_settings(self, settings):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)

    def save_settings(self):
        settings = {
            "llamacpp_path": self.llamacpp_path,
            "model_search_path": self.model_search_paths,
            "model_sort_option": self.model_sort_option,
            "remember_window_state": self.remember_window_state,
            "remember_advanced_state": self.remember_advanced_state,
            "no_gpu_ability_check": self.no_gpu_ability_check,
            "window_geometry": self.window_geometry,
            "advanced_state": self.advanced_state,
        }
        current_settings = self._read_settings()
        current_settings.update(settings)
        self._write_settings(current_settings)

    def _load_settings(self):
        settings = self._read_settings()
        self.llamacpp_path = settings.get("llamacpp_path", "")
        self.model_search_paths = settings.get("model_search_paths", "")
        self.model_sort_option = settings.get("model_sort_option", "修改时间")
        self.remember_window_state = settings.get("remember_window_state", False)
        self.remember_advanced_state = settings.get("remember_advanced_state", False)
        self.no_gpu_ability_check = settings.get("no_gpu_ability_check", False)
        self.window_geometry = settings.get("window_geometry", None)
        self.advanced_state = settings.get("advanced_state", False)


setting = Setting()
