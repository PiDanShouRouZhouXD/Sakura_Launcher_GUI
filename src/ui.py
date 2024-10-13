from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QFrame, QWidget
from qfluentwidgets import (
    CheckBox,
    SpinBox,
    Slider,
    LineEdit,
)


def UiCheckBox(parent, text, checked):
    w = CheckBox(parent)
    w.setText(text)
    w.setChecked(checked)
    w.setStyleSheet("font-size: 12px")
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

    return h_layout


def UiHLine(self):
    w = QFrame(self)
    w.setFrameShape(QFrame.HLine)
    w.setFrameShadow(QFrame.Sunken)
    w.setFixedHeight(32)
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
