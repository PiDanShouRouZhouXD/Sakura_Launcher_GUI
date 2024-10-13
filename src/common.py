import sys
import os
import subprocess
import logging
from enum import Enum
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
)
from qfluentwidgets import (
    PushButton,
    CheckBox,
    SpinBox,
    EditableComboBox,
    FluentIcon as FIF,
    Slider,
    ComboBox,
    LineEdit,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_resource_path(relative_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    else:
        return os.path.join(os.path.abspath("."), relative_path)


def get_self_path():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


CURRENT_DIR = get_self_path()
CONFIG_FILE = "sakura-launcher_config.json"
ICON_FILE = "icon.png"
CLOUDFLARED = "cloudflared-windows-amd64.exe"
SAKURA_LAUNCHER_GUI_VERSION = "0.0.8-beta"

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


class LlamaCPPWorker(QObject):
    progress = Signal(str)
    finished = Signal(bool)

    def __init__(self, command):
        super().__init__()
        self.command = command

    def run(self):
        try:
            self.progress.emit(f"Running command: {self.command}")
            proc = subprocess.Popen(
                self.command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            processes.append(proc)
            for line in iter(proc.stdout.readline, b""):
                self.progress.emit(line.decode("utf-8").strip())
            while proc.poll() is None:
                for line in iter(proc.stdout.readline, b""):
                    self.progress.emit(line.decode("utf-8").strip())
                for line in iter(proc.stderr.readline, b""):
                    self.progress.emit("stderr: " + line.decode("utf-8").strip())
            if proc.returncode == 0:
                self.finished.emit(True)
            else:
                self.progress.emit(
                    "Error: Command failed with exit code {}".format(proc.returncode)
                )
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
        self.setObjectName(title.replace(" ", "-"))
        self.title = title

    def _create_gpu_selection_layout(self):
        layout = QHBoxLayout()
        self.gpu_combo = ComboBox(self)
        self.manully_select_gpu_index = LineEdit(self)
        self.manully_select_gpu_index.setPlaceholderText("手动指定GPU索引")
        self.manully_select_gpu_index.setFixedWidth(140)
        layout.addWidget(self.gpu_combo)
        layout.addWidget(self.manully_select_gpu_index)
        return layout

    def _create_model_selection_layout(self):
        layout = QHBoxLayout()
        self.model_path = EditableComboBox(self)
        self.model_path.setPlaceholderText("请选择模型路径")
        self.refresh_model_button = PushButton(FIF.SYNC, "刷新", self)
        self.refresh_model_button.clicked.connect(self.refresh_models)
        layout.addWidget(self.model_path)
        layout.addWidget(self.refresh_model_button)
        return layout

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
