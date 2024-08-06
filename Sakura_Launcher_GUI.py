"""
#TODO: 
1. 直接使用QProcess启动。
"""

import sys
import os
import wmi
import json
import subprocess
import atexit
from functools import partial
from PySide6.QtCore import Qt, Signal, QObject, Slot, QTimer, QThread
from PySide6.QtWidgets import QApplication, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGroupBox, QHeaderView, QTableWidgetItem, QWidget, QStackedWidget
from PySide6.QtGui import QIcon, QColor
from qfluentwidgets import PushButton, CheckBox, SpinBox, PrimaryPushButton, TextEdit, EditableComboBox, MessageBox, setTheme, Theme, MSFluentWindow, FluentIcon as FIF, Slider, ComboBox, setThemeColor, LineEdit, HyperlinkButton, NavigationItemPosition, TableWidget, TransparentPushButton, SegmentedWidget, InfoBar, InfoBarPosition, ProgressBar


import logging
import subprocess
import requests
logging.basicConfig(level=logging.DEBUG)
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
SAKURA_LAUNCHER_GUI_VERSION = '0.0.3'


processes = []

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
        layout.addWidget(self.gpu_enabled_check)
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
        for path in search_paths:
            if os.path.exists(path) and os.path.isdir(path):
                for root, _, files in os.walk(path):
                    models.extend([os.path.join(root, f) for f in files if f.endswith('.gguf')])
        self.model_path.addItems(models)

    def refresh_gpus(self):
        self.gpu_combo.clear()
        self.nvidia_gpus = []
        self.amd_gpus = []
        
        try:
            # 检测NVIDIA GPU
            os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            result = subprocess.run('nvidia-smi --query-gpu=name --format=csv,noheader', shell=True, capture_output=True, text=True)
            if result.returncode == 0:
                self.nvidia_gpus = result.stdout.strip().split('\n')
            
            # 检测AMD GPU
            c = wmi.WMI()
            for gpu in c.Win32_VideoController():
                if 'AMD' in gpu.Name or 'ATI' in gpu.Name:
                    self.amd_gpus.append(gpu.Name)
            
            # 优先添加NVIDIA GPU
            if self.nvidia_gpus:
                self.gpu_combo.addItems(self.nvidia_gpus)
            
            # 如果有AMD GPU，添加到列表末尾
            if self.amd_gpus:
                self.gpu_combo.addItems(self.amd_gpus)
            
            if not self.nvidia_gpus and not self.amd_gpus:
                print("未检测到NVIDIA或AMD GPU")
            
        except Exception as e:
            print(f"获取GPU信息时出错: {str(e)}")

    def save_preset(self):
        preset_name = self.config_preset_combo.currentText()
        if not preset_name:
            MessageBox("错误", "预设名称不能为空", self).exec()
            return

        # 读取当前配置
        config_file_path = os.path.join(CURRENT_DIR, CONFIG_FILE)
        if not os.path.exists(config_file_path):
            with open(config_file_path, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=4)
        
        with open(config_file_path, 'r', encoding='utf-8') as f:
            try:
                current_settings = json.load(f)
            except json.JSONDecodeError:
                current_settings = {}

        # 更新或新增预设
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
                'model_path': self.model_path.currentText()
            }
        }

        if self.title == '运行server':
            new_preset['config'].update({
                'context_length': self.context_length.value(),
                'n_parallel': self.n_parallel_spinbox.value(),
                'host': self.host_input.currentText(),
                'port': self.port_input.text(),
                'log_format': self.log_format_combo.currentText()
            })

        for i, preset in enumerate(preset_section):
            if preset['name'] == preset_name:
                preset_section[i] = new_preset
                break
        else:
            preset_section.append(new_preset)

        current_settings[self.title] = preset_section

        # 保存配置
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
                    self.model_path.setCurrentText(config.get('model_path', ''))  # 加载模型路径
                    if self.title == '运行server':
                        if hasattr(self, 'context_length'):
                            self.context_length.setValue(config.get('context_length', 1024))
                        if hasattr(self, 'n_parallel_spinbox'):
                            self.n_parallel_spinbox.setValue(config.get('n_parallel', 1))
                        if hasattr(self, 'host_input'):
                            self.host_input.setText(config.get('host', '127.0.0.1'))
                        if hasattr(self, 'port_input'):
                            self.port_input.setText(config.get('port', '8080'))
                        if hasattr(self, 'log_format_combo'):
                            self.log_format_combo.setText(config.get('log_format', 'text'))
                    self.flash_attention_check.setChecked(config.get('flash_attention', True))
                    self.no_mmap_check.setChecked(config.get('no_mmap', True))
                    self.gpu_enabled_check.setChecked(config.get('gpu_enabled', True))
                    self.gpu_combo.setCurrentText(config.get('gpu', ''))
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

        # 按钮布局右对齐
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
        self.log_format_combo = self._create_editable_combo_box(["text", "json"])
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


        self.flash_attention_check = self._create_check_box("启用 Flash Attention -fa", True)
        layout.addWidget(self.flash_attention_check)

        self.no_mmap_check = self._create_check_box("启用 --no-mmap", True)
        layout.addWidget(self.no_mmap_check)

        layout.addLayout(self._create_gpu_selection_layout())

        self.custom_command_append = TextEdit(self)
        self.custom_command_append.setPlaceholderText("手动追加命令（追加到UI选择的命令后）")
        layout.addWidget(self.custom_command_append)

        self.custom_command = TextEdit(self)
        self.custom_command.setPlaceholderText("手动自定义命令（覆盖UI选择）")
        layout.addWidget(self.custom_command)

        self.setLayout(layout)

    def _create_context_length_layout(self):
        layout = QHBoxLayout()
        self.context_length = Slider(Qt.Horizontal, self)
        self.context_length.setRange(256, 32768)
        self.context_length.setPageStep(256)
        self.context_length.setValue(2048)
        self.context_length.valueChanged.connect(lambda value: self.context_length_input.setValue(value))

        self.context_length_input = SpinBox(self)
        self.context_length_input.setRange(256, 32768)
        self.context_length_input.setSingleStep(256)
        self.context_length_input.setValue(2048)
        self.context_length_input.valueChanged.connect(lambda value: self.context_length.setValue(value))

        layout.addWidget(self.context_length)
        layout.addWidget(self.context_length_input)
        return layout

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

        self.custom_command_append = TextEdit(self)
        self.custom_command_append.setPlaceholderText("手动追加命令（追加到UI选择的命令后）")
        layout.addWidget(self.custom_command_append)

        self.custom_command = TextEdit(self)
        self.custom_command.setPlaceholderText("手动自定义命令（覆盖UI选择）")
        layout.addWidget(self.custom_command)

        self.setLayout(layout)
        
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

        # 新增批量基准测试相关UI
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
                'model_path': self.model_path.currentText(),
                'npp': self.npp_input.text(),
                'ntg': self.ntg_input.text(),
                'npl': self.npl_input.text(),
                'pps': self.pps_check.isChecked(),
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
                    break

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

    def __init__(self, url, filename):
        super().__init__()
        self.url = url
        self.filename = filename

    def run(self):
        try:
            response = requests.get(self.url, stream=True)
            total_size = int(response.headers.get('content-length', 0))
            block_size = 1024
            downloaded = 0

            with open(self.filename, 'wb') as file:
                for data in response.iter_content(block_size):
                    file.write(data)
                    downloaded += len(data)
                    if total_size:
                        progress = int((downloaded / total_size) * 100)
                        self.progress.emit(progress)

            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

class DownloadSection(QFrame):
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
        layout = QVBoxLayout(self.model_download_section)

        # 添加说明性文字
        description = QLabel(
            "您可以在这里下载不同版本的模型，或手动从huggingface下载模型。\n8G以下显存推荐使用GalTransl-7B-v1.5_IQ4_XS.gguf，\n8G以上显存推荐使用Sakura-14B-Qwen2beta-v0.9.2_IQ4_XS.gguf。\n模型会下载到程序所在的目录。")
        description.setWordWrap(True)
        layout.addWidget(description)

        self.model_download_table = self.create_download_table()
        self.add_download_item(self.model_download_table,
                               "GalTransl-7B-v1.5_IQ4_XS.gguf", self.download_model)
        self.add_download_item(
            self.model_download_table, "Sakura-14B-Qwen2beta-v0.9.2_IQ4_XS.gguf", self.download_model)
        layout.addWidget(self.model_download_table)
        self.model_download_section.setLayout(layout)

    def init_llamacpp_download_section(self):
        layout = QVBoxLayout(self.llamacpp_download_section)

        # 添加说明性文字
        description = QLabel(
            "您可以在这里下载不同版本的llama.cpp，或手动从Github下载发行版。\nNvidia显卡请选择CUDA版本下载，\nAMD显卡请查看下面的AMD显卡支持列表，\n如果在列表中，请选择ROCm版本下载，\n如果不在列表中，请选择Vulkan版本下载或手动编译。\n注意，Vulkan版本现在还不支持IQ系列的量化。\nllama.cpp会下载到程序所在的目录的llama文件夹内。\n")
        description.setWordWrap(True)
        layout.addWidget(description)

        amd_support_list = """
AMD显卡支持列表：
 - RX 7900 系列显卡
 - RX 7800 系列显卡
 - RX 7700 系列显卡
 - RX 6900/6800 系列显卡
 - RX 6700 系列显卡
        """
        self.amd_support_label = QLabel(self)
        self.amd_support_label.setText(amd_support_list)
        self.amd_support_label.setWordWrap(True)
        layout.addWidget(self.amd_support_label)

        self.llamacpp_download_table = self.create_download_table()
        self.add_download_item(self.llamacpp_download_table,
                               "CUDA 版本", self.download_llamacpp)
        self.add_download_item(self.llamacpp_download_table,
                               "ROCm 版本 (感谢Sora维护)", self.download_llamacpp)
        self.add_download_item(self.llamacpp_download_table,
                               "Vulkan 版本", self.download_llamacpp)
        layout.addWidget(self.llamacpp_download_table)

        self.llamacpp_download_section.setLayout(layout)

    def create_download_table(self):
        table = TableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(['名称', '操作'])
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def add_download_item(self, table, name, download_function):
        row = table.rowCount()
        table.insertRow(row)

        name_item = QTableWidgetItem(name)
        table.setItem(row, 0, name_item)

        download_button = TransparentPushButton(FIF.DOWNLOAD, "下载")
        download_button.clicked.connect(lambda: download_function(name))
        table.setCellWidget(row, 1, download_button)

    def download_model(self, model_name):
        if model_name == "GalTransl-7B-v1.5_IQ4_XS.gguf":
            url = "https://hf-mirror.com/SakuraLLM/GalTransl-7B-v1.5/resolve/main/GalTransl-7B-v1.5-IQ4_XS.gguf"
        elif model_name == "Sakura-14B-Qwen2beta-v0.9.2_IQ4_XS.gguf":
            url = "https://hf-mirror.com/SakuraLLM/Sakura-14B-Qwen2beta-v0.9.2-GGUF/resolve/main/sakura-14b-qwen2beta-v0.9.2-iq4xs.gguf"
        else:
            self.on_download_error("未知的模型名称")
            return

        self.start_download(url, model_name)

    def download_llamacpp(self, version):
        if version == "CUDA 版本":
            url = "https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI/releases/download/v0.0.3-alpha/llama-b3384-bin-win-cuda-cu12.2.0-x64.zip"
        elif version == "ROCm 版本 (感谢Sora维护)":
            url = "https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI/releases/download/v0.0.3-alpha/llama-b3384-bin-win-rocm-avx2-x64.zip"
        elif version == "Vulkan 版本":
            url = "https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI/releases/download/v0.0.3-alpha/llama-b3384-bin-win-vulkan-x64.zip"
        else:
            self.on_download_error("未知的版本")
            return

        self.start_download(url, f"llama.cpp_{version}.zip")

    def unzip_llamacpp(self, filename):
        import zipfile
        #解压到llama文件夹
        llama_folder = os.path.join(CURRENT_DIR, 'llama')
        file_path = os.path.join(CURRENT_DIR, filename)
        print(f"Unzipping {filename} to {llama_folder}")
        if not os.path.exists(llama_folder):
            os.mkdir(llama_folder)
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            # 解压所有文件到llama文件夹，覆盖已存在的文件
            zip_ref.extractall(llama_folder)


        
    # 直接使用requests下载
    def start_download(self, url, filename):
        self.download_thread = DownloadThread(url, filename)
        self.download_thread.progress.connect(self.global_progress_bar.setValue)
        self.download_thread.finished.connect(self.on_download_finished)
        self.download_thread.error.connect(self.on_download_error)
        self.download_thread.start()
        self.main_window.createSuccessInfoBar("下载中", "文件正在下载，请耐心等待，下载进度请关注最下方的进度条。")

    def on_download_finished(self):
        self.main_window.createSuccessInfoBar("下载完成", "文件已成功下载")
        for file in os.listdir(CURRENT_DIR):
            if file.endswith(".zip") and file.startswith("llama.cpp_"):
                self.unzip_llamacpp(file)
                self.main_window.createSuccessInfoBar("解压完成", "已经将llama.cpp解压到程序所在目录的llama文件夹内。")
                os.remove(os.path.join(CURRENT_DIR, file))
                break
            

    def on_download_error(self, error_message):
        logger.error(f"Download error: {error_message}")
        QApplication.processEvents()  # 确保UI更新
        MessageBox("错误", f"下载失败: {error_message}", self).exec()

class SettingsSection(QFrame):
    def __init__(self, title,main_window, parent=None):
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
            'model_search_paths': self.model_search_paths.toPlainText().split('\n')
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
        
        self.init_run_server_section()
        self.init_run_bench_section()

        self.add_sub_interface(self.run_server_section, 'run_server_section', 'Server')
        self.add_sub_interface(self.run_bench_section, 'run_bench_section', 'Bench')

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

        settings = {
            '运行server': server_configs,
            '运行bench': bench_configs
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
        self.init_navigation()
        self.init_window()
        atexit.register(self.terminate_all_processes)

    def init_navigation(self):
        self.settings_section = SettingsSection("设置", self)
        self.run_server_section = RunServerSection("运行server", self)
        self.run_bench_section = RunBenchmarkSection("运行bench", self)
        self.run_llamacpp_batch_bench_section = RunBatchBenchmarkSection("批量运行bench", self)
        self.log_section = LogSection("日志输出")
        self.about_section = AboutSection("关于")
        self.config_editor_section = ConfigEditor("配置编辑", self)
        self.dowload_section = DownloadSection("下载", self)


        self.addSubInterface(self.run_server_section, FIF.COMMAND_PROMPT, "运行server")
        self.addSubInterface(self.run_bench_section, FIF.COMMAND_PROMPT, "运行bench")
        self.addSubInterface(self.run_llamacpp_batch_bench_section, FIF.COMMAND_PROMPT, "batch-bench")
        self.addSubInterface(self.log_section, FIF.BOOK_SHELF, "日志输出")
        self.addSubInterface(self.config_editor_section, FIF.EDIT, "配置编辑")
        self.addSubInterface(self.dowload_section, FIF.DOWNLOAD, "下载")
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
        self.setWindowTitle("Sakura 启动器")
        self.resize(600, 400)

        desktop = QApplication.screens()[0].availableGeometry()
        w, h = desktop.width(), desktop.height()
        self.move(w // 2 - self.width() // 2, h // 2 - self.height() // 2)

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
        return self.settings_section.model_search_paths.toPlainText().split('\n')

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
        llamacpp_path = self.get_llamacpp_path()
        exe_extension = '.exe' if sys.platform == 'win32' else ''

        if not os.path.exists(llamacpp_path):
            MessageBox("错误", f"llamacpp路径不存在", self).exec()
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
                command += f' -c {section.context_length.value()}'
                command += f' -a {model_name}'
                command += f' --host {section.host_input.currentText()} --port {section.port_input.text()}'
                command += f' --log-format {section.log_format_combo.currentText()}'
                command += f' -np {section.n_parallel_spinbox.value()}'

                if section.flash_attention_check.isChecked():
                    command += ' -fa'
                if section.no_mmap_check.isChecked():
                    command += ' --no-mmap'
                if section.custom_command_append.toPlainText().strip():
                    command += f' {section.custom_command_append.toPlainText().strip()}'
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

        # 如果启用单GPU选项被选中
        if section.gpu_enabled_check.isChecked():
            selected_gpu = section.gpu_combo.currentText()  # 获取当前选中的GPU名称
            selected_index = section.gpu_combo.currentIndex()  # 获取当前选中的GPU索引
            
            # 检查是否存在NVIDIA GPU
            if section.nvidia_gpus:
                # 如果选中的是NVIDIA GPU (索引小于NVIDIA GPU总数)
                if selected_index < len(section.nvidia_gpus):
                    # 设置CUDA_VISIBLE_DEVICES环境变量,使CUDA只能看到选中的GPU
                    os.environ["CUDA_VISIBLE_DEVICES"] = str(selected_index)
                    self.log_info(f"CUDA_VISIBLE_DEVICES: {selected_index}")
                else:
                    # 如果选中的是AMD GPU,计算AMD GPU的索引
                    amd_index = selected_index - len(section.nvidia_gpus)
                    # 设置HIP_VISIBLE_DEVICES环境变量,使ROCm只能看到选中的GPU
                    os.environ["HIP_VISIBLE_DEVICES"] = str(amd_index)
                    self.log_info(f"HIP_VISIBLE_DEVICES: {amd_index}")
            else:
                # 如果没有NVIDIA GPU,假定全部是AMD GPU
                os.environ["HIP_VISIBLE_DEVICES"] = str(selected_index)
                self.log_info(f"HIP_VISIBLE_DEVICES: {selected_index}")

            # 检查选中的GPU是否为AMD GPU
            if 'AMD' in selected_gpu or 'ATI' in selected_gpu:
                # 设置HSA_OVERRIDE_GFX_VERSION环境变量,以确保兼容性
                os.environ["HSA_OVERRIDE_GFX_VERSION"] = "10.3.0"
                self.log_info("设置 HSA_OVERRIDE_GFX_VERSION = 10.3.0")


        self.log_info(f"执行命令: {command}")

        if sys.platform == 'win32':
            command = f'start cmd /K "{command}"'
            subprocess.Popen(command, shell=True)
        else:
            command = f'x-terminal-emulator -e "{command}"'
            subprocess.Popen(command, shell=True)

        self.log_info("命令已在新的终端窗口中启动。")

    def log_info(self, message):
        self.log_section.log_display.append(message)
        self.log_section.log_display.ensureCursorVisible()

    def terminate_all_processes(self):
        for proc in processes:
            proc.terminate()
        processes.clear()


if __name__ == "__main__":
    setTheme(Theme.DARK)
    setThemeColor(QColor(222, 142, 204))
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
        