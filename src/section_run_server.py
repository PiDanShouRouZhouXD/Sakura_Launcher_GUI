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

from .common import CURRENT_DIR, CONFIG_FILE, RunSection
from .ui import *


class RunServerSection(RunSection):
    def __init__(self, title, main_window, parent=None):
        super().__init__(title, main_window, parent)
        self._init_ui()
        self.load_presets()
        self.refresh_models()
        self.refresh_gpus()
        self.load_selected_preset()

    def _init_ui(self):
        layout = QVBoxLayout()

        self._init_simple_options(layout)
        layout.addWidget(UiHLine(self))
        self._init_advance_options(layout)
        self._init_override_options(layout)
        self.setLayout(layout)

        self.context_length_input.valueChanged.connect(self.update_slider_from_input)
        self.context_length.valueChanged.connect(self.update_context_per_thread)
        self.n_parallel_spinbox.valueChanged.connect(self.update_context_per_thread)

        self.update_context_per_thread()

    def _create_preset_options(self):
        preset_layout = QHBoxLayout()

        self.config_preset_combo = EditableComboBox(self)
        self.config_preset_combo.currentIndexChanged.connect(self.load_selected_preset)
        preset_layout.addWidget(self.config_preset_combo)

        self.save_preset_button = PushButton(FIF.SAVE, "保存", self)
        self.save_preset_button.clicked.connect(self.save_preset)
        preset_layout.addWidget(self.save_preset_button)

        self.load_preset_button = PushButton(FIF.SYNC, "刷新", self)
        self.load_preset_button.clicked.connect(self.load_presets)
        preset_layout.addWidget(self.load_preset_button)

        return preset_layout

    def _create_ip_port_log_option(self):
        ip_port_log_layout = QHBoxLayout()

        ip_layout = QVBoxLayout()
        self.host_input = self._create_editable_combo_box(["127.0.0.1", "0.0.0.0"])
        ip_layout.addWidget(QLabel("主机地址 --host"))
        ip_layout.addWidget(self.host_input)

        host_layout = QVBoxLayout()
        self.port_input = UiLineEdit(self, "", "8080")
        host_layout.addWidget(QLabel("端口 --port"))
        host_layout.addWidget(self.port_input)

        log_layout = QVBoxLayout()
        self.log_format_combo = self._create_editable_combo_box(
            ["none", "text", "json"]
        )
        log_layout.addWidget(QLabel("日志格式 --log-format"))
        log_layout.addWidget(self.log_format_combo)

        ip_port_log_layout.addLayout(ip_layout)
        ip_port_log_layout.addLayout(host_layout)
        ip_port_log_layout.addLayout(log_layout)

        return ip_port_log_layout

    def _create_benchmark_layout(self):
        row1 = QHBoxLayout()
        self.npp_input = UiLineEdit(self, "Prompt数量", "128,256,512")
        self.ntg_input = UiLineEdit(self, "生成文本数量", "128,256")
        self.npl_input = UiLineEdit(self, "并行Prompt数量", "1,2,4,8,16,32")
        row1.addLayout(UiCol("Prompt数量 -npp", self.npp_input))
        row1.addLayout(UiCol("生成文本数量 -ntg", self.ntg_input))
        row1.addLayout(UiCol("并行Prompt数量 -npl", self.npl_input))

        self.pps_check = UiCheckBox(self, "Prompt共享 -pps", False)

        layout = QVBoxLayout()
        layout.addLayout(row1)
        layout.addWidget(self.pps_check)

        return layout

    def _init_simple_options(self, layout):
        buttons_layout = QHBoxLayout()
        buttons_layout.setAlignment(Qt.AlignRight)

        self.benchmark_button = PushButton(FIF.UNIT, "性能测试", self)
        self.benchmark_button.setFixedSize(110, 30)
        buttons_layout.addWidget(self.benchmark_button)

        self.run_button = PrimaryPushButton(FIF.PLAY, "运行", self)
        self.run_button.setFixedSize(110, 30)
        buttons_layout.addWidget(self.run_button)

        buttons_group = QGroupBox("")
        buttons_group.setStyleSheet(
            """ QGroupBox {border: 0px solid darkgray; background-color: #202020; border-radius: 8px;}"""
        )
        buttons_group.setLayout(buttons_layout)
        layout.addWidget(buttons_group)

        layout.addLayout(UiRow("模型", self._create_model_selection_layout()))
        layout.addLayout(UiRow("显卡", self._create_gpu_selection_layout()))

        layout.addLayout(UiRow("上下文长度 -c", self._create_context_length_layout()))
        layout.addLayout(
            UiRow("工作线程数量 -np", UiSlider(self, "n_parallel", 1, 1, 32, 1))
        )

        self.context_per_thread_label = QLabel(self)
        layout.addWidget(self.context_per_thread_label)

    def _init_advance_options(self, layout):
        layout_extra_options = QHBoxLayout()
        self.is_sharing = UiCheckBox(self, "启动后自动开启共享", False)
        layout_extra_options.addWidget(self.is_sharing)

        self.flash_attention_check = UiCheckBox(self, "启用 Flash Attention -fa", True)
        layout_extra_options.addWidget(self.flash_attention_check)

        self.no_mmap_check = UiCheckBox(self, "启用 --no-mmap", True)
        layout_extra_options.addWidget(self.no_mmap_check)
        layout.addLayout(layout_extra_options)

        layout.addLayout(UiRow("配置预设选择", self._create_preset_options()))
        layout.addLayout(
            UiRow("GPU层数 -ngl", UiSlider(self, "gpu_layers", 200, 0, 200, 1))
        )
        layout.addLayout(self._create_ip_port_log_option())

        layout.addLayout(self._create_benchmark_layout())

    def _init_override_options(self, layout):
        # 新增llamacpp覆盖选项
        self.llamacpp_override = UiLineEdit(self, "覆盖默认llamacpp路径（可选）", "")
        layout.addWidget(self.llamacpp_override)

        self.custom_command_append = TextEdit(self)
        self.custom_command_append.setPlaceholderText(
            "手动追加命令（追加到UI选择的命令后）"
        )
        layout.addWidget(self.custom_command_append)

        self.custom_command = TextEdit(self)
        self.custom_command.setPlaceholderText("手动自定义命令（覆盖UI选择）")
        layout.addWidget(self.custom_command)

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

        self.context_length.valueChanged.connect(self.update_context_from_slider)
        self.context_length_input.valueChanged.connect(self.update_slider_from_input)

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
        self.update_context_per_thread()

    def update_slider_from_input(self, value):

        value = round(value / 256) * 256
        slider_value = self.context_to_slider(value)
        slider_value = max(0, min(10000, slider_value))
        self.context_length.setValue(slider_value)
        self.context_length.update()
        self.update_context_per_thread()

    def update_context_per_thread(self):
        total_context = self.context_length_input.value()
        n_parallel = self.n_parallel_spinbox.value()
        context_per_thread = total_context // n_parallel
        self.context_per_thread_label.setText(
            f"每个工作线程的上下文大小: {context_per_thread}"
        )

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
                "flash_attention": self.flash_attention_check.isChecked(),
                "no_mmap": self.no_mmap_check.isChecked(),
                "gpu": self.gpu_combo.currentText(),
                "model_path": self.model_path.currentText(),
                "context_length": self.context_length_input.value(),
                "n_parallel": self.n_parallel_spinbox.value(),
                "host": self.host_input.currentText(),
                "port": self.port_input.text(),
                "log_format": self.log_format_combo.currentText(),
                "gpu_index": self.manully_select_gpu_index.text(),
                "npp": self.npp_input.text(),
                "ntg": self.ntg_input.text(),
                "npl": self.npl_input.text(),
                "pps": self.pps_check.isChecked(),
                "llamacpp_override": self.llamacpp_override.text(),
                "is_sharing": self.is_sharing.isChecked(),
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
                    self.gpu_layers_spinbox.setValue(config.get("gpu_layers", 200))
                    self.model_path.setCurrentText(config.get("model_path", ""))
                    self.context_length_input.setValue(
                        config.get("context_length", 2048)
                    )
                    self.n_parallel_spinbox.setValue(config.get("n_parallel", 1))
                    self.host_input.setCurrentText(config.get("host", "127.0.0.1"))
                    self.port_input.setText(config.get("port", "8080"))
                    self.log_format_combo.setCurrentText(
                        config.get("log_format", "none")
                    )
                    self.flash_attention_check.setChecked(
                        config.get("flash_attention", True)
                    )
                    self.npp_input.setText(config.get("npp", "128,256,512"))
                    self.ntg_input.setText(config.get("ntg", "128,256"))
                    self.npl_input.setText(config.get("npl", "1,2,4,8,16,32"))
                    self.pps_check.setChecked(config.get("pps", False))
                    self.no_mmap_check.setChecked(config.get("no_mmap", True))
                    self.gpu_combo.setCurrentText(config.get("gpu", ""))
                    self.manully_select_gpu_index.setText(config.get("gpu_index", ""))
                    self.llamacpp_override.setText(config.get("llamacpp_override", ""))
                    self.is_sharing.setChecked(config.get("is_sharing", False))
                    self.update_context_per_thread()
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
