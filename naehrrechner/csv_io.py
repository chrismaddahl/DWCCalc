"""CSV-Export und -Import.

Export: Semikolon als Trennzeichen, Komma als Dezimalzeichen, UTF-8 mit BOM –
so öffnet ein deutsches Excel die Dateien direkt richtig.
Import: Trennzeichen (; , Tab) und Dezimalzeichen (Komma oder Punkt) werden erkannt.
Element-Spalten dürfen auch in Oxidform angegeben werden (z. B. "P2O5", "K2O").
Vorhandene Einträge mit gleichem Namen werden überschrieben.
"""
import csv
from dataclasses import dataclass, field
from pathlib import Path

from .core.elements import ELEMENTS, NUTRIENTS, lookup_column
from .core.models import Fertilizer, Recipe, WaterProfile
from .core.numbers import format_plain, parse_number
from .core.solver import PRIORITY_NAMES
from .db import Database

FERTILIZER_FILE = "duenger.csv"
WATER_FILE = "wasser.csv"
RECIPE_FILE = "rezepte.csv"

KIND_FERTILIZER, KIND_WATER, KIND_RECIPE = "Dünger", "Wasserprofile", "Rezepte"


@dataclass
class ImportReport:
    counts: dict[str, int] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def text(self) -> str:
        lines = [f"{kind}: {n} importiert" for kind, n in self.counts.items()]
        if self.problems:
            lines += ["", "Hinweise:"] + [f"• {p}" for p in self.problems]
        return "\n".join(lines) or "Nichts importiert."


def _writer(path: Path):
    fh = open(path, "w", newline="", encoding="utf-8-sig")
    return fh, csv.writer(fh, delimiter=";")


def _bool_text(b: bool) -> str:
    return "ja" if b else "nein"


def export_all(db: Database, folder: str | Path) -> list[Path]:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)

    fh, w = _writer(folder / FERTILIZER_FILE)
    with fh:
        w.writerow(["Name", "Formel", "Typ", "Dichte [g/mL]", "Löslichkeit [g/L]", "Tank", "Vorhanden", "Notiz"]
                   + [f"{e.key} [%]" for e in NUTRIENTS])
        for f in db.fertilizers():
            w.writerow([f.name, f.formula, "flüssig" if f.liquid else "fest", format_plain(f.density),
                        format_plain(f.solubility), f.tank, _bool_text(f.available), f.note]
                       + [format_plain(f.composition.get(e.key)) for e in NUTRIENTS])

    fh, w = _writer(folder / WATER_FILE)
    with fh:
        w.writerow(["Name"] + [f"{e.key} [mg/L]" for e in ELEMENTS])
        for wp in db.waters():
            w.writerow([wp.name] + [format_plain(wp.values.get(e.key)) for e in ELEMENTS])

    names = {f.id: f.name for f in db.fertilizers()}
    fh, w = _writer(folder / RECIPE_FILE)
    with fh:
        w.writerow(["Name", "Beschreibung"] + [f"{e.key} [mg/L]" for e in NUTRIENTS] + ["Dünger", "Priorität"])
        for r in db.recipes():
            w.writerow([r.name, r.description] + [format_plain(r.targets.get(e.key)) for e in NUTRIENTS]
                       + [" | ".join(names[i] for i in r.fertilizer_ids if i in names),
                          " | ".join(f"{k}: {v}" for k, v in r.priorities.items())])
    return [folder / FERTILIZER_FILE, folder / WATER_FILE, folder / RECIPE_FILE]


def _read_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    first = text.splitlines()[0] if text else ""
    delimiter = max(";,\t", key=first.count)
    rows = [r for r in csv.reader(text.splitlines(), delimiter=delimiter) if any(c.strip() for c in r)]
    if not rows:
        return [], []
    return [h.strip() for h in rows[0]], rows[1:]


def detect_kind(path: Path, header: list[str]) -> str:
    name = path.name.lower()
    low = [h.split("[")[0].strip().lower() for h in header]
    if "rezept" in name or "beschreibung" in low or "dünger" in low or "duenger" in low:
        return KIND_RECIPE
    if "dünger" in name or "duenger" in name or {"formel", "typ", "löslichkeit", "dichte"} & set(low):
        return KIND_FERTILIZER
    return KIND_WATER


def _num(cell: str, where: str, report: ImportReport) -> float | None:
    try:
        return parse_number(cell)
    except ValueError:
        report.problems.append(f"{where}: '{cell}' ist keine Zahl und wurde ignoriert.")
        return None


def _parse_row(header, row, report, where):
    cells, values = {}, {}
    for h, cell in zip(header, row):
        col = lookup_column(h)
        if col:
            v = _num(cell, f"{where}, Spalte {h}", report)
            if v is not None:
                key, factor = col
                values[key] = values.get(key, 0.0) + v * factor
        else:
            cells[h.split("[")[0].strip().lower()] = cell.strip()
    return cells, values


def _parse_priorities(text: str, where: str, report: ImportReport) -> dict[str, str]:
    """Liest "Ca: hoch | NO3_N: niedrig"."""
    out = {}
    for part in filter(None, (p.strip() for p in text.split("|"))):
        name, _, level = part.partition(":")
        col = lookup_column(name)
        level = level.strip().lower()
        if col and level in PRIORITY_NAMES:
            if level != "normal":
                out[col[0]] = level
        else:
            report.problems.append(f"{where}: Priorität '{part}' nicht erkannt.")
    return out


def import_files(db: Database, paths: list[str | Path]) -> ImportReport:
    report = ImportReport()
    order = {KIND_FERTILIZER: 0, KIND_WATER: 1, KIND_RECIPE: 2}
    files = []
    for p in map(Path, paths):
        header, rows = _read_rows(p)
        if not header:
            report.problems.append(f"{p.name}: Datei ist leer.")
            continue
        files.append((order[detect_kind(p, header)], p, header, rows))
    files.sort(key=lambda t: t[0])

    for _, p, header, rows in files:
        kind = detect_kind(p, header)
        n = 0
        for i, row in enumerate(rows, start=2):
            where = f"{p.name} Zeile {i}"
            cells, values = _parse_row(header, row, report, where)
            name = cells.get("name", "")
            if not name:
                report.problems.append(f"{where}: kein Name, übersprungen.")
                continue
            if kind == KIND_FERTILIZER:
                old = db.fertilizer_by_name(name)
                values = {k: v for k, v in values.items() if k in {e.key for e in NUTRIENTS}}
                f = Fertilizer(
                    name=name, composition=values, formula=cells.get("formel", ""),
                    liquid=cells.get("typ", "").lower().startswith(("fl", "liq")),
                    density=_num(cells.get("dichte", ""), where, report),
                    solubility=_num(cells.get("löslichkeit", cells.get("loeslichkeit", "")), where, report),
                    tank=cells.get("tank", "auto").upper() if cells.get("tank", "").upper() in ("A", "B", "C") else "auto",
                    available=cells.get("vorhanden", "ja").lower() not in ("nein", "n", "0", "no", "false"),
                    note=cells.get("notiz", ""), id=old.id if old else None)
                if sum(values.values()) > 100.5:
                    report.problems.append(f"{where}: Gehalte von '{name}' ergeben mehr als 100 %.")
                db.save_fertilizer(f)
            elif kind == KIND_WATER:
                old = next((w for w in db.waters() if w.name.lower() == name.lower()), None)
                db.save_water(WaterProfile(name, values, old.id if old else None))
            else:
                old = next((r for r in db.recipes() if r.name.lower() == name.lower()), None)
                fids = []
                for fname in filter(None, (s.strip() for s in cells.get("dünger", cells.get("duenger", "")).split("|"))):
                    f = db.fertilizer_by_name(fname)
                    if f:
                        fids.append(f.id)
                    else:
                        report.problems.append(f"{where}: Dünger '{fname}' nicht in der Datenbank.")
                prio = _parse_priorities(cells.get("priorität", cells.get("prioritaet", "")), where, report)
                db.save_recipe(Recipe(name, values, cells.get("beschreibung", ""), fids, prio,
                                      old.id if old else None))
            n += 1
        report.counts[kind] = report.counts.get(kind, 0) + n
    return report
