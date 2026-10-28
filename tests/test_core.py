from pathlib import Path

import pytest

from naehrrechner import csv_io
from naehrrechner.core.batch import (BatchLine, BatchPlan, CONCENTRATE, assign_tank, estimate_ec,
                                     plan_concentrate, plan_direct, precipitation_risks)
from naehrrechner.core.models import Fertilizer, VE_WATER
from naehrrechner.core.numbers import format_number, parse_number
from naehrrechner.core.solver import solve_auto, solve_manual
from naehrrechner.db import Database

EXAMPLES = Path(__file__).parent.parent / "beispiele"


@pytest.fixture
def db():
    d = Database(":memory:")
    csv_io.import_files(d, [EXAMPLES / "duenger_beispiel.csv", EXAMPLES / "rezepte_beispiel.csv"])
    return d


@pytest.mark.parametrize("text,value", [
    ("1,5", 1.5), ("1.5", 1.5), ("0,05", 0.05), (",5", 0.5), ("1.234,5", 1234.5),
    ("1,234.5", 1234.5), (" 12 ", 12.0), ("", None), ("-3,2", -3.2),
])
def test_parse_number(text, value):
    assert parse_number(text) == value


@pytest.mark.parametrize("text", ["abc", "1,2,3", "1..2", "nan", "inf"])
def test_parse_number_invalid(text):
    with pytest.raises(ValueError):
        parse_number(text)


def test_format_number():
    assert format_number(1234.5678, 2) == "1234,57"
    assert format_number(0.5000, 3, trim=True) == "0,5"
    assert format_number(-0.0001, 2) == "0,00"


def test_import(db):
    ferts = db.fertilizers()
    assert len(ferts) == 12
    cn = db.fertilizer_by_name("Calciumnitrat (technisch)")
    assert cn.composition["Ca"] == 19 and cn.composition["NH4_N"] == 1.1
    r = db.recipes()[0]
    assert r.targets["Mo"] == 0.05 and "Na" not in r.targets


def test_oxide_columns(tmp_path):
    p = tmp_path / "duenger.csv"
    p.write_text("Name,Typ,NO3-N,P2O5,K2O\nTestdünger,fest,10,\"20,0\",30.0\n", encoding="utf-8")
    d = Database(":memory:")
    rep = csv_io.import_files(d, [p])
    f = d.fertilizer_by_name("Testdünger")
    assert rep.counts == {"Dünger": 1}
    assert f.composition["P"] == pytest.approx(20 * 0.4364)
    assert f.composition["K"] == pytest.approx(30 * 0.8301)


def test_export_roundtrip(db, tmp_path):
    csv_io.export_all(db, tmp_path)
    d2 = Database(":memory:")
    csv_io.import_files(d2, sorted(tmp_path.glob("*.csv")))
    assert [f.composition for f in d2.fertilizers()] == [f.composition for f in db.fertilizers()]
    assert d2.recipes()[0].targets == db.recipes()[0].targets


def test_manual_solution_hits_targets(db):
    r = db.recipes()[0]
    sol = solve_manual(r.targets, VE_WATER, db.fertilizers())
    for k in ("NO3_N", "K", "Ca", "Mg", "P", "Fe", "B", "Mo"):
        assert abs(sol.deviation(k)) < 12, (k, sol.deviation(k))
    assert sol.score < 10


def test_water_is_subtracted(db):
    # ohne NH4-Ziel, sonst erzwingt der einzige NH4-Lieferant (Calciumnitrat) zusätzliches Ca
    targets = {k: v for k, v in db.recipes()[0].targets.items() if k != "NH4_N"}
    hard = {"Ca": 80.0, "Mg": 15.0}
    soft = solve_manual(targets, VE_WATER, db.fertilizers())
    tap = solve_manual(targets, hard, db.fertilizers())
    assert tap.supplied["Ca"] < soft.supplied["Ca"] - 40
    assert tap.total["Ca"] == pytest.approx(soft.total["Ca"], rel=0.15)


def test_auto_selection(db):
    r = db.recipes()[0]
    sols = solve_auto(r.targets, VE_WATER, db.fertilizers(), max_count=10)
    best = sols[0]
    assert best.score < 12
    assert len(best.fertilizers) <= 10
    assert len(sols) >= 2
    few = solve_auto(r.targets, VE_WATER, db.fertilizers(), max_count=4)[0]
    assert len(few.fertilizers) <= 4


def test_concentrate_split(db):
    r = db.recipes()[0]
    sol = solve_manual(r.targets, VE_WATER, db.fertilizers())
    plan = plan_concentrate(sol, 100, 10, 2)
    tank = {ln.fertilizer.name: ln.tank for ln in plan.lines}
    assert tank["Calciumnitrat (technisch)"] == "A"
    assert tank["Magnesiumsulfat"] == "B"
    assert tank["Monokaliumphosphat"] == "B"
    assert plan.ml_per_liter == 10
    direct = plan_direct(sol, 10)
    cn = next(ln for ln in direct.lines if ln.fertilizer.name.startswith("Calcium"))
    cn_c = next(ln for ln in plan.lines if ln.fertilizer.name.startswith("Calcium"))
    assert cn_c.grams == pytest.approx(cn.grams * 100)


def test_concentrate_warnings(db):
    r = db.recipes()[0]
    sol = solve_manual(r.targets, VE_WATER, db.fertilizers())
    plan = plan_concentrate(sol, 800, 10, 1)
    text = " ".join(plan.warnings)
    assert "Gips" in text and "A/B-Aufteilung wählen" in text
    assert "übersteigt die Löslichkeit" in text   # Kaliumnitrat bei 800x
    assert plan.max_factor is not None and plan.max_factor < 800
    assert not plan_concentrate(sol, 100, 10, 2).warnings   # MKP und Bittersalz bei 100x: unkritisch


def test_liquid_ml():
    f = Fertilizer("Flüssig", {"K": 10}, liquid=True, density=1.25)
    sol = solve_manual({"K": 100}, {}, [f])
    plan = plan_direct(sol, 10)
    assert plan.lines[0].ml == pytest.approx(plan.lines[0].grams / 1.25)


def test_assign_tank():
    assert assign_tank(Fertilizer("Fe", {"Fe": 11})) == "A"
    assert assign_tank(Fertilizer("B", {"B": 17})) == "B"
    assert assign_tank(Fertilizer("x", {"Ca": 19}, tank="B")) == "B"
    mg = Fertilizer("Bittersalz", {"Mg": 9.6, "S": 13})
    assert assign_tank(mg, 2) == "B" and assign_tank(mg, 3) == "C"
    assert assign_tank(Fertilizer("MKP", {"K": 28, "P": 22.7}), 3) == "B"
    assert assign_tank(Fertilizer("Kieserit", {"Mg": 15}), 3) == "C"
    assert assign_tank(Fertilizer("x", {"K": 1}, tank="C"), 2) == "B"
    assert assign_tank(mg, 1) == ""


def _tank_plan(grams, n_tanks, factor=100):
    plan = BatchPlan(CONCENTRATE, 0.5, factor, n_tanks)
    for f, g in grams:
        plan.lines.append(BatchLine(f, assign_tank(f, n_tanks), g, None, g / 0.5))
    return plan


def test_precipitation_reported_case():
    """Gemeldeter Fall: Tank B mit Bittersalz, Vitaphos-K und Hakaphos ist ausgefallen."""
    epso = Fertilizer("EPSO Top", {"Mg": 9.6, "S": 13})
    vita = Fertilizer("Vitaphos-K", {"K": 40.67, "NO3_N": 4, "P": 13.516})
    haka = Fertilizer("Hakaphos", {"NO3_N": 13, "NH4_N": 11, "P": 2.616, "K": 9.96, "Mg": 1.2})
    calc = Fertilizer("Calcinit", {"Ca": 18.59, "NH4_N": 1.1, "NO3_N": 14.4})
    grams = [(epso, 15.3), (vita, 12.7), (haka, 2.39), (calc, 21.6)]
    risks = precipitation_risks(_tank_plan(grams, 2))
    assert [(r.tank, r.pair.a, r.pair.b, r.level) for r in risks] == [("B", "Mg", "P", "hoch")]
    assert risks[0].basic and risks[0].ammonium
    assert 20 < risks[0].safe_factor < 60
    assert precipitation_risks(_tank_plan(grams, 3)) == []
    one = {(r.pair.a, r.pair.b) for r in precipitation_risks(_tank_plan(grams, 1))}
    assert {("Ca", "S"), ("Ca", "P"), ("Mg", "P")} <= one


def test_precipitation_acid_mkp():
    epso = Fertilizer("Bittersalz", {"Mg": 9.6, "S": 13})
    mkp = Fertilizer("MKP", {"K": 28.22, "P": 22.69})
    assert precipitation_risks(_tank_plan([(epso, 25.5), (mkp, 11)], 2)) == []
    strong = precipitation_risks(_tank_plan([(epso, 76), (mkp, 33)], 2, factor=300))
    assert [r.level for r in strong] == ["mittel"]
    assert 100 < strong[0].safe_factor < 300


def test_plan_three_tanks(db):
    r = db.recipes()[0]
    sol = solve_manual(r.targets, VE_WATER, db.fertilizers())
    plan = plan_concentrate(sol, 100, 10, 3)
    assert plan.tank_label == "Tank A, Tank B und Tank C"
    tank = {ln.fertilizer.name: ln.tank for ln in plan.lines}
    assert tank["Magnesiumsulfat"] == "C" and tank["Monokaliumphosphat"] == "B"
    assert plan_concentrate(sol, 100, 10, 2).tank_label == "Tank A und Tank B"


def test_ec_plausible(db):
    # Hoagland-ähnliche Lösung liegt bei etwa 2 mS/cm
    r = db.recipes()[0]
    sol = solve_manual(r.targets, VE_WATER, db.fertilizers())
    ec = estimate_ec(sol.total)
    assert 1.6 < ec < 2.8
    assert estimate_ec({}) == 0


def test_contributions_add_up(db):
    r = db.recipes()[0]
    water = {"Ca": 40.0, "Mg": 8.0}
    sol = solve_manual(r.targets, water, db.fertilizers())
    rows = sol.contributions()
    assert rows[-1] == ("Wasser", water)
    for k in r.targets:
        assert sum(v.get(k, 0) for _, v in rows) == pytest.approx(sol.total[k])
    names = [n for n, _ in rows[:-1]]
    assert "Monokaliumphosphat" in names
    p_sources = [n for n, v in rows if v.get("P")]
    assert p_sources == ["Monokaliumphosphat"]


def test_shortfall_explains_why_calcium_is_missing():
    # gemeldeter Fall: Ca-Dünger würden NO3 bzw. Mn weit überdosieren
    from fall_ca import FERTS, TARGETS
    sol = solve_auto(TARGETS, VE_WATER, FERTS)[0]
    ca = [w for w in sol.warnings if w.startswith("Ca ")]
    assert len(ca) == 1
    assert "YaraTera CALCINIT (N (NO₃)" in ca[0] and "Wuxal Calcium (Mn" in ca[0]
    assert not any("Kein" in w for w in sol.warnings)


def test_shortfall_without_source():
    from fall_ca import FERTS, TARGETS
    sol = solve_manual(TARGETS, VE_WATER, [f for f in FERTS if "Ca" not in f.composition])
    assert "Ca: Kein ausgewählter Dünger enthält dieses Element." in sol.warnings


def test_priority_brings_in_calcium():
    from fall_ca import FERTS, TARGETS
    normal = solve_auto(TARGETS, VE_WATER, FERTS)[0]
    hoch = solve_auto(TARGETS, VE_WATER, FERTS, priorities={"Ca": "hoch"})[0]
    beide = solve_auto(TARGETS, VE_WATER, FERTS, priorities={"Ca": "hoch", "NO3_N": "niedrig"})[0]
    assert normal.total["Ca"] < 1
    assert hoch.total["Ca"] > 50
    assert abs(beide.deviation("Ca")) < 2
    assert beide.total["NO3_N"] > 40            # der Preis dafür: mehr Nitrat
    manual = solve_manual(TARGETS, VE_WATER, FERTS, priorities={"Ca": "hoch", "NO3_N": "niedrig"})
    assert abs(manual.deviation("Ca")) < 5


def test_priorities_saved_and_exported(tmp_path):
    from naehrrechner.core.models import Recipe
    d = Database(":memory:")
    d.save_recipe(Recipe("R", {"Ca": 70, "NO3_N": 10}, priorities={"Ca": "hoch", "NO3_N": "niedrig"}))
    assert d.recipes()[0].priorities == {"Ca": "hoch", "NO3_N": "niedrig"}
    csv_io.export_all(d, tmp_path)
    d2 = Database(":memory:")
    rep = csv_io.import_files(d2, [tmp_path / "rezepte.csv"])
    assert d2.recipes()[0].priorities == {"Ca": "hoch", "NO3_N": "niedrig"}
    assert not rep.problems


def test_priority_import_tolerant(tmp_path):
    p = tmp_path / "rezepte.csv"
    p.write_text("Name;Beschreibung;Ca;N (NO₃);Priorität\nR;;70;10;Ca: Hoch | NO3-N: niedrig | X: egal\n",
                 encoding="utf-8")
    d = Database(":memory:")
    rep = csv_io.import_files(d, [p])
    assert d.recipes()[0].priorities == {"Ca": "hoch", "NO3_N": "niedrig"}
    assert len(rep.problems) == 1 and "X: egal" in rep.problems[0]


def test_shortfall_reason_respects_priorities():
    from fall_ca import FERTS, TARGETS
    sol = solve_auto(TARGETS, VE_WATER, FERTS, priorities={"Ca": "hoch", "NO3_N": "niedrig"})[0]
    nh4 = next(w for w in sol.warnings if w.startswith("N (NH₄)"))
    assert "Hakaphos Soft Elite 24-6-12(+2) (Cu" in nh4
