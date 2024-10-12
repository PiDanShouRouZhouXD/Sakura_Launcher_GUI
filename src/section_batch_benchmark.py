import os
import json
import math
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QGroupBox
from qfluentwidgets import (
    PushButton,
    SpinBox,
    PrimaryPushButton,
    TextEdit,
    EditableComboBox,
    MessageBox,
    FluentIcon as FIF,
    Slider,
)

from common import CURRENT_DIR, CONFIG_FILE, RunSection


class RunBatchBenchmarkSection(RunSection):
    def __init__(self, title, main_window, parent=None):
        super().__init__(title, main_window, parent)
        self._init_ui()
        self.load_presets()
        self.refresh_models()
        self.refresh_gpus()
        self.load_selected_preset()

    def _init_ui(self):
        layout = QVBoxLayout()

        buttons_group = QGroupBox("")
        buttons_layout = QHBoxLayout()

        self.save_preset_button = PushButton(FIF.SAVE, "保存预设", self)
        self.save_preset_button.clicked.connect(self.save_preset)
        self.save_preset_button.setFixedSize(110, 30)
        buttons_layout.addWidget(self.save_preset_button)

        self.load_preset_button = PushButton(FIF.SYNC, "刷新预设", self)
        self.load_preset_button.clicked.connect(self.load_presets)
        self.load_preset_button.setFixedSize(110, 30)
        buttons_layout.addWidget(self.load_preset_button)

        self.run_button = PrimaryPushButton(FIF.PLAY, "运行", self)
        self.run_button.setFixedSize(110, 30)
        buttons_layout.addWidget(self.run_button)

        buttons_layout.setAlignment(Qt.AlignRight)
        buttons_group.setStyleSheet(
            """ QGroupBox {border: 0px solid darkgray; background-color: #202020; border-radius: 8px;}"""
        )
        buttons_group.setLayout(buttons_layout)
        layout.addWidget(buttons_group)

        layout.addWidget(QLabel("模型选择"))
        layout.addLayout(self._create_model_selection_layout())
        layout.addWidget(QLabel("配置预设选择"))
        self.config_preset_combo = EditableComboBox(self)
        self.config_preset_combo.currentIndexChanged.connect(self.load_selected_preset)
        layout.addWidget(self.config_preset_combo)

        layout.addLayout(
            self._create_slider_spinbox_layout(
                "GPU层数 -ngl", "gpu_layers", 200, 0, 200, 1
            )
        )

        # 替换原有的上下文长度设置
        layout.addWidget(QLabel("上下文长度 -c"))
        layout.addLayout(self._create_context_length_layout())

        layout.addWidget(QLabel("Prompt数量 -npp"))
        self.npp_input = self._create_line_edit(
            "Prompt数量，多个值用英文逗号分隔，如： 128,256,512", "128,256,512"
        )
        layout.addWidget(self.npp_input)

        layout.addWidget(QLabel("生成文本（text generation）数量 -ntg"))
        self.ntg_input = self._create_line_edit(
            "生成文本（text generation）数量，多个值用英文逗号分隔，如： 128,256",
            "128,256",
        )
        layout.addWidget(self.ntg_input)

        layout.addWidget(QLabel("并行Prompt数量 -npl"))
        self.npl_input = self._create_line_edit(
            "并行Prompt数量，多个值用英文逗号分隔，如： 1,2,4,8,16,32", "1,2,4,8,16,32"
        )
        layout.addWidget(self.npl_input)

        self.pps_check = self._create_check_box("Prompt共享 -pps", False)
        layout.addWidget(self.pps_check)

        self.flash_attention_check = self._create_check_box(
            "启用 Flash Attention -fa", True
        )
        layout.addWidget(self.flash_attention_check)

        self.no_mmap_check = self._create_check_box("启用 --no-mmap", True)
        layout.addWidget(self.no_mmap_check)

        layout.addLayout(self._create_gpu_selection_layout())

        # 新增llamacpp覆盖选项
        self.llamacpp_override = self._create_line_edit(
            "覆盖默认llamacpp路径（可选）", ""
        )
        layout.addWidget(QLabel("覆盖默认llamacpp路径"))
        layout.addWidget(self.llamacpp_override)

        self.custom_command_append = TextEdit(self)
        self.custom_command_append.setPlaceholderText(
            "手动追加命令（追加到UI选择的命令后）"
        )
        layout.addWidget(self.custom_command_append)

        self.custom_command = TextEdit(self)
        self.custom_command.setPlaceholderText("手动自定义命令（覆盖UI选择）")
        layout.addWidget(self.custom_command)

        self.setLayout(layout)

        # 连接信号
        self.context_length_input.valueChanged.connect(self.update_slider_from_input)
        self.context_length.valueChanged.connect(self.update_context_from_slider)

    def _create_context_length_layout(self):
        layout = QHBoxLayout()
        self.context_length = Slider(Qt.Horizontal, self)
        self.context_length.setRange(0, 10000)
        self.context_length.setPageStep(5)
        self.context_length.setValue(5000)

        self.context_length_input = SpinBox(self)
        self.context_length_input.setRange(256, 131072)
        self.context_length_input.setSingleStep(256)
        self.context_length_input.setValue(2048)

        layout.addWidget(self.context_length)
        layout.addWidget(self.context_length_input)

        return layout

    def context_to_slider(self, context):
        min_value = math.log(256)
        max_value = math.log(131072)
        return int(10000 * (math.log(context) - min_value) / (max_value - min_value))

    def slider_to_context(self, value):
        min_value = math.log(256)
        max_value = math.log(131072)
        return int(math.exp(min_value + (value / 10000) * (max_value - min_value)))

    def update_context_from_slider(self, value):
        context_length = self.slider_to_context(value)
        context_length = max(256, min(131072, context_length))
        context_length = round(context_length / 256) * 256
        self.context_length_input.blockSignals(True)
        self.context_length_input.setValue(context_length)
        self.context_length_input.blockSignals(False)

    def update_slider_from_input(self, value):
        value = round(value / 256) * 256
        slider_value = self.context_to_slider(value)
        slider_value = max(0, min(10000, slider_value))
        self.context_length.setValue(slider_value)
        self.context_length.update()

    def save_preset(self):
        preset_name = self.config_preset_combo.currentText()
        if not preset_name:
            MessageBox("错误", "预设名称不能为空", self).exec()
            return

        config_file_path = os.path.join(CURRENT_DIR, CONFIG_FILE)
        if not os.path.exists(config_file_path):
            with open(config_file_path, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=4)

        with open(config_file_path, "r", encoding="utf-8") as f:
            try:
                current_settings = json.load(f)
            except json.JSONDecodeError:
                current_settings = {}

        preset_section = current_settings.get(self.title, [])
        new_preset = {
            "name": preset_name,
            "config": {
                "custom_command": self.custom_command.toPlainText(),
                "custom_command_append": self.custom_command_append.toPlainText(),
                "gpu_layers": self.gpu_layers_spinbox.value(),
                "context_length": self.context_length_input.value(),
                "flash_attention": self.flash_attention_check.isChecked(),
                "no_mmap": self.no_mmap_check.isChecked(),
                "gpu_enabled": self.gpu_enabled_check.isChecked(),
                "gpu": self.gpu_combo.currentText(),
                "gpu_index": self.manully_select_gpu_index.text(),
                "model_path": self.model_path.currentText(),
                "npp": self.npp_input.text(),
                "ntg": self.ntg_input.text(),
                "npl": self.npl_input.text(),
                "pps": self.pps_check.isChecked(),
                "llamacpp_override": self.llamacpp_override.text(),
            },
        }

        for i, preset in enumerate(preset_section):
            if preset["name"] == preset_name:
                preset_section[i] = new_preset
                break
        else:
            preset_section.append(new_preset)

        current_settings[self.title] = preset_section

        with open(config_file_path, "w", encoding="utf-8") as f:
            json.dump(current_settings, f, ensure_ascii=False, indent=4)

        self.load_presets()
        self.main_window.createSuccessInfoBar("成功", "预设已保存")

    def load_presets(self):
        self.config_preset_combo.clear()
        presets = self.load_presets_from_file()
        if not presets or presets == {}:
            return
        if self.title in presets:
            self.config_preset_combo.addItems(
                [preset["name"] for preset in presets[self.title]]
            )

    def load_selected_preset(self):
        preset_name = self.config_preset_combo.currentText()
        presets = self.load_presets_from_file()
        if not presets or presets == {}:
            return
        if self.title in presets:
            for preset in presets[self.title]:
                if preset["name"] == preset_name:
                    config = preset["config"]
                    self.custom_command.setPlainText(config.get("custom_command", ""))
                    self.custom_command_append.setPlainText(
                        config.get("custom_command_append", "")
                    )
                    self.gpu_layers_spinbox.setValue(config.get("gpu_layers", 99))
                    self.context_length_input.setValue(
                        config.get("context_length", 2048)
                    )
                    self.update_slider_from_input(self.context_length_input.value())
                    self.model_path.setCurrentText(config.get("model_path", ""))
                    self.npp_input.setText(config.get("npp", ""))
                    self.ntg_input.setText(config.get("ntg", ""))
                    self.npl_input.setText(config.get("npl", ""))
                    self.pps_check.setChecked(config.get("pps", False))
                    self.flash_attention_check.setChecked(
                        config.get("flash_attention", True)
                    )
                    self.no_mmap_check.setChecked(config.get("no_mmap", True))
                    self.gpu_enabled_check.setChecked(config.get("gpu_enabled", True))
                    self.gpu_combo.setCurrentText(config.get("gpu", ""))
                    self.manully_select_gpu_index.setText(config.get("gpu_index", ""))
                    self.llamacpp_override.setText(config.get("llamacpp_override", ""))
                    break

    def load_presets_from_file(self):
        config_file_path = os.path.join(CURRENT_DIR, CONFIG_FILE)
        if os.path.exists(config_file_path):
            with open(config_file_path, "r", encoding="utf-8") as f:
                try:
                    return json.load(f) or {}
                except json.JSONDecodeError:
                    return {}
        return {}
