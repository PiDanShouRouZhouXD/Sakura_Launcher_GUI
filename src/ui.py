from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame
from qfluentwidgets import CheckBox, FluentStyleSheet, LineEdit, Slider, SpinBox
from qfluentwidgets.common.style_sheet import (
    StyleSheetManager, getStyleSheet, StyleSheetCompose, CustomStyleSheet
)
from qfluentwidgets.common.config import qconfig

class CustomStyleSheetManager(StyleSheetManager):
    def addCustomStyle(self, widget: QWidget, customStyle: str):
        """ 添加自定义样式到小部件，而不覆盖现有样式 """
        if widget in self.widgets:
            source = self.widgets[widget]
            if isinstance(source, StyleSheetCompose):
                custom_source = next((s for s in source.sources if isinstance(s, CustomStyleSheet)), None)
                if custom_source:
                    existing_style = custom_source.content()
                    new_style = existing_style + '\n' + customStyle
                    custom_source.setCustomStyleSheet(new_style, new_style)
                else:
                    custom_source = CustomStyleSheet(widget)
                    custom_source.setCustomStyleSheet(customStyle, customStyle)
                    source.add(custom_source)
            else:
                custom_source = CustomStyleSheet(widget)
                custom_source.setCustomStyleSheet(customStyle, customStyle)
                self.widgets[widget] = StyleSheetCompose([source, custom_source])
        else:
            custom_source = CustomStyleSheet(widget)
            custom_source.setCustomStyleSheet(customStyle, customStyle)
            self.register(custom_source, widget)

        self.updateWidgetStyleSheet(widget)

    def updateWidgetStyleSheet(self, widget: QWidget):
        """ 更新特定小部件的样式表 """
        if widget in self.widgets:
            source = self.widgets[widget]
            widget.setStyleSheet(getStyleSheet(source, qconfig.theme))

# 创建自定义样式表管理器的实例
custom_style_manager = CustomStyleSheetManager()

def addCustomWidgetStyle(widget: QWidget, customStyle: str):
    """ 添加自定义样式到小部件，而不覆盖现有样式 """
    custom_style_manager.addCustomStyle(widget, customStyle)

def UiCheckBox(parent, text, checked):
    w = CheckBox(parent)
    w.setText(text)
    w.setChecked(checked)
    
    # 注册默认样式
    custom_style_manager.register(FluentStyleSheet.CHECK_BOX, w)
    
    # 设置 CheckBox 的大小
    checkbox_size = 12  # 可以根据需要调整这个值
    w.setIconSize(QSize(checkbox_size, checkbox_size))
    
    # 添加自定义样式（在下一个事件循环中应用，以确保覆盖其他样式）
    QTimer.singleShot(0, lambda: addCustomWidgetStyle(w, f"""
        QCheckBox {{
            font-size: 12px !important;
        }}
        QCheckBox::indicator {{
            width: {checkbox_size}px;
            height: {checkbox_size}px;
        }}
    """))
    
    return w


def UiLineEdit(parent, placeholder, text):
    w = LineEdit(parent)
    w.setPlaceholderText(placeholder)
    w.setText(text)
    return w


def UiSlider(
    parent,
    variable_name,
    slider_value,
    slider_min,
    slider_max,
    slider_step,
    spinbox_fixed_width=None,
    slider_fixed_width=None,
):
    h_layout = QHBoxLayout()
    slider = Slider(Qt.Horizontal, parent)
    slider.setRange(slider_min, slider_max)
    slider.setPageStep(slider_step)
    slider.setValue(slider_value)

    spinbox = SpinBox(parent)
    spinbox.setRange(slider_min, slider_max)
    spinbox.setSingleStep(slider_step)
    spinbox.setValue(slider_value)

    slider.valueChanged.connect(spinbox.setValue)
    spinbox.valueChanged.connect(slider.setValue)

    h_layout.addWidget(slider)
    h_layout.addWidget(spinbox)

    setattr(parent, f"{variable_name.replace(' ', '_')}", slider)
    setattr(parent, f"{variable_name.replace(' ', '_')}_spinbox", spinbox)

    if slider_fixed_width is not None:
        slider.setFixedWidth(slider_fixed_width)
    if spinbox_fixed_width is not None:
        spinbox.setFixedWidth(spinbox_fixed_width)

    return h_layout


def UiHLine(self):
    w = QFrame(self)
    w.setFrameShape(QFrame.HLine)
    w.setFrameShadow(QFrame.Plain)  # 改为Plain以去除阴影效果
    w.setFixedHeight(32)
    # 使用更深的灰色作为背景色，并设置上下边距
    w.setStyleSheet("""
        background-color: #393939;
        margin-top: 15px;
        margin-bottom: 15px;
        max-height: 1px;
        border: none;  /* 去掉边框 */
    """)
    return w


def UiRow(text, content):
    layout = QHBoxLayout()
    layout.addWidget(QLabel(text))
    if issubclass(type(content), QWidget):
        layout.addWidget(content)
    else:
        layout.addLayout(content)
    return layout

def UiCol(text, content):
    layout = QVBoxLayout()
    layout.addWidget(QLabel(text))
    if issubclass(type(content), QWidget):
        layout.addWidget(content)
    else:
        layout.addLayout(content)
    return layout
