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
    InfoBar,
    InfoBarPosition,
)

from src.common import *
from src.section_run_server import GPUManager, RunServerSection
from src.section_download import DownloadSection
from src.section_log import LogSection
from src.section_share import CFShareSection
from src.section_about import AboutSection
from src.section_config_editor import ConfigEditor
from src.section_settings import SettingsSection


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
        self.settings_section = SettingsSection("设置", self)
        self.run_server_section = RunServerSection("运行", self)
        self.log_section = LogSection("日志输出")
        self.about_section = AboutSection("关于")
        self.config_editor_section = ConfigEditor("配置编辑", self)
        self.dowload_section = DownloadSection("下载", self)
        self.cf_share_section = CFShareSection("共享", self)

        self.addSubInterface(self.run_server_section, FIF.COMMAND_PROMPT, "运行")
        self.addSubInterface(self.log_section, FIF.BOOK_SHELF, "日志输出")
        self.addSubInterface(self.config_editor_section, FIF.EDIT, "配置编辑")
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
        self.setWindowTitle(f"Sakura 启动器 v{SAKURA_LAUNCHER_GUI_VERSION}")
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
            parent=self,
        )

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
        self._run_llamacpp(self.run_server_section, "server", "llama-server")

    def run_llamacpp_server_and_share(self):
        self._run_llamacpp(self.run_server_section, "server", "llama-server")
        cf_share_url = self.cf_share_section.worker_url_input.text()
        if not cf_share_url:
            MessageBox("错误", "分享链接不能为空", self).exec()
            return
        QTimer.singleShot(18000, self.cf_share_section.start_cf_share)

    def run_llamacpp_batch_bench(self):
        self._run_llamacpp(self.run_server_section, "llama-batched-bench")

    def get_llamacpp_version(self, executable_path):
        try:
            self.log_info(f"尝试执行命令: {executable_path} --version")
            result = subprocess.run(
                [executable_path, "--version"],
                capture_output=True,
                text=True,
                timeout=2,
                shell=True,
            )
            version_output = result.stderr.strip()  # 使用 stderr 而不是 stdout
            self.log_info(f"版本输出: {version_output}")
            version_match = re.search(r"version: (\d+)", version_output)
            if version_match:
                return int(version_match.group(1))
            else:
                self.log_info("无法匹配版本号")
        except subprocess.TimeoutExpired as e:
            self.log_info(f"获取llama.cpp版本超时: {e.stdout}, {e.stderr}")
        except Exception as e:
            self.log_info(f"获取llama.cpp版本时出错: {str(e)}")
        return None

    def _run_llamacpp(self, section, old_executable, new_executable=None):
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
        self.log_info(f"模型路径: {model_path}")
        self.log_info(f"模型名称: {model_name}")

        # 判断使用哪个可执行文件
        executable_path = os.path.join(
            llamacpp_path, f"{new_executable or old_executable}{exe_extension}"
        )
        if new_executable and not os.path.exists(executable_path):
            executable_path = os.path.join(
                llamacpp_path, f"{old_executable}{exe_extension}"
            )
        elif not os.path.exists(executable_path):
            MessageBox("错误", f"可执行文件不存在: {executable_path}", self).exec()
            return

        executable_path = self._add_quotes(executable_path)

        # 获取llama.cpp版本
        version = self.get_llamacpp_version(executable_path.strip('"'))
        self.log_info(f"llama.cpp版本: {version}")

        if custom_command:
            command = f"{executable_path} --model {model_path} {custom_command}"
        else:
            command = f"{executable_path} --model {model_path}"

            if old_executable == "server" or new_executable == "llama-server":
                command += f" -ngl {section.gpu_layers_spinbox.value()}"
                command += f" -c {section.context_length_input.value()}"
                command += f" -a {model_name}"
                command += f" --host {section.host_input.currentText()} --port {section.port_input.text()}"
                if section.log_format_combo.currentText() not in ("none", ""):
                    command += f" --log-format {section.log_format_combo.currentText()}"
                command += f" -np {section.n_parallel_spinbox.value()}"

                if section.flash_attention_check.isChecked():
                    command += " -fa"
                if section.no_mmap_check.isChecked():
                    command += " --no-mmap"
                if section.custom_command_append.toPlainText().strip():
                    command += f" {section.custom_command_append.toPlainText().strip()}"
                command += " --metrics"

                # 根据版本添加--slots参数
                if version is not None and version >= 3898:
                    self.log_info("版本大于等于3898，添加--slots参数")
                    command += " --slots"
            elif old_executable == "llama-bench":
                command += f" -ngl {section.gpu_layers_spinbox.value()}"

                if section.flash_attention_check.isChecked():
                    command += " -fa 1,0"
                if section.no_mmap_check.isChecked():
                    command += " -mmp 0"
                if section.custom_command_append.toPlainText().strip():
                    command += f" {section.custom_command_append.toPlainText().strip()}"
            elif old_executable == "llama-batched-bench":
                command += f" -c {section.context_length_input.value()}"
                command += f" -ngl {section.gpu_layers_spinbox.value()}"
                command += f" -npp {section.npp_input.text()}"
                command += f" -ntg {section.ntg_input.text()}"
                command += f" -npl {section.npl_input.text()}"
                if section.flash_attention_check.isChecked():
                    command += " -fa"
                if section.no_mmap_check.isChecked():
                    command += " --no-mmap"
                if section.custom_command_append.toPlainText().strip():
                    command += f" {section.custom_command_append.toPlainText().strip()}"

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
                self.log_info(f"设置GPU环境变量时出错: {str(e)}")
                MessageBox("错误", f"设置GPU环境变量时出错: {str(e)}", self).exec()
                return

        self.log_info(f"执行命令: {command}")

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
                self.log_info(f"请手动运行以下命令：\n{command}")
                return

        self.log_info("命令已在新的终端窗口中启动。")

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

    def log_info(self, message):
        self.log_section.log_display.append(message)
        self.log_section.log_display.ensureCursorVisible()

    def closeEvent(self, event):
        self.save_window_state()
        self.save_advanced_state()  # 新增：保存高级设置状态
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
            self.log_info("未检测到NVIDIA或AMD GPU")

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

    def save_advanced_state(self):
        if self.settings_section.remember_advanced_state.isChecked():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config_data = json.load(f)
            if self.settings_section.remember_advanced_state.isChecked():
                config_data["advanced_state"] = (
                    self.run_server_section.get_advanced_state()
                )
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
    better_font.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(better_font)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
