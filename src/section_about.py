from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout,
    QLabel,
    QFrame,
    QGroupBox,
)
from qfluentwidgets import (
    FluentIcon as FIF,
    HyperlinkButton,
)

from common import SAKURA_LAUNCHER_GUI_VERSION


class AboutSection(QFrame):
    def __init__(self, text: str, parent=None):
        super().__init__(parent=parent)
        self.setObjectName(text.replace(" ", "-"))
        self.init_ui()

    def init_ui(self):

        # 文本
        text_group = QGroupBox()
        text_group.setStyleSheet(
            """ QGroupBox {border: 0px solid lightgray; border-radius: 8px;}"""
        )
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
            url="https://github.com/SakuraLLM/SakuraLLM",
            text="SakuraLLM 项目地址",
            parent=self,
            icon=FIF.LINK,
        )

        self.hyperlinkButton_2 = HyperlinkButton(
            url="https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI",
            text="Sakura Launcher GUI 项目地址",
            parent=self,
            icon=FIF.LINK,
        )

        text_group_layout.addWidget(self.text_label)
        text_group_layout.addWidget(self.text_label_2)
        text_group_layout.addWidget(self.hyperlinkButton_1)
        text_group_layout.addWidget(self.hyperlinkButton_2)
        text_group_layout.addStretch(1)  # 添加伸缩项
        text_group.setLayout(text_group_layout)

        container = QVBoxLayout()

        self.setLayout(container)
        container.setSpacing(28)  # 设置布局内控件的间距为28
        container.setContentsMargins(
            50, 70, 50, 30
        )  # 设置布局的边距, 也就是外边框距离，分别为左、上、右、下

        container.addStretch(1)  # 添加伸缩项
        container.addWidget(text_group)
        container.addStretch(1)  # 添加伸缩项
