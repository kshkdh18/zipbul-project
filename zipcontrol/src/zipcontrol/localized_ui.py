"""Retranslate Qt properties without recreating controls or changing their state."""

from weakref import WeakKeyDictionary

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QLabel
from shiboken6 import isValid

from .i18n import LANGUAGES, translate


class I18n(QObject):
    changed = Signal()

    def __init__(self, language="en", parent=None):
        super().__init__(parent)
        if language not in LANGUAGES:
            raise ValueError("Unsupported language")
        self.language = language
        self.bindings = WeakKeyDictionary()

    def render(self, value):
        return translate(value, self.language)

    def set_language(self, language):
        if language not in LANGUAGES:
            raise ValueError("Unsupported language")
        self.language = language
        for widget, bindings in list(self.bindings.items()):
            if isValid(widget):
                for (method, index), value in bindings.items():
                    self._apply(widget, method, index, value)
        self.changed.emit()

    def _apply(self, widget, method, index, value):
        args = [self.render(value)] if index is None else [index, self.render(value)]
        getattr(widget, method)(*args)

    def set(self, widget, method, value, index=None):
        self.bindings.setdefault(widget, {})[(method, index)] = value
        self._apply(widget, method, index, value)

    def widget(self, widget_type, text="", *args, **kwargs):
        widget = widget_type(*args, **kwargs)
        self.set(widget, "setTitle" if widget_type.__name__ == "QGroupBox" else "setText", text)
        return widget

    def item(self, combo, text, *data):
        combo.addItem(self.render(text), *data)
        self.set(combo, "setItemText", text, combo.count() - 1)

    def items(self, combo, values):
        for value in values:
            self.item(combo, value)

    def tab(self, tabs, widget, text):
        index = tabs.addTab(widget, self.render(text))
        self.set(tabs, "setTabText", text, index)
        return index

    def row(self, layout, label, field):
        layout.addRow(self.widget(QLabel, label), field)
