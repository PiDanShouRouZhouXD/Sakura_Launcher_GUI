import logging
import sys
import os
import json
import subprocess
import re
import shutil
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QAbstractScrollArea
from PySide6.QtGui import QIcon, QColor, QFont
from qfluentwidgets import (
    MessageBox,
    setTheme,
    Theme,
    MSFluentWindow,
    FluentIcon as FIF,
    setThemeColor,
    NavigationItemPosition,
    InfoBarPosition,
)

from src.common import *
from src.llamacpp import get_llamacpp_version
from src.section_run_server import GPUManager, RunServerSection
from src.section_download import DownloadSection
from src.section_share import CFShareSection
from src.section_about import AboutSection
from src.section_settings import SettingsSection
from src.ui import *


class MainWindow(MSFluentWindow):
    def __init__(self):
        super().__init__()
        self.gpu_manager = GPUManager()
        self.init_navigation()
        self.init_window()
        cloudflared_path = get_resource_path(CLOUDFLARED)
        if not os.path.exists(cloudflared_path):
            MessageBox(
                "错误", f"cloudflared 可执行文件不存在: {cloudflared_path}", self
            ).exec()
        self.setMinimumSize(600, 700)
        self.load_window_state()

        # 黑魔法，强行覆盖函数以关闭标签页切换动画
        def setCurrentWidget(widget, _=True):
            if isinstance(widget, QAbstractScrollArea):
                widget.verticalScrollBar().setValue(0)
            self.stackedWidget.view.setCurrentWidget(widget, duration=0)

        self.stackedWidget.setCurrentWidget = (
            lambda widget, popOut=True: setCurrentWidget(widget, popOut)
        )

    def init_navigation(self):
        self.settings_section = SettingsSection("设置")
        self.run_server_section = RunServerSection("运行", self)
        self.about_section = AboutSection("关于")
        self.dowload_section = DownloadSection("下载")
        self.cf_share_section = CFShareSection("共享", self)

        self.addSubInterface(self.run_server_section, FIF.COMMAND_PROMPT, "运行")
        self.addSubInterface(self.dowload_section, FIF.DOWNLOAD, "下载")
        self.addSubInterface(self.cf_share_section, FIF.IOT, "共享")
        self.addSubInterface(self.settings_section, FIF.SETTING, "设置")
        self.addSubInterface(
            self.about_section, FIF.INFO, "关于", position=NavigationItemPosition.BOTTOM
        )

        self.navigationInterface.setCurrentItem(self.run_server_section.objectName())

    def init_window(self):
        self.run_server_section.run_button.clicked.connect(self.run_llamacpp_server)
        self.run_server_section.run_and_share_button.clicked.connect(
            self.run_llamacpp_server_and_share
        )
        self.run_server_section.benchmark_button.clicked.connect(
            self.run_llamacpp_batch_bench
        )
        self.run_server_section.load_preset_button.clicked.connect(
            self.run_server_section.load_presets
        )
        self.run_server_section.refresh_model_button.clicked.connect(
            self.run_server_section.refresh_models
        )

        # 连接设置更改信号
        self.settings_section.sig_need_update.connect(
            self.dowload_section.start_download_launcher
        )
        self.settings_section.model_sort_combo.currentIndexChanged.connect(
            self.run_server_section.refresh_models
        )

        self.setStyleSheet(
            """
            QLabel {
                color: #dadada;
            }

            CheckBox {
                color: #dadada;
            }

            AcrylicWindow{
                background-color: #272727;
            }
        """
        )

        icon = get_resource_path(ICON_FILE)
        self.setWindowIcon(QIcon(icon))
        self.setWindowTitle(f"Sakura 启动器 {SAKURA_LAUNCHER_GUI_VERSION}")

        desktop = QApplication.screens()[0].availableGeometry()
        w, h = desktop.width(), desktop.height()
        self.move(w // 2 - self.width() // 2, h // 2 - self.height() // 2)

    def get_llamacpp_path(self):
        path = self.settings_section.llamacpp_path.text()
        if not path:
            return os.path.join(CURRENT_DIR, "llama")
        return os.path.abspath(path)

    def get_model_search_paths(self):
        paths = self.settings_section.model_search_paths.toPlainText().split("\n")
        return [path.strip() for path in paths if path.strip()]

    def _add_quotes(self, path):
        return f'"{path}"'

    def run_llamacpp_server(self):
        self._run_llamacpp(self.run_server_section, "llama-server")

    def run_llamacpp_server_and_share(self):
        self._run_llamacpp(self.run_server_section, "llama-server")
        cf_share_url = self.cf_share_section.worker_url_input.text()
        if not cf_share_url:
            MessageBox("错误", "分享链接不能为空", self).exec()
            return
        QTimer.singleShot(18000, self.cf_share_section.start_cf_share)

    def run_llamacpp_batch_bench(self):
        self._run_llamacpp(self.run_server_section, "llama-batched-bench")

    def _run_llamacpp(self, section, executable):
        custom_command = section.custom_command.toPlainText().strip()
        llamacpp_override = section.llamacpp_override.text().strip()
        llamacpp_path = (
            llamacpp_override if llamacpp_override else self.get_llamacpp_path()
        )
        exe_extension = ".exe" if sys.platform == "win32" else ""

        if not os.path.exists(llamacpp_path):
            MessageBox("错误", f"llamacpp路径不存在: {llamacpp_path}", self).exec()
            return

        model_name = section.model_path.currentText().split(os.sep)[-1]
        model_path = self._add_quotes(section.model_path.currentText())
        logging.info(f"模型路径: {model_path}")
        logging.info(f"模型名称: {model_name}")

        # 判断使用哪个可执行文件
        executable_path = os.path.join(llamacpp_path, f"{executable}{exe_extension}")
        if not os.path.exists(executable_path):
            MessageBox("错误", f"可执行文件不存在: {executable_path}", self).exec()
            return

        executable_path = self._add_quotes(executable_path)

        # 获取llama.cpp版本
        version = get_llamacpp_version(llamacpp_path)
        logging.info(f"llama.cpp版本: {version}")

        if custom_command:
            command = f"{executable_path} --model {model_path} {custom_command}"
        else:
            command = f"{executable_path} --model {model_path}"

            if executable == "llama-server":
                command += f" -ngl {section.gpu_layers_spinbox.value()}"
                command += f" -c {section.context_length_input.value()}"
                command += f" -a {model_name}"
                command += f" --host {section.host_input.currentText()} --port {section.port_input.text()}"
                command += f" -np {section.n_parallel_spinbox.value()}"

                if section.flash_attention_check.isChecked():
                    command += " -fa"
                if section.no_mmap_check.isChecked():
                    command += " --no-mmap"
                if section.custom_command_append.text().strip():
                    command += f" {section.custom_command_append.text().strip()}"
                command += " --metrics"

                # 根据版本添加--slots参数
                if version is not None and version >= 3898:
                    logging.info("版本大于等于3898，添加--slots参数")
                    command += " --slots"
            elif executable == "llama-batched-bench":
                command += f" -c {section.context_length_input.value()}"
                command += f" -ngl {section.gpu_layers_spinbox.value()}"
                command += f" -npp {section.npp_input.text()}"
                command += f" -ntg {section.ntg_input.text()}"
                command += f" -npl {section.npl_input.text()}"
                if section.flash_attention_check.isChecked():
                    command += " -fa"
                if section.no_mmap_check.isChecked():
                    command += " --no-mmap"
                if section.custom_command_append.text().strip():
                    command += f" {section.custom_command_append.text().strip()}"

        env = os.environ.copy()
        if section.gpu_combo.currentText() != "自动":
            selected_gpu = section.gpu_combo.currentText()
            selected_index = section.gpu_combo.currentIndex()
            manual_index = section.manully_select_gpu_index.text()

            try:
                self.gpu_manager.set_gpu_env(
                    env, selected_gpu, selected_index, manual_index
                )
            except Exception as e:
                logging.info(f"设置GPU环境变量时出错: {str(e)}")
                MessageBox("错误", f"设置GPU环境变量时出错: {str(e)}", self).exec()
                return

        logging.info(f"执行命令: {command}")

        # 在运行命令的部分
        if sys.platform == "win32":
            command = f'start cmd /K "{command}"'
            subprocess.Popen(command, env=env, shell=True)
        else:
            terminal = self.find_terminal()
            if terminal:
                if terminal == "gnome-terminal":
                    subprocess.Popen([terminal, "--", "bash", "-c", command], env=env)
                else:
                    subprocess.Popen([terminal, "-e", command], env=env)
            else:
                MessageBox(
                    "错误", "无法找到合适的终端模拟器。请手动运行命令。", self
                ).exec()
                logging.info(f"请手动运行以下命令：\n{command}")
                return

        logging.info("命令已在新的终端窗口中启动。")

    def find_terminal(self):
        terminals = [
            "x-terminal-emulator",
            "gnome-terminal",
            "konsole",
            "xfce4-terminal",
            "xterm",
        ]
        for term in terminals:
            if shutil.which(term):
                return term
        return None

    def closeEvent(self, event):
        self.save_window_state()
        self.terminate_all_processes()
        event.accept()

    def terminate_all_processes(self):
        print("Terminating all processes...")
        try:
            self.cf_share_section.stop_cf_share()
        except AttributeError:
            print("Warning: CFShareSection not properly initialized")
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

        if not self.gpu_manager.nvidia_gpus and not self.gpu_manager.amd_gpus:
            logging.info("未检测到NVIDIA或AMD GPU")

    def save_window_state(self):
        if self.settings_section.remember_window_state.isChecked():
            settings = {
                "window_geometry": {
                    "x": self.x(),
                    "y": self.y(),
                    "width": self.width(),
                    "height": self.height(),
                }
            }
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config_data = json.load(f)
            config_data.update(settings)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)

    def load_window_state(self):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                settings = json.load(f)
            if settings.get("remember_window_state", False):
                geometry = settings.get("window_geometry", {})
                if geometry:
                    self.setGeometry(
                        geometry.get("x", self.x()),
                        geometry.get("y", self.y()),
                        geometry.get("width", self.width()),
                        geometry.get("height", self.height()),
                    )
        except (FileNotFoundError, json.JSONDecodeError):
            pass


if __name__ == "__main__":
    setTheme(Theme.DARK)
    setThemeColor(QColor(222, 142, 204))
    app = QApplication(sys.argv)
    better_font = QFont()

    # 获取主屏幕的缩放比例和原始分辨率
    screen = app.primaryScreen()
    screen_geometry = screen.geometry()
    device_pixel_ratio = screen.devicePixelRatio()
    print(f"设备像素比: {device_pixel_ratio}")

    # 计算原始分辨率
    original_width = screen_geometry.width() * device_pixel_ratio
    original_height = screen_geometry.height() * device_pixel_ratio
    print(f"原始屏幕分辨率: {original_width}x{original_height}")

    # 如果原始分辨率大于1920x1080，关闭hinting
    if original_width > 1920 and original_height > 1080:
        print("原始屏幕分辨率大于1920x1080，关闭hinting")
        better_font.setHintingPreference(QFont.PreferNoHinting)

    app.setFont(better_font)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
