import os
import json
from PySide6.QtWidgets import (
    QVBoxLayout,
    QLabel,
    QFrame,
)
from qfluentwidgets import (
    PushButton,
    CheckBox,
    PrimaryPushButton,
    TextEdit,
    FluentIcon as FIF,
    ComboBox,
    LineEdit,
)

from common import CONFIG_FILE


class SettingsSection(QFrame):
    def __init__(self, title, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName(title.replace(" ", "-"))
        self._init_ui()
        self.load_settings()

    def _init_ui(self):
        layout = QVBoxLayout()

        self.llamacpp_path = self._create_line_edit(
            "llama.cpp二进制文件所在的路径（可选），留空则为当前目录下的llama文件夹", ""
        )
        layout.addWidget(QLabel("llama.cpp 文件夹"))
        layout.addWidget(self.llamacpp_path)

        self.model_search_paths = TextEdit(self)
        self.model_search_paths.setPlaceholderText(
            "模型搜索路径（每行一个路径，已经默认包含当前目录）"
        )
        layout.addWidget(QLabel("模型搜索路径"))
        layout.addWidget(self.model_search_paths)

        self.remember_window_state = CheckBox("记住窗口位置和大小", self)
        layout.addWidget(self.remember_window_state)

        # 添加模型排序设置
        layout.addWidget(QLabel("模型列表排序方式:"))
        self.model_sort_combo = ComboBox(self)
        self.model_sort_combo.addItems(["修改时间", "文件名", "文件大小"])
        layout.addWidget(self.model_sort_combo)

        self.save_button = PrimaryPushButton(FIF.SAVE, "保存设置", self)
        self.save_button.clicked.connect(self.save_settings)
        layout.addWidget(self.save_button)

        self.load_settings_button = PushButton(FIF.SYNC, "加载设置", self)
        self.load_settings_button.clicked.connect(self.load_settings)
        layout.addWidget(self.load_settings_button)

        self.setLayout(layout)

    def _create_line_edit(self, placeholder, text):
        line_edit = LineEdit(self)
        line_edit.setPlaceholderText(placeholder)
        line_edit.setText(text)
        return line_edit

    def save_settings(self):
        settings = {
            "llamacpp_path": self.llamacpp_path.text(),
            "model_search_paths": self.model_search_paths.toPlainText().split("\n"),
            "remember_window_state": self.remember_window_state.isChecked(),
            "model_sort_option": self.model_sort_combo.currentText(),
        }
        if not os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=4)

        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config_data = json.load(f)
            config_data.update(settings)

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)

        self.main_window.createSuccessInfoBar("成功", "设置已保存")

    def load_settings(self):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except FileNotFoundError:
            return
        except json.JSONDecodeError:
            return
        self.llamacpp_path.setText(settings.get("llamacpp_path", ""))
        self.model_search_paths.setPlainText(
            "\n".join(settings.get("model_search_paths", []))
        )
        self.remember_window_state.setChecked(
            settings.get("remember_window_state", True)
        )
        self.model_sort_combo.setCurrentText(
            settings.get("model_sort_option", "修改时间")
        )
