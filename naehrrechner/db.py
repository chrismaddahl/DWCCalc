"""SQLite-Datenbank für Dünger, Wasserprofile und Rezepte."""
import json
import sqlite3
from pathlib import Path

from .core.models import Fertilizer, Recipe, WaterProfile

SCHEMA = """
CREATE TABLE IF NOT EXISTS fertilizer (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    formula TEXT NOT NULL DEFAULT '',
    liquid INTEGER NOT NULL DEFAULT 0,
    density REAL,
    solubility REAL,
    tank TEXT NOT NULL DEFAULT 'auto',
    available INTEGER NOT NULL DEFAULT 1,
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS fertilizer_content (
    fertilizer_id INTEGER NOT NULL REFERENCES fertilizer(id) ON DELETE CASCADE,
    element TEXT NOT NULL,
    percent REAL NOT NULL,
    PRIMARY KEY (fertilizer_id, element)
);
CREATE TABLE IF NOT EXISTS water (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE IF NOT EXISTS water_value (
    water_id INTEGER NOT NULL REFERENCES water(id) ON DELETE CASCADE,
    element TEXT NOT NULL,
    mg_l REAL NOT NULL,
    PRIMARY KEY (water_id, element)
);
CREATE TABLE IF NOT EXISTS recipe (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS recipe_target (
    recipe_id INTEGER NOT NULL REFERENCES recipe(id) ON DELETE CASCADE,
    element TEXT NOT NULL,
    mg_l REAL NOT NULL,
    PRIMARY KEY (recipe_id, element)
);
CREATE TABLE IF NOT EXISTS recipe_fertilizer (
    recipe_id INTEGER NOT NULL REFERENCES recipe(id) ON DELETE CASCADE,
    fertilizer_id INTEGER NOT NULL REFERENCES fertilizer(id) ON DELETE CASCADE,
    PRIMARY KEY (recipe_id, fertilizer_id)
);
CREATE TABLE IF NOT EXISTS recipe_priority (
    recipe_id INTEGER NOT NULL REFERENCES recipe(id) ON DELETE CASCADE,
    element TEXT NOT NULL,
    level TEXT NOT NULL,
    PRIMARY KEY (recipe_id, element)
);
CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(path))
        self.con.execute("PRAGMA foreign_keys = ON")
        self.con.executescript(SCHEMA)
        self.con.execute("PRAGMA user_version = 1")
        self.con.commit()

    def close(self):
        self.con.close()

    # --- Programmzustand (letzte Sitzung) ----------------------------------
    def load_state(self, key: str) -> dict | None:
        row = self.con.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        try:
            return json.loads(row[0]) if row else None
        except ValueError:
            return None

    def save_state(self, key: str, value: dict):
        with self.con:
            self.con.execute("INSERT OR REPLACE INTO app_state VALUES (?, ?)", (key, json.dumps(value)))

    # --- Dünger -----------------------------------------------------------
    def fertilizers(self, only_available: bool = False) -> list[Fertilizer]:
        sql = "SELECT id, name, formula, liquid, density, solubility, tank, available, note FROM fertilizer"
        if only_available:
            sql += " WHERE available = 1"
        result = []
        for row in self.con.execute(sql + " ORDER BY name COLLATE NOCASE"):
            comp = dict(self.con.execute(
                "SELECT element, percent FROM fertilizer_content WHERE fertilizer_id = ?", (row[0],)))
            result.append(Fertilizer(id=row[0], name=row[1], formula=row[2], liquid=bool(row[3]),
                                     density=row[4], solubility=row[5], tank=row[6],
                                     available=bool(row[7]), note=row[8], composition=comp))
        return result

    def fertilizer_by_name(self, name: str) -> Fertilizer | None:
        return next((f for f in self.fertilizers() if f.name.lower() == name.strip().lower()), None)

    def save_fertilizer(self, f: Fertilizer) -> int:
        values = (f.name.strip(), f.formula, int(f.liquid), f.density, f.solubility, f.tank,
                  int(f.available), f.note)
        with self.con:
            if f.id is None:
                f.id = self.con.execute(
                    "INSERT INTO fertilizer (name, formula, liquid, density, solubility, tank, available, note)"
                    " VALUES (?,?,?,?,?,?,?,?)", values).lastrowid
            else:
                self.con.execute(
                    "UPDATE fertilizer SET name=?, formula=?, liquid=?, density=?, solubility=?, tank=?,"
                    " available=?, note=? WHERE id=?", values + (f.id,))
            self.con.execute("DELETE FROM fertilizer_content WHERE fertilizer_id = ?", (f.id,))
            self.con.executemany(
                "INSERT INTO fertilizer_content VALUES (?,?,?)",
                [(f.id, k, v) for k, v in f.composition.items() if v])
        return f.id

    def delete_fertilizer(self, fid: int):
        with self.con:
            self.con.execute("DELETE FROM fertilizer WHERE id = ?", (fid,))

    # --- Wasser -----------------------------------------------------------
    def waters(self) -> list[WaterProfile]:
        result = []
        for wid, name in self.con.execute("SELECT id, name FROM water ORDER BY name COLLATE NOCASE"):
            vals = dict(self.con.execute("SELECT element, mg_l FROM water_value WHERE water_id = ?", (wid,)))
            result.append(WaterProfile(name, vals, wid))
        return result

    def save_water(self, w: WaterProfile) -> int:
        with self.con:
            if w.id is None:
                w.id = self.con.execute("INSERT INTO water (name) VALUES (?)", (w.name.strip(),)).lastrowid
            else:
                self.con.execute("UPDATE water SET name = ? WHERE id = ?", (w.name.strip(), w.id))
            self.con.execute("DELETE FROM water_value WHERE water_id = ?", (w.id,))
            self.con.executemany("INSERT INTO water_value VALUES (?,?,?)",
                                 [(w.id, k, v) for k, v in w.values.items() if v])
        return w.id

    def delete_water(self, wid: int):
        with self.con:
            self.con.execute("DELETE FROM water WHERE id = ?", (wid,))

    # --- Rezepte ----------------------------------------------------------
    def recipes(self) -> list[Recipe]:
        result = []
        for rid, name, desc in self.con.execute(
                "SELECT id, name, description FROM recipe ORDER BY name COLLATE NOCASE"):
            targets = dict(self.con.execute("SELECT element, mg_l FROM recipe_target WHERE recipe_id = ?", (rid,)))
            fids = [r[0] for r in self.con.execute(
                "SELECT fertilizer_id FROM recipe_fertilizer WHERE recipe_id = ?", (rid,))]
            prio = dict(self.con.execute("SELECT element, level FROM recipe_priority WHERE recipe_id = ?", (rid,)))
            result.append(Recipe(name, targets, desc, fids, prio, rid))
        return result

    def save_recipe(self, r: Recipe) -> int:
        with self.con:
            if r.id is None:
                r.id = self.con.execute("INSERT INTO recipe (name, description) VALUES (?, ?)",
                                        (r.name.strip(), r.description)).lastrowid
            else:
                self.con.execute("UPDATE recipe SET name = ?, description = ? WHERE id = ?",
                                 (r.name.strip(), r.description, r.id))
            self.con.execute("DELETE FROM recipe_target WHERE recipe_id = ?", (r.id,))
            self.con.executemany("INSERT INTO recipe_target VALUES (?,?,?)",
                                 [(r.id, k, v) for k, v in r.targets.items() if v is not None])
            self.con.execute("DELETE FROM recipe_fertilizer WHERE recipe_id = ?", (r.id,))
            self.con.executemany("INSERT INTO recipe_fertilizer VALUES (?,?)",
                                 [(r.id, fid) for fid in dict.fromkeys(r.fertilizer_ids)])
            self.con.execute("DELETE FROM recipe_priority WHERE recipe_id = ?", (r.id,))
            self.con.executemany("INSERT INTO recipe_priority VALUES (?,?,?)",
                                 [(r.id, k, v) for k, v in r.priorities.items() if v != "normal"])
        return r.id

    def delete_recipe(self, rid: int):
        with self.con:
            self.con.execute("DELETE FROM recipe WHERE id = ?", (rid,))
