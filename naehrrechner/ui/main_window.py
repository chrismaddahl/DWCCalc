"""Hauptfenster mit den Registerkarten Berechnung, Rezepte, Dünger und Wasser."""
import traceback
from html import escape
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtPrintSupport import QPrintPreviewDialog
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QFileDialog,
                               QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QRadioButton,
                               QScrollArea, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser,
                               QVBoxLayout, QWidget)

from .. import __version__, csv_io
from ..core.batch import CONCENTRATE, estimate_ec, plan_concentrate, plan_direct
from ..core.elements import BY_KEY, ELEMENTS, NUTRIENT_KEYS, NUTRIENTS
from ..core.models import VE_WATER, Recipe
from ..core.numbers import format_amount_g, format_amount_ml, format_number
from ..core.solver import CalculationError, solve_auto, solve_manual
from ..db import Database
from ..printing import SheetData, a5_printer, build_html, render, save_pdf
from .dialogs import ElementTable, FertilizerDialog, RecipeDialog, WaterDialog, checked_ids, fertilizer_list
from .widgets import NumberEdit, combo, number_item, readonly_item, setup_table

MAJOR_COLUMNS = ("NO3_N", "NH4_N", "P", "K", "Ca", "Mg", "S")


def _button_row(*buttons) -> QHBoxLayout:
    row = QHBoxLayout()
    for b in buttons:
        row.addWidget(b)
    row.addStretch()
    return row


def _confirm(parent, title, text) -> bool:
    return QMessageBox.question(parent, title, text) == QMessageBox.Yes


# --------------------------------------------------------------------------- Dünger
class FertilizerTab(QWidget):
    changed = Signal()

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.only_available = QCheckBox("nur vorhandene anzeigen")
        self.only_available.toggled.connect(self.refresh)
        self.table = QTableWidget()
        setup_table(self.table, ["Name", "Formel", "Typ", "Dichte [g/mL]", "Vorhanden"]
                    + [f"{BY_KEY[k].label} %" for k in MAJOR_COLUMNS] + ["weitere %"], stretch_col=0)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit)

        new, edit, copy, delete = (QPushButton(t) for t in ("Neu…", "Bearbeiten…", "Kopieren", "Löschen"))
        new.clicked.connect(self.new)
        edit.clicked.connect(self.edit)
        copy.clicked.connect(self.copy)
        delete.clicked.connect(self.delete)

        lay = QVBoxLayout(self)
        top = _button_row(new, edit, copy, delete)
        top.addWidget(self.only_available)
        lay.addLayout(top)
        lay.addWidget(self.table)
        self.refresh()

    def refresh(self):
        self.items = self.db.fertilizers(self.only_available.isChecked())
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.items))
        for r, f in enumerate(self.items):
            name = readonly_item(f.name)
            name.setData(Qt.UserRole, f.id)
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, readonly_item(f.formula))
            self.table.setItem(r, 2, readonly_item("flüssig" if f.liquid else "fest"))
            if f.liquid and not f.density:
                density = readonly_item("fehlt", align_right=True)
                density.setForeground(QColor("#b45309"))
                density.setToolTip("Ohne Dichte wird dieser Flüssigdünger in g statt mL angegeben.")
            else:
                density = number_item(f.density if f.liquid else None, 3, editable=False)
            self.table.setItem(r, 3, density)
            self.table.setItem(r, 4, readonly_item("ja" if f.available else "nein"))
            for c, k in enumerate(MAJOR_COLUMNS, start=5):
                self.table.setItem(r, c, number_item(f.composition.get(k), 2, editable=False))
            rest = [f"{BY_KEY[k].label} {format_number(v, 3, True)}" for k, v in f.composition.items()
                    if k not in MAJOR_COLUMNS]
            self.table.setItem(r, len(MAJOR_COLUMNS) + 5, readonly_item(" · ".join(rest)))
        self.table.setSortingEnabled(True)

    def _selected(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        fid = self.table.item(row, 0).data(Qt.UserRole)
        return next((f for f in self.items if f.id == fid), None)

    def _names(self):
        return {f.name.lower() for f in self.db.fertilizers()}

    def _open(self, fert):
        dlg = FertilizerDialog(fert, self._names(), self)
        if dlg.exec():
            self.db.save_fertilizer(dlg.fert)
            self.changed.emit()

    def new(self):
        self._open(None)

    def edit(self):
        f = self._selected()
        if f:
            self._open(f)

    def copy(self):
        f = self._selected()
        if f:
            f.id, f.name = None, f"{f.name} (Kopie)"
            self._open(f)

    def delete(self):
        f = self._selected()
        if f and _confirm(self, "Dünger löschen",
                          f"„{f.name}“ löschen?\nEr wird auch aus gespeicherten Düngerauswahlen entfernt."):
            self.db.delete_fertilizer(f.id)
            self.changed.emit()


# --------------------------------------------------------------------------- Wasser
class WaterTab(QWidget):
    changed = Signal()

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.table = QTableWidget()
        setup_table(self.table, ["Name"] + [f"{e.label}" for e in ELEMENTS], stretch_col=0)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit)
        new, edit, delete = (QPushButton(t) for t in ("Neu…", "Bearbeiten…", "Löschen"))
        new.clicked.connect(lambda: self._open(None))
        edit.clicked.connect(self.edit)
        delete.clicked.connect(self.delete)
        info = QLabel("Alle Werte in mg/L. „VE-Wasser“ ist immer vorhanden und enthält keine Nährstoffe.")
        lay = QVBoxLayout(self)
        lay.addLayout(_button_row(new, edit, delete))
        lay.addWidget(self.table)
        lay.addWidget(info)
        self.refresh()

    def refresh(self):
        self.items = self.db.waters()
        self.table.setRowCount(len(self.items))
        for r, w in enumerate(self.items):
            self.table.setItem(r, 0, readonly_item(w.name))
            for c, e in enumerate(ELEMENTS, start=1):
                self.table.setItem(r, c, number_item(w.values.get(e.key), 2, editable=False))

    def _selected(self):
        r = self.table.currentRow()
        return self.items[r] if 0 <= r < len(self.items) else None

    def _open(self, water):
        dlg = WaterDialog(water, {w.name.lower() for w in self.items}, self)
        if dlg.exec():
            self.db.save_water(dlg.water)
            self.changed.emit()

    def edit(self):
        w = self._selected()
        if w:
            self._open(w)

    def delete(self):
        w = self._selected()
        if w and _confirm(self, "Wasserprofil löschen", f"„{w.name}“ löschen?"):
            self.db.delete_water(w.id)
            self.changed.emit()


# --------------------------------------------------------------------------- Rezepte
class RecipeTab(QWidget):
    changed = Signal()
    calculate = Signal(int)

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.show_detail)
        self.list.itemDoubleClicked.connect(lambda _: self.edit())
        self.detail = QTextBrowser()
        new, edit, copy, delete, calc = (QPushButton(t) for t in
                                         ("Neu…", "Bearbeiten…", "Kopieren", "Löschen", "Berechnen →"))
        new.clicked.connect(lambda: self._open(None))
        edit.clicked.connect(self.edit)
        copy.clicked.connect(self.copy)
        delete.clicked.connect(self.delete)
        calc.clicked.connect(self._calc)
        split = QSplitter()
        split.addWidget(self.list)
        split.addWidget(self.detail)
        split.setSizes([280, 700])
        lay = QVBoxLayout(self)
        lay.addLayout(_button_row(new, edit, copy, delete, calc))
        lay.addWidget(split)
        self.refresh()

    def refresh(self):
        current = self._selected()
        self.items = self.db.recipes()
        self.ferts = {f.id: f for f in self.db.fertilizers()}
        self.list.clear()
        for r in self.items:
            self.list.addItem(r.name)
        if self.items:
            ids = [r.id for r in self.items]
            self.list.setCurrentRow(ids.index(current.id) if current and current.id in ids else 0)
        else:
            self.detail.setHtml("<p>Noch keine Rezepte. Mit „Neu…“ anlegen oder per CSV importieren.</p>")

    def _selected(self) -> Recipe | None:
        r = self.list.currentRow() if hasattr(self, "items") else -1
        return self.items[r] if 0 <= r < len(self.items) else None

    def show_detail(self, _row=None):
        r = self._selected()
        if not r:
            return
        rows = "".join(
            f"<tr><td>{escape(e.label)}</td><td align='right'>{format_number(r.targets[e.key], 3, True)}</td>"
            f"<td>{r.priorities.get(e.key, '')}</td></tr>"
            for e in NUTRIENTS if e.key in r.targets)
        ferts = "".join(f"<li>{escape(self.ferts[i].name)}</li>" for i in r.fertilizer_ids if i in self.ferts)
        ferts = f"<ul>{ferts}</ul>" if ferts else "<p><i>keine Düngerauswahl gespeichert</i></p>"
        desc = f"<p>{escape(r.description)}</p>" if r.description else ""
        self.detail.setHtml(
            f"<h2>{escape(r.name)}</h2>{desc}"
            f"<table cellpadding='3'><tr><td valign='top'>"
            f"<table border='1' cellspacing='0' cellpadding='4'><tr><th>Nährstoff</th><th>mg/L</th><th>Priorität</th></tr>{rows}</table>"
            f"</td><td width='30'></td><td valign='top'><b>Düngerauswahl</b>{ferts}"
            f"<p>Geschätzte EC: <b>{format_number(estimate_ec(r.targets), 2)} mS/cm</b></p></td></tr></table>")

    def _open(self, recipe):
        dlg = RecipeDialog(recipe, self.db.fertilizers(), {r.name.lower() for r in self.items}, self)
        if dlg.exec():
            self.db.save_recipe(dlg.recipe)
            self.changed.emit()

    def edit(self):
        r = self._selected()
        if r:
            self._open(r)

    def copy(self):
        r = self._selected()
        if r:
            r.id, r.name = None, f"{r.name} (Kopie)"
            self._open(r)

    def delete(self):
        r = self._selected()
        if r and _confirm(self, "Rezept löschen", f"„{r.name}“ löschen?"):
            self.db.delete_recipe(r.id)
            self.changed.emit()

    def _calc(self):
        r = self._selected()
        if r:
            self.calculate.emit(r.id)


# --------------------------------------------------------------------------- Berechnung
class CalcTab(QWidget):
    changed = Signal()

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.solutions = []
        self.solution = None
        self.plan = None
        self.plans = []            # ein Ansatz je Variante, gleiche Reihenfolge wie self.solutions
        self._col_variant = {}     # (Tabelle, Spalte) -> Variante, für Klick auf den Spaltenkopf

        # Rezept / Zielwerte
        self.recipe_box = QComboBox()
        self.recipe_box.currentIndexChanged.connect(self._recipe_selected)
        self.targets = ElementTable(NUTRIENTS, {}, "Ziel [mg/L]", priorities={})
        self.targets.setMinimumHeight(330)
        self.save_selection = QCheckBox("Düngerauswahl mitspeichern")
        self.save_selection.setChecked(True)
        save = QPushButton("Rezept speichern…")
        save.clicked.connect(self.save_recipe)
        g_recipe = QGroupBox("1  Rezept / Zielwerte")
        lay = QVBoxLayout(g_recipe)
        lay.addWidget(self.recipe_box)
        lay.addWidget(self.targets)
        lay.addLayout(_button_row(save, self.save_selection))

        # Wasser
        self.water_box = QComboBox()
        g_water = QGroupBox("2  Wasser")
        QVBoxLayout(g_water).addWidget(self.water_box)

        # Dünger
        self.manual = QRadioButton("Dünger selbst auswählen")
        self.auto = QRadioButton("Beste Kombination aus allen vorhandenen Düngern")
        self.manual.setChecked(True)
        self.fert_list = QListWidget()
        self.fert_list.setMinimumHeight(160)
        self.max_count = QSpinBox()
        self.max_count.setRange(1, 20)
        self.max_count.setValue(12)
        self.max_count.setToolTip("Spurenelemente brauchen meist je einen eigenen Dünger.")
        all_btn, none_btn = QPushButton("alle"), QPushButton("keine")
        all_btn.clicked.connect(lambda: self._check_all(True))
        none_btn.clicked.connect(lambda: self._check_all(False))
        self.manual.toggled.connect(self._mode_changed)
        g_fert = QGroupBox("3  Dünger")
        lay = QVBoxLayout(g_fert)
        lay.addWidget(self.manual)
        lay.addWidget(self.fert_list)
        lay.addLayout(_button_row(all_btn, none_btn))
        lay.addWidget(self.auto)
        row = QHBoxLayout()
        row.addWidget(QLabel("höchstens"))
        row.addWidget(self.max_count)
        row.addWidget(QLabel("Dünger"))
        row.addStretch()
        lay.addLayout(row)

        # Ansatz
        self.direct = QRadioButton("Direkter Ansatz")
        self.conc = QRadioButton("Konzentrat")
        self.direct.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.direct)
        grp.addButton(self.conc)
        self.volume = NumberEdit(10, 2)
        self.factor = QSpinBox()
        self.factor.setRange(2, 1000)
        self.factor.setValue(100)
        self.factor.setSuffix(" ×")
        self.tank_volume = NumberEdit(10, 2)
        self.split = combo([("ein Konzentrat", 1), ("Tank A / B", 2), ("Tank A / B / C", 3)])
        self.split.setCurrentIndex(1)
        self.split.setToolTip("A/B trennt Calcium von Sulfat und Phosphat.\n"
                              "A/B/C trennt zusätzlich Magnesium vom Phosphat (Magnesiumphosphat, Struvit).")
        g_batch = QGroupBox("4  Ansatz")
        grid = QGridLayout(g_batch)
        grid.addWidget(self.direct, 0, 0, 1, 2)
        grid.addWidget(QLabel("Volumen [L]"), 1, 0)
        grid.addWidget(self.volume, 1, 1)
        grid.addWidget(self.conc, 2, 0, 1, 2)
        grid.addWidget(QLabel("Faktor"), 3, 0)
        grid.addWidget(self.factor, 3, 1)
        grid.addWidget(QLabel("Volumen je Tank [L]"), 4, 0)
        grid.addWidget(self.tank_volume, 4, 1)
        grid.addWidget(QLabel("Aufteilung"), 5, 0)
        grid.addWidget(self.split, 5, 1)
        self.conc.toggled.connect(self._batch_mode_changed)
        for sig in (self.conc.toggled, self.factor.valueChanged, self.split.currentIndexChanged,
                    self.volume.editingFinished, self.tank_volume.editingFinished):
            sig.connect(self._replan)

        calc = QPushButton("Berechnen")
        calc.setMinimumHeight(36)
        calc.setStyleSheet("font-weight: bold;")
        calc.clicked.connect(lambda: self.calculate())

        left = QWidget()
        llay = QVBoxLayout(left)
        for w in (g_recipe, g_water, g_fert, g_batch, calc):
            llay.addWidget(w)
        llay.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(left)
        scroll.setMinimumWidth(400)

        # Ergebnis
        self.headline = QLabel("Noch keine Berechnung.")
        self.headline.setStyleSheet("font-size: 14pt; font-weight: bold;")
        self.variant = QComboBox()
        self.variant.currentIndexChanged.connect(self._variant_selected)
        self.variant_label = QLabel("Details (Herkunft, EC, Hinweise) für:")
        self.weigh = QTableWidget()
        self.weigh.verticalHeader().setVisible(False)
        self.weigh.setAlternatingRowColors(True)
        self.weigh.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.dosing = QLabel()
        self.dosing.setWordWrap(True)
        self.compare = QTableWidget()
        self.compare.verticalHeader().setVisible(False)
        self.compare.setAlternatingRowColors(True)
        self.compare.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for table in (self.weigh, self.compare):
            table.horizontalHeader().sectionClicked.connect(
                lambda col, t=table: self._header_clicked(t, col))
        self.contrib = QTableWidget()
        self.contrib.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.contrib_unit = QComboBox()
        self.contrib_unit.addItem("mg/L", False)
        self.contrib_unit.addItem("Anteil in % vom Gesamtgehalt", True)
        self.contrib_unit.currentIndexChanged.connect(self._fill_contrib)
        contrib_page = QWidget()
        clay = QVBoxLayout(contrib_page)
        crow = QHBoxLayout()
        crow.addWidget(QLabel("Welcher Dünger liefert wie viel – Anzeige:"))
        crow.addWidget(self.contrib_unit)
        crow.addStretch()
        clay.addLayout(crow)
        clay.addWidget(self.contrib)
        compare_page = QWidget()
        play = QVBoxLayout(compare_page)
        play.addWidget(QLabel("mg/L in der fertigen Lösung"))
        play.addWidget(self.compare)
        self.result_tabs = QTabWidget()
        self.result_tabs.addTab(compare_page, "Nährstoffe: Ziel und Ergebnis")
        self.result_tabs.addTab(contrib_page, "Herkunft der Nährstoffe")
        self.ec = QLabel()
        self.ec.setStyleSheet("font-size: 11pt;")
        self.warnings = QLabel()
        self.warnings.setWordWrap(True)
        self.warnings.setStyleSheet("color: #b45309;")
        self.print_btn = QPushButton("Merkzettel drucken (A5 quer)…")
        self.pdf_btn = QPushButton("Als PDF speichern…")
        self.print_btn.clicked.connect(self.print_sheet)
        self.pdf_btn.clicked.connect(self.pdf_sheet)

        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.addWidget(self.headline)
        vrow = QHBoxLayout()
        vrow.addWidget(self.variant_label)
        vrow.addWidget(self.variant, 1)
        rlay.addLayout(vrow)
        rlay.addWidget(QLabel("<b>Wiegeliste</b>"))
        rlay.addWidget(self.weigh, 3)
        rlay.addWidget(self.dosing)
        rlay.addWidget(self.result_tabs, 4)
        rlay.addWidget(self.ec)
        rlay.addWidget(self.warnings)
        rlay.addLayout(_button_row(self.print_btn, self.pdf_btn))

        split = QSplitter()
        split.addWidget(scroll)
        split.addWidget(right)
        split.setSizes([420, 800])
        QVBoxLayout(self).addWidget(split)
        self._mode_changed()
        self._batch_mode_changed()
        self._show_result()
        self.refresh()

    # --- Daten ------------------------------------------------------------
    def refresh(self):
        keep_recipe = self.recipe_box.currentData()
        keep_water = self.water_box.currentData()
        keep_checked = set(checked_ids(self.fert_list))
        self.recipes = {r.id: r for r in self.db.recipes()}
        self.waters = {w.id: w for w in self.db.waters()}
        self.ferts = {f.id: f for f in self.db.fertilizers()}

        self.recipe_box.blockSignals(True)
        self.recipe_box.clear()
        self.recipe_box.addItem("— eigene Eingabe —", None)
        for r in self.recipes.values():
            self.recipe_box.addItem(r.name, r.id)
        self.recipe_box.setCurrentIndex(max(0, self.recipe_box.findData(keep_recipe)))
        self.recipe_box.blockSignals(False)

        self.water_box.clear()
        self.water_box.addItem(VE_WATER.name, None)
        for w in self.waters.values():
            self.water_box.addItem(w.name, w.id)
        self.water_box.setCurrentIndex(max(0, self.water_box.findData(keep_water)))

        self._fill_fert_list(keep_checked)

    def _fill_fert_list(self, checked: set[int]):
        self.fert_list.clear()
        for f in self.ferts.values():
            if not f.available and f.id not in checked:
                continue
            item = QListWidgetItem(f.name if f.available else f"{f.name}  (nicht vorhanden)")
            item.setData(Qt.UserRole, f.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if f.id in checked else Qt.Unchecked)
            self.fert_list.addItem(item)

    def _check_all(self, on: bool):
        for i in range(self.fert_list.count()):
            self.fert_list.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)

    def open_recipe(self, rid: int):
        self.recipe_box.setCurrentIndex(max(0, self.recipe_box.findData(rid)))
        self._recipe_selected()

    def _recipe_selected(self):
        r = self.recipes.get(self.recipe_box.currentData())
        if not r:
            return
        self.targets.set_values(r.targets)
        self.targets.set_priorities(r.priorities)
        if r.fertilizer_ids:
            self._fill_fert_list(set(r.fertilizer_ids))
            self.manual.setChecked(True)

    def _mode_changed(self):
        self.fert_list.setEnabled(self.manual.isChecked())
        self.max_count.setEnabled(self.auto.isChecked())

    def _batch_mode_changed(self):
        c = self.conc.isChecked()
        self.volume.setEnabled(not c)
        for w in (self.factor, self.tank_volume, self.split):
            w.setEnabled(c)

    # --- Sitzung sichern / wiederherstellen ----------------------------------
    def get_state(self) -> dict:
        return {
            "recipe": self.recipe_box.currentData(),
            "targets": self.targets.values(),
            "priorities": self.targets.priorities(),
            "water": self.water_box.currentData(),
            "auto": self.auto.isChecked(),
            "fertilizers": checked_ids(self.fert_list),
            "max_count": self.max_count.value(),
            "concentrate": self.conc.isChecked(),
            "volume": self.volume.value(),
            "factor": self.factor.value(),
            "tank_volume": self.tank_volume.value(),
            "tanks": self.split.currentData(),
            "save_selection": self.save_selection.isChecked(),
            "has_result": self.solution is not None,
            "variant": max(0, self.variant.currentIndex()),
            "result_tab": self.result_tabs.currentIndex(),
            "contrib_percent": self.contrib_unit.currentIndex(),
        }

    def set_state(self, st: dict):
        """Stellt den Stand der letzten Sitzung her; gelöschte Rezepte/Dünger werden übergangen."""
        self.recipe_box.blockSignals(True)
        self.recipe_box.setCurrentIndex(max(0, self.recipe_box.findData(st.get("recipe"))))
        self.recipe_box.blockSignals(False)
        self.targets.set_values(st.get("targets", {}))
        self.targets.set_priorities(st.get("priorities", {}))
        self.water_box.setCurrentIndex(max(0, self.water_box.findData(st.get("water"))))
        self._fill_fert_list({i for i in st.get("fertilizers", []) if i in self.ferts})
        (self.auto if st.get("auto") else self.manual).setChecked(True)
        self.max_count.setValue(st.get("max_count", self.max_count.value()))
        self.volume.setValue(st.get("volume") or 10)
        self.factor.setValue(st.get("factor", self.factor.value()))
        self.tank_volume.setValue(st.get("tank_volume") or 10)
        tanks = st.get("tanks", 2 if st.get("split", True) else 1)
        self.split.setCurrentIndex(max(0, self.split.findData(tanks)))
        self.save_selection.setChecked(st.get("save_selection", True))
        self.contrib_unit.setCurrentIndex(st.get("contrib_percent", 0))
        self.result_tabs.setCurrentIndex(st.get("result_tab", 0))
        (self.conc if st.get("concentrate") else self.direct).setChecked(True)
        if st.get("has_result"):
            self.calculate(quiet=True)
            if 0 < st.get("variant", 0) < self.variant.count():
                self.variant.setCurrentIndex(st["variant"])

    # --- Berechnung -------------------------------------------------------
    def calculate(self, quiet: bool = False):
        targets = self.targets.values()
        water = self.waters.get(self.water_box.currentData(), VE_WATER)
        prio = self.targets.priorities()
        try:
            if self.manual.isChecked():
                ferts = [self.ferts[i] for i in checked_ids(self.fert_list)]
                self.solutions = [solve_manual(targets, water, ferts, priorities=prio)]
            else:
                ferts = [f for f in self.ferts.values() if f.available]
                if not ferts:
                    raise CalculationError("Es sind keine vorhandenen Dünger in der Datenbank.")
                self.solutions = solve_auto(targets, water, ferts, self.max_count.value(), priorities=prio)
        except CalculationError as e:
            if not quiet:
                QMessageBox.warning(self, "Berechnung nicht möglich", str(e))
            return
        self.variant.blockSignals(True)
        self.variant.clear()
        for i, s in enumerate(self.solutions, start=1):
            self.variant.addItem(f"Variante {i}: {len(s.fertilizers)} Dünger, "
                                 f"mittlere Abweichung {format_number(s.score, 1)} %")
        self.variant.blockSignals(False)
        self.solution = self.solutions[0]
        self._replan()

    def _variant_selected(self, idx):
        if 0 <= idx < len(self.solutions):
            self.solution = self.solutions[idx]
            self.plan = self.plans[idx] if idx < len(self.plans) else None
            self._show_result()

    def _header_clicked(self, table, col):
        idx = self._col_variant.get((id(table), col))
        if idx is not None:
            self.variant.setCurrentIndex(idx)

    def _replan(self):
        if not self.solutions:
            return
        try:
            if self.conc.isChecked():
                self.plans = [plan_concentrate(sol, self.factor.value(), self.tank_volume.value() or 0,
                                               self.split.currentData()) for sol in self.solutions]
            else:
                self.plans = [plan_direct(sol, self.volume.value() or 0) for sol in self.solutions]
        except ValueError as e:
            QMessageBox.warning(self, "Ansatz prüfen", str(e))
            return
        idx = max(0, self.variant.currentIndex())
        self.solution, self.plan = self.solutions[idx], self.plans[idx]
        self._show_result()

    @staticmethod
    def _deviation_item(dev) -> QTableWidgetItem:
        item = readonly_item("–" if dev is None else ("über Ziel" if dev == float("inf")
                                                       else f"{format_number(dev, 1)} %"), True)
        if dev is not None:
            a = abs(dev)
            item.setBackground(QColor("#c8efd0") if a <= 5 else QColor("#fde9b8") if a <= 15
                               else QColor("#f8c8c8"))
            item.setForeground(QColor("#1a1a1a"))
        return item

    def _set_headers(self, table, headers, variant_of_col: dict[int, int], stretch_col: int | None):
        """Spaltenköpfe setzen; bei mehreren Varianten die ausgewählte fett."""
        multi = len(self.solutions) > 1
        sel = max(0, self.variant.currentIndex())
        table.setColumnCount(len(headers))
        for c, text in enumerate(headers):
            item = QTableWidgetItem(text)
            if multi and c in variant_of_col:
                item.setToolTip("Klicken, um Herkunft, EC und Hinweise dieser Variante anzuzeigen")
                if variant_of_col[c] == sel:
                    item.setFont(self._bold())
            table.setHorizontalHeaderItem(c, item)
        for c, v in variant_of_col.items():
            self._col_variant[(id(table), c)] = v
        h = table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeToContents)
        if stretch_col is not None:
            h.setSectionResizeMode(stretch_col, QHeaderView.Stretch)

    def _show_result(self):
        has = bool(self.solutions) and len(self.plans) == len(self.solutions) and self.plan is not None
        for w in (self.print_btn, self.pdf_btn):
            w.setEnabled(has)
        n = len(self.solutions)
        multi = n > 1
        self.variant.setVisible(multi)
        self.variant_label.setVisible(multi)
        self._col_variant = {}
        if not has:
            self.weigh.setRowCount(0)
            self.compare.setRowCount(0)
            self.contrib.setRowCount(0)
            return
        s, p = self.solution, self.plan
        conc = p.mode == CONCENTRATE
        self.headline.setText(self._title())

        # --- Wiegeliste: eine Mengenspalte je Variante ----------------------------
        rows = {}     # Düngername -> (Tank, {Variante: BatchLine})
        for vi, plan in enumerate(self.plans):
            for ln in plan.lines:
                rows.setdefault(ln.fertilizer.name, (ln.tank, {}))[1][vi] = ln
        order = sorted(rows, key=lambda name: (rows[name][0], name.lower()))
        show_conc = conc and not multi
        headers = ["Tank", "Dünger"] + [f"Variante {i + 1}" if multi else "Menge" for i in range(n)]
        headers += ["g/L im Tank"] if show_conc else []
        self._set_headers(self.weigh, headers, {2 + i: i for i in range(n)}, stretch_col=1)
        self.weigh.setColumnHidden(0, not (conc and p.split))
        self.weigh.setRowCount(len(order))
        for r, name in enumerate(order):
            tank, lines = rows[name]
            self.weigh.setItem(r, 0, readonly_item(tank))
            self.weigh.setItem(r, 1, readonly_item(name))
            for vi in range(n):
                ln = lines.get(vi)
                if ln is None:
                    self.weigh.setItem(r, 2 + vi, readonly_item(""))
                    continue
                v, u = format_amount_ml(ln.ml) if ln.ml is not None else format_amount_g(ln.grams)
                cell = readonly_item(f"{v} {u}", align_right=True)
                cell.setFont(self._bold())
                if conc:
                    cell.setToolTip(f"{format_number(ln.tank_conc, 3 if ln.tank_conc < 1 else 1)} g/L im Tank")
                self.weigh.setItem(r, 2 + vi, cell)
            if show_conc:
                conc_gl = lines[0].tank_conc
                self.weigh.setItem(r, 2 + n, readonly_item(
                    format_number(conc_gl, 3 if conc_gl < 1 else 1), align_right=True))

        if conc:
            ml = format_number(p.ml_per_liter, 2, True)
            limits = [(f"Variante {i + 1}: " if multi else "") + f"{format_number(pl.max_factor, 0)} ×"
                      for i, pl in enumerate(self.plans) if pl.max_factor]
            self.dosing.setText(
                f"Dosierung: je <b>{ml} mL</b> " + ("von " + p.tank_label.replace(" und ", " <u>und</u> ") if p.split else "Konzentrat")
                + " pro Liter Wasser."
                + (" Höchster Faktor laut Löslichkeit: " + ", ".join(limits) + "." if limits else ""))
        else:
            self.dosing.setText(f"Für {format_number(p.volume_l, 2, True)} L fertige Nährlösung.")

        # --- Ziel und Ergebnis: Gesamt und Abweichung je Variante -------------------
        keys = [k for k in NUTRIENT_KEYS
                if k in s.targets or any(sol.total.get(k, 0) > 1e-6 for sol in self.solutions)]
        per_variant = ["Gesamt", "Abweichung"] if multi else ["aus Düngern", "Gesamt", "Abweichung"]
        width = len(per_variant)
        headers = ["Nährstoff", "Ziel", "aus Wasser"]
        col_variant = {}
        for i in range(n):
            for name in per_variant:
                col_variant[len(headers)] = i
                headers.append(f"V{i + 1} {name}" if multi else name)
        self._set_headers(self.compare, headers, col_variant, stretch_col=None)
        self.compare.setRowCount(len(keys) + 2)
        for r, k in enumerate(keys):
            dec = 3 if BY_KEY[k].micro else 1
            self.compare.setItem(r, 0, readonly_item(BY_KEY[k].label))
            self.compare.setItem(r, 1, number_item(s.targets.get(k), dec, editable=False))
            self.compare.setItem(r, 2, number_item(s.water.get(k, 0), dec, editable=False))
            for i, sol in enumerate(self.solutions):
                c = 3 + i * width
                if not multi:
                    self.compare.setItem(r, c, number_item(sol.supplied.get(k, 0), dec, editable=False))
                    c += 1
                self.compare.setItem(r, c, number_item(sol.total.get(k, 0), dec, editable=False))
                self.compare.setItem(r, c + 1, self._deviation_item(sol.deviation(k)))
        # Zusammenfassung je Variante: EC in der Gesamt-Spalte, mittlere Abweichung in der Abweichungs-Spalte
        summary = len(keys)
        for r, label in ((summary, "geschätzte EC [mS/cm]"), (summary + 1, "mittlere Abweichung")):
            head = readonly_item(label)
            head.setFont(self._bold())
            self.compare.setItem(r, 0, head)
            for c in range(1, self.compare.columnCount()):
                self.compare.setItem(r, c, readonly_item(""))
        for i, sol in enumerate(self.solutions):
            c = 3 + i * width + (0 if multi else 1)
            ec = readonly_item(format_number(estimate_ec(sol.total), 2), align_right=True)
            score = readonly_item(f"{format_number(sol.score, 1)} %", align_right=True)
            for cell in (ec, score):
                cell.setFont(self._bold())
            self.compare.setItem(summary, c, ec)
            self.compare.setItem(summary + 1, c + 1, score)

        self._fill_contrib()
        self.ec.setText(f"Geschätzte EC{f' (Variante {self.variant.currentIndex() + 1})' if multi else ''}: "
                        f"<b>{format_number(estimate_ec(s.total), 2)} mS/cm</b> (25 °C, ohne Spurenelemente)")
        warn = s.warnings + p.warnings
        self.warnings.setText("<br>".join(f"⚠ {escape(w)}" for w in warn))

    def _fill_contrib(self):
        """Tabelle Herkunft: Zeilen = Dünger und Wasser, Spalten = Nährstoffe."""
        s = self.solution
        if s is None:
            return
        percent = bool(self.contrib_unit.currentData())
        # Nährstoffe mit Zielwert immer zeigen, auch wenn nichts sie liefert (leere Spalte)
        keys = [k for k in NUTRIENT_KEYS if k in s.targets or s.total.get(k, 0) > 1e-9]
        rows = [(n, v) for n, v in s.contributions() if any(v.get(k) for k in keys)]
        self.contrib.clear()
        self.contrib.setColumnCount(len(keys) + 1)
        self.contrib.setHorizontalHeaderLabels(["Herkunft"] + [BY_KEY[k].label for k in keys])
        self.contrib.verticalHeader().setVisible(False)
        self.contrib.setRowCount(len(rows) + 1)
        for r, (name, values) in enumerate(rows):
            item = readonly_item(name)
            if name == "Wasser":
                item.setFont(self._italic())
            self.contrib.setItem(r, 0, item)
            for c, k in enumerate(keys, start=1):
                mg = values.get(k, 0.0)
                share = mg / s.total[k] if s.total[k] > 1e-9 else 0.0
                if mg <= 1e-9:
                    text = ""
                elif percent:
                    text = f"{format_number(share * 100, 1)} %" if share >= 0.0005 else "< 0,1 %"
                else:
                    text = format_number(mg, 3 if BY_KEY[k].micro else 1)
                cell = readonly_item(text, align_right=True)
                if mg > 1e-9:
                    # je größer der Anteil, desto kräftiger die Farbe
                    cell.setBackground(QColor(59, 130, 246, int(25 + 150 * share)))
                    cell.setForeground(QColor("#1a1a1a"))
                    cell.setToolTip(f"{name}: {format_number(mg, 3)} mg/L {BY_KEY[k].label} "
                                    f"= {format_number(share * 100, 1)} % des Gesamtgehalts")
                self.contrib.setItem(r, c, cell)
        last = len(rows)
        total = readonly_item("Gesamt")
        total.setFont(self._bold())
        self.contrib.setItem(last, 0, total)
        for c, k in enumerate(keys, start=1):
            if s.total[k] <= 1e-9:
                text = "–"
            else:
                text = "100 %" if percent else format_number(s.total[k], 3 if BY_KEY[k].micro else 1)
            cell = readonly_item(text, align_right=True)
            cell.setFont(self._bold())
            self.contrib.setItem(last, c, cell)
        h = self.contrib.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeToContents)

    def _italic(self):
        f = self.font()
        f.setItalic(True)
        return f

    def _bold(self):
        f = self.font()
        f.setBold(True)
        return f

    def _title(self) -> str:
        r = self.recipes.get(self.recipe_box.currentData())
        return r.name if r else "Eigene Nährlösung"

    # --- Speichern / Drucken ----------------------------------------------
    def save_recipe(self):
        targets = self.targets.values()
        if not targets:
            QMessageBox.warning(self, "Zielwerte fehlen", "Bitte mindestens einen Zielwert eingeben.")
            return
        if self.save_selection.isChecked():
            if self.manual.isChecked():
                fids = checked_ids(self.fert_list)
            else:
                fids = [f.id for f in self.solution.fertilizers] if self.solution else []
        else:
            fids = None
        current = self.recipes.get(self.recipe_box.currentData())
        recipe = None
        if current:
            box = QMessageBox(QMessageBox.Question, "Rezept speichern",
                              f"Rezept „{current.name}“ überschreiben oder als neues Rezept speichern?", parent=self)
            over = box.addButton("Überschreiben", QMessageBox.AcceptRole)
            new = box.addButton("Als neues Rezept…", QMessageBox.ActionRole)
            box.addButton("Abbrechen", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() == over:
                recipe = current
            elif box.clickedButton() != new:
                return
        if recipe is None:
            name, ok = QInputDialog.getText(self, "Neues Rezept", "Name des Rezepts:")
            if not ok or not name.strip():
                return
            if name.strip().lower() in {r.name.lower() for r in self.recipes.values()}:
                QMessageBox.warning(self, "Name vergeben", f"„{name.strip()}“ gibt es bereits.")
                return
            recipe = Recipe(name.strip())
        recipe.targets = targets
        recipe.priorities = self.targets.priorities()
        if fids is not None:
            recipe.fertilizer_ids = fids
        rid = self.db.save_recipe(recipe)
        self.changed.emit()
        self.recipe_box.blockSignals(True)
        self.recipe_box.setCurrentIndex(max(0, self.recipe_box.findData(rid)))
        self.recipe_box.blockSignals(False)

    def _sheet_html(self, idx: int) -> str:
        r = self.recipes.get(self.recipe_box.currentData())
        water = self.water_box.currentText()
        sol, plan = self.solutions[idx], self.plans[idx]
        title = self._title() + (f" – Variante {idx + 1}" if len(self.solutions) > 1 else "")
        return build_html(SheetData(title, water, sol, plan, estimate_ec(sol.total), r.description if r else ""))

    def _choose_variant(self, purpose: str) -> int | None:
        """Bei mehreren Varianten nachfragen, welche gedruckt werden soll."""
        if len(self.solutions) <= 1:
            return 0
        items = [self.variant.itemText(i) for i in range(self.variant.count())]
        text, ok = QInputDialog.getItem(self, purpose, "Welche Variante?", items,
                                        max(0, self.variant.currentIndex()), False)
        return items.index(text) if ok else None

    def print_sheet(self):
        idx = self._choose_variant("Merkzettel drucken")
        if idx is None:
            return
        html = self._sheet_html(idx)
        # Der Dialog übernimmt den Drucker nicht: ohne Referenz räumt Python ihn weg -> Absturz.
        self._printer = a5_printer()
        dlg = QPrintPreviewDialog(self._printer, self)
        dlg.setWindowTitle("Merkzettel drucken")
        dlg.paintRequested.connect(lambda printer: render(html, printer))
        dlg.resize(900, 700)
        dlg.exec()

    def pdf_sheet(self):
        idx = self._choose_variant("Als PDF speichern")
        if idx is None:
            return
        suffix = f" Variante {idx + 1}" if len(self.solutions) > 1 else ""
        path, _ = QFileDialog.getSaveFileName(self, "Als PDF speichern", f"{self._title()}{suffix}.pdf",
                                              "PDF (*.pdf)")
        if path:
            save_pdf(self._sheet_html(idx), path)


# --------------------------------------------------------------------------- Fenster
class MainWindow(QMainWindow):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.setWindowTitle("Nährlösungsrechner")
        self.resize(1280, 860)
        self.calc = CalcTab(db)
        self.recipes = RecipeTab(db)
        self.ferts = FertilizerTab(db)
        self.water = WaterTab(db)
        self.tabs = QTabWidget()
        for w, name in ((self.calc, "Berechnung"), (self.recipes, "Rezepte"),
                        (self.ferts, "Dünger"), (self.water, "Wasser")):
            self.tabs.addTab(w, name)
            w.changed.connect(self.refresh_all)
        self.recipes.calculate.connect(self._calc_recipe)
        self.setCentralWidget(self.tabs)

        menu = self.menuBar().addMenu("&Datei")
        for text, slot in (("CSV &exportieren…", self.export_csv), ("CSV &importieren…", self.import_csv),
                           (None, None), ("Speicherort der Datenbank", self.show_db_path),
                           (None, None), ("&Beenden", self.close)):
            if text is None:
                menu.addSeparator()
            else:
                act = QAction(text, self)
                act.triggered.connect(slot)
                menu.addAction(act)
        about = QAction("Ü&ber", self)
        about.triggered.connect(lambda: QMessageBox.about(
            self, "Über", f"<b>Nährlösungsrechner</b> {__version__}<br>"
                          "Berechnung von Nährlösungen für Hydrokultur.<br>"
                          "Inspiriert von HydroBuddy (Daniel Fernández).<br><br>"
                          "Der Programmcode wurde mit KI erstellt (Claude von Anthropic), "
                          "Anforderungen und Praxistests stammen vom Menschen.<br>"
                          "Alle Ergebnisse ohne Gewähr – Etiketten prüfen, EC und pH nachmessen."))
        self.menuBar().addMenu("&Hilfe").addAction(about)
        self.restore_session()

    # --- Sitzung ------------------------------------------------------------
    def restore_session(self):
        st = self.db.load_state("session")
        if not st:
            return
        try:
            if st.get("geometry"):
                self.restoreGeometry(QByteArray.fromBase64(st["geometry"].encode()))
            self.calc.set_state(st.get("calc", {}))
            self.tabs.setCurrentIndex(st.get("tab", 0))
        except Exception:  # alter oder beschädigter Stand soll den Start nicht verhindern
            traceback.print_exc()

    def save_session(self):
        self.db.save_state("session", {
            "geometry": bytes(self.saveGeometry().toBase64()).decode(),
            "tab": self.tabs.currentIndex(),
            "calc": self.calc.get_state(),
        })

    def closeEvent(self, event):
        try:
            self.save_session()
        except Exception:
            traceback.print_exc()
        super().closeEvent(event)

    def refresh_all(self):
        for w in (self.calc, self.recipes, self.ferts, self.water):
            w.refresh()

    def _calc_recipe(self, rid: int):
        self.calc.open_recipe(rid)
        self.tabs.setCurrentWidget(self.calc)

    def export_csv(self):
        folder = QFileDialog.getExistingDirectory(self, "Ordner für den CSV-Export wählen")
        if folder:
            files = csv_io.export_all(self.db, folder)
            QMessageBox.information(self, "Export abgeschlossen",
                                    "Geschrieben:\n" + "\n".join(str(f) for f in files))

    def import_csv(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "CSV-Dateien importieren (Dünger, Wasser, Rezepte)", "", "CSV-Dateien (*.csv *.txt)")
        if not paths:
            return
        try:
            report = csv_io.import_files(self.db, paths)
        except Exception as e:  # Datei unlesbar oder unerwartetes Format
            QMessageBox.critical(self, "Import fehlgeschlagen", str(e))
            return
        self.refresh_all()
        QMessageBox.information(self, "Import abgeschlossen", report.text())

    def show_db_path(self):
        QMessageBox.information(self, "Datenbank", f"Die Daten liegen in:\n{Path(self.db.path).resolve()}")
