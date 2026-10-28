"""Eingabefelder für Zahlen, die Komma und Punkt als Dezimalzeichen akzeptieren."""
from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (QComboBox, QHeaderView, QLineEdit, QStyledItemDelegate,
                               QTableWidget, QTableWidgetItem)

from ..core.numbers import format_number, parse_number

NUMBER_RE = QRegularExpression(r"^\s*\d*([.,]\d*)?\s*$")


class NumberEdit(QLineEdit):
    """Zahleneingabe: "1,5" und "1.5" sind gleichwertig. Leer bedeutet "kein Wert"."""

    def __init__(self, value: float | None = None, decimals: int = 4, parent=None):
        super().__init__(parent)
        self.decimals = decimals
        self.setValidator(QRegularExpressionValidator(NUMBER_RE, self))
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.editingFinished.connect(self._reformat)
        self.setValue(value)

    def value(self) -> float | None:
        try:
            return parse_number(self.text())
        except ValueError:
            return None

    def setValue(self, value: float | None):
        self.setText(format_number(value, self.decimals, trim=True) if value is not None else "")

    def _reformat(self):
        v = self.value()
        if v is not None:
            self.setValue(v)


class NumberDelegate(QStyledItemDelegate):
    """Tabellenzellen mit NumberEdit als Editor; der Zellentext bleibt im deutschen Format."""

    def __init__(self, decimals: int = 4, parent=None):
        super().__init__(parent)
        self.decimals = decimals

    def createEditor(self, parent, option, index):
        return NumberEdit(decimals=self.decimals, parent=parent)

    def setEditorData(self, editor, index):
        editor.setValue(parse_number(index.data() or ""))

    def setModelData(self, editor, model, index):
        v = editor.value()
        model.setData(index, format_number(v, self.decimals, trim=True) if v is not None else "")


def cell_number(table: QTableWidget, row: int, col: int) -> float | None:
    item = table.item(row, col)
    try:
        return parse_number(item.text()) if item else None
    except ValueError:
        return None


def readonly_item(text: str, align_right: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    if align_right:
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return item


def number_item(value: float | None, decimals: int = 4, editable: bool = True) -> QTableWidgetItem:
    text = format_number(value, decimals, trim=True) if value is not None else ""
    item = QTableWidgetItem(text) if editable else readonly_item(text)
    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return item


def setup_table(table: QTableWidget, headers: list[str], stretch_col: int | None = 0):
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    h = table.horizontalHeader()
    h.setSectionResizeMode(QHeaderView.ResizeToContents)
    if stretch_col is not None:
        h.setSectionResizeMode(stretch_col, QHeaderView.Stretch)


def combo(items: list[tuple[str, object]], parent=None) -> QComboBox:
    c = QComboBox(parent)
    for text, data in items:
        c.addItem(text, data)
    return c
