"""Bearbeitungsdialoge für Dünger, Wasserprofile und Rezepte."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QTableWidget, QVBoxLayout, QWidget)

from ..core.elements import ELEMENTS, NUTRIENTS
from ..core.models import Fertilizer, Recipe, WaterProfile
from ..core.numbers import format_number
from ..core.solver import PRIORITY_NAMES
from .widgets import NumberDelegate, NumberEdit, cell_number, combo, number_item, readonly_item, setup_table


def _buttons(dialog: QDialog) -> QDialogButtonBox:
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.button(QDialogButtonBox.Ok).setText("Speichern")
    bb.button(QDialogButtonBox.Cancel).setText("Abbrechen")
    bb.accepted.connect(dialog.accept)
    bb.rejected.connect(dialog.reject)
    return bb


def _require_name(dialog, edit: QLineEdit, taken: set[str], own: str = "") -> bool:
    name = edit.text().strip()
    if not name:
        QMessageBox.warning(dialog, "Name fehlt", "Bitte einen Namen eingeben.")
        return False
    if name.lower() in taken and name.lower() != own.lower():
        QMessageBox.warning(dialog, "Name vergeben", f"„{name}“ gibt es bereits.")
        return False
    return True


class ElementTable(QTableWidget):
    """Tabelle Element | Wert [| Priorität], leere Zellen bedeuten "kein Wert".

    Mit priorities (auch leeres dict) erscheint eine Spalte mit Auswahl hoch/normal/niedrig.
    """

    def __init__(self, elements, values: dict[str, float], unit: str, parent=None,
                 priorities: dict[str, str] | None = None):
        with_prio = priorities is not None
        super().__init__(len(elements), 3 if with_prio else 2, parent)
        self.elements = list(elements)
        setup_table(self, ["Nährstoff", unit] + (["Priorität"] if with_prio else []), stretch_col=1)
        self.setItemDelegateForColumn(1, NumberDelegate(4, self))
        self.prio_boxes: list[QComboBox] = []
        for r, e in enumerate(self.elements):
            self.setItem(r, 0, readonly_item(e.label))
            self.setItem(r, 1, number_item(values.get(e.key)))
            if with_prio:
                box = combo([(name, name) for name in PRIORITY_NAMES])
                box.setToolTip("Wie wichtig es ist, diesen Zielwert genau zu treffen.\n"
                               "hoch: Abweichungen zählen 10-fach, niedrig: nur ein Zehntel.")
                box.currentIndexChanged.connect(lambda _=0, b=box: self._style_box(b))
                self.prio_boxes.append(box)
                self.setCellWidget(r, 2, box)
        if with_prio:
            self.set_priorities(priorities)

    def priorities(self) -> dict[str, str]:
        """Nur Einträge, die von "normal" abweichen."""
        return {e.key: b.currentData() for e, b in zip(self.elements, self.prio_boxes)
                if b.currentData() != "normal"}

    def set_priorities(self, priorities: dict[str, str]):
        for e, b in zip(self.elements, self.prio_boxes):
            b.setCurrentIndex(max(0, b.findData(priorities.get(e.key, "normal"))))
            self._style_box(b)

    @staticmethod
    def _style_box(box: QComboBox):
        level = box.currentData()
        box.setStyleSheet("font-weight: bold;" if level == "hoch"
                          else "color: palette(placeholder-text);" if level == "niedrig" else "")

    def values(self) -> dict[str, float]:
        """Alle eingetragenen Werte; leere Zellen fehlen, 0 bleibt erhalten."""
        out = {}
        for r, e in enumerate(self.elements):
            v = cell_number(self, r, 1)
            if v is not None:
                out[e.key] = v
        return out

    def set_values(self, values: dict[str, float]):
        for r, e in enumerate(self.elements):
            self.setItem(r, 1, number_item(values.get(e.key)))


class FertilizerDialog(QDialog):
    def __init__(self, fert: Fertilizer | None, taken: set[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dünger bearbeiten" if fert else "Neuer Dünger")
        self.resize(520, 720)
        self.fert = fert or Fertilizer("")
        self.taken = taken
        f = self.fert

        self.name = QLineEdit(f.name)
        self.formula = QLineEdit(f.formula)
        self.typ = combo([("fest", False), ("flüssig", True)])
        self.typ.setCurrentIndex(1 if f.liquid else 0)
        self.density = NumberEdit(f.density, 3)
        self.solubility = NumberEdit(f.solubility, 1)
        self.tank = combo([("automatisch", "auto"), ("Tank A", "A"), ("Tank B", "B"),
                           ("Tank C (bei A/B: Tank B)", "C")])
        self.tank.setCurrentIndex(max(0, self.tank.findData(f.tank)))
        self.available = QCheckBox("im Bestand vorhanden")
        self.available.setChecked(f.available)
        self.note = QLineEdit(f.note)
        self.typ.currentIndexChanged.connect(self._typ_changed)

        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("Formel", self.formula)
        form.addRow("Typ", self.typ)
        form.addRow("Dichte [g/mL]", self.density)
        form.addRow("Löslichkeit [g/L]", self.solubility)
        form.addRow("Konzentrat-Tank", self.tank)
        form.addRow("", self.available)
        form.addRow("Notiz", self.note)

        self.table = QTableWidget(len(NUTRIENTS), 3)
        setup_table(self.table, ["Nährstoff", "Gehalt [%]", "Angabe als"], stretch_col=1)
        self.table.setItemDelegateForColumn(1, NumberDelegate(4, self.table))
        self.forms: dict[int, QComboBox] = {}
        for r, e in enumerate(NUTRIENTS):
            self.table.setItem(r, 0, readonly_item(e.label))
            self.table.setItem(r, 1, number_item(f.composition.get(e.key)))
            if e.oxide:
                c = combo([(f"Element ({e.label})", 1.0), (f"Oxid ({e.oxide})", e.oxide_factor)])
                self.forms[r] = c
                self.table.setCellWidget(r, 2, c)
            else:
                self.table.setItem(r, 2, readonly_item("Element"))

        hint = QLabel("Gehalte in Massen-% wie auf dem Etikett. Bei P, K, Ca, Mg, S, Na, Si kann die "
                      "Oxidform (z. B. P₂O₅, K₂O) gewählt werden – umgerechnet wird beim Speichern. "
                      "Komma oder Punkt als Dezimalzeichen.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text);")

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(QLabel("<b>Zusammensetzung</b>"))
        lay.addWidget(self.table, 1)
        lay.addWidget(hint)
        lay.addWidget(_buttons(self))
        self._typ_changed()

    def _typ_changed(self):
        self.density.setEnabled(bool(self.typ.currentData()))

    def accept(self):
        if not _require_name(self, self.name, self.taken, self.fert.name):
            return
        comp = {}
        for r, e in enumerate(NUTRIENTS):
            v = cell_number(self.table, r, 1)
            if v:
                factor = self.forms[r].currentData() if r in self.forms else 1.0
                comp[e.key] = v * factor
        if not comp:
            QMessageBox.warning(self, "Zusammensetzung fehlt", "Bitte mindestens einen Nährstoffgehalt eingeben.")
            return
        if sum(comp.values()) > 100.5:
            QMessageBox.warning(self, "Zusammensetzung prüfen",
                                f"Die Gehalte ergeben zusammen {format_number(sum(comp.values()), 1)} %.")
            return
        liquid = bool(self.typ.currentData())
        if liquid and not self.density.value():
            if QMessageBox.question(self, "Dichte fehlt", "Ohne Dichte kann die Menge nur in g angegeben werden. "
                                    "Trotzdem speichern?") != QMessageBox.Yes:
                return
        f = self.fert
        f.name, f.formula, f.note = self.name.text().strip(), self.formula.text().strip(), self.note.text().strip()
        f.liquid, f.density, f.solubility = liquid, self.density.value() if liquid else None, self.solubility.value()
        f.tank, f.available, f.composition = self.tank.currentData(), self.available.isChecked(), comp
        super().accept()


class WaterDialog(QDialog):
    def __init__(self, water: WaterProfile | None, taken: set[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wasserprofil bearbeiten" if water else "Neues Wasserprofil")
        self.resize(420, 620)
        self.water = water or WaterProfile("")
        self.taken = taken
        self.name = QLineEdit(self.water.name)
        self.table = ElementTable(ELEMENTS, self.water.values, "Gehalt [mg/L]")
        form = QFormLayout()
        form.addRow("Name", self.name)
        hint = QLabel("Werte aus der Wasseranalyse des Versorgers in mg/L. "
                      "Hydrogencarbonat (HCO₃) fließt nur in die EC-Schätzung ein.")
        hint.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.table, 1)
        lay.addWidget(hint)
        lay.addWidget(_buttons(self))

    def accept(self):
        if not _require_name(self, self.name, self.taken, self.water.name):
            return
        self.water.name = self.name.text().strip()
        self.water.values = {k: v for k, v in self.table.values().items() if v}
        super().accept()


def fertilizer_list(fertilizers: list[Fertilizer], checked_ids, parent=None) -> QListWidget:
    lst = QListWidget(parent)
    for f in fertilizers:
        text = f.name if f.available else f"{f.name}  (nicht vorhanden)"
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, f.id)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if f.id in checked_ids else Qt.Unchecked)
        lst.addItem(item)
    return lst


def checked_ids(lst: QListWidget) -> list[int]:
    return [lst.item(i).data(Qt.UserRole) for i in range(lst.count())
            if lst.item(i).checkState() == Qt.Checked]


class RecipeDialog(QDialog):
    def __init__(self, recipe: Recipe | None, fertilizers: list[Fertilizer], taken: set[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Rezept bearbeiten" if recipe else "Neues Rezept")
        self.resize(760, 640)
        self.recipe = recipe or Recipe("")
        self.taken = taken
        self.name = QLineEdit(self.recipe.name)
        self.desc = QPlainTextEdit(self.recipe.description)
        self.desc.setMaximumHeight(70)
        self.table = ElementTable(NUTRIENTS, self.recipe.targets, "Ziel [mg/L]",
                                  priorities=self.recipe.priorities)
        self.ferts = fertilizer_list(fertilizers, set(self.recipe.fertilizer_ids))

        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("Beschreibung", self.desc)

        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Zielwerte</b> (leer = egal, 0 = soll nicht enthalten sein)"))
        left.addWidget(self.table)
        right = QVBoxLayout()
        right.addWidget(QLabel("<b>Gespeicherte Düngerauswahl</b> (optional)"))
        right.addWidget(self.ferts)
        cols = QHBoxLayout()
        lw, rw = QWidget(), QWidget()
        lw.setLayout(left)
        rw.setLayout(right)
        cols.addWidget(lw, 1)
        cols.addWidget(rw, 1)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(cols, 1)
        lay.addWidget(_buttons(self))

    def accept(self):
        if not _require_name(self, self.name, self.taken, self.recipe.name):
            return
        targets = self.table.values()
        if not targets:
            QMessageBox.warning(self, "Zielwerte fehlen", "Bitte mindestens einen Zielwert eingeben.")
            return
        r = self.recipe
        r.name, r.description = self.name.text().strip(), self.desc.toPlainText().strip()
        r.targets, r.fertilizer_ids = targets, checked_ids(self.ferts)
        r.priorities = self.table.priorities()
        super().accept()
