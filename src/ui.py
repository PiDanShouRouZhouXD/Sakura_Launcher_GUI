import os
import json
import math
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QGroupBox
from qfluentwidgets import (
    PushButton,
    CheckBox,
    SpinBox,
    EditableComboBox,
    FluentIcon as FIF,
    Slider,
    ComboBox,
    LineEdit,
)


def UiCheckBox(parent, text, checked):
    w = CheckBox(parent)
    w.setText(text)
    w.setChecked(checked)
    return w


def UiLineEdit(parent, placeholder, text):
    w = LineEdit(parent)
    w.setPlaceholderText(placeholder)
    w.setText(text)
    return w

def UiSlider(
    parent,
    text,
    variable_name,
    slider_value,
    slider_min,
    slider_max,
    slider_step,
):
    layout = QVBoxLayout()
    label = QLabel(text)
    layout.addWidget(label)

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
    layout.addLayout(h_layout)

    setattr(parent, f"{variable_name.replace(' ', '_')}", slider)
    setattr(parent, f"{variable_name.replace(' ', '_')}_spinbox", spinbox)

    return layout