from enum import Enum
import logging
import os
import json
import math
import subprocess
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QGroupBox
from qfluentwidgets import (
    ComboBox,
    PushButton,
    SpinBox,
    PrimaryPushButton,
    TextEdit,
    EditableComboBox,
    MessageBox,
    FluentIcon as FIF,
    Slider,
)

from .common import CURRENT_DIR, CONFIG_FILE
from .ui import *


class GPUType(Enum):
    NVIDIA = 1
    AMD = 2
    UNKNOWN = 3


class GPUManager:
    def __init__(self):
        self.nvidia_gpus = []
        self.amd_gpus = []
        self.detect_gpus()

    def detect_gpus(self):
        # 检测NVIDIA GPU
        try:
            os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            result = subprocess.run(
                "nvidia-smi --query-gpu=name --format=csv,noheader",
                shell=True,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                self.nvidia_gpus = result.stdout.strip().split("\n")
        except Exception as e:
            logging.error(f"检测NVIDIA GPU时出错: {str(e)}")

        # 检测AMD GPU
        try:
            import wmi

            c = wmi.WMI()
            amd_gpus_temp = []
            for gpu in c.Win32_VideoController():
                if "AMD" in gpu.Name or "ATI" in gpu.Name:
                    amd_gpus_temp.append(gpu.Name)
            logging.info(f"检测到AMD GPU(正向列表): {amd_gpus_temp}")
            # 反向添加AMD GPU
            self.amd_gpus = list(reversed(amd_gpus_temp))
            logging.info(f"检测到AMD GPU(反向列表): {self.amd_gpus}")
        except Exception as e:
            logging.error(f"检测AMD GPU时出错: {str(e)}")

    def get_gpu_type(self, gpu_name):
        if "NVIDIA" in gpu_name.upper():
            return GPUType.NVIDIA
        elif "AMD" in gpu_name.upper() or "ATI" in gpu_name.upper():
            return GPUType.AMD
        else:
            return GPUType.UNKNOWN

    def set_gpu_env(self, env, selected_gpu, selected_index, manual_index=None):
        gpu_type = self.get_gpu_type(selected_gpu)
        if manual_index == "":
            manual_index = None
        if gpu_type == GPUType.NVIDIA:
            if manual_index is not None:
                env["CUDA_VISIBLE_DEVICES"] = str(manual_index)
                logging.info(f"设置 CUDA_VISIBLE_DEVICES = {manual_index}")
            else:
                env["CUDA_VISIBLE_DEVICES"] = str(selected_index)
                logging.info(f"设置 CUDA_VISIBLE_DEVICES = {selected_index}")
        elif gpu_type == GPUType.AMD:
            if manual_index is not None:
                env["HIP_VISIBLE_DEVICES"] = str(manual_index - len(self.nvidia_gpus))
                logging.info(
                    f"设置 HIP_VISIBLE_DEVICES = {manual_index - len(self.nvidia_gpus)}"
                )
            else:
                env["HIP_VISIBLE_DEVICES"] = str(selected_index - len(self.nvidia_gpus))
                logging.info(
                    f"设置 HIP_VISIBLE_DEVICES = {selected_index - len(self.nvidia_gpus)}"
                )
        else:
            logging.warning(f"未知的GPU类型: {selected_gpu}")
        return env


class RunServerSection(QFrame):
    def __init__(self, title, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName(title.replace(" ", "-"))
        self.title = title

        self._init_ui()
        self.load_presets()
        self.refresh_models()
        self.refresh_gpus()
        self.load_selected_preset()
        self.load_advanced_state()  # 新增：加载高级设置状态

    def _init_ui(self):
        menu_base = self._create_menu_base()
        menu_advance = self._create_advance_menu()

        layout = QVBoxLayout()
        layout.addLayout(menu_base)
        layout.addWidget(menu_advance)
        layout.insertStretch(-1)
        self.setLayout(layout)

        self.context_length_input.valueChanged.connect(self.update_slider_from_input)
        self.context_length.valueChanged.connect(self.update_context_per_thread)
        self.n_parallel_spinbox.valueChanged.connect(self.update_context_per_thread)
        self.update_context_per_thread()

    def _create_menu_base(self):
        self.benchmark_button = PushButton(FIF.UNIT, "性能测试")
        self.run_and_share_button = PushButton(FIF.IOT, "启动/共享")
        self.run_button = PrimaryPushButton(FIF.PLAY, "启动")

        buttons_group = UiButtonGroup(
            UiButton("高级设置", FIF.MORE, self.toggle_advanced_settings),
            self.benchmark_button,
            self.run_and_share_button,
            self.run_button,
        )

        self.context_per_thread_label = QLabel()

        return UiCol(
            buttons_group,
            UiOptionRow("模型", self._create_model_selection_layout()),
            UiOptionRow("显卡", self._create_gpu_selection_layout()),
            UiOptionRow(
                "上下文长度 -c",
                self._create_context_length_layout(),
                label_width=74,
            ),
            UiOptionRow(
                "并发数量 -np",
                UiSlider(self, "n_parallel", 1, 1, 32, 1, spinbox_fixed_width=140),
                label_width=74,
            ),
            self.context_per_thread_label,
        )

    def _create_preset_options(self):
        self.config_preset_combo = EditableComboBox(self)
        self.config_preset_combo.currentIndexChanged.connect(self.load_selected_preset)

        self.save_preset_button = PushButton(FIF.SAVE, "保存")
        self.save_preset_button.clicked.connect(self.save_preset)

        self.load_preset_button = PushButton(FIF.SYNC, "刷新")
        self.load_preset_button.clicked.connect(self.load_presets)

        return UiRow(
            (self.config_preset_combo, 1),
            (self.save_preset_button, 0),
            (self.load_preset_button, 0),
        )

    def _create_ip_port_log_option(self):
        self.host_input = UiEditableComboBox(["127.0.0.1", "0.0.0.0"])
        self.port_input = UiLineEdit("", "8080")
        self.gpu_layers_spinbox = SpinBox()
        self.gpu_layers_spinbox.setRange(0, 200)
        self.gpu_layers_spinbox.setValue(200)
        return UiRow(
            UiOptionCol("主机地址 --host", self.host_input),
            UiOptionCol("端口 --port", self.port_input),
            UiOptionCol("GPU层数 -ngl", self.gpu_layers_spinbox),
        )

    def _create_benchmark_layout(self):
        self.npp_input = UiLineEdit("Prompt数量", "768")
        self.ntg_input = UiLineEdit("生成文本数量", "384")
        self.npl_input = UiLineEdit("并行Prompt数量", "1,2,4,8,16")
        return UiRow(
            UiOptionCol("Prompt数量 -npp", self.npp_input),
            UiOptionCol("生成文本数量 -ntg", self.ntg_input),
            UiOptionCol("并行Prompt数量 -npl", self.npl_input),
        )

    def _create_advance_menu(self):
        self.flash_attention_check = UiCheckBox("启用 Flash Attention -fa", True)
        self.no_mmap_check = UiCheckBox("启用 --no-mmap", True)
        layout_extra_options = UiRow(
            self.flash_attention_check,
            self.no_mmap_check,
            None,
        )
        layout_extra_options.setContentsMargins(0, 0, 0, 0)  # 设置内部边距

        self.llamacpp_override = UiLineEdit("覆盖默认llamacpp路径（可选）", "")
        self.custom_command_append = UiLineEdit("手动追加命令，到UI选择的命令后", "")

        self.custom_command = TextEdit()
        self.custom_command.setAcceptRichText(False)
        self.custom_command.setPlaceholderText("手动自定义命令（覆盖UI选择）")

        layout = UiCol(
            UiHLine(),
            layout_extra_options,
            UiOptionRow("配置预设选择", self._create_preset_options()),
            self._create_ip_port_log_option(),
            self._create_benchmark_layout(),
            self.llamacpp_override,
            self.custom_command_append,
            self.custom_command,
        )
        layout.setContentsMargins(0, 0, 0, 0)  # 确保布局的边距也被移除
        self.menu_advance = QFrame()
        self.menu_advance.setLayout(layout)
        self.menu_advance.setVisible(False)
        return self.menu_advance

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
        self.context_length_input.setFixedWidth(140)

        layout.addWidget(self.context_length)
        layout.addWidget(self.context_length_input)

        self.context_length.valueChanged.connect(self.update_context_from_slider)
        self.context_length_input.valueChanged.connect(self.update_slider_from_input)

        return layout

    def _create_model_selection_layout(self):
        layout = QHBoxLayout()
        self.model_path = EditableComboBox(self)
        self.model_path.setPlaceholderText("请选择模型路径")
        self.refresh_model_button = PushButton(FIF.SYNC, "刷新")
        self.refresh_model_button.clicked.connect(self.refresh_models)
        self.refresh_model_button.setFixedWidth(140)
        layout.addWidget(self.model_path)
        layout.addWidget(self.refresh_model_button)
        return layout

    def refresh_models(self):
        self.model_path.clear()
        models = []
        search_paths = [CURRENT_DIR] + self.main_window.get_model_search_paths()
        logging.debug(f"搜索路径: {search_paths}")
        for path in search_paths:
            logging.debug(f"正在搜索路径: {path}")
            if os.path.exists(path):
                logging.debug(f"路径存在: {path}")
                if os.path.isdir(path):
                    logging.debug(f"路径是目录: {path}")
                    for root, dirs, files in os.walk(path):
                        logging.debug(f"正在搜索子目录: {root}")
                        logging.debug(f"文件列表: {files}")
                        for f in files:
                            if f.endswith(".gguf"):
                                full_path = os.path.join(root, f)
                                logging.debug(f"找到模型文件: {full_path}")
                                models.append(full_path)
                else:
                    logging.debug(f"路径不是目录: {path}")
            else:
                logging.debug(f"路径不存在: {path}")

        logging.debug(f"找到的模型文件: {models}")

        # 从设置中获取排序选项
        sort_option = self.main_window.settings_section.model_sort_combo.currentText()

        # 根据选择的排序方式对模型列表进行排序
        if sort_option == "修改时间":
            models.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        elif sort_option == "文件名":
            models.sort(key=lambda x: os.path.basename(x).lower())
        elif sort_option == "文件大小":
            models.sort(key=lambda x: os.path.getsize(x), reverse=True)

        self.model_path.addItems(models)

    def _create_gpu_selection_layout(self):
        layout = QHBoxLayout()
        self.gpu_combo = ComboBox(self)
        self.manully_select_gpu_index = LineEdit(self)
        self.manully_select_gpu_index.setPlaceholderText("手动指定GPU索引")
        self.manully_select_gpu_index.setFixedWidth(140)
        layout.addWidget(self.gpu_combo)
        layout.addWidget(self.manully_select_gpu_index)
        return layout

    def refresh_gpus(self):
        self.gpu_combo.clear()
        self.nvidia_gpus = self.main_window.gpu_manager.nvidia_gpus
        self.amd_gpus = self.main_window.gpu_manager.amd_gpus

        # 优先添加NVIDIA GPU
        if self.nvidia_gpus:
            self.gpu_combo.addItems(self.nvidia_gpus)

        # 如果有AMD GPU，添加到列表末尾
        if self.amd_gpus:
            self.gpu_combo.addItems(self.amd_gpus)

        if not self.nvidia_gpus and not self.amd_gpus:
            logging.warning("未检测到NVIDIA或AMD GPU")

        self.gpu_combo.addItems(["自动"])

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
                "custom_command_append": self.custom_command_append.text(),
                "gpu_layers": self.gpu_layers_spinbox.value(),
                "flash_attention": self.flash_attention_check.isChecked(),
                "no_mmap": self.no_mmap_check.isChecked(),
                "gpu": self.gpu_combo.currentText(),
                "model_path": self.model_path.currentText(),
                "context_length": self.context_length_input.value(),
                "n_parallel": self.n_parallel_spinbox.value(),
                "host": self.host_input.currentText(),
                "port": self.port_input.text(),
                "gpu_index": self.manully_select_gpu_index.text(),
                "npp": self.npp_input.text(),
                "ntg": self.ntg_input.text(),
                "npl": self.npl_input.text(),
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

        self.load_presets(preset_name)  # 传入当前预设名称
        UiInfoBarSuccess(self, "预设已保存")

    def load_presets(self, current_preset=None):
        self.config_preset_combo.blockSignals(True)  # 阻止信号触发
        self.config_preset_combo.clear()
        presets = self.load_presets_from_file()
        if not presets or presets == {}:
            self.config_preset_combo.blockSignals(False)
            return
        if self.title in presets:
            preset_names = [preset["name"] for preset in presets[self.title]]
            self.config_preset_combo.addItems(preset_names)
            if current_preset and current_preset in preset_names:
                self.config_preset_combo.setCurrentText(current_preset)
            elif preset_names:
                self.config_preset_combo.setCurrentText(preset_names[0])
        self.config_preset_combo.blockSignals(False)  # 恢复信号
        self.load_selected_preset()  # 加载选中的预设

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
                    self.custom_command_append.setText(
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
                    self.flash_attention_check.setChecked(
                        config.get("flash_attention", True)
                    )
                    self.npp_input.setText(config.get("npp", "768"))
                    self.ntg_input.setText(config.get("ntg", "384"))
                    self.npl_input.setText(config.get("npl", "1,2,4,8,16"))
                    self.no_mmap_check.setChecked(config.get("no_mmap", True))
                    self.gpu_combo.setCurrentText(config.get("gpu", ""))
                    self.manully_select_gpu_index.setText(config.get("gpu_index", ""))
                    self.llamacpp_override.setText(config.get("llamacpp_override", ""))
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

    def toggle_advanced_settings(self):
        new_state = not self.menu_advance.isVisible()
        self.menu_advance.setVisible(new_state)
        if self.main_window.settings_section.remember_advanced_state.isChecked():
            self.save_advanced_state()

    def load_advanced_state(self):
        config_file_path = os.path.join(CURRENT_DIR, CONFIG_FILE)
        try:
            with open(config_file_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            if (
                config.get("remember_advanced_state", False)
                and self.main_window.settings_section.remember_advanced_state.isChecked()
            ):
                self.menu_advance.setVisible(config.get("advanced_state", False))
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def save_advanced_state(self):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config_data = json.load(f)
            config_data["advanced_state"] = self.menu_advance.isVisible()
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
