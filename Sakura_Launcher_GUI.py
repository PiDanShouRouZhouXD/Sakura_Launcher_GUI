import sys
import os
import json
import subprocess
import logging
import requests
import math
import re
import time
import zipfile
import py7zr
import shutil
from enum import Enum
from functools import partial
from hashlib import sha256
from PySide6.QtCore import Qt, Signal, QObject, Slot, QTimer, QThread
from PySide6.QtWidgets import QApplication, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGroupBox, QHeaderView, QTableWidgetItem, QWidget, QStackedWidget, QSpacerItem, QSizePolicy
from PySide6.QtGui import QIcon, QColor
from qfluentwidgets import PushButton, CheckBox, SpinBox, PrimaryPushButton, TextEdit, EditableComboBox, MessageBox, setTheme, Theme, MSFluentWindow, FluentIcon as FIF, Slider, ComboBox, setThemeColor, LineEdit, HyperlinkButton, NavigationItemPosition, TableWidget, TransparentPushButton, SegmentedWidget, InfoBar, InfoBarPosition, ProgressBar

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_self_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    else:
        return os.path.join(os.path.abspath("."), relative_path)

CURRENT_DIR = get_self_path()
CONFIG_FILE = 'sakura-launcher_config.json'
ICON_FILE = 'icon.png'
CLOUDFLARED = 'cloudflared-windows-amd64.exe'
SAKURA_LAUNCHER_GUI_VERSION = '0.0.8-beta'

processes = []

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
            result = subprocess.run('nvidia-smi --query-gpu=name --format=csv,noheader', shell=True, capture_output=True, text=True)
            if result.returncode == 0:
                self.nvidia_gpus = result.stdout.strip().split('\n')
        except Exception as e:
            logging.error(f"检测NVIDIA GPU时出错: {str(e)}")

        # 检测AMD GPU
        try:
            import wmi
            c = wmi.WMI()
            amd_gpus_temp = []
            for gpu in c.Win32_VideoController():
                if 'AMD' in gpu.Name or 'ATI' in gpu.Name:
                    amd_gpus_temp.append(gpu.Name)
            logging.info(f"检测到AMD GPU(正向列表): {amd_gpus_temp}")
            # 反向添加AMD GPU
            self.amd_gpus = list(reversed(amd_gpus_temp))
            logging.info(f"检测到AMD GPU(反向列表): {self.amd_gpus}")
        except Exception as e:
            logging.error(f"检测AMD GPU时出错: {str(e)}")

    def get_gpu_type(self, gpu_name):
        if 'NVIDIA' in gpu_name.upper():
            return GPUType.NVIDIA
        elif 'AMD' in gpu_name.upper() or 'ATI' in gpu_name.upper():
            return GPUType.AMD
        else:
            return GPUType.UNKNOWN

    def set_gpu_env(self, selected_gpu, selected_index, manual_index=None):
        gpu_type = self.get_gpu_type(selected_gpu)
        if manual_index == '':
            manual_index = None
        if gpu_type == GPUType.NVIDIA:
            if manual_index is not None:
                os.environ["CUDA_VISIBLE_DEVICES"] = str(manual_index)
                logging.info(f"设置 CUDA_VISIBLE_DEVICES = {manual_index}")
            else:
                os.environ["CUDA_VISIBLE_DEVICES"] = str(selected_index)
                logging.info(f"设置 CUDA_VISIBLE_DEVICES = {selected_index}")
        elif gpu_type == GPUType.AMD:
            if manual_index is not None:
                os.environ["HIP_VISIBLE_DEVICES"] = str(manual_index - len(self.nvidia_gpus))
                logging.info(f"设置 HIP_VISIBLE_DEVICES = {manual_index - len(self.nvidia_gpus)}")
            else:
                os.environ["HIP_VISIBLE_DEVICES"] = str(selected_index - len(self.nvidia_gpus))
                logging.info(f"设置 HIP_VISIBLE_DEVICES = {selected_index - len(self.nvidia_gpus)}")
        else:
            logging.warning(f"未知的GPU类型: {selected_gpu}")

class LlamaCPPWorker(QObject):
    progress = Signal(str)
    finished = Signal(bool)

    def __init__(self, command):
        super().__init__()
        self.command = command

    def run(self):
        try:
            self.progress.emit(f"Running command: {self.command}")
            proc = subprocess.Popen(self.command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            processes.append(proc)
            for line in iter(proc.stdout.readline, b''):
                self.progress.emit(line.decode('utf-8').strip())
            while proc.poll() is None:
                for line in iter(proc.stdout.readline, b''):
                    self.progress.emit(line.decode('utf-8').strip())
                for line in iter(proc.stderr.readline, b''):
                    self.progress.emit("stderr: " + line.decode('utf-8').strip())
            if proc.returncode == 0:
                self.finished.emit(True)
            else:
                self.progress.emit("Error: Command failed with exit code {}".format(proc.returncode))
                self.finished.emit(False)
        except Exception as e:
            self.progress.emit(f"Error: {str(e)}")
            self.finished.emit(False)

    def terminate_all(self):
        for proc in processes:
            proc.terminate()
        processes.clear()

class RunSection(QFrame):
    def __init__(self, title, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName(title.replace(' ', '-'))
        self.title = title

    def _init_common_ui(self, layout):
        # 跳过
        pass

    def _create_gpu_selection_layout(self):
        layout = QHBoxLayout()
        self.gpu_enabled_check = self._create_check_box("单GPU启动", True)
        self.gpu_enabled_check.stateChanged.connect(self.toggle_gpu_selection)
        self.gpu_combo = ComboBox(self)
        self.manully_select_gpu_index = LineEdit(self)
        self.manully_select_gpu_index.setPlaceholderText("手动指定GPU索引")
        self.manully_select_gpu_index.setFixedWidth(140)
        layout.addWidget(self.gpu_enabled_check)
        layout.addWidget(self.manully_select_gpu_index)
        layout.addWidget(self.gpu_combo)
        return layout

    def _create_line_edit(self, placeholder, text):
        line_edit = LineEdit(self)
        line_edit.setPlaceholderText(placeholder)
        line_edit.setText(text)
        return line_edit

    def _create_slider_spinbox_layout(self, label_text, variable_name, slider_value, slider_min, slider_max, slider_step):
        layout = QVBoxLayout()
        label = QLabel(label_text)
        layout.addWidget(label)

        h_layout = QHBoxLayout()
        slider = Slider(Qt.Horizontal, self)
        slider.setRange(slider_min, slider_max)
        slider.setPageStep(slider_step)
        slider.setValue(slider_value)

        spinbox = SpinBox(self)
        spinbox.setRange(slider_min, slider_max)
        spinbox.setSingleStep(slider_step)
        spinbox.setValue(slider_value)

        slider.valueChanged.connect(spinbox.setValue)
        spinbox.valueChanged.connect(slider.setValue)

        h_layout.addWidget(slider)
        h_layout.addWidget(spinbox)
        layout.addLayout(h_layout)

        setattr(self, f"{variable_name.replace(' ', '_')}", slider)
        setattr(self, f"{variable_name.replace(' ', '_')}_spinbox", spinbox)

        return layout

    def _create_model_selection_layout(self):
        layout = QHBoxLayout()
        self.model_path = EditableComboBox(self)
        self.model_path.setPlaceholderText("请选择模型路径")
        self.refresh_model_button = PushButton(FIF.SYNC, '刷新模型', self)
        self.refresh_model_button.clicked.connect(self.refresh_models)
        layout.addWidget(self.model_path)
        layout.addWidget(self.refresh_model_button)
        return layout

    def _create_check_box(self, text, checked):
        check_box = CheckBox(text, self)
        check_box.setChecked(checked)
        return check_box

    def _create_editable_combo_box(self, items):
        combo_box = EditableComboBox(self)
        combo_box.addItems(items)
        return combo_box

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
                            if f.endswith('.gguf'):
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
        if sort_option == '修改时间':
            models.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        elif sort_option == '文件名':
            models.sort(key=lambda x: os.path.basename(x).lower())
        elif sort_option == '文件大小':
            models.sort(key=lambda x: os.path.getsize(x), reverse=True)
        
        self.model_path.addItems(models)

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

    def toggle_gpu_selection(self):
        self.gpu_combo.setEnabled(self.gpu_enabled_check.isChecked())

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

        buttons_group = QGroupBox("")
        buttons_layout = QHBoxLayout()

        self.save_preset_button = PushButton(FIF.SAVE, '保存预设', self)
        self.save_preset_button.clicked.connect(self.save_preset)
        self.save_preset_button.setFixedSize(110, 30)
        buttons_layout.addWidget(self.save_preset_button)

        self.load_preset_button = PushButton(FIF.SYNC, '刷新预设', self)
        self.load_preset_button.clicked.connect(self.load_presets)
        self.load_preset_button.setFixedSize(110, 30)
        buttons_layout.addWidget(self.load_preset_button)

        self.run_button = PrimaryPushButton(FIF.PLAY, '运行', self)
        self.run_button.setFixedSize(110, 30)
        buttons_layout.addWidget(self.run_button)

        buttons_layout.setAlignment(Qt.AlignRight)
        buttons_group.setStyleSheet(""" QGroupBox {border: 0px solid darkgray; background-color: #202020; border-radius: 8px;}""")

        buttons_group.setLayout(buttons_layout)
        layout.addWidget(buttons_group)

        layout.addWidget(QLabel("模型选择"))
        layout.addLayout(self._create_model_selection_layout())
        layout.addWidget(QLabel("配置预设选择"))
        self.config_preset_combo = EditableComboBox(self)
        self.config_preset_combo.currentIndexChanged.connect(self.load_selected_preset)
        layout.addWidget(self.config_preset_combo)

        ip_port_log_layout = QHBoxLayout()

        ip_layout = QVBoxLayout()
        self.host_input = self._create_editable_combo_box(["127.0.0.1", "0.0.0.0"])
        ip_layout.addWidget(QLabel("主机地址 --host"))
        ip_layout.addWidget(self.host_input)

        host_layout = QVBoxLayout()
        self.port_input = self._create_line_edit("", "8080")
        host_layout.addWidget(QLabel("端口 --port"))
        host_layout.addWidget(self.port_input)

        log_layout = QVBoxLayout()
        self.log_format_combo = self._create_editable_combo_box(["none", "text", "json"])
        log_layout.addWidget(QLabel("日志格式 --log-format"))
        log_layout.addWidget(self.log_format_combo)

        ip_port_log_layout.addLayout(ip_layout)
        ip_port_log_layout.addLayout(host_layout)
        ip_port_log_layout.addLayout(log_layout)

        layout.addLayout(ip_port_log_layout)

        layout.addLayout(self._create_slider_spinbox_layout("GPU层数 -ngl", "gpu_layers", 200, 0, 200, 1))

        layout.addWidget(QLabel("上下文长度 -c"))
        layout.addLayout(self._create_context_length_layout())

        layout.addLayout(self._create_slider_spinbox_layout("并行工作线程数 -np", "n_parallel", 1, 1, 32, 1))

        self.context_per_thread_label = QLabel(self)
        layout.addWidget(self.context_per_thread_label)

        self.flash_attention_check = self._create_check_box("启用 Flash Attention -fa", True)
        layout.addWidget(self.flash_attention_check)

        self.no_mmap_check = self._create_check_box("启用 --no-mmap", True)
        layout.addWidget(self.no_mmap_check)

        self.is_sharing = self._create_check_box("启动后自动开启共享", False)
        layout.addWidget(self.is_sharing)

        layout.addLayout(self._create_gpu_selection_layout())

        # 新增llamacpp覆盖选项
        self.llamacpp_override = self._create_line_edit("覆盖默认llamacpp路径（可选）", "")
        layout.addWidget(QLabel("覆盖默认llamacpp路径"))
        layout.addWidget(self.llamacpp_override)

        self.custom_command_append = TextEdit(self)
        self.custom_command_append.setPlaceholderText("手动追加命令（追加到UI选择的命令后）")
        layout.addWidget(self.custom_command_append)

        self.custom_command = TextEdit(self)
        self.custom_command.setPlaceholderText("手动自定义命令（覆盖UI选择）")
        layout.addWidget(self.custom_command)

        self.setLayout(layout)

        self.context_length_input.valueChanged.connect(self.update_slider_from_input)
        self.context_length.valueChanged.connect(self.update_context_per_thread)
        self.n_parallel_spinbox.valueChanged.connect(self.update_context_per_thread)

        self.update_context_per_thread()


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
        self.context_per_thread_label.setText(f"每个线程的context数量: {context_per_thread}")

    def save_preset(self):
        preset_name = self.config_preset_combo.currentText()
        if not preset_name:
            MessageBox("错误", "预设名称不能为空", self).exec()
            return

        config_file_path = os.path.join(CURRENT_DIR, CONFIG_FILE)
        if not os.path.exists(config_file_path):
            with open(config_file_path, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=4)

        with open(config_file_path, 'r', encoding='utf-8') as f:
            try:
                current_settings = json.load(f)
            except json.JSONDecodeError:
                current_settings = {}

        preset_section = current_settings.get(self.title, [])
        new_preset = {
            'name': preset_name,
            'config': {
                'custom_command': self.custom_command.toPlainText(),
                'custom_command_append': self.custom_command_append.toPlainText(),
                'gpu_layers': self.gpu_layers_spinbox.value(),
                'flash_attention': self.flash_attention_check.isChecked(),
                'no_mmap': self.no_mmap_check.isChecked(),
                'gpu_enabled': self.gpu_enabled_check.isChecked(),
                'gpu': self.gpu_combo.currentText(),
                'model_path': self.model_path.currentText(),
                'context_length': self.context_length_input.value(),
                'n_parallel': self.n_parallel_spinbox.value(),
                'host': self.host_input.currentText(),
                'port': self.port_input.text(),
                'log_format': self.log_format_combo.currentText(),
                'gpu_index': self.manully_select_gpu_index.text(),
                'llamacpp_override': self.llamacpp_override.text(),
                'is_sharing': self.is_sharing.isChecked()
            }
        }

        for i, preset in enumerate(preset_section):
            if preset['name'] == preset_name:
                preset_section[i] = new_preset
                break
        else:
            preset_section.append(new_preset)

        current_settings[self.title] = preset_section

        with open(config_file_path, 'w', encoding='utf-8') as f:
            json.dump(current_settings, f, ensure_ascii=False, indent=4)

        self.load_presets()
        self.main_window.createSuccessInfoBar("成功", "预设已保存")

    def load_presets(self):
        self.config_preset_combo.clear()
        presets = self.load_presets_from_file()
        if not presets or presets == {}:
            return
        if self.title in presets:
            self.config_preset_combo.addItems([preset['name'] for preset in presets[self.title]])

    def load_selected_preset(self):
        preset_name = self.config_preset_combo.currentText()
        presets = self.load_presets_from_file()
        if not presets or presets == {}:
            return
        if self.title in presets:
            for preset in presets[self.title]:
                if preset['name'] == preset_name:
                    config = preset['config']
                    self.custom_command.setPlainText(config.get('custom_command', ''))
                    self.custom_command_append.setPlainText(config.get('custom_command_append', ''))
                    self.gpu_layers_spinbox.setValue(config.get('gpu_layers', 200))
                    self.model_path.setCurrentText(config.get('model_path', ''))
                    self.context_length_input.setValue(config.get('context_length', 2048))
                    self.n_parallel_spinbox.setValue(config.get('n_parallel', 1))
                    self.host_input.setCurrentText(config.get('host', '127.0.0.1'))
                    self.port_input.setText(config.get('port', '8080'))
                    self.log_format_combo.setCurrentText(config.get('log_format', 'none'))
                    self.flash_attention_check.setChecked(config.get('flash_attention', True))
                    self.no_mmap_check.setChecked(config.get('no_mmap', True))
                    self.gpu_enabled_check.setChecked(config.get('gpu_enabled', True))
                    self.gpu_combo.setCurrentText(config.get('gpu', ''))
                    self.manully_select_gpu_index.setText(config.get('gpu_index', ''))
                    self.llamacpp_override.setText(config.get('llamacpp_override', ''))
                    self.is_sharing.setChecked(config.get('is_sharing', False))
                    self.update_context_per_thread()
                    break

    def load_presets_from_file(self):
        config_file_path = os.path.join(CURRENT_DIR, CONFIG_FILE)
        if os.path.exists(config_file_path):
            with open(config_file_path, 'r', encoding='utf-8') as f:
                try:
                    return json.load(f) or {}
                except json.JSONDecodeError:
                    return {}
        return {}

class RunBenchmarkSection(RunSection):
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

        self.save_preset_button = PushButton(FIF.SAVE, '保存预设', self)
        self.save_preset_button.clicked.connect(self.save_preset)
        self.save_preset_button.setFixedSize(110, 30)
        buttons_layout.addWidget(self.save_preset_button)

        self.load_preset_button = PushButton(FIF.SYNC, '刷新预设', self)
        self.load_preset_button.clicked.connect(self.load_presets)
        self.load_preset_button.setFixedSize(110, 30)
        buttons_layout.addWidget(self.load_preset_button)

        self.run_button = PrimaryPushButton(FIF.PLAY, '运行', self)
        self.run_button.setFixedSize(110, 30)
        buttons_layout.addWidget(self.run_button)

        buttons_layout.setAlignment(Qt.AlignRight)
        buttons_group.setStyleSheet(""" QGroupBox {border: 0px solid darkgray; background-color: #202020; border-radius: 8px;}""")
        buttons_group.setLayout(buttons_layout)
        layout.addWidget(buttons_group)

        layout.addWidget(QLabel("模型选择"))
        layout.addLayout(self._create_model_selection_layout())
        layout.addWidget(QLabel("配置预设选择"))
        self.config_preset_combo = EditableComboBox(self)
        self.config_preset_combo.currentIndexChanged.connect(self.load_selected_preset)
        layout.addWidget(self.config_preset_combo)

        layout.addLayout(self._create_slider_spinbox_layout("GPU层数 -ngl", "gpu_layers", 200, 0, 200, 1))

        self.flash_attention_check = self._create_check_box("启用 Flash Attention -fa", True)
        layout.addWidget(self.flash_attention_check)

        self.no_mmap_check = self._create_check_box("启用 --no-mmap", True)
        layout.addWidget(self.no_mmap_check)

        layout.addLayout(self._create_gpu_selection_layout())

        # 新增llamacpp覆盖选项
        self.llamacpp_override = self._create_line_edit("覆盖默认llamacpp路径（可选）", "")
        layout.addWidget(QLabel("覆盖默认llamacpp路径"))
        layout.addWidget(self.llamacpp_override)

        self.custom_command_append = TextEdit(self)
        self.custom_command_append.setPlaceholderText("手动追加命令（追加到UI选择的命令后）")
        layout.addWidget(self.custom_command_append)

        self.custom_command = TextEdit(self)
        self.custom_command.setPlaceholderText("手动自定义命令（覆盖UI选择）")
        layout.addWidget(self.custom_command)

        self.setLayout(layout)

    def save_preset(self):
        preset_name = self.config_preset_combo.currentText()
        if not preset_name:
            MessageBox("错误", "预设名称不能为空", self).exec()
            return

        config_file_path = os.path.join(CURRENT_DIR, CONFIG_FILE)
        if not os.path.exists(config_file_path):
            with open(config_file_path, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=4)

        with open(config_file_path, 'r', encoding='utf-8') as f:
            try:
                current_settings = json.load(f)
            except json.JSONDecodeError:
                current_settings = {}

        preset_section = current_settings.get(self.title, [])
        new_preset = {
            'name': preset_name,
            'config': {
                'custom_command': self.custom_command.toPlainText(),
                'custom_command_append': self.custom_command_append.toPlainText(),
                'gpu_layers': self.gpu_layers_spinbox.value(),
                'flash_attention': self.flash_attention_check.isChecked(),
                'no_mmap': self.no_mmap_check.isChecked(),
                'gpu_enabled': self.gpu_enabled_check.isChecked(),
                'gpu': self.gpu_combo.currentText(),
                'model_path': self.model_path.currentText(),
                'gpu_index': self.manully_select_gpu_index.text(),
                'llamacpp_override': self.llamacpp_override.text()
            }
        }

        for i, preset in enumerate(preset_section):
            if preset['name'] == preset_name:
                preset_section[i] = new_preset
                break
        else:
            preset_section.append(new_preset)

        current_settings[self.title] = preset_section

        with open(config_file_path, 'w', encoding='utf-8') as f:
            json.dump(current_settings, f, ensure_ascii=False, indent=4)

        self.load_presets()
        self.main_window.createSuccessInfoBar("成功", "预设已保存")

    def load_presets(self):
        self.config_preset_combo.clear()
        presets = self.load_presets_from_file()
        if not presets or presets == {}:
            return
        if self.title in presets:
            self.config_preset_combo.addItems([preset['name'] for preset in presets[self.title]])

    def load_selected_preset(self):
        preset_name = self.config_preset_combo.currentText()
        presets = self.load_presets_from_file()
        if not presets or presets == {}:
            return
        if self.title in presets:
            for preset in presets[self.title]:
                if preset['name'] == preset_name:
                    config = preset['config']
                    self.custom_command.setPlainText(config.get('custom_command', ''))
                    self.custom_command_append.setPlainText(config.get('custom_command_append', ''))
                    self.gpu_layers_spinbox.setValue(config.get('gpu_layers', 99))
                    self.model_path.setCurrentText(config.get('model_path', ''))
                    self.flash_attention_check.setChecked(config.get('flash_attention', True))
                    self.no_mmap_check.setChecked(config.get('no_mmap', True))
                    self.gpu_enabled_check.setChecked(config.get('gpu_enabled', True))
                    self.gpu_combo.setCurrentText(config.get('gpu', ''))
                    self.manully_select_gpu_index.setText(config.get('gpu_index', ''))
                    self.llamacpp_override.setText(config.get('llamacpp_override', ''))
                    break

    def load_presets_from_file(self):
        config_file_path = os.path.join(CURRENT_DIR, CONFIG_FILE)
        if os.path.exists(config_file_path):
            with open(config_file_path, 'r', encoding='utf-8') as f:
                try:
                    return json.load(f) or {}
                except json.JSONDecodeError:
                    return {}
        return {}

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

        self.save_preset_button = PushButton(FIF.SAVE, '保存预设', self)
        self.save_preset_button.clicked.connect(self.save_preset)
        self.save_preset_button.setFixedSize(110, 30)
        buttons_layout.addWidget(self.save_preset_button)

        self.load_preset_button = PushButton(FIF.SYNC, '刷新预设', self)
        self.load_preset_button.clicked.connect(self.load_presets)
        self.load_preset_button.setFixedSize(110, 30)
        buttons_layout.addWidget(self.load_preset_button)

        self.run_button = PrimaryPushButton(FIF.PLAY, '运行', self)
        self.run_button.setFixedSize(110, 30)
        buttons_layout.addWidget(self.run_button)

        buttons_layout.setAlignment(Qt.AlignRight)
        buttons_group.setStyleSheet(""" QGroupBox {border: 0px solid darkgray; background-color: #202020; border-radius: 8px;}""")
        buttons_group.setLayout(buttons_layout)
        layout.addWidget(buttons_group)

        layout.addWidget(QLabel("模型选择"))
        layout.addLayout(self._create_model_selection_layout())
        layout.addWidget(QLabel("配置预设选择"))
        self.config_preset_combo = EditableComboBox(self)
        self.config_preset_combo.currentIndexChanged.connect(self.load_selected_preset)
        layout.addWidget(self.config_preset_combo)

        layout.addLayout(self._create_slider_spinbox_layout("GPU层数 -ngl", "gpu_layers", 200, 0, 200, 1))
        layout.addLayout(self._create_slider_spinbox_layout("最大上下文长度 -c", "ctx_size", 8192, 1, 65535, 512))

        layout.addWidget(QLabel("Prompt数量 -npp"))
        self.npp_input = self._create_line_edit("Prompt数量，多个值用英文逗号分隔，如： 128,256,512", "128,256,512")
        layout.addWidget(self.npp_input)

        layout.addWidget(QLabel("生成文本（text generation）数量 -ntg"))
        self.ntg_input = self._create_line_edit("生成文本（text generation）数量，多个值用英文逗号分隔，如： 128,256", "128,256")
        layout.addWidget(self.ntg_input)

        layout.addWidget(QLabel("并行Prompt数量 -npl"))
        self.npl_input = self._create_line_edit("并行Prompt数量，多个值用英文逗号分隔，如： 1,2,4,8,16,32", "1,2,4,8,16,32")
        layout.addWidget(self.npl_input)

        self.pps_check = self._create_check_box("Prompt共享 -pps", False)
        layout.addWidget(self.pps_check)

        self.flash_attention_check = self._create_check_box("启用 Flash Attention -fa", True)
        layout.addWidget(self.flash_attention_check)

        self.no_mmap_check = self._create_check_box("启用 --no-mmap", True)
        layout.addWidget(self.no_mmap_check)

        layout.addLayout(self._create_gpu_selection_layout())

        # 新增llamacpp覆盖选项
        self.llamacpp_override = self._create_line_edit("覆盖默认llamacpp路径（可选）", "")
        layout.addWidget(QLabel("覆盖默认llamacpp路径"))
        layout.addWidget(self.llamacpp_override)

        self.custom_command_append = TextEdit(self)
        self.custom_command_append.setPlaceholderText("手动追加命令（追加到UI选择的命令后）")
        layout.addWidget(self.custom_command_append)

        self.custom_command = TextEdit(self)
        self.custom_command.setPlaceholderText("手动自定义命令（覆盖UI选择）")
        layout.addWidget(self.custom_command)

        self.setLayout(layout)

    def save_preset(self):
        preset_name = self.config_preset_combo.currentText()
        if not preset_name:
            MessageBox("错误", "预设名称不能为空", self).exec()
            return

        config_file_path = os.path.join(CURRENT_DIR, CONFIG_FILE)
        if not os.path.exists(config_file_path):
            with open(config_file_path, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=4)

        with open(config_file_path, 'r', encoding='utf-8') as f:
            try:
                current_settings = json.load(f)
            except json.JSONDecodeError:
                current_settings = {}

        preset_section = current_settings.get(self.title, [])
        new_preset = {
            'name': preset_name,
            'config': {
                'custom_command': self.custom_command.toPlainText(),
                'custom_command_append': self.custom_command_append.toPlainText(),
                'gpu_layers': self.gpu_layers_spinbox.value(),
                'ctx_size': self.ctx_size_spinbox.value(),
                'flash_attention': self.flash_attention_check.isChecked(),
                'no_mmap': self.no_mmap_check.isChecked(),
                'gpu_enabled': self.gpu_enabled_check.isChecked(),
                'gpu': self.gpu_combo.currentText(),
                'gpu_index': self.manully_select_gpu_index.text(),
                'model_path': self.model_path.currentText(),
                'npp': self.npp_input.text(),
                'ntg': self.ntg_input.text(),
                'npl': self.npl_input.text(),
                'pps': self.pps_check.isChecked(),
                'llamacpp_override': self.llamacpp_override.text()
            }
        }

        for i, preset in enumerate(preset_section):
            if preset['name'] == preset_name:
                preset_section[i] = new_preset
                break
        else:
            preset_section.append(new_preset)

        current_settings[self.title] = preset_section

        with open(config_file_path, 'w', encoding='utf-8') as f:
            json.dump(current_settings, f, ensure_ascii=False, indent=4)

        self.load_presets()
        self.main_window.createSuccessInfoBar("成功", "预设已保存")

    def load_presets(self):
        self.config_preset_combo.clear()
        presets = self.load_presets_from_file()
        if not presets or presets == {}:
            return
        if self.title in presets:
            self.config_preset_combo.addItems([preset['name'] for preset in presets[self.title]])

    def load_selected_preset(self):
        preset_name = self.config_preset_combo.currentText()
        presets = self.load_presets_from_file()
        if not presets or presets == {}:
            return
        if self.title in presets:
            for preset in presets[self.title]:
                if preset['name'] == preset_name:
                    config = preset['config']
                    self.custom_command.setPlainText(config.get('custom_command', ''))
                    self.custom_command_append.setPlainText(config.get('custom_command_append', ''))
                    self.gpu_layers_spinbox.setValue(config.get('gpu_layers', 99))
                    self.ctx_size_spinbox.setValue(config.get('ctx_size', 8192))
                    self.model_path.setCurrentText(config.get('model_path', ''))
                    self.npp_input.setText(config.get('npp', ''))
                    self.ntg_input.setText(config.get('ntg', ''))
                    self.npl_input.setText(config.get('npl', ''))
                    self.pps_check.setChecked(config.get('pps', False))
                    self.flash_attention_check.setChecked(config.get('flash_attention', True))
                    self.no_mmap_check.setChecked(config.get('no_mmap', True))
                    self.gpu_enabled_check.setChecked(config.get('gpu_enabled', True))
                    self.gpu_combo.setCurrentText(config.get('gpu', ''))
                    self.manully_select_gpu_index.setText(config.get('gpu_index', ''))
                    self.llamacpp_override.setText(config.get('llamacpp_override', ''))
                    break

    def load_presets_from_file(self):
        config_file_path = os.path.join(CURRENT_DIR, CONFIG_FILE)
        if os.path.exists(config_file_path):
            with open(config_file_path, 'r', encoding='utf-8') as f:
                try:
                    return json.load(f) or {}
                except json.JSONDecodeError:
                    return {}
        return {}

class LogSection(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName(title.replace(' ', '-'))
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()

        self.log_display = TextEdit(self)
        self.log_display.setReadOnly(True)
        layout.addWidget(self.log_display)

        self.clear_log_button = PushButton(FIF.DELETE, "清空日志", self)
        self.clear_log_button.clicked.connect(self.clear_log)
        layout.addWidget(self.clear_log_button)

        self.setLayout(layout)

    def clear_log(self):
        self.log_display.clear()

    def log_info(self, message):
        self.log_display.append(message)
        self.log_display.ensureCursorVisible()

    @Slot()
    def terminate_all_processes(self):
        for proc in processes:
            proc.terminate()
        processes.clear()
        self.log_info("所有进程已终止。")

class DownloadThread(QThread):
    progress = Signal(int)
    finished = Signal()
    error = Signal(str)

    def __init__(self, url, filename, main_window):
        super().__init__()
        self.url = url
        self.filename = filename
        self.main_window = main_window
        self._is_finished = False

    def run(self):
        try:
            self.main_window.log_info(f"开始下载: {self.filename}")
            response = requests.get(self.url, stream=True)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            block_size = 1024  # 1 KB
            downloaded_size = 0

            file_path = os.path.join(get_self_path(), self.filename)
            with open(file_path, 'wb') as file:
                for data in response.iter_content(block_size):
                    size = file.write(data)
                    downloaded_size += size
                    if total_size > 0:
                        progress = int((downloaded_size / total_size) * 100)
                        self.progress.emit(progress)

            self.main_window.log_info(f"下载完成: {self.filename}")
            
            if not self._is_finished:
                self._is_finished = True
                self.finished.emit()
        except requests.RequestException as e:
            error_msg = f"下载出错: {str(e)}"
            self.main_window.log_info(error_msg)
            self.error.emit(error_msg)
        except IOError as e:
            error_msg = f"文件写入错误: {str(e)}"
            self.main_window.log_info(error_msg)
            self.error.emit(error_msg)
        except Exception as e:
            error_msg = f"未知错误: {str(e)}"
            self.main_window.log_info(error_msg)
            self.error.emit(error_msg)

    def safe_disconnect(self):
        self.main_window.log_info("正在断开下载线程的所有信号连接")
        try:
            self.progress.disconnect()
            self.main_window.log_info("断开 progress 信号")
        except TypeError:
            pass
        try:
            self.finished.disconnect()
            self.main_window.log_info("断开 finished 信号")
        except TypeError:
            pass
        try:
            self.error.disconnect()
            self.main_window.log_info("断开 error 信号")
        except TypeError:
            pass
        self.main_window.log_info("下载线程的所有信号已断开")

    def stop(self):
        self.main_window.log_info("正在停止下载线程")
        self.terminate()
        self.wait()
        self._is_finished = True
        self.main_window.log_info("下载线程已停止")

class DownloadSection(QFrame):
    model_links = [
        ("GalTransl-7B-v2-IQ4_XS.gguf", "https://hf-mirror.com/SakuraLLM/GalTransl-7B-v2/resolve/main/GalTransl-7B-v2-IQ4_XS.gguf"),
        ("sakura-14b-qwen2beta-v0.9.2-iq4xs.gguf", "https://hf-mirror.com/SakuraLLM/Sakura-14B-Qwen2beta-v0.9.2-GGUF/resolve/main/sakura-14b-qwen2beta-v0.9.2-iq4xs.gguf"),
        ("sakura-14b-qwen2beta-v0.9.2-q4km.gguf", "https://hf-mirror.com/SakuraLLM/Sakura-14B-Qwen2beta-v0.9.2-GGUF/resolve/main/sakura-14b-qwen2beta-v0.9.2-q4km.gguf"),
    ]
    llamacpp_links = [
        ("b3855-CUDA", "Nvidia独显", "https://mirror.ghproxy.com/https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI/releases/download/v0.0.3-alpha/llama-b3855-bin-win-cuda-cu12.2.0-x64.7z"),
        ("b3384-ROCm", "部分AMD独显", "https://mirror.ghproxy.com/https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI/releases/download/v0.0.3-alpha/llama-b3384-bin-win-rocm-avx2-x64.zip"),
        ("b3534-ROCm-780m", "部分AMD核显", "https://mirror.ghproxy.com/https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI/releases/download/v0.0.3-alpha/llama-b3534-bin-win-rocm-avx512-x64.zip"),
        ("b3855-Vulkan", "通用，不推荐", "https://mirror.ghproxy.com/https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI/releases/download/v0.0.3-alpha/llama-b3855-bin-win-vulkan-x64.zip"),
    ]

    def __init__(self, title, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName(title.replace(' ', '-'))
        self.resize(400, 400)
        self.init_ui()

    def init_ui(self):
        self.pivot = SegmentedWidget(self)
        self.stacked_widget = QStackedWidget(self)
        self.layout = QVBoxLayout(self)

        self.model_download_section = QWidget(self)
        self.llamacpp_download_section = QWidget(self)

        self.init_model_download_section()
        self.init_llamacpp_download_section()

        self.add_sub_interface(self.model_download_section,
                               'model_download_section', '模型下载')
        self.add_sub_interface(
            self.llamacpp_download_section, 'llamacpp_download_section', 'llama.cpp下载')

        self.layout.addWidget(self.pivot)
        self.layout.addWidget(self.stacked_widget)

        # 添加全局进度条
        self.global_progress_bar = ProgressBar(self)
        self.layout.addWidget(self.global_progress_bar)

        self.stacked_widget.currentChanged.connect(
            self.on_current_index_changed)
        self.stacked_widget.setCurrentWidget(self.model_download_section)
        self.pivot.setCurrentItem(self.model_download_section.objectName())

        self.setLayout(self.layout)

    def add_sub_interface(self, widget: QWidget, object_name, text):
        widget.setObjectName(object_name)
        self.stacked_widget.addWidget(widget)
        self.pivot.addItem(
            routeKey=object_name,
            text=text,
            onClick=lambda: self.stacked_widget.setCurrentWidget(widget),
        )

    def on_current_index_changed(self, index):
        widget = self.stacked_widget.widget(index)
        self.pivot.setCurrentItem(widget.objectName())

    def init_model_download_section(self):
        table = self.create_download_table(['名称', '操作'])
        for name, url in self.model_links:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, self.create_table_label(name))
            download_fn = lambda: self.start_download(url, name)
            table.setCellWidget(row, 1, self.create_table_button(download_fn))

        description = self.create_description_label("""
        <p>您可以在这里下载不同版本的模型，模型会保存到启动器所在的目录。您也可以手动从<a href="https://hf-mirror.com/SakuraLLM/Sakura-14B-Qwen2beta-v0.9.2-GGUF/">Hugging Face镜像站</a>下载模型。</p>
        <p>12G以下显存推荐使用GalTransl-7B-v2-IQ4_XS.gguf</p>
        <p>12G及以上显存推荐使用Sakura-14B-Qwen2beta-v0.9.2_IQ4_XS.gguf</p>
        """)

        layout = QVBoxLayout(self.model_download_section)
        layout.addWidget(description)
        layout.addWidget(table)
        self.model_download_section.setLayout(layout)

    def init_llamacpp_download_section(self):
        table = self.create_download_table(['版本', '适合显卡', '下载'])
        # 添加GitHub最新CUDA版本选项
        latest_cuda = self.get_latest_cuda_release()
        if latest_cuda:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, self.create_table_label(f"最新CUDA版本 ({latest_cuda['name']})"))
            table.setItem(row, 1, self.create_table_label("Nvidia独显"))
            download_fn = lambda url=latest_cuda['url'], name=latest_cuda['name']: self.start_download(url, name)
            table.setCellWidget(row, 2, self.create_table_button(download_fn))
        
        # 添加现有的下载选项
        for version, gpu, url in self.llamacpp_links:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, self.create_table_label(version))
            table.setItem(row, 1, self.create_table_label(gpu))
            # 从 URL 中提取文件名
            filename = url.split('/')[-1]
            download_fn = lambda url=url, filename=filename: self.start_download(url, filename)
            table.setCellWidget(row, 2, self.create_table_button(download_fn))

        description = self.create_description_label("""
        <p>您可以在这里下载不同版本的llama.cpp，文件会保存到启动器所在的目录。您也可以手动从<a href="https://github.com/ggerganov/llama.cpp/releases">GitHub发布页面</a>下载发行版。</p>
        <p><b>ROCm支持的独显型号(感谢Sora维护)</b>
            <ul>
                <li>RX 7900 / 7800 / 7700系列显卡</li>
                <li>RX 6900 / 6800 / 6700系列显卡</li>
            </ul>
        </p>
        <p><b>ROCm-780m支持的核显型号</b>
            <ul>
                <li>7840hs/7940hs/8840hs/8845hs </li>
                <li>理论上支持任何2022年后的AMD GPU，但要求CPU支持AVX512，且不对任何非780m显卡的可用性负责</li>
            </ul>
        </p>
        <p><b>注意：</b></p>
        <p>最新CUDA版本不包含cudart，如果你不知道这是什么，请不要下载最新CUDA版本</p>
        <p>Vulkan版本现在还不支持IQ系列的量化。</p>
        """)

        layout = QVBoxLayout(self.llamacpp_download_section)
        layout.addWidget(description)
        layout.addWidget(table)
        self.llamacpp_download_section.setLayout(layout)

    def create_description_label(self, content):
        description = QLabel()
        description.setText(content)
        description.setTextFormat(Qt.RichText)
        description.setWordWrap(True)
        description.setOpenExternalLinks(True)  # 允许打开外部链接
        description.setMargin(16)
        description.setTextInteractionFlags(Qt.TextSelectableByMouse|Qt.LinksAccessibleByMouse)
        return description

    def create_download_table(self, columns):
        table = TableWidget()
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def create_table_label(self, text):
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsEnabled)
        return item

    def create_table_button(self, download_function):
        download_button = TransparentPushButton(FIF.DOWNLOAD, "下载")
        download_button.clicked.connect(download_function)
        return download_button

    def unzip_llamacpp(self, filename):
        llama_folder = os.path.join(CURRENT_DIR, 'llama')
        file_path = os.path.join(CURRENT_DIR, filename)
        print(f"解压 {filename} 到 {llama_folder}")
        
        if not os.path.exists(llama_folder):
            os.mkdir(llama_folder)
        
        # 解压，如果文件已存在则覆盖
        if filename.endswith('.zip'):
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(llama_folder)
        elif filename.endswith('.7z'):
            with py7zr.SevenZipFile(file_path, mode='r') as z:
                z.extractall(llama_folder)
        else:
            print(f"不支持的文件格式: {filename}")
            return
        
        print(f"{filename} 已成功解压到 {llama_folder}")

    # 直接使用requests下载
    def start_download(self, url, filename):
        self.main_window.log_info(f"开始下载: URL={url}, 文件名={filename}")

        # 重置下载状态
        if hasattr(self, '_download_processed'):
            delattr(self, '_download_processed')
        
        # 确保旧的下载线程已经停止并且信号已经断开
        if hasattr(self, 'download_thread'):
            self.download_thread.safe_disconnect()
            self.download_thread.wait()  # 等待线程完全停止
        
        self.download_thread = DownloadThread(url, filename, self.main_window)
        
        # 连接信号，使用 Qt.UniqueConnection 确保只连接一次
        self.download_thread.progress.connect(self.global_progress_bar.setValue, Qt.UniqueConnection)
        self.download_thread.finished.connect(self.on_download_finished, Qt.UniqueConnection)
        self.download_thread.error.connect(self.on_download_error, Qt.UniqueConnection)
        
        self.download_thread.start()
        self.main_window.createSuccessInfoBar("下载中", "文件正在下载，请耐心等待，下载进度请关注最下方的进度条。")

    def on_download_finished(self):
        if hasattr(self, '_download_processed') and self._download_processed:
            self.main_window.log_info("下载已经处理过，跳过重复处理")
            return

        self._download_processed = True
        self.main_window.log_info("开始处理下载完成的文件")
        self.main_window.createSuccessInfoBar("下载完成", "文件已成功下载")
        # 获取下载的文件名
        downloaded_file = self.download_thread.filename
        file_path = os.path.join(CURRENT_DIR, downloaded_file)

        # 检查文件是否存在
        if not os.path.exists(file_path):
            self.main_window.log_info(f"错误：文件 {file_path} 不存在")
            return

        # 检查是否为llama.cpp文件
        if downloaded_file.startswith("llama"):
            try:
                self.unzip_llamacpp(downloaded_file)
                self.main_window.createSuccessInfoBar("解压完成", "已经将llama.cpp解压到程序所在目录的llama文件夹内。")
            except Exception as e:
                self.main_window.log_info(f"解压文件时出错: {str(e)}")
            finally:
                # 无论解压是否成功，都删除原始zip文件
                if os.path.exists(file_path):
                    os.remove(file_path)
        else:
            # 对模型文件进行SHA256校验
            expected_sha256 = ""
            if downloaded_file == "GalTransl-7B-v2-IQ4_XS.gguf":
                expected_sha256 = "8749e704993a2c327f319278818ba0a7f9633eae8ed187d54eb63456a11812aa"
            elif downloaded_file == "sakura-14b-qwen2beta-v0.9.2-iq4xs.gguf":
                expected_sha256 = "254a7e97e5e2a5daa371145e55bb2b0a0a789615dab2d4316189ba089a3ced67"
            elif downloaded_file == "sakura-14b-qwen2beta-v0.9.2-q4km.gguf":
                expected_sha256 = "8bae1ae35b7327fa7c3a8f3ae495b81a071847d560837de2025e1554364001a5"

            if expected_sha256:
                if self.check_sha256(file_path, expected_sha256):
                    self.main_window.createSuccessInfoBar("校验成功", "文件SHA256校验通过。")
                else:
                    self.main_window.createWarningInfoBar("校验失败", "文件SHA256校验未通过，请重新下载。")
                    os.remove(file_path)  # 删除校验失败的文件
            else:
                self.main_window.createWarningInfoBar("未校验", "无法为此文件执行SHA256校验。")
        
        # 不要删除标志，以防止重复处理
        # delattr(self, '_download_processed')

    def check_sha256(self, filename, expected_sha256):
        sha256_hash = sha256()
        with open(filename, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest() == expected_sha256

    def on_download_error(self, error_message):
        logger.error(f"Download error: {error_message}")
        QApplication.processEvents()  # 确保UI更新
        MessageBox("错误", f"下载失败: {error_message}", self).exec()

    def get_latest_cuda_release(self):
        try:
            # 发送请求到最新release页面
            response = requests.get('https://github.com/ggerganov/llama.cpp/releases/latest', allow_redirects=False)
            
            # 从重定向URL中提取版本号
            if response.status_code == 302:
                redirect_url = response.headers.get('Location')
                version = redirect_url.split('/')[-1]
                
                # 构造下载URL
                download_url = f'https://github.com/ggerganov/llama.cpp/releases/download/{version}/llama-{version}-bin-win-cuda-cu12.2.0-x64.zip'
                
                return {
                    'name': f'llama-{version}-bin-win-cuda-cu12.2.0-x64.zip',
                    'url': download_url
                }
            else:
                self.main_window.log_info("无法获取最新版本信息")
                return None
        except Exception as e:
            self.main_window.log_info(f"获取最新CUDA版本时出错: {str(e)}")
            return None

class CFShareWorker(QThread):
    tunnel_url_found = Signal(str)
    error_occurred = Signal(str)
    health_check_failed = Signal()
    metrics_updated = Signal(dict)

    def __init__(self, port, worker_url):
        super().__init__()
        self.port = port
        self.worker_url = worker_url
        self.cloudflared_process = None
        self.tunnel_url = None
        self.is_running = False

    def run(self):
        self.is_running = True
        cloudflared_path = get_resource_path(CLOUDFLARED)
        self.cloudflared_process = subprocess.Popen([cloudflared_path, "tunnel", "--url", f"http://localhost:{self.port}", "--metrics", "localhost:8081"])
        
        # Wait for tunnel URL
        time.sleep(10)
        self.check_tunnel_url()

        # Start health check and metrics update
        while self.is_running:
            if not self.check_local_health_status():
                self.health_check_failed.emit()
                break
            self.update_metrics()
            time.sleep(5)

    def check_tunnel_url(self):
        try:
            metrics_response = requests.get("http://localhost:8081/metrics")
            tunnel_url_match = re.search(r'(https://.*?\.trycloudflare\.com)', metrics_response.text)
            if tunnel_url_match:
                self.tunnel_url = tunnel_url_match.group(1)
                self.tunnel_url_found.emit(self.tunnel_url)
            else:
                self.error_occurred.emit("Failed to get tunnel URL")
        except Exception as e:
            self.error_occurred.emit(f"Error checking tunnel URL: {str(e)}")

    def check_local_health_status(self):
        health_url = f"http://localhost:{self.port}/health"
        try:
            response = requests.get(health_url)
            data = response.json()
            return data['status'] in ["ok", "no slot available"]
        except Exception:
            return False

    def update_metrics(self):
        try:
            response = requests.get(f"http://localhost:{self.port}/metrics")
            metrics = self.parse_metrics(response.text)
            self.metrics_updated.emit(metrics)
        except Exception as e:
            self.error_occurred.emit(f"Error updating metrics: {str(e)}")

    def parse_metrics(self, metrics_text):
        metrics = {}
        for line in metrics_text.split('\n'):
            if line.startswith('#') or not line.strip():
                continue
            key, value = line.split(' ')
            metrics[key.split(':')[-1]] = float(value)
        return metrics

    def stop(self):
        self.is_running = False
        if self.cloudflared_process:
            self.cloudflared_process.terminate()
            try:
                self.cloudflared_process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                self.cloudflared_process.kill()
            self.cloudflared_process = None

class CFShareSection(RunSection):
    def __init__(self, title, main_window, parent=None):
        super().__init__(title, main_window, parent)
        self._init_ui()
        self.load_settings()
        self.worker = None

    def _init_ui(self):
        layout = QVBoxLayout()

        buttons_group = QGroupBox("")
        buttons_layout = QHBoxLayout()

        self.start_button = PrimaryPushButton(FIF.PLAY, '上线', self)
        self.start_button.clicked.connect(self.start_cf_share)
        self.start_button.setFixedSize(110, 30)
        buttons_layout.addWidget(self.start_button)

        self.stop_button = PushButton(FIF.CLOSE, '下线', self)
        self.stop_button.clicked.connect(self.stop_cf_share)
        self.stop_button.setEnabled(False)
        self.stop_button.setFixedSize(110, 30)
        buttons_layout.addWidget(self.stop_button)

        self.save_button = PushButton(FIF.SAVE, '保存', self)
        self.save_button.clicked.connect(self.save_settings)
        self.save_button.setFixedSize(110, 30)
        buttons_layout.addWidget(self.save_button)

        self.refresh_slots_button = PushButton(FIF.SYNC, '刷新在线数量', self)
        self.refresh_slots_button.clicked.connect(self.refresh_slots)
        self.refresh_slots_button.setFixedSize(150, 30)
        buttons_layout.addWidget(self.refresh_slots_button)

        buttons_layout.setAlignment(Qt.AlignRight)
        buttons_group.setStyleSheet(""" QGroupBox {border: 0px solid darkgray; background-color: #202020; border-radius: 8px;}""")
        buttons_group.setLayout(buttons_layout)
        layout.addWidget(buttons_group)

        layout.addWidget(QLabel("WORKER_URL:"))
        self.worker_url_input = self._create_line_edit("输入WORKER_URL", "https://sakura-share.one")
        layout.addWidget(self.worker_url_input)

        self.status_label = QLabel("状态: 未运行")
        layout.addWidget(self.status_label)

        self.slots_status_label = QLabel("在线slot数量: 未知")
        layout.addWidget(self.slots_status_label)

        # 更新指标
        self.metrics_labels = {
            'prompt_tokens_total': QLabel("提示词 tokens 总数: 暂无数据"),
            'prompt_seconds_total': QLabel("提示词处理总时间: 暂无数据"),
            'tokens_predicted_total': QLabel("生成的 tokens 总数: 暂无数据"),
            'tokens_predicted_seconds_total': QLabel("生成处理总时间: 暂无数据"),
            'n_decode_total': QLabel("llama_decode() 调用总次数: 暂无数据"),
            'n_busy_slots_per_decode': QLabel("每次 llama_decode() 调用的平均忙碌槽位数: 暂无数据"),
            'prompt_tokens_seconds': QLabel("提示词平均吞吐量: 暂无数据"),
            'predicted_tokens_seconds': QLabel("生成平均吞吐量: 暂无数据"),
            'kv_cache_usage_ratio': QLabel("KV-cache 使用率: 暂无数据"),
            'kv_cache_tokens': QLabel("KV-cache tokens: 暂无数据"),
            'requests_processing': QLabel("正在处理的请求数: 暂无数据"),
            'requests_deferred': QLabel("延迟的请求数: 暂无数据")
        }

        tooltips = {
            'prompt_tokens_total': "已处理的提示词 tokens 总数",
            'prompt_seconds_total': "提示词处理的总时间",
            'tokens_predicted_total': "已生成的 tokens 总数",
            'tokens_predicted_seconds_total': "生成处理的总时间",
            'n_decode_total': "llama_decode() 函数的总调用次数",
            'n_busy_slots_per_decode': "每次 llama_decode() 调用时的平均忙碌槽位数",
            'prompt_tokens_seconds': "提示词的平均处理速度",
            'predicted_tokens_seconds': "生成的平均速度",
            'kv_cache_usage_ratio': "KV-cache 的使用率（1 表示 100% 使用）",
            'kv_cache_tokens': "KV-cache 中的 token 数量",
            'requests_processing': "当前正在处理的请求数",
            'requests_deferred': "被延迟的请求数"
        }

        metrics_title = QLabel("\n数据统计")
        metrics_title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(metrics_title)

        for key, label in self.metrics_labels.items():
            label.setToolTip(tooltips[key])
            layout.addWidget(label)

        description = QLabel()
        description.setText("""
        <html>
        <body>
        <h3>说明</h3>
        <p>这是一个一键分享你本地部署的Sakura模型给其他用户（成为帕鲁）的工具，服务端部署请按照下面的仓库的文档进行。</p>
        <ol>
            <li>请确保本地服务已启动。</li>
            <li>请确保WORKER_URL正确。<br>
            <span>如无特殊需求，请使用默认的WORKER_URL，此链接是由共享脚本开发者本人维护的。</span></li>
            <li>目前仅支持Windows系统，其他系统请自行更改脚本。</li>
            <li>目前仅支持以下两种模型（服务端有模型指纹检查）：
                <ul>
                    <li>sakura-14b-qwen2beta-v0.9.2-iq4xs</li>
                    <li>sakura-14b-qwen2beta-v0.9.2-q4km</li>
                </ul>
            </li>
            <li>当你不想成为帕鲁的时候，也可以通过这个链接来访问其他帕鲁的模型，但不保证服务的可用性与稳定性。</li>
        </ol>
        </body>
        </html>
        """)
        description.setTextFormat(Qt.RichText)
        description.setWordWrap(True)
        description.setStyleSheet("""
            QLabel {
                border-radius: 5px;
                padding: 15px;
            }
        """)
        layout.addWidget(description)

        sakura_share_url = "https://github.com/1PercentSync/sakura-share"
        link = QLabel(f"<a href='{sakura_share_url}'>点击前往仓库</a>")
        link.setOpenExternalLinks(True)
        link.setAlignment(Qt.AlignCenter)
        link.setStyleSheet("""
            QLabel {
                padding: 10px;
            }
        """)
        layout.addWidget(link)

        layout.addItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))

        self.setLayout(layout)

    @Slot()
    def start_cf_share(self):
        worker_url = self.worker_url_input.text().strip()
        if not worker_url:
            MessageBox("错误", "请输入WORKER_URL", self).exec_()
            return
        port = self.main_window.run_server_section.port_input.text().strip()
        if not port:
            MessageBox("错误", "请在运行server面板中设置端口号", self).exec_()
            return
        if not self.check_local_health_status():
            MessageBox("错误", "本地服务未启动或未正常运行，请先启动本地服务", self).exec_()
            return

        self.worker = CFShareWorker(port, worker_url)
        self.worker.tunnel_url_found.connect(self.on_tunnel_url_found)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.health_check_failed.connect(self.stop_cf_share)
        self.worker.metrics_updated.connect(self.update_metrics_display)
        self.worker.start()

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    @Slot(str)
    def on_tunnel_url_found(self, tunnel_url):
        self.tunnel_url = tunnel_url
        self.main_window.log_info(f"Tunnel URL: {self.tunnel_url}")
        self.register_node()
        self.status_label.setText(f"状态: 运行中 - {self.tunnel_url}")
        self.main_window.createSuccessInfoBar("成功", "已经成功启动分享。")

    @Slot(str)
    def on_error(self, error_message):
        self.main_window.log_info(error_message)
        self.stop_cf_share()

    @Slot()
    def stop_cf_share(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
            self.worker = None

        if self.tunnel_url:
            self.take_node_offline()
            self.tunnel_url = None

        self.status_label.setText("状态: 未运行")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    @Slot(dict)
    def update_metrics_display(self, metrics):
        for key, label in self.metrics_labels.items():
            if key in metrics:
                value = metrics[key]
                if key in ['prompt_tokens_total', 'tokens_predicted_total']:
                    label.setText(f"{label.text().split(':')[0]}: {value:.0f} tokens")
                elif key in ['prompt_seconds_total', 'tokens_predicted_seconds_total']:
                    label.setText(f"{label.text().split(':')[0]}: {value:.2f} 秒")
                elif key == 'n_decode_total':
                    label.setText(f"{label.text().split(':')[0]}: {value:.0f} 次")
                elif key == 'n_busy_slots_per_decode':
                    label.setText(f"{label.text().split(':')[0]}: {value:.2f}")
                elif key in ['prompt_tokens_seconds', 'predicted_tokens_seconds']:
                    label.setText(f"{label.text().split(':')[0]}: {value:.2f} tokens/s")
                elif key == 'kv_cache_usage_ratio':
                    label.setText(f"{label.text().split(':')[0]}: {value*100:.2f}%")
                elif key == 'kv_cache_tokens':
                    label.setText(f"{label.text().split(':')[0]}: {value:.0f} tokens")
                elif key in ['requests_processing', 'requests_deferred']:
                    label.setText(f"{label.text().split(':')[0]}: {value:.0f}")
                else:
                    label.setText(f"{label.text().split(':')[0]}: {value:.2f}")

    def save_settings(self):
        settings = {
            'worker_url': self.worker_url_input.text().strip()
        }
        if not os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=4)

        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
            config_data.update(settings)

        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)

    def load_settings(self):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        except FileNotFoundError:
            return
        except json.JSONDecodeError:
            return
        self.worker_url_input.setText(settings.get('worker_url', 'https://sakura-share.one'))

    def refresh_slots(self):
        worker_url = self.worker_url_input.text().strip()
        if not worker_url:
            self.slots_status_label.setText("在线slot数量: 获取失败 - WORKER_URL为空")
            return

        try:
            response = requests.get(f"{worker_url}/health")
            data = response.json()
            if data['status'] == "ok":
                slots_idle = data.get('slots_idle', '未知')
                slots_processing = data.get('slots_processing', '未知')
                self.slots_status_label.setText(f"在线slot数量: 空闲 {slots_idle}, 处理中 {slots_processing}")
            else:
                self.slots_status_label.setText("在线slot数量: 获取失败")
        except Exception as e:
            self.slots_status_label.setText(f"在线slot数量: 获取失败 - {str(e)}")

    def check_local_health_status(self):
        port = self.main_window.run_server_section.port_input.text().strip()
        health_url = f"http://localhost:{port}/health"
        try:
            response = requests.get(health_url)
            data = response.json()
            if data['status'] in ["ok", "no slot available"]:
                return True
            else:
                self.main_window.log_info(f"Local health status: Not healthy - {data['status']}")
                return False
        except Exception as e:
            self.main_window.log_info(f"Error checking local health status: {str(e)}")
            return False

    def register_node(self):
        try:
            api_response = requests.post(
                f"{self.worker.worker_url}/register-node",
                json={"url": self.tunnel_url},
                headers={"Content-Type": "application/json"}
            )
            self.main_window.log_info(f"API Response: {api_response.text}")
        except Exception as e:
            self.main_window.log_info(f"Error registering node: {str(e)}")

    def take_node_offline(self):
        try:
            offline_response = requests.post(
                f"{self.worker.worker_url}/delete-node",
                json={"url": self.tunnel_url},
                headers={"Content-Type": "application/json"}
            )
            self.main_window.log_info(f"Offline Response: {offline_response.text}")
        except Exception as e:
            self.main_window.log_info(f"Error taking node offline: {str(e)}")


class SettingsSection(QFrame):
    def __init__(self, title, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName(title.replace(' ', '-'))
        self._init_ui()
        self.load_settings()

    def _init_ui(self):
        layout = QVBoxLayout()

        self.llamacpp_path = self._create_line_edit("llama.cpp二进制文件所在的路径（可选），留空则为当前目录下的llama文件夹", "")
        layout.addWidget(QLabel("llama.cpp 文件夹"))
        layout.addWidget(self.llamacpp_path)

        self.model_search_paths = TextEdit(self)
        self.model_search_paths.setPlaceholderText("模型搜索路径（每行一个路径，已经默认包含当前目录）")
        layout.addWidget(QLabel("模型搜索路径"))
        layout.addWidget(self.model_search_paths)

        self.remember_window_state = CheckBox("记住窗口位置和大小", self)
        layout.addWidget(self.remember_window_state)

        # 添加模型排序设置
        layout.addWidget(QLabel("模型列表排序方式:"))
        self.model_sort_combo = ComboBox(self)
        self.model_sort_combo.addItems(['修改时间', '文件名', '文件大小'])
        layout.addWidget(self.model_sort_combo)

        self.save_button = PrimaryPushButton(FIF.SAVE, '保存设置', self)
        self.save_button.clicked.connect(self.save_settings)
        layout.addWidget(self.save_button)

        self.load_settings_button = PushButton(FIF.SYNC, '加载设置', self)
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
            'llamacpp_path': self.llamacpp_path.text(),
            'model_search_paths': self.model_search_paths.toPlainText().split('\n'),
            'remember_window_state': self.remember_window_state.isChecked(),
            'model_sort_option': self.model_sort_combo.currentText()
        }
        if not os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=4)

        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
            config_data.update(settings)

        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)

        self.main_window.createSuccessInfoBar("成功", "设置已保存")

    def load_settings(self):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        except FileNotFoundError:
            return
        except json.JSONDecodeError:
            return
        self.llamacpp_path.setText(settings.get('llamacpp_path', ''))
        self.model_search_paths.setPlainText('\n'.join(settings.get('model_search_paths', [])))
        self.remember_window_state.setChecked(settings.get('remember_window_state', True))
        self.model_sort_combo.setCurrentText(settings.get('model_sort_option', '修改时间'))

class AboutSection(QFrame):
    def __init__(self, text: str, parent=None):
        super().__init__(parent=parent)
        self.setObjectName(text.replace(' ', '-'))
        self.init_ui()

    def init_ui(self):


        # 文本
        text_group = QGroupBox()
        text_group.setStyleSheet(""" QGroupBox {border: 0px solid lightgray; border-radius: 8px;}""")
        text_group_layout = QVBoxLayout()


        self.text_label = QLabel(self)
        self.text_label.setStyleSheet("font-size: 25px;")
        self.text_label.setText("测试版本UI，可能有很多bug")
        self.text_label.setAlignment(Qt.AlignCenter)

        self.text_label_2 = QLabel(self)
        self.text_label_2.setStyleSheet("font-size: 18px;")
        self.text_label_2.setText(f"GUI版本： v{SAKURA_LAUNCHER_GUI_VERSION}")
        self.text_label_2.setAlignment(Qt.AlignCenter)

        self.hyperlinkButton_1 = HyperlinkButton(
            url='https://github.com/SakuraLLM/SakuraLLM',
            text='SakuraLLM 项目地址',
            parent=self,
            icon=FIF.LINK
        )

        self.hyperlinkButton_2 = HyperlinkButton(
            url='https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI',
            text='Sakura Launcher GUI 项目地址',
            parent=self,
            icon=FIF.LINK
        )

        text_group_layout.addWidget(self.text_label)
        text_group_layout.addWidget(self.text_label_2)
        text_group_layout.addWidget(self.hyperlinkButton_1)
        text_group_layout.addWidget(self.hyperlinkButton_2)
        text_group_layout.addStretch(1)  # 添加伸缩项
        text_group.setLayout(text_group_layout)

        container = QVBoxLayout()

        self.setLayout(container)
        container.setSpacing(28) # 设置布局内控件的间距为28
        container.setContentsMargins(50, 70, 50, 30) # 设置布局的边距, 也就是外边框距离，分别为左、上、右、下

        container.addStretch(1)  # 添加伸缩项
        container.addWidget(text_group)
        container.addStretch(1)  # 添加伸缩项

class ConfigEditor(QFrame):
    LONG_PRESS_TIME = 500  # 设置长按延迟时间（毫秒）

    def __init__(self, title, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName(title.replace(' ', '-'))
        self.setStyleSheet("""
            Demo{background: white}
            QLabel{
                font: 20px 'Segoe UI';
                background: rgb(242,242,242);
                border-radius: 8px;
            }
        """)
        self.resize(400, 400)
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        self.pivot = SegmentedWidget(self)
        self.stacked_widget = QStackedWidget(self)
        self.layout = QVBoxLayout(self)

        self.run_server_section = QWidget(self)
        self.run_bench_section = QWidget(self)
        self.run_batch_bench_section = QWidget(self)  # New section for batch bench

        self.init_run_server_section()
        self.init_run_bench_section()
        self.init_run_batch_bench_section()  # Initialize the new section

        self.add_sub_interface(self.run_server_section, 'run_server_section', 'Server')
        self.add_sub_interface(self.run_bench_section, 'run_bench_section', 'Bench')
        self.add_sub_interface(self.run_batch_bench_section, 'run_batch_bench_section', 'Batch Bench')  # Add new interface

        save_button = PrimaryPushButton(FIF.SAVE, '保存配置预设', self)
        save_button.clicked.connect(self.save_settings)

        load_button = PushButton(FIF.SYNC, '加载配置预设', self)
        load_button.clicked.connect(self.load_settings)

        self.layout.addWidget(self.pivot)
        self.layout.addWidget(self.stacked_widget)
        self.layout.addWidget(save_button)
        self.layout.addWidget(load_button)

        self.stacked_widget.currentChanged.connect(self.on_current_index_changed)
        self.stacked_widget.setCurrentWidget(self.run_server_section)
        self.pivot.setCurrentItem(self.run_server_section.objectName())

        self.setLayout(self.layout)

    def add_sub_interface(self, widget: QWidget, object_name, text):
        widget.setObjectName(object_name)
        self.stacked_widget.addWidget(widget)
        self.pivot.addItem(
            routeKey=object_name,
            text=text,
            onClick=lambda: self.stacked_widget.setCurrentWidget(widget),
        )

    def on_current_index_changed(self, index):
        widget = self.stacked_widget.widget(index)
        self.pivot.setCurrentItem(widget.objectName())

    def init_run_server_section(self):
        layout = QVBoxLayout(self.run_server_section)
        self.run_server_table = self.create_config_table()
        layout.addWidget(self.run_server_table)
        self.run_server_section.setLayout(layout)

    def init_run_bench_section(self):
        layout = QVBoxLayout(self.run_bench_section)
        self.run_bench_table = self.create_config_table()
        layout.addWidget(self.run_bench_table)
        self.run_bench_section.setLayout(layout)

    def init_run_batch_bench_section(self):
        layout = QVBoxLayout(self.run_batch_bench_section)
        self.run_batch_bench_table = self.create_config_table()
        layout.addWidget(self.run_batch_bench_table)
        self.run_batch_bench_section.setLayout(layout)

    def create_config_table(self):
        table = TableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(['配置名称', '上移', '下移', '删除'])
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        return table

    def save_settings(self):
        server_configs = self.table_to_config(self.run_server_table)
        bench_configs = self.table_to_config(self.run_bench_table)
        batch_bench_configs = self.table_to_config(self.run_batch_bench_table)  # Add this line

        settings = {
            '运行server': server_configs,
            '运行bench': bench_configs,
            '批量运行bench': batch_bench_configs  # Add this line
        }

        config_file_path = os.path.join(CURRENT_DIR, CONFIG_FILE)
        if not os.path.exists(config_file_path):
            with open(config_file_path, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=4)

        with open(config_file_path, 'r', encoding='utf-8') as f:
            try:
                current_settings = json.load(f)
            except json.JSONDecodeError:
                current_settings = {}

        current_settings.update(settings)

        with open(config_file_path, 'w', encoding='utf-8') as f:
            json.dump(current_settings, f, ensure_ascii=False, indent=4)

        self.main_window.createSuccessInfoBar("成功", "配置预设已保存")

    def load_settings(self):
        config_file_path = os.path.join(CURRENT_DIR, CONFIG_FILE)
        try:
            with open(config_file_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            settings = {}

        self.config_to_table(self.run_server_table, settings.get('运行server', []))
        self.config_to_table(self.run_bench_table, settings.get('运行bench', []))
        self.config_to_table(self.run_batch_bench_table, settings.get('批量运行bench', []))  # Add this line

    def table_to_config(self, table):
        configs = []
        for row in range(table.rowCount()):
            name_item = table.item(row, 0)
            if name_item:
                config_name = name_item.text()
                config = name_item.data(Qt.UserRole)
                configs.append({'name': config_name, 'config': config})
        return configs

    def config_to_table(self, table, configs):
        table.setRowCount(len(configs))
        for row, config in enumerate(configs):
            name_item = QTableWidgetItem(config['name'])
            name_item.setData(Qt.UserRole, config['config'])
            table.setItem(row, 0, name_item)
            table.setCellWidget(row, 1, self.create_move_up_button(table, row))
            table.setCellWidget(row, 2, self.create_move_down_button(table, row))
            table.setCellWidget(row, 3, self.create_delete_button(table))

    def create_move_up_button(self, table, row):
        button = TransparentPushButton(FIF.UP, "上移", self)
        button.pressed.connect(lambda: self.start_timer(button, table, row, self.move_up, self.move_to_top))
        button.released.connect(lambda: self.stop_timer(button))
        button.setToolTip("向上移动配置，长按可快速移动到顶部")
        return button

    def create_move_down_button(self, table, row):
        button = TransparentPushButton(FIF.DOWN, "下移", self)
        button.pressed.connect(lambda: self.start_timer(button, table, row, self.move_down, self.move_to_bottom))
        button.released.connect(lambda: self.stop_timer(button))
        button.setToolTip("向下移动配置，长按可快速移动到底部")
        return button

    def create_delete_button(self, table):
        button = TransparentPushButton(FIF.DELETE, "删除", self)
        button.clicked.connect(partial(self.delete_row, table, button))
        return button

    def start_timer(self, button, table, row, move_func, long_press_func):
        self.click_timer = QTimer()
        self.click_timer.timeout.connect(lambda: self.perform_long_press_action(table, row, long_press_func))
        self.click_timer.start(self.LONG_PRESS_TIME)  # 设置长按延迟
        button.click_action = lambda: move_func(table, row)

    def stop_timer(self, button):
        if hasattr(self, 'click_timer'):
            if self.click_timer.isActive():
                self.click_timer.stop()
                button.click_action()
            delattr(self, 'click_timer')

    def perform_long_press_action(self, table, row, long_press_func):
        self.click_timer.stop()
        long_press_func(table, row)

    def move_up(self, table, row):
        if row > 0:
            self.swap_rows(table, row, row - 1)
            table.selectRow(row - 1)

    def move_down(self, table, row):
        if row < table.rowCount() - 1:
            self.swap_rows(table, row, row + 1)
            table.selectRow(row + 1)

    def move_to_top(self, table, row):
        self.move_to(table, row, 0)

    def move_to_bottom(self, table, row):
        self.move_to(table, row, table.rowCount() - 1)

    def move_to(self, table, row, target_row):
        while row != target_row:
            if row < target_row:
                self.swap_rows(table, row, row + 1)
                row += 1
            else:
                self.swap_rows(table, row, row - 1)
                row -= 1
        table.selectRow(target_row)

    def swap_rows(self, table, row1, row2):
        for col in range(table.columnCount()):
            item1 = table.takeItem(row1, col)
            item2 = table.takeItem(row2, col)
            if item1 and item2:
                table.setItem(row1, col, QTableWidgetItem(item2))
                table.setItem(row2, col, QTableWidgetItem(item1))

    def delete_row(self, table, button):
        index = table.indexAt(button.pos())
        if index.isValid():
            table.removeRow(index.row())

class MainWindow(MSFluentWindow):
    def __init__(self):
        super().__init__()
        self.gpu_manager = GPUManager()
        self.init_navigation()
        self.init_window()
        cloudflared_path = get_resource_path(CLOUDFLARED)
        if not os.path.exists(cloudflared_path):
            MessageBox("错误", f"cloudflared 可执行文件不存在: {cloudflared_path}", self).exec()
        self.load_window_state()

    def init_navigation(self):
        self.settings_section = SettingsSection("设置", self)
        self.run_server_section = RunServerSection("运行server", self)
        self.run_bench_section = RunBenchmarkSection("运行bench", self)
        self.run_llamacpp_batch_bench_section = RunBatchBenchmarkSection("批量运行bench", self)
        self.log_section = LogSection("日志输出")
        self.about_section = AboutSection("关于")
        self.config_editor_section = ConfigEditor("配置编辑", self)
        self.dowload_section = DownloadSection("下载", self)
        self.cf_share_section = CFShareSection("共享", self)


        self.addSubInterface(self.run_server_section, FIF.COMMAND_PROMPT, "运行server")
        self.addSubInterface(self.run_bench_section, FIF.COMMAND_PROMPT, "运行bench")
        self.addSubInterface(self.run_llamacpp_batch_bench_section, FIF.COMMAND_PROMPT, "batch-bench")
        self.addSubInterface(self.log_section, FIF.BOOK_SHELF, "日志输出")
        self.addSubInterface(self.config_editor_section, FIF.EDIT, "配置编辑")
        self.addSubInterface(self.dowload_section, FIF.DOWNLOAD, "下载")
        self.addSubInterface(self.cf_share_section, FIF.SHARE, "共享")
        self.addSubInterface(self.settings_section, FIF.SETTING, "设置")
        self.addSubInterface(self.about_section, FIF.INFO, "关于", position=NavigationItemPosition.BOTTOM)

        self.navigationInterface.setCurrentItem(self.run_server_section.objectName())

    def init_window(self):
        self.run_server_section.run_button.clicked.connect(self.run_llamacpp_server)
        self.run_bench_section.run_button.clicked.connect(self.run_llamacpp_bench)
        self.run_llamacpp_batch_bench_section.run_button.clicked.connect(self.run_llamacpp_batch_bench)
        self.run_server_section.load_preset_button.clicked.connect(self.run_server_section.load_presets)
        self.run_bench_section.load_preset_button.clicked.connect(self.run_bench_section.load_presets)
        self.run_llamacpp_batch_bench_section.load_preset_button.clicked.connect(self.run_llamacpp_batch_bench_section.load_presets)
        self.run_server_section.refresh_model_button.clicked.connect(self.run_server_section.refresh_models)
        self.run_bench_section.refresh_model_button.clicked.connect(self.run_bench_section.refresh_models)
        self.run_llamacpp_batch_bench_section.refresh_model_button.clicked.connect(self.run_llamacpp_batch_bench_section.refresh_models)

        # 连接设置更改信号
        self.settings_section.model_sort_combo.currentIndexChanged.connect(self.refresh_all_model_lists)

        self.setStyleSheet("""
            QLabel {
                color: #dadada;
            }

            CheckBox {
                color: #dadada;
            }

            AcrylicWindow{
                background-color: #272727;
            }
        """)

        icon = get_resource_path(ICON_FILE)
        self.setWindowIcon(QIcon(icon))
        self.setWindowTitle(f"Sakura 启动器 v{SAKURA_LAUNCHER_GUI_VERSION}")
        self.resize(600, 400)

        desktop = QApplication.screens()[0].availableGeometry()
        w, h = desktop.width(), desktop.height()
        self.move(w // 2 - self.width() // 2, h // 2 - self.height() // 2)

    def refresh_all_model_lists(self):
        self.run_server_section.refresh_models()
        self.run_bench_section.refresh_models()
        self.run_llamacpp_batch_bench_section.refresh_models()

    def createSuccessInfoBar(self, title, content):
        InfoBar.success(
            title=title,
            content=content,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=2000,
            parent=self
        )

    def get_llamacpp_path(self):
        path = self.settings_section.llamacpp_path.text()
        if not path:
            return os.path.join(CURRENT_DIR, 'llama')
        return os.path.abspath(path)

    def get_model_search_paths(self):
        paths = self.settings_section.model_search_paths.toPlainText().split('\n')
        return [path.strip() for path in paths if path.strip()]

    def _add_quotes(self, path):
        return f'"{path}"'

    def run_llamacpp_server(self):
        self._run_llamacpp(self.run_server_section, 'server', 'llama-server')

    def run_llamacpp_bench(self):
        self._run_llamacpp(self.run_bench_section, 'llama-bench')

    def run_llamacpp_batch_bench(self):
        self._run_llamacpp(self.run_llamacpp_batch_bench_section, 'llama-batched-bench')

    def _run_llamacpp(self, section, old_executable, new_executable=None):
        custom_command = section.custom_command.toPlainText().strip()
        llamacpp_override = section.llamacpp_override.text().strip()
        llamacpp_path = llamacpp_override if llamacpp_override else self.get_llamacpp_path()
        exe_extension = '.exe' if sys.platform == 'win32' else ''

        if not os.path.exists(llamacpp_path):
            MessageBox("错误", f"llamacpp路径不存在: {llamacpp_path}", self).exec()
            return

        model_name = section.model_path.currentText().split(os.sep)[-1]
        model_path = self._add_quotes(section.model_path.currentText())
        self.log_info(f"模型路径: {model_path}")
        self.log_info(f"模型名称: {model_name}")

        # 判断使用哪个可执行文件
        executable_path = os.path.join(llamacpp_path, f"{new_executable or old_executable}{exe_extension}")
        if new_executable and not os.path.exists(executable_path):
            executable_path = os.path.join(llamacpp_path, f"{old_executable}{exe_extension}")
        elif not os.path.exists(executable_path):
            MessageBox("错误", f"可执行文件不存在: {executable_path}", self).exec()
            return

        executable_path = self._add_quotes(executable_path)

        if custom_command:
            command = f'{executable_path} --model {model_path} {custom_command}'
        else:
            command = f'{executable_path} --model {model_path}'

            if old_executable == 'server' or new_executable == 'llama-server':
                command += f' -ngl {section.gpu_layers_spinbox.value()}'
                command += f' -c {section.context_length_input.value()}'
                command += f' -a {model_name}'
                command += f' --host {section.host_input.currentText()} --port {section.port_input.text()}'
                if section.log_format_combo.currentText() not in ("none", ""):
                    command += f' --log-format {section.log_format_combo.currentText()}'
                command += f' -np {section.n_parallel_spinbox.value()}'

                if section.flash_attention_check.isChecked():
                    command += ' -fa'
                if section.no_mmap_check.isChecked():
                    command += ' --no-mmap'
                if section.custom_command_append.toPlainText().strip():
                    command += f' {section.custom_command_append.toPlainText().strip()}'
                if hasattr(section, 'is_sharing') and section.is_sharing.isChecked():
                    command += ' --metrics'
            elif old_executable == 'llama-bench':
                command += f' -ngl {section.gpu_layers_spinbox.value()}'

                if section.flash_attention_check.isChecked():
                    command += ' -fa 1,0'
                if section.no_mmap_check.isChecked():
                    command += ' -mmp 0'
                if section.custom_command_append.toPlainText().strip():
                    command += f' {section.custom_command_append.toPlainText().strip()}'
            elif old_executable == 'llama-batched-bench':
                command += f' -c {section.ctx_size_spinbox.value()}'
                command += f' -ngl {section.gpu_layers_spinbox.value()}'
                command += f' -npp {section.npp_input.text()}'
                command += f' -ntg {section.ntg_input.text()}'
                command += f' -npl {section.npl_input.text()}'
                if section.pps_check.isChecked():
                    command += ' -pps'
                if section.flash_attention_check.isChecked():
                    command += ' -fa'
                if section.no_mmap_check.isChecked():
                    command += ' --no-mmap'
                if section.custom_command_append.toPlainText().strip():
                    command += f' {section.custom_command_append.toPlainText().strip()}'

        if section.gpu_enabled_check.isChecked():
            selected_gpu = section.gpu_combo.currentText()
            selected_index = section.gpu_combo.currentIndex()
            manual_index = section.manully_select_gpu_index.text()

            try:
                self.gpu_manager.set_gpu_env(selected_gpu, selected_index, manual_index)
            except Exception as e:
                self.log_info(f"设置GPU环境变量时出错: {str(e)}")
                MessageBox("错误", f"设置GPU环境变量时出错: {str(e)}", self).exec()
                return

        self.log_info(f"执行命令: {command}")

        # 在运行命令的部分
        if sys.platform == 'win32':
            command = f'start cmd /K "{command}"'
            subprocess.Popen(command, shell=True)
        else:
            terminal = self.find_terminal()
            if terminal:
                if terminal == 'gnome-terminal':
                    subprocess.Popen([terminal, '--', 'bash', '-c', command])
                else:
                    subprocess.Popen([terminal, '-e', command])
            else:
                MessageBox("错误", "无法找到合适的终端模拟器。请手动运行命令。", self).exec()
                self.log_info(f"请手动运行以下命令：\n{command}")
                return

        self.log_info("命令已在新的终端窗口中启动。")

        if hasattr(section, 'is_sharing') and section.is_sharing.isChecked():
            cf_share_url = self.cf_share_section.worker_url_input.text()
            if not cf_share_url:
                MessageBox("错误", "分享链接不能为空", self).exec()
                return
            QTimer.singleShot(25000, self.cf_share_section.start_cf_share)

    def find_terminal(self):
        terminals = [
            'x-terminal-emulator',
            'gnome-terminal',
            'konsole',
            'xfce4-terminal',
            'xterm'
        ]
        for term in terminals:
            if shutil.which(term):
                return term
        return None

    def log_info(self, message):
        self.log_section.log_display.append(message)
        self.log_section.log_display.ensureCursorVisible()

    def closeEvent(self, event):
        self.save_window_state()
        self.terminate_all_processes()
        event.accept()

    def terminate_all_processes(self):
        print("Terminating all processes...")
        self.cf_share_section.stop_cf_share()
        for proc in processes:
            proc.terminate()
            try:
                proc.wait(timeout=0.1)  # 等待最多0.1秒
            except subprocess.TimeoutExpired:
                proc.kill()
        processes.clear()

    def refresh_gpus(self):
        self.gpu_manager.detect_gpus()
        self.run_server_section.refresh_gpus()
        self.run_bench_section.refresh_gpus()
        self.run_llamacpp_batch_bench_section.refresh_gpus()

        if not self.gpu_manager.nvidia_gpus and not self.gpu_manager.amd_gpus:
            self.log_info("未检测到NVIDIA或AMD GPU")

    def save_window_state(self):
        if self.settings_section.remember_window_state.isChecked():
            settings = {
                'window_geometry': {
                    'x': self.x(),
                    'y': self.y(),
                    'width': self.width(),
                    'height': self.height()
                }
            }
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            config_data.update(settings)
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)

    def load_window_state(self):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            if settings.get('remember_window_state', False):
                geometry = settings.get('window_geometry', {})
                if geometry:
                    self.setGeometry(
                        geometry.get('x', self.x()),
                        geometry.get('y', self.y()),
                        geometry.get('width', self.width()),
                        geometry.get('height', self.height())
                    )
        except (FileNotFoundError, json.JSONDecodeError):
            pass

if __name__ == "__main__":
    setTheme(Theme.DARK)
    setThemeColor(QColor(222, 142, 204))
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())