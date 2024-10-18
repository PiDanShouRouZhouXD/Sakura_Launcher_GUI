import logging
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import QFrame
from qfluentwidgets import PushButton, TextEdit, FluentIcon as FIF

from .ui import UiCol


class LogEmitter(QObject):
    sig = Signal(str)


class LogHandler(logging.Handler):
    emitter = LogEmitter()

    def emit(self, record):
        msg = self.format(record)
        self.emitter.sig.emit(msg)


class LogSection(QFrame):
    handler = LogHandler()

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName(title.replace(" ", "-"))
        self._init_ui()

        logger = logging.getLogger()
        logger.addHandler(self.handler)
        logger.setLevel(logging.INFO)
        self.handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    def _init_ui(self):
        log_display = TextEdit()
        log_display.setReadOnly(True)

        def append_log(msg):
            log_display.append(msg)
            log_display.ensureCursorVisible()

        self.handler.emitter.sig.connect(append_log, Qt.UniqueConnection)

        def clear_log():
            log_display.clear()

        button_clear = PushButton(FIF.DELETE, "清空日志")
        button_clear.clicked.connect(clear_log)

        layout = UiCol(
            log_display,
            button_clear,
        )
        self.setLayout(layout)
