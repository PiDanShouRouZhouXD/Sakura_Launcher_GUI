import logging
import sys
import os
import subprocess
import shutil
from PySide6.QtCore import QTimer
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
)

from src.common import *
from src.llamacpp import get_llamacpp_version
from src.gpu import GPUManager
from src.section_run_server import RunServerSection
from src.section_download import DownloadSection
from src.section_share import CFShareSection
from src.section_about import AboutSection
from src.section_settings import SettingsSection
from src.setting import *
from src.ui import *

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO").upper())

# 设置CUDA设备顺序，保证nvidia-smi的输出顺序和llama.cpp的输出顺序一致
os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"


class MainWindow(MSFluentWindow):
    def __init__(self):
        super().__init__()
        self.gpu_manager = GPUManager()
        self.init_navigation()
        self.init_window()
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
        self.run_server_section = RunServerSection("启动", self)
        self.dowload_section = DownloadSection("下载")
        self.cf_share_section = CFShareSection("共享", self)
        self.settings_section = SettingsSection("设置")
        self.about_section = AboutSection("关于")

        self.addSubInterface(self.run_server_section, FIF.COMMAND_PROMPT, "启动")
        self.addSubInterface(self.dowload_section, FIF.DOWNLOAD, "下载")
        self.addSubInterface(self.cf_share_section, FIF.IOT, "共享")
        self.addSubInterface(self.settings_section, FIF.SETTING, "设置")
        self.addSubInterface(
            self.about_section,
            FIF.INFO,
            "关于",
            position=NavigationItemPosition.BOTTOM,
        )

        self.navigationInterface.setCurrentItem("启动")

    def init_window(self):
        self.run_server_section.run_button.clicked.connect(self.run_llamacpp_server)
        self.run_server_section.run_and_share_button.clicked.connect(
            self.run_llamacpp_server_and_share
        )
        self.run_server_section.benchmark_button.clicked.connect(
            self.run_llamacpp_batch_bench
        )

        self.settings_section.sig_need_update.connect(
            self.dowload_section.start_download_launcher
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
        path = SETTING.llamacpp_path
        if not path:
            return os.path.join(CURRENT_DIR, "llama")
        return os.path.abspath(path)

    def run_llamacpp_server(self):
        self.refresh_gpus()
        self._run_llamacpp("llama-server")

    def run_llamacpp_server_and_share(self):
        self._run_llamacpp("llama-server")
        cf_share_url = self.cf_share_section.worker_url_input.text()
        if not cf_share_url:
            MessageBox("错误", "分享链接不能为空", self).exec()
            return
        QTimer.singleShot(18000, self.cf_share_section.start_cf_share)

    def run_llamacpp_batch_bench(self):
        self._run_llamacpp("llama-batched-bench")

    def check_gpu_ability(self, selected_gpu_display, model_name, context_length, n_parallel):
        """检查GPU能力"""
        try:
            check_result = self.gpu_manager.check_gpu_ability(
                selected_gpu_display,
                model_name,
                context_length,
                n_parallel,
            )
            if not check_result.is_capable and not SETTING.no_gpu_ability_check:
                if check_result.is_fatal:
                    MessageBox(
                        "致命错误：GPU 不满足强制需求",
                        f"显卡 {selected_gpu_display} 无法运行 {model_name}。\n\n"
                        f"原因：{check_result.reason}\n\n"
                        f"注：GPU能力检测对话框可以在设置中关闭",
                        self,
                    ).exec()
                    return False
                else:
                    box = MessageBox(
                        "警告：GPU 不满足运行最低需求",
                        f"显卡 {selected_gpu_display} 无法运行 {model_name}。\n\n"
                        f"原因：{check_result.reason}\n\n"
                        f"你可以继续使用，但是运行可能发生异常\n\n"
                        f"注：GPU能力检测对话框可以在设置中关闭",
                        self,
                    )
                    is_quit = False

                    def on_yes():
                        nonlocal is_quit
                        is_quit = False

                    def on_cancel():
                        nonlocal is_quit
                        is_quit = True

                    box.yesSignal.connect(on_yes)
                    box.cancelSignal.connect(on_cancel)
                    box.yesButton.setText("无视风险继续！")
                    box.cancelButton.setText("停止")
                    box.exec()
                    return not is_quit
        except Exception as e:
            logging.info(f"检查GPU能力时出错: {str(e)}")
            MessageBox("错误", f"检查GPU能力时出错: {str(e)}", self).exec()
            return False
        return True

    def check_context_per_thread(self, context_length, n_parallel):
        """检查每线程上下文长度"""
        context_per_thread = context_length // n_parallel
        if context_per_thread < 1024 and not SETTING.no_context_check:
            box = MessageBox(
                "警告：每线程上下文长度过小",
                f"当前每个线程的上下文长度为 {context_per_thread}，\n"
                f"小于推荐的最小值 1024。\n\n"
                f"这可能会导致模型无法正常使用。建议：\n"
                f"1. 增加总上下文长度\n"
                f"2. 减少并发数量\n"
                f"3. 点击「自动配置」按钮进行自动优化，然后继续\n（仅支持「下载」页面中的模型）\n\n"
                f"注：此警告可以在设置中关闭",
                self,
            )
            is_quit = False

            def on_yes():
                nonlocal is_quit
                is_quit = False

            def on_cancel():
                nonlocal is_quit
                is_quit = True

            def on_auto_config():
                nonlocal is_quit
                is_quit = True
                # 调用 RunServerSection 的自动配置功能
                self.run_server_section.auto_configure()

            box.yesSignal.connect(on_yes)
            box.cancelSignal.connect(on_cancel)

            # 创建自动配置按钮并添加到buttonGroup
            from qfluentwidgets import PushButton

            auto_config_button = PushButton("自动配置", box)
            auto_config_button.clicked.connect(on_auto_config)
            box.buttonGroup.layout().insertWidget(
                1, auto_config_button
            )  # 插入到yes和cancel按钮之间

            box.yesButton.setText("继续")
            box.cancelButton.setText("停止")
            box.exec()
            return not is_quit
        return True

    def check_launch_requirements(
        self, selected_gpu_display, model_name, context_length, n_parallel
    ):
        """检查启动要求"""
        # 检查GPU能力
        if not self.check_gpu_ability(
            selected_gpu_display,
            model_name,
            context_length,
            n_parallel
        ):
            return False

        # 检查每线程上下文长度
        if not self.check_context_per_thread(context_length, n_parallel):
            return False

        return True

    def _run_llamacpp(self, executable):
        section = self.run_server_section

        llamacpp_override = section.llamacpp_override.text().strip()
        llamacpp_path = (
            llamacpp_override if llamacpp_override else self.get_llamacpp_path()
        )
        exe_extension = ".exe" if sys.platform == "win32" else ""

        if not os.path.exists(llamacpp_path):
            MessageBox("错误", f"llamacpp路径不存在: {llamacpp_path}", self).exec()
            return

        model_name = section.model_path.currentText().split(os.sep)[-1]
        model_path = section.model_path.currentText()
        logging.info(f"模型路径: {model_path}")
        logging.info(f"模型名称: {model_name}")

        # 将GPU检查提前到这里
        if section.gpu_combo.currentText() != "自动":
            selected_gpu_display = section.gpu_combo.currentText()
            selected_index = section.gpu_combo.currentIndex()

            # 检查启动要求
            if not self.check_launch_requirements(
                selected_gpu_display,
                model_name,
                section.context_length_input.value(),
                section.n_parallel_spinbox.value(),
            ):
                return

        # 判断使用哪个可执行文件
        executable_path = os.path.join(llamacpp_path, f"{executable}{exe_extension}")
        if not os.path.exists(executable_path):
            MessageBox("错误", f"可执行文件不存在: {executable_path}", self).exec()
            return

        # 获取llama.cpp版本
        version = get_llamacpp_version(llamacpp_path)
        logging.info(f"llama.cpp版本: {version}")

        option_model = ["--model", model_path]
        option_extra = []

        option_extra += [
            "-c",
            str(section.context_length_input.value()),
            "-ngl",
            str(section.gpu_layers_spinbox.value()),
        ]

        if executable == "llama-server":
            option_extra += [
                "-a",
                model_name,
                "--host",
                section.host_input.text(),
                "--port",
                section.port_input.text(),
                "-np",
                str(section.n_parallel_spinbox.value()),
            ]
            option_extra.append("--metrics")

            # 根据版本添加--slots参数
            if version is not None and version >= 3898:
                logging.info("版本大于等于3898，添加--slots参数")
                option_extra.append("--slots")
        elif executable == "llama-batched-bench":
            option_extra += [
                "-npp",
                section.npp_input.text(),
                "-ntg",
                section.ntg_input.text(),
                "-npl",
                section.npl_input.text(),
            ]

        if section.flash_attention_check.isChecked():
            option_extra.append("-fa")
        if section.no_mmap_check.isChecked():
            option_extra.append("--no-mmap")

        command = []
        command_template: str = section.command_template.toPlainText().strip()
        if not command_template:
            command_template = "%cmd%"
        for command_part in command_template.split(" "):
            command_part = command_part.strip()
            if command_part == "%cmd%":
                command.append(executable_path)
                command += option_model
                command += option_extra
            elif command_part == "%cmd_raw%":
                command.append(executable_path)
                command += option_model
            elif command_part:
                command.append(command_part)

        env = os.environ.copy()
        try:
            if section.gpu_combo.currentText() != "自动":
                self.gpu_manager.set_gpu_env(
                    env,
                    section.gpu_combo.currentText(),
                    section.gpu_combo.currentIndex(),
                )
        except Exception as e:
            logging.info(f"设置GPU环境变量时出错: {str(e)}")
            MessageBox("错误", f"设置GPU环境变量时出错: {str(e)}", self).exec()
            return

        command_plain = " ".join(command)
        logging.info(f"执行命令: {command_plain}")

        # 在运行命令的部分
        if sys.platform == "win32":
            command_prefix = ["start", "cmd", "/K"]
            subprocess.Popen(command_prefix + command, env=env, shell=True)
        elif sys.platform == "darwin":
            cmd_str = " ".join(command)
            # 使用 osascript 执行命令，要先进入正确目录
            apple_script = [
                'osascript',
                '-e',
                f'''tell application "Terminal"
                    do script "cd {CURRENT_DIR} && {cmd_str}"
                end tell'''
            ]
            subprocess.Popen(apple_script, env=env)
        else:
            terminal = self.find_terminal()
            if not terminal:
                MessageBox("错误", "无法找到合适的终端，请手动运行命令。", self).exec()
                logging.info(f"请手动运行以下命令：\n{command_plain}")
                return
            if terminal == "gnome-terminal":
                command_prefix = [terminal, "--", "bash", "-c"]
            else:
                command_prefix = [terminal, "-e"]
            subprocess.Popen(command_prefix + command, env=env)

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
        self.run_server_section.refresh_gpus(keep_selected=True)

        if not self.gpu_manager.nvidia_gpus and not self.gpu_manager.amd_gpus:
            logging.info("未检测到NVIDIA或AMD GPU")

    def save_window_state(self):
        if SETTING.remember_window_state:
            SETTING.window_geometry = {
                "x": self.x(),
                "y": self.y(),
                "width": self.width(),
                "height": self.height(),
            }
            SETTING.save_settings()

    def load_window_state(self):
        if SETTING.remember_window_state:
            geometry = SETTING.window_geometry
            if geometry:
                self.setGeometry(
                    geometry.get("x", self.x()),
                    geometry.get("y", self.y()),
                    geometry.get("width", self.width()),
                    geometry.get("height", self.height()),
                )


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
