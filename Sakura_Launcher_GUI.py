from math import e
import sys
import os
import json
import subprocess
import atexit
from functools import partial
from PySide6.QtCore import Qt, Signal, QObject, Slot
from PySide6.QtWidgets import QApplication, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGroupBox, QHeaderView, QTableWidgetItem, QTabWidget, QWidget, QStackedWidget
from PySide6.QtGui import QIcon, QColor
from qfluentwidgets import PushButton, CheckBox, SpinBox, PrimaryPushButton, TextEdit, EditableComboBox, MessageBox, setTheme, Theme, MSFluentWindow, FluentIcon as FIF, Slider, ComboBox, setThemeColor, LineEdit, HyperlinkButton, NavigationItemPosition, TableWidget, TransparentPushButton, SegmentedWidget

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
SAKURA_LAUNCHER_GUI_VERSION = '0.0.2'

print(CURRENT_DIR)

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
        self.config_preset_combo = None
        self.custom_command = None
        self.custom_command_append = None
        self.gpu_layers_spinbox = None
        self.model_path = None
        self.refresh_model_button = None
        self.gpu_enabled_check = None
        self.gpu_combo = None
        self.flash_attention_check = None
        self.no_mmap_check = None
        self.context_length = None
        self.n_parallel_spinbox = None
        self.host_input = None
        self.port_input = None
        self.log_format_combo = None

    def _init_common_ui(self, layout):
        layout.addLayout(self._create_model_selection_layout())
        layout.addWidget(QLabel("配置预设选择"))
        self.config_preset_combo = EditableComboBox(self)
        self.config_preset_combo.currentIndexChanged.connect(self.load_selected_preset)
        layout.addWidget(self.config_preset_combo)

        self.custom_command = TextEdit(self)
        self.custom_command.setPlaceholderText("手动自定义命令（覆盖UI选择）")
        layout.addWidget(self.custom_command)

        self.custom_command_append = TextEdit(self)
        self.custom_command_append.setPlaceholderText("手动追加命令（追加到UI选择的命令后）")
        layout.addWidget(self.custom_command_append)

        layout.addLayout(self._create_slider_spinbox_layout("GPU层数 -ngl", "gpu_layers", 999, 1, 999, 1))

    def _create_gpu_selection_layout(self):
        layout = QHBoxLayout()
        self.gpu_enabled_check = self._create_check_box("单GPU启动（仅支持NVIDIA显卡）", True)
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
                models.extend([os.path.join(path, f) for f in os.listdir(path) if f.endswith('.gguf')])
        self.model_path.addItems(models)

    def refresh_gpus(self):
        self.gpu_combo.clear()
        try:
            os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            result = subprocess.run('nvidia-smi --query-gpu=name --format=csv,noheader', shell=True, capture_output=True, text=True)
            gpus = result.stdout.strip().split('\n')
            self.gpu_combo.addItems(gpus)
        except Exception as e:
            print(f"未检测到GPU，可能是因为你使用的是AMD显卡或者核显: {str(e)}")

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
        MessageBox("成功", "预设已保存", self).exec()

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
        self._init_common_ui(layout)

        layout.addWidget(QLabel("上下文长度 -c"))
        layout.addLayout(self._create_context_length_layout())

        layout.addLayout(self._create_slider_spinbox_layout("并行工作线程数 -np", "n_parallel", 1, 1, 32, 1))

        self.host_input = self._create_editable_combo_box(["127.0.0.1", "0.0.0.0"])
        layout.addWidget(QLabel("主机地址 --host"))
        layout.addWidget(self.host_input)

        self.port_input = self._create_line_edit("", "8080")
        layout.addWidget(QLabel("端口 --port"))
        layout.addWidget(self.port_input)

        self.log_format_combo = self._create_editable_combo_box(["text", "json"])
        layout.addWidget(QLabel("日志格式 --log-format"))
        layout.addWidget(self.log_format_combo)

        self.flash_attention_check = self._create_check_box("启用 Flash Attention -fa", True)
        layout.addWidget(self.flash_attention_check)

        self.no_mmap_check = self._create_check_box("启用 --no-mmap", True)
        layout.addWidget(self.no_mmap_check)

        layout.addLayout(self._create_gpu_selection_layout())

        self.run_button = PrimaryPushButton(FIF.PLAY, '运行', self)
        layout.addWidget(self.run_button)

        self.save_preset_button = PushButton(FIF.SAVE, '保存预设', self)
        self.save_preset_button.clicked.connect(self.save_preset)
        layout.addWidget(self.save_preset_button)

        self.load_preset_button = PushButton(FIF.SYNC, '刷新预设', self)
        self.load_preset_button.clicked.connect(self.load_presets)
        layout.addWidget(self.load_preset_button)

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
        self._init_common_ui(layout)

        self.flash_attention_check = self._create_check_box("启用 Flash Attention -fa", True)
        layout.addWidget(self.flash_attention_check)

        self.no_mmap_check = self._create_check_box("启用 --no-mmap", True)
        layout.addWidget(self.no_mmap_check)

        layout.addLayout(self._create_gpu_selection_layout())

        self.run_button = PrimaryPushButton(FIF.PLAY, '运行', self)
        layout.addWidget(self.run_button)

        self.save_preset_button = PushButton(FIF.SAVE, '保存预设', self)
        self.save_preset_button.clicked.connect(self.save_preset)
        layout.addWidget(self.save_preset_button)

        self.load_preset_button = PushButton(FIF.SYNC, '刷新预设', self)
        self.load_preset_button.clicked.connect(self.load_presets)
        layout.addWidget(self.load_preset_button)

        self.setLayout(layout)
        

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

        self.clear_log_button = PushButton("清空日志", self)
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

class SettingsSection(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
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

        self.save_button = PushButton(FIF.SAVE, '保存设置', self)
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

        MessageBox("成功", "设置已保存", self).exec()

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
        # MessageBox("成功", "设置已加载", self).exec()

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

from PySide6.QtCore import QTimer, Qt

class ConfigEditor(QFrame):
    LONG_PRESS_TIME = 500  # 设置长按延迟时间（毫秒）

    def __init__(self, title, parent=None):
        super().__init__(parent)
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

        MessageBox("成功", "设置已保存", self).exec()

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
        self.settings_section = SettingsSection("设置")
        self.run_server_section = RunServerSection("运行server", self)
        self.run_bench_section = RunBenchmarkSection("运行bench", self)
        self.log_section = LogSection("日志输出")
        self.about_section = AboutSection("关于")
        self.config_editor_section = ConfigEditor("配置编辑")


        self.addSubInterface(self.run_server_section, FIF.COMMAND_PROMPT, "运行server")
        self.addSubInterface(self.run_bench_section, FIF.COMMAND_PROMPT, "运行bench")
        self.addSubInterface(self.log_section, FIF.BOOK_SHELF, "日志输出")
        self.addSubInterface(self.config_editor_section, FIF.EDIT, "配置编辑")
        self.addSubInterface(self.settings_section, FIF.SETTING, "设置")
        self.addSubInterface(self.about_section, FIF.INFO, "关于", position=NavigationItemPosition.BOTTOM)

        self.navigationInterface.setCurrentItem(self.run_server_section.objectName())

    def init_window(self):
        self.run_server_section.run_button.clicked.connect(self.run_llamacpp_server)
        self.run_bench_section.run_button.clicked.connect(self.run_llamacpp_bench)
        self.run_server_section.load_preset_button.clicked.connect(self.run_server_section.load_presets)
        self.run_bench_section.load_preset_button.clicked.connect(self.run_bench_section.load_presets)
        self.run_server_section.refresh_model_button.clicked.connect(self.run_server_section.refresh_models)
        self.run_bench_section.refresh_model_button.clicked.connect(self.run_bench_section.refresh_models)
        
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
        self.resize(800, 600)

        desktop = QApplication.screens()[0].availableGeometry()
        w, h = desktop.width(), desktop.height()
        self.move(w // 2 - self.width() // 2, h // 2 - self.height() // 2)

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

        if section.gpu_enabled_check.isChecked():
            os.environ["CUDA_VISIBLE_DEVICES"] = str(section.gpu_combo.currentIndex())
            self.log_info(f"CUDA_VISIBLE_DEVICES: {os.environ['CUDA_VISIBLE_DEVICES']}")

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

    @Slot()
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
        