import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from naehrrechner.ui.widgets import NumberEdit


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("typed,value,shown", [("1,5", 1.5, "1,5"), ("1.5", 1.5, "1,5"),
                                               ("0.05", 0.05, "0,05"), ("200", 200.0, "200")])
def test_number_edit_accepts_comma_and_point(app, typed, value, shown):
    e = NumberEdit()
    QTest.keyClicks(e, typed)
    assert e.value() == value
    e.editingFinished.emit()
    assert e.text() == shown


def test_number_edit_rejects_letters(app):
    e = NumberEdit()
    QTest.keyClicks(e, "1a,2b")
    assert e.value() == 1.2


def test_session_restored_after_restart(app, tmp_path):
    from pathlib import Path

    from naehrrechner import csv_io
    from naehrrechner.core.models import WaterProfile
    from naehrrechner.db import Database
    from naehrrechner.ui.main_window import MainWindow

    ex = Path(__file__).parent.parent / "beispiele"
    path = tmp_path / "test.db"
    db = Database(path)
    csv_io.import_files(db, [ex / "duenger_beispiel.csv", ex / "rezepte_beispiel.csv"])
    wid = db.save_water(WaterProfile("Leitung", {"Ca": 40}))
    rid = db.recipes()[0].id

    w = MainWindow(db)
    c = w.calc
    w._calc_recipe(rid)
    c.water_box.setCurrentIndex(c.water_box.findData(wid))
    c.auto.setChecked(True)
    c.conc.setChecked(True)
    c.factor.setValue(150)
    c.targets.set_values({**db.recipes()[0].targets, "K": 280})
    c.calculate()
    c.result_tabs.setCurrentIndex(1)
    names = [f.name for f in c.solution.fertilizers]
    w.close()
    db.close()

    db2 = Database(path)
    w2 = MainWindow(db2)
    c2 = w2.calc
    assert c2.recipe_box.currentData() == rid
    assert c2.water_box.currentData() == wid
    assert c2.auto.isChecked() and c2.conc.isChecked()
    assert c2.factor.value() == 150
    assert c2.targets.values()["K"] == 280          # geänderte Zielwerte bleiben erhalten
    assert c2.solution is not None and [f.name for f in c2.solution.fertilizers] == names
    assert c2.plan.factor == 150
    assert c2.result_tabs.currentIndex() == 1
    w2.close()
    db2.close()


def test_start_without_session(app):
    from naehrrechner.db import Database
    from naehrrechner.ui.main_window import MainWindow

    w = MainWindow(Database(":memory:"))
    assert w.calc.solution is None


def test_contrib_shows_target_without_source(app):
    from fall_ca import FERTS, TARGETS
    from naehrrechner.core.solver import solve_auto
    from naehrrechner.db import Database
    from naehrrechner.ui.main_window import MainWindow

    w = MainWindow(Database(":memory:"))
    c = w.calc
    c.solutions = solve_auto(TARGETS, {}, FERTS)
    c.solution = c.solutions[0]
    c._replan()
    headers = [c.contrib.horizontalHeaderItem(i).text() for i in range(c.contrib.columnCount())]
    assert "Ca" in headers
    col = headers.index("Ca")
    last = c.contrib.rowCount() - 1
    assert all(c.contrib.item(r, col).text() == "" for r in range(last))
    assert c.contrib.item(last, col).text() == "–"
    c.contrib_unit.setCurrentIndex(1)          # Prozentanzeige darf nicht durch 0 teilen
    assert c.contrib.item(last, col).text() == "–"


def test_priorities_in_calc_tab_and_session(app, tmp_path):
    from naehrrechner.core.models import Recipe
    from naehrrechner.db import Database
    from naehrrechner.ui.main_window import MainWindow

    path = tmp_path / "p.db"
    db = Database(path)
    rid = db.save_recipe(Recipe("R", {"Ca": 70, "K": 100}, priorities={"Ca": "hoch"}))
    w = MainWindow(db)
    w._calc_recipe(rid)
    assert w.calc.targets.priorities() == {"Ca": "hoch"}
    keys = [e.key for e in w.calc.targets.elements]
    w.calc.targets.prio_boxes[keys.index("K")].setCurrentIndex(2)   # niedrig
    assert w.calc.targets.priorities() == {"Ca": "hoch", "K": "niedrig"}
    w.close()
    db.close()
    db2 = Database(path)
    w2 = MainWindow(db2)
    assert w2.calc.targets.priorities() == {"Ca": "hoch", "K": "niedrig"}
    w2.close()
    db2.close()


def test_fertilizer_table_shows_density(app):
    from naehrrechner.core.models import Fertilizer
    from naehrrechner.db import Database
    from naehrrechner.ui.main_window import FertilizerTab

    db = Database(":memory:")
    db.save_fertilizer(Fertilizer("A fest", {"K": 40}))
    db.save_fertilizer(Fertilizer("B flüssig", {"K": 10}, liquid=True, density=1.25))
    db.save_fertilizer(Fertilizer("C flüssig ohne", {"K": 10}, liquid=True))
    tab = FertilizerTab(db)
    t = tab.table
    headers = [t.horizontalHeaderItem(i).text() for i in range(t.columnCount())]
    col = headers.index("Dichte [g/mL]")
    assert [t.item(r, col).text() for r in range(3)] == ["", "1,25", "fehlt"]
    assert t.item(0, headers.index("K %")).text() == "40"


def _calc_with_variants(app):
    from pathlib import Path

    from naehrrechner import csv_io
    from naehrrechner.db import Database
    from naehrrechner.ui.main_window import MainWindow

    ex = Path(__file__).parent.parent / "beispiele"
    db = Database(":memory:")
    csv_io.import_files(db, [ex / "duenger_beispiel.csv", ex / "rezepte_beispiel.csv"])
    w = MainWindow(db)
    w._calc_recipe(db.recipes()[0].id)
    w.calc.auto.setChecked(True)
    w.calc.calculate()
    return w


def _headers(t):
    return [t.horizontalHeaderItem(i).text() for i in range(t.columnCount())]


def test_variants_side_by_side(app):
    w = _calc_with_variants(app)
    c = w.calc
    n = len(c.solutions)
    assert n >= 2 and len(c.plans) == n
    assert _headers(c.weigh)[2:2 + n] == [f"Variante {i + 1}" for i in range(n)]
    names = {c.weigh.item(r, 1).text() for r in range(c.weigh.rowCount())}
    used = {f.name for s in c.solutions for f in s.fertilizers}
    assert names == used                            # Vereinigung aller Varianten
    h = _headers(c.compare)
    assert h[:3] == ["Nährstoff", "Ziel", "aus Wasser"]
    assert "V2 Gesamt" in h and "V2 Abweichung" in h
    last = c.compare.rowCount() - 1
    assert c.compare.item(last, 0).text() == "mittlere Abweichung"
    # Klick auf den Spaltenkopf wählt die Variante für die Details
    c._header_clicked(c.weigh, 3)
    assert c.variant.currentIndex() == 1 and c.solution is c.solutions[1]


def test_print_asks_for_variant(app, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    w = _calc_with_variants(app)
    c = w.calc
    monkeypatch.setattr(QInputDialog, "getItem",
                        staticmethod(lambda *a, **k: (c.variant.itemText(1), True)))
    assert c._choose_variant("Merkzettel drucken") == 1
    html = c._sheet_html(1)
    assert "Variante 2" in html
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("", False)))
    assert c._choose_variant("Merkzettel drucken") is None


def test_print_preview_does_not_crash(app, monkeypatch):
    """Die Vorschau muss zeichnen können, nachdem Python aufgeräumt hat."""
    import gc
    from PySide6.QtPrintSupport import QPrintPreviewDialog
    from PySide6.QtWidgets import QInputDialog
    w = _calc_with_variants(app)
    c = w.calc
    monkeypatch.setattr(QInputDialog, "getItem",
                        staticmethod(lambda *a, **k: (c.variant.itemText(1), True)))
    painted = []

    def fake_exec(dlg):
        dlg.paintRequested.connect(lambda p: painted.append(p))
        gc.collect()
        dlg.show()
        for _ in range(20):
            app.processEvents()
        dlg.close()
    monkeypatch.setattr(QPrintPreviewDialog, "exec", fake_exec)
    c.print_sheet()
    assert painted


def test_single_variant_layout(app):
    w = _calc_with_variants(app)
    c = w.calc
    c.manual.setChecked(True)
    c._check_all(True)
    c.calculate()
    assert len(c.solutions) == 1
    assert _headers(c.weigh)[2] == "Menge"
    assert _headers(c.compare)[3:] == ["aus Düngern", "Gesamt", "Abweichung"]
    assert c._choose_variant("x") == 0


def test_three_tanks_ui(app):
    w = _calc_with_variants(app)
    c = w.calc
    c.conc.setChecked(True)
    c.split.setCurrentIndex(c.split.findData(3))
    assert all(p.n_tanks == 3 for p in c.plans)
    tanks = {c.weigh.item(r, 0).text() for r in range(c.weigh.rowCount())}
    assert "C" in tanks and not c.weigh.isColumnHidden(0)
    assert "Tank C" in c.dosing.text()
    html = c._sheet_html(0)
    assert "Tank C" in html and "Tank A, Tank B und Tank C" in html
    assert c.get_state()["tanks"] == 3
    c.set_state({"split": False, "concentrate": True})      # Stand aus älterer Version
    assert c.split.currentData() == 1
