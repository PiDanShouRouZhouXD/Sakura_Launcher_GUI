import logging
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QThread
from PySide6.QtWidgets import QFrame, QHeaderView, QTableWidgetItem
from qfluentwidgets import (
    TextEdit,
    FluentIcon as FIF,
    TableWidget,
    TransparentPushButton,
)
import requests

from .common import SAKURA_LAUNCHER_GUI_VERSION
from .setting import SETTING
from .ui import *


def get_launcher_latest_version():
    response = requests.get(
        "https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI/releases/latest",
        allow_redirects=False,
    )
    if response.status_code != 302:
        return
    redirect_url = response.headers.get("Location")
    version = redirect_url.split("/")[-1]
    if version == "releases":
        return
    return version


class CheckUpdateThread(QThread):
    sig_version = Signal(str)

    def run(self):
        try:
            version = get_launcher_latest_version()
            if version:
                self.sig_version.emit(version)
            else:
                raise RuntimeError("无法获取最新版本信息")
        except Exception as e:
            logging.error(f"获取最新启动器版本时出错: {str(e)}")


class ConfigEditor(TableWidget):
    LONG_PRESS_TIME = 500  # 设置长按延迟时间（毫秒）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(4)
        self.setHorizontalHeaderLabels(["配置名称", "上移", "下移", "删除"])
        self.verticalHeader().hide()
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def get_config(self):
        configs = []
        for row in range(self.rowCount()):
            name_item = self.item(row, 0)
            if name_item:
                config_name = name_item.text()
                config = name_item.data(Qt.UserRole)
                configs.append({"name": config_name, "config": config})
        return configs

    def set_config(self, configs):
        self.setRowCount(len(configs))
        for row, config in enumerate(configs):
            name_item = QTableWidgetItem(config["name"])
            name_item.setData(Qt.UserRole, config["config"])
            self.setItem(row, 0, name_item)
            self.setCellWidget(row, 1, self.create_move_up_button(row))
            self.setCellWidget(row, 2, self.create_move_down_button(row))
            self.setCellWidget(row, 3, self.create_delete_button(row))

    def create_move_up_button(self, row):
        button = TransparentPushButton(FIF.UP, "上移")
        button.pressed.connect(
            lambda: self.start_timer(button, row, self.move_up, self.move_to_top)
        )
        button.released.connect(lambda: self.stop_timer(button))
        button.setToolTip("向上移动配置，长按可快速移动到顶部")
        return button

    def create_move_down_button(self, row):
        button = TransparentPushButton(FIF.DOWN, "下移")
        button.pressed.connect(
            lambda: self.start_timer(button, row, self.move_down, self.move_to_bottom)
        )
        button.released.connect(lambda: self.stop_timer(button))
        button.setToolTip("向下移动配置，长按可快速移动到底部")
        return button

    def create_delete_button(self, row):
        button = TransparentPushButton(FIF.DELETE, "删除")
        button.clicked.connect(lambda: self.delete_row(row))
        return button

    def start_timer(self, button, row, move_func, long_press_func):
        self.click_timer = QTimer()
        self.click_timer.timeout.connect(
            lambda: self.perform_long_press_action(row, long_press_func)
        )
        self.click_timer.start(self.LONG_PRESS_TIME)  # 设置长按延迟
        button.click_action = lambda: move_func(row)

    def stop_timer(self, button):
        if hasattr(self, "click_timer"):
            if self.click_timer.isActive():
                self.click_timer.stop()
                button.click_action()
            delattr(self, "click_timer")

    def perform_long_press_action(self, row, long_press_func):
        self.click_timer.stop()
        long_press_func(row)

    def move_up(self, row):
        if row > 0:
            self.move_to(row, row - 1)

    def move_down(self, row):
        if row < self.rowCount() - 1:
            self.move_to(row, row + 1)

    def move_to_top(self, row):
        self.move_to(self, row, 0)

    def move_to_bottom(self, row):
        self.move_to(row, self.rowCount() - 1)

    def move_to(self, row, target_row):
        while row != target_row:
            if row < target_row:
                self.swap_rows(row, row + 1)
                row += 1
            else:
                self.swap_rows(row, row - 1)
                row -= 1
        self.selectRow(target_row)

    def swap_rows(self, row1, row2):
        for col in range(self.columnCount()):
            item1 = self.takeItem(row1, col)
            item2 = self.takeItem(row2, col)
            if item1 and item2:
                self.setItem(row1, col, QTableWidgetItem(item2))
                self.setItem(row2, col, QTableWidgetItem(item1))

    def delete_row(self, row):
        self.removeRow(row)


class LogEmitter(QObject):
    sig = Signal(str)


class LogHandler(logging.Handler):
    emitter = LogEmitter()

    def emit(self, record):
        msg = self.format(record)
        self.emitter.sig.emit(msg)


class SettingsSection(QFrame):
    sig_need_update = Signal(str)
    handler = LogHandler()

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName(title.replace(" ", "-"))
        self._init_ui()

    def _init_ui(self):
        self.setLayout(
            UiStackedWidget(
                ("设置", self._create_setting_section()),
                ("编辑预设", self._create_config_editor_section()),
                ("日志输出", self._create_log_section()),
            ),
        )

    def _create_setting_section(self):
        self.check_launcher_update()

        button_group = UiButtonGroup(
            UiButton("更新版本", FIF.UPDATE, self.update_launcher),
        )

        remember_window_state = UiCheckBox(
            "记住窗口位置和大小", SETTING.remember_window_state
        )
        remember_window_state.toggled.connect(
            lambda checked: SETTING.set_value("remember_window_state", checked)
        )
        remember_advanced_state = UiCheckBox(
            "记住高级设置状态", SETTING.remember_advanced_state
        )
        remember_advanced_state.toggled.connect(
            lambda checked: SETTING.set_value("remember_advanced_state", checked)
        )
        no_gpu_ability_check = UiCheckBox(
            "关闭 GPU 能力检测", SETTING.no_gpu_ability_check
        )
        no_gpu_ability_check.toggled.connect(
            lambda checked: SETTING.set_value("no_gpu_ability_check", checked)
        )
        no_context_check = UiCheckBox(
            "关闭每线程上下文长度检查", SETTING.no_context_check
        )
        no_context_check.toggled.connect(
            lambda checked: SETTING.set_value("no_context_check", checked)
        )
        model_sort_combo = UiComboBox(["修改时间", "文件名", "文件大小"])
        model_sort_combo.setCurrentText(SETTING.model_sort_option)
        model_sort_combo.currentTextChanged.connect(
            lambda text: SETTING.set_value("model_sort_option", text)
        )
        
        llamacpp_path = UiLineEdit("可选，手动指定llama.cpp路径", SETTING.llamacpp_path)
        llamacpp_path.textChanged.connect(
            lambda text: SETTING.set_value("llamacpp_path", text)
        )
        model_search_paths = TextEdit()
        model_search_paths.setPlaceholderText(
            "模型搜索路径（每行一个路径，已经默认包含当前目录）"
        )
        model_search_paths.setPlainText(SETTING.model_search_paths)
        model_search_paths.textChanged.connect(
            lambda: SETTING.set_value(
                "model_search_paths", model_search_paths.toPlainText()
            )
        )

        return UiCol(
            button_group,
            remember_window_state,
            remember_advanced_state,
            no_gpu_ability_check,
            no_context_check,
            UiOptionRow("模型列表排序", model_sort_combo),
            UiOptionRow("llama.cpp文件夹", llamacpp_path),
            UiOptionCol("模型搜索路径", model_search_paths),
        )

    def _create_config_editor_section(self):
        self.config_table = ConfigEditor()

        def save_run_setting():
            presets = self.config_table.get_config()
            SETTING.set_value("presets", presets)

        button_group = UiButtonGroup(
            UiButton("保存配置预设", FIF.SAVE, save_run_setting, primary=True),
        )

        SETTING.presets_changed.connect(self.config_table.set_config)
        self.config_table.set_config(SETTING.presets)

        return UiCol(
            button_group,
            self.config_table,
        )

    def _create_log_section(self):
        logger = logging.getLogger()
        logger.addHandler(self.handler)
        logger.setLevel(logging.INFO)

        log_display = TextEdit()
        log_display.setReadOnly(True)

        def append_log(msg):
            log_display.append(msg)
            log_display.ensureCursorVisible()

        self.handler.emitter.sig.connect(append_log, Qt.UniqueConnection)
        self.handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

        def clear_log():
            log_display.clear()

        button_group = UiButtonGroup(
            UiButton("清空日志", FIF.DELETE, clear_log),
        )

        return UiCol(
            button_group,
            log_display,
        )

    def is_version_newer(self, version: str):
        def split_version(v: str):
            parts = v.removeprefix("v").replace("-", ".").split(".")
            if len(parts) == 3:
                parts.append("release")
            parts = list(map(int, parts[:3])) + [parts[3]]
            return parts

        return split_version(version) > split_version(SAKURA_LAUNCHER_GUI_VERSION)

    def check_launcher_update(self):
        def notify_need_update(version: str):
            if self.is_version_newer(version):
                UiInfoBarWarning(self, f"检测到新版本启动器{version}发布")

        thread = CheckUpdateThread(self)
        thread.sig_version.connect(notify_need_update)
        thread.start()

    def update_launcher(self):
        def notify_need_update(version: str):
            if self.is_version_newer(version):
                self.sig_need_update.emit(version)
            else:
                UiInfoBarSuccess(self, "启动器版本已是最新")

        thread = CheckUpdateThread(self)
        thread.sig_version.connect(notify_need_update)
        thread.start()
