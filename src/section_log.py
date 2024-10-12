from PySide6.QtCore import Slot
from PySide6.QtWidgets import QVBoxLayout, QFrame
from qfluentwidgets import PushButton, TextEdit, FluentIcon as FIF

from common import processes


class LogSection(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName(title.replace(" ", "-"))
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
