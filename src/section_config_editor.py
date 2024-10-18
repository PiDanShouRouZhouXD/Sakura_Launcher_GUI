import os
import json
from functools import partial
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QVBoxLayout,
    QFrame,
    QHeaderView,
    QTableWidgetItem,
    QWidget,
)
from qfluentwidgets import (
    PushButton,
    PrimaryPushButton,
    FluentIcon as FIF,
    TableWidget,
    TransparentPushButton,
)

from .common import CONFIG_FILE, CURRENT_DIR


class ConfigEditor(QFrame):
    LONG_PRESS_TIME = 500  # 设置长按延迟时间（毫秒）

    def __init__(self, title, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName(title.replace(" ", "-"))
        self.setStyleSheet(
            """
            Demo{background: white}
            QLabel{
                font: 20px 'Segoe UI';
                background: rgb(242,242,242);
                border-radius: 8px;
            }
        """
        )
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        self.layout = QVBoxLayout(self)

        self.run_server_section = QWidget(self)
        self.run_server_section.setObjectName("run_server_section")
        self.init_run_server_section()

        save_button = PrimaryPushButton(FIF.SAVE, "保存配置预设", self)
        save_button.clicked.connect(self.save_settings)

        load_button = PushButton(FIF.SYNC, "加载配置预设", self)
        load_button.clicked.connect(self.load_settings)

        self.layout.addWidget(self.run_server_section)
        self.layout.addWidget(save_button)
        self.layout.addWidget(load_button)

        self.setLayout(self.layout)

    def init_run_server_section(self):
        layout = QVBoxLayout(self.run_server_section)
        self.run_server_table = self.create_config_table()
        layout.addWidget(self.run_server_table)
        self.run_server_section.setLayout(layout)

    def create_config_table(self):
        table = TableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["配置名称", "上移", "下移", "删除"])
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        return table

    def save_settings(self):
        server_configs = self.table_to_config(self.run_server_table)
        settings = {"运行": server_configs}

        config_file_path = os.path.join(CURRENT_DIR, CONFIG_FILE)
        if not os.path.exists(config_file_path):
            with open(config_file_path, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=4)

        with open(config_file_path, "r", encoding="utf-8") as f:
            try:
                current_settings = json.load(f)
            except json.JSONDecodeError:
                current_settings = {}

        current_settings.update(settings)

        with open(config_file_path, "w", encoding="utf-8") as f:
            json.dump(current_settings, f, ensure_ascii=False, indent=4)

        self.main_window.createSuccessInfoBar("成功", "配置预设已保存")

    def load_settings(self):
        config_file_path = os.path.join(CURRENT_DIR, CONFIG_FILE)
        try:
            with open(config_file_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            settings = {}

        self.config_to_table(self.run_server_table, settings.get("运行", []))

    def table_to_config(self, table):
        configs = []
        for row in range(table.rowCount()):
            name_item = table.item(row, 0)
            if name_item:
                config_name = name_item.text()
                config = name_item.data(Qt.UserRole)
                configs.append({"name": config_name, "config": config})
        return configs

    def config_to_table(self, table, configs):
        table.setRowCount(len(configs))
        for row, config in enumerate(configs):
            name_item = QTableWidgetItem(config["name"])
            name_item.setData(Qt.UserRole, config["config"])
            table.setItem(row, 0, name_item)
            table.setCellWidget(row, 1, self.create_move_up_button(table, row))
            table.setCellWidget(row, 2, self.create_move_down_button(table, row))
            table.setCellWidget(row, 3, self.create_delete_button(table))

    def create_move_up_button(self, table, row):
        button = TransparentPushButton(FIF.UP, "上移", self)
        button.pressed.connect(
            lambda: self.start_timer(button, table, row, self.move_up, self.move_to_top)
        )
        button.released.connect(lambda: self.stop_timer(button))
        button.setToolTip("向上移动配置，长按可快速移动到顶部")
        return button

    def create_move_down_button(self, table, row):
        button = TransparentPushButton(FIF.DOWN, "下移", self)
        button.pressed.connect(
            lambda: self.start_timer(
                button, table, row, self.move_down, self.move_to_bottom
            )
        )
        button.released.connect(lambda: self.stop_timer(button))
        button.setToolTip("向下移动配置，长按可快速移动到底部")
        return button

    def create_delete_button(self, table):
        button = TransparentPushButton(FIF.DELETE, "删除", self)
        button.clicked.connect(partial(self.delete_row, table, button))
        return button

    def start_timer(self, button, table, row, move_func, long_press_func):
        self.click_timer = QTimer()
        self.click_timer.timeout.connect(
            lambda: self.perform_long_press_action(table, row, long_press_func)
        )
        self.click_timer.start(self.LONG_PRESS_TIME)  # 设置长按延迟
        button.click_action = lambda: move_func(table, row)

    def stop_timer(self, button):
        if hasattr(self, "click_timer"):
            if self.click_timer.isActive():
                self.click_timer.stop()
                button.click_action()
            delattr(self, "click_timer")

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
