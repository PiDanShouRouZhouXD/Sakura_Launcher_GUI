import sys
import os
import json
import subprocess
import atexit
from PySide6.QtCore import Qt, Signal, QObject, Slot
from PySide6.QtWidgets import QApplication, QVBoxLayout, QHBoxLayout, QLabel,QFrame
from PySide6.QtGui import QIcon, QColor
from qfluentwidgets import PushButton, CheckBox, SpinBox, PrimaryPushButton, TextEdit, EditableComboBox, MessageBox, setTheme, Theme, MSFluentWindow, FluentIcon as FIF, Slider, ComboBox, setThemeColor, LineEdit

def get_self_path():
    if getattr(sys, 'frozen', False):
        # 如果程序是被打包的，sys.frozen 会被设置为 True
        return os.path.dirname(sys.executable)
    else:
        # 如果程序没有被打包，返回脚本所在目录
        return os.path.dirname(os.path.abspath(__file__))

def get_resource_path(relative_path):
    """ 获取资源文件路径，支持在 PyInstaller 打包后的程序中使用。"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    else:
        return os.path.join(os.path.abspath("."), relative_path)

CURRENT_DIR = get_self_path()
CONFIG_FILE = 'sakura-launcher_config.json'
ICON_FILE = 'icon.png'

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
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName(title.replace(' ', '-'))
        self.title = title

    def _init_common_ui(self, layout):
        layout.addLayout(self._create_model_selection_layout())
        layout.addWidget(QLabel("配置预设选择"))
        self.config_preset_combo = EditableComboBox(self)
        self.config_preset_combo.currentIndexChanged.connect(self.load_selected_preset)
        layout.addWidget(self.config_preset_combo)

        self.llamacpp_path = self._create_line_edit("llama.cpp二进制文件所在的路径（可选），留空则为当前目录下的llama文件夹", "")
        layout.addWidget(QLabel("llama.cpp 文件夹"))
        layout.addWidget(self.llamacpp_path)

        self.custom_command = TextEdit(self)
        self.custom_command.setPlaceholderText("手动自定义命令（覆盖UI选择）")
        layout.addWidget(self.custom_command)

        self.custom_command_append = TextEdit(self)
        self.custom_command_append.setPlaceholderText("手动追加命令（追加到UI选择的命令后）")
        layout.addWidget(self.custom_command_append)

        layout.addLayout(self._create_slider_spinbox_layout("GPU层数 -ngl", "gpu_layers", 999, 1, 999, 1))

    def _create_slider_spinbox_layout(self, label_text, variable_name, slider_value, slider_min, slider_max, slider_step):
        """
        创建一个包含Slider和SpinBox的通用布局，并设置它们之间的同步
        """
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

        # 保存slider和spinbox到实例变量以便访问
        setattr(self, f"{variable_name.replace(' ', '_')}", slider)
        setattr(self, f"{variable_name.replace(' ', '_')}_spinbox", spinbox)
        
        return layout

    def _create_model_selection_layout(self):
        layout = QHBoxLayout()
        self.model_path = EditableComboBox(self)
        self.model_path.setPlaceholderText("请选择模型路径")
        self.refresh_model_button = PushButton(FIF.SYNC,'刷新模型', self)
        self.refresh_model_button.clicked.connect(self.refresh_models)
        layout.addWidget(self.model_path)
        layout.addWidget(self.refresh_model_button)
        return layout

    def _create_line_edit(self, placeholder, text):
        line_edit = LineEdit(self)
        line_edit.setPlaceholderText(placeholder)
        line_edit.setText(text)
        return line_edit

    def _create_check_box(self, text, checked):
        check_box = CheckBox(text, self)
        check_box.setChecked(checked)
        return check_box

    def _create_gpu_selection_layout(self):
        layout = QHBoxLayout()
        self.gpu_enabled_check = self._create_check_box("单GPU启动（仅支持NVIDIA显卡）", True)
        self.gpu_enabled_check.stateChanged.connect(self.toggle_gpu_selection)
        self.gpu_combo = ComboBox(self)
        layout.addWidget(self.gpu_enabled_check)
        layout.addWidget(self.gpu_combo)
        return layout

    def refresh_models(self):
        self.model_path.clear()
        models = [f for f in os.listdir('.') if f.endswith('.gguf')]
        self.model_path.addItems(models)

    def refresh_gpus(self):
        self.gpu_combo.clear()
        try:
            os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            result = subprocess.run(
                'nvidia-smi --query-gpu=name --format=csv,noheader', shell=True, capture_output=True, text=True)
            gpus = result.stdout.strip().split('\n')
            self.gpu_combo.addItems(gpus)
        except Exception as e:
            print(f"未检测到GPU，可能是因为你使用的是AMD显卡或者核显: {str(e)}")

    def save_preset(self):
        preset_name = self.config_preset_combo.currentText()
        if not preset_name:
            MessageBox("错误", "预设名称不能为空", self).exec()
            return

        presets = self.load_presets_from_file()
        if self.title not in presets:
            presets[self.title] = []

        new_preset = {
            'name': preset_name,
            'config': {
                'llamacpp_path': self.llamacpp_path.text(),
                'custom_command': self.custom_command.toPlainText(),
                'custom_command_append': self.custom_command_append.toPlainText(),
                'gpu_layers': self.gpu_layers_spinbox.value(),
                'flash_attention': self.flash_attention_check.isChecked(),
                'no_mmap': self.no_mmap_check.isChecked(),
                'gpu_enabled': self.gpu_enabled_check.isChecked(),
                'gpu': self.gpu_combo.currentText()
            }
        }

        if hasattr(self, 'context_length'):
            new_preset['config'].update({
                'context_length': self.context_length.value(),
                'n_parallel': self.n_parallel_spinbox.value(),
                'host': self.host_input.currentText(),
                'port': self.port_input.text(),
                'log_format': self.log_format_combo.currentText()
            })

        # 查找同名预设并更新，否则追加
        for i, preset in enumerate(presets[self.title]):
            if preset['name'] == preset_name:
                presets[self.title][i] = new_preset
                break
        else:
            presets[self.title].append(new_preset)
        
        config_file_path = os.path.join(CURRENT_DIR, CONFIG_FILE)
        with open(config_file_path, 'w', encoding='utf-8') as f:
            json.dump(presets, f, ensure_ascii=False, indent=4)

        self.load_presets()
        MessageBox("成功", "预设已保存", self).exec()

    def load_presets(self):
        self.config_preset_combo.clear()
        presets = self.load_presets_from_file()
        if self.title in presets:
            self.config_preset_combo.addItems([preset['name'] for preset in presets[self.title]])

    def load_selected_preset(self):
        preset_name = self.config_preset_combo.currentText()
        presets = self.load_presets_from_file()
        if self.title in presets:
            for preset in presets[self.title]:
                if preset['name'] == preset_name:
                    config = preset['config']
                    self.llamacpp_path.setText(config.get('llamacpp_path', ''))
                    self.custom_command.setPlainText(config.get('custom_command', ''))
                    self.custom_command_append.setPlainText(config.get('custom_command_append', ''))
                    self.gpu_layers_spinbox.setValue(config.get('gpu_layers', 99))
                    if hasattr(self, 'context_length'):
                        self.context_length.setValue(config.get('context_length', 1024))
                    if hasattr(self, 'n_parallel_spinbox'):
                        self.n_parallel_spinbox.setValue(config.get('n_parallel', 1))
                    if hasattr(self, 'host_input'):
                        self.host_input.setCurrentText(config.get('host', '127.0.0.1'))
                    if hasattr(self, 'port_input'):
                        self.port_input.setText(config.get('port', '8080'))
                    if hasattr(self, 'log_format_combo'):
                        self.log_format_combo.setCurrentText(config.get('log_format', 'text'))
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
    def __init__(self, title, parent=None):
        super().__init__(title, parent)
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

        self.save_preset_button = PushButton(FIF.SAVE,'保存预设', self)
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

    def _create_editable_combo_box(self, items):
        combo_box = EditableComboBox(self)
        combo_box.addItems(items)
        return combo_box


class RunBenchmarkSection(RunSection):
    def __init__(self, title, parent=None):
        super().__init__(title, parent)
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

        self.save_preset_button = PushButton(FIF.SAVE,'保存预设', self)
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

        # self.terminate_button = PrimaryPushButton("关闭所有进程", self)
        # self.terminate_button.clicked.connect(self.terminate_all_processes)
        # layout.addWidget(self.terminate_button)

        self.setLayout(layout)

    def clear_log(self):
        self.log_display.clear()

    def log_info(self, message):
        self.log_display.append(message)
        self.log_display.ensureCursorVisible()  # 确保日志滚动到最新

    @Slot()
    def terminate_all_processes(self):
        for proc in processes:
            proc.terminate()
        processes.clear()
        self.log_info("所有进程已终止。")


class MainWindow(MSFluentWindow):
    def __init__(self):
        super().__init__()
        self.init_navigation()
        self.init_window()


        atexit.register(self.terminate_all_processes)

    def init_navigation(self):
        self.run_server_section = RunServerSection("运行server")
        self.run_bench_section = RunBenchmarkSection("运行bench")
        self.log_section = LogSection("日志输出")

        self.addSubInterface(self.run_server_section, FIF.COMMAND_PROMPT, "运行server")
        self.addSubInterface(self.run_bench_section, FIF.COMMAND_PROMPT, "运行bench")
        self.addSubInterface(self.log_section, FIF.BOOK_SHELF, "日志输出")

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

        # 居中显示窗口
        desktop = QApplication.screens()[0].availableGeometry()
        w, h = desktop.width(), desktop.height()
        self.move(w // 2 - self.width() // 2, h // 2 - self.height() // 2)

    def run_llamacpp_server(self):
        self._run_llamacpp(self.run_server_section, 'server')

    def run_llamacpp_bench(self):
        self._run_llamacpp(self.run_bench_section, 'llama-bench')

    def _run_llamacpp(self, section, executable):
        custom_command = section.custom_command.toPlainText().strip()
        if section.llamacpp_path.text() == '':
            llamacpp_path = os.path.join(CURRENT_DIR, 'llama')
        else:
            llamacpp_path = section.llamacpp_path.text()
        exe_extension = '.exe' if sys.platform == 'win32' else ''
        
        if not os.path.exists(llamacpp_path):
            MessageBox("错误", f"llamacpp路径不存在", self).exec()
            return

        executable_path = os.path.join(llamacpp_path, f'{executable}{exe_extension}')

        if custom_command:
            command = custom_command
        else:
            model_path = section.model_path.currentText()
            command = f"{executable_path} --model {model_path}"
            command += f" -ngl {section.gpu_layers_spinbox.value()}"

            if executable == 'server':
                command += f" -c {section.context_length.value()}"
                command += f" -a {model_path}"
                command += f" --host {section.host_input.currentText()} --port {section.port_input.text()}"
                command += f" --log-format {section.log_format_combo.currentText()}"
                command += f" -np {section.n_parallel_spinbox.value()}"


                if section.flash_attention_check.isChecked():
                    command += " -fa"
                if section.no_mmap_check.isChecked():
                    command += " --no-mmap"
                if section.custom_command_append.toPlainText().strip():
                    command += f" {section.custom_command_append.toPlainText().strip()}"
            else:
                if section.flash_attention_check.isChecked():
                    command += " -fa 1,0"
                if section.no_mmap_check.isChecked():
                    command += " -mmp 0"
                if section.custom_command_append.toPlainText().strip():
                    command += f" {section.custom_command_append.toPlainText().strip()}"

        if section.gpu_enabled_check.isChecked():
            os.environ["CUDA_VISIBLE_DEVICES"] = str(section.gpu_combo.currentIndex())
            self.log_info(f"CUDA_VISIBLE_DEVICES: {os.environ['CUDA_VISIBLE_DEVICES']}")

        self.log_info(f"执行命令: {command}")

        # 在新的终端窗口中运行命令
        if sys.platform == 'win32':
            subprocess.Popen(f'start cmd /K {command}', shell=True)
        else:
            subprocess.Popen(f'x-terminal-emulator -e "{command}"', shell=True)

        self.log_info("命令已在新的终端窗口中启动。")

    def log_info(self, message):
        self.log_section.log_display.append(message)
        self.log_section.log_display.ensureCursorVisible()  # 确保日志滚动到最新

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
