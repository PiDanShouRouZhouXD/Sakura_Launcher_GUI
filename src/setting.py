import json
from PySide6.QtCore import QObject, Signal

CONFIG_FILE = "sakura-launcher_config.json"


class Setting(QObject):
    llamacpp_path = ""
    model_search_paths = ""
    model_sort_option = "修改时间"
    remember_window_state = False
    remember_advanced_state = False
    no_gpu_ability_check = False
    window_geometry = None
    advanced_state = False
    worker_url = ""
    presets = []
    no_context_check = False
    token = ""
    port_override = ""

    # 各个属性的专用信号
    llamacpp_path_changed = Signal(str)
    model_search_paths_changed = Signal(str)
    model_sort_option_changed = Signal(str)
    remember_window_state_changed = Signal(bool)
    remember_advanced_state_changed = Signal(bool)
    no_gpu_ability_check_changed = Signal(bool)
    worker_url_changed = Signal(str)
    presets_changed = Signal(list)
    no_context_check_changed = Signal(bool)
    token_changed = Signal(str)
    port_override_changed = Signal(str)

    # 通用的值变化信号
    value_changed = Signal(str, object)  # (key, value)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._load_settings()

        for sig in [
            self.llamacpp_path_changed,
            self.model_search_paths_changed,
            self.model_sort_option_changed,
            self.remember_window_state_changed,
            self.remember_advanced_state_changed,
            self.no_gpu_ability_check_changed,
            self.presets_changed,
            self.worker_url_changed,
            self.no_context_check_changed,
            self.token_changed,
            self.port_override_changed,
        ]:
            sig.connect(lambda: self.save_settings())

    def set_value(self, name: str, value):
        """设置值并发出相应的信号"""
        self.__setattr__(name, value)
        # 发出专用信号
        if hasattr(self, name + "_changed"):
            self.__getattribute__(name + "_changed").emit(value)
        # 发出通用信号
        self.value_changed.emit(name, value)

    def set_preset(self, name: str, config):
        is_preset_exist = False
        for preset in self.presets:
            if preset["name"] == name:
                preset["config"] = config
                is_preset_exist = True
                break
        if not is_preset_exist:
            new_preset = {"name": name, "config": config}
            self.presets.append(new_preset)
        self.presets_changed.emit(self.presets)

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
            "model_search_paths": self.model_search_paths,
            "model_sort_option": self.model_sort_option,
            "remember_window_state": self.remember_window_state,
            "remember_advanced_state": self.remember_advanced_state,
            "no_gpu_ability_check": self.no_gpu_ability_check,
            "window_geometry": self.window_geometry,
            "advanced_state": self.advanced_state,
            "worker_url": self.worker_url,
            "运行": self.presets,
            "no_context_check": self.no_context_check,
            "token": self.token,
            "port_override": self.port_override,
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
        self.presets = settings.get("运行", [])
        self.worker_url = settings.get("worker_url", "https://sakura-share.one")
        self.no_context_check = settings.get("no_context_check", False)
        self.token = settings.get("token", "")
        self.port_override = settings.get("port_override", "")

        # 兼容 v1.0.0-beta
        if type(self.model_search_paths) == list:
            self.model_search_paths = "\n".join(self.model_search_paths)


SETTING = Setting()
