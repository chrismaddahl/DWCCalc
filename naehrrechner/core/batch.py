"""Ansatz: direkte Lösung oder Konzentrat (ein Tank, A/B oder A/B/C), Ausfällungsprüfung und EC-Schätzung."""
import math
from dataclasses import dataclass, field

from .elements import BY_KEY, IONS
from .models import Fertilizer
from .solver import Solution

DIRECT = "direkt"
CONCENTRATE = "konzentrat"


@dataclass
class BatchLine:
    fertilizer: Fertilizer
    tank: str             # "" beim direkten Ansatz oder ohne Aufteilung, sonst "A"/"B"/"C"
    grams: float
    ml: float | None      # nur bei flüssigen Düngern mit Dichte
    tank_conc: float      # g/L im Tank bzw. in der fertigen Lösung


@dataclass
class BatchPlan:
    mode: str
    volume_l: float                # Volumen fertige Lösung bzw. je Tank
    factor: int = 1
    n_tanks: int = 1               # 1 = ein Konzentrat, 2 = A/B, 3 = A/B/C
    lines: list[BatchLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    max_factor: float | None = None   # höchster Faktor, den die Löslichkeit zulässt
    risks: list["Risk"] = field(default_factory=list)

    @property
    def split(self) -> bool:
        return self.n_tanks > 1

    @property
    def tanks(self) -> list[str]:
        return sorted({ln.tank for ln in self.lines})

    @property
    def ml_per_liter(self) -> float:
        """mL je Tank pro Liter fertiger Lösung."""
        return 1000.0 / self.factor

    @property
    def tank_names(self) -> list[str]:
        return list("ABC"[:self.n_tanks]) if self.n_tanks > 1 else [""]

    @property
    def tank_label(self) -> str:
        """„Tank A und Tank B“, „Tank A, Tank B und Tank C“ oder „Konzentrat“."""
        names = [f"Tank {t}" for t in self.tank_names if t]
        if not names:
            return "Konzentrat"
        return ", ".join(names[:-1]) + " und " + names[-1]


def assign_tank(f: Fertilizer, n_tanks: int = 2) -> str:
    """Tank für einen Dünger.

    A/B: Calcium in A, Sulfat und Phosphat in B (sonst fällt Gips bzw. Calciumphosphat aus).
    A/B/C: zusätzlich Magnesium und Sulfat getrennt vom Phosphat in C (Magnesiumphosphat, Struvit).
    """
    if n_tanks < 2:
        return ""
    if f.tank in ("A", "B", "C"):
        return "B" if f.tank == "C" and n_tanks == 2 else f.tank
    c = {k: v for k, v in f.composition.items() if v > 0}
    rest = "B" if n_tanks == 2 else "C"
    if c.get("Ca"):
        return "A"
    if c.get("P"):
        return "B"
    if c.get("S") or (c.get("Mg") and n_tanks == 3):
        return rest
    if set(c) == {"Fe"}:
        return "A"
    if c and all(BY_KEY[k].micro or k in ("Na", "Cl") for k in c):
        return rest
    return "A"


# --- Ausfällung ---------------------------------------------------------------
@dataclass(frozen=True)
class Pair:
    a: str
    b: str
    product: str      # was ausfällt
    limit: float      # Ionenprodukt in (mol/L)², ab dem gewarnt wird
    strict: bool      # gehört grundsätzlich nicht in einen Tank


# Grobe Richtwerte, kein Löslichkeitsgleichgewicht: der pH-Wert im Tank ist unbekannt.
# In der fertigen Nährlösung liegen alle Produkte deutlich darunter.
PAIRS = (
    Pair("Ca", "S", "Gips (Calciumsulfat)", 5e-4, True),
    Pair("Ca", "P", "Calciumphosphat", 1e-5, True),
    Pair("Mg", "P", "Magnesiumphosphat", 2e-3, False),
)
# Mg/P bei saurem Phosphat (MKP, MAP) ohne Ammonium: erst ab diesem Ionenprodukt warnen
MG_P_ACID_LIMIT = 5e-2
# Kationen je Phosphat, ab der das Phosphat überwiegend als Hydrogenphosphat vorliegt (alkalisch)
BASIC_RATIO = 1.25


@dataclass
class Risk:
    tank: str
    pair: Pair
    ion_product: float
    safe_factor: float        # Faktor, bis zu dem das Produkt unter dem Richtwert bleibt
    ammonium: bool            # Ammonium im selben Tank begünstigt Struvit
    basic: bool               # Phosphat eher als Hydrogenphosphat (höherer pH)

    @property
    def level(self) -> str:
        return "hoch" if self.pair.strict or self.ammonium or self.basic else "mittel"


def phosphate_ratio(mol: dict[str, float]) -> float | None:
    """Kationen-Äquivalente je mol Phosphat nach Abzug der übrigen Anionen.

    Etwa 1 entspricht Dihydrogenphosphat (MKP, MAP, pH um 4,5), etwa 2 Hydrogenphosphat (pH um 9).
    """
    p = mol.get("P", 0.0)
    if p <= 0:
        return None
    cations = (mol.get("K", 0) + mol.get("Na", 0) + mol.get("NH4_N", 0)
               + 2 * mol.get("Mg", 0) + 2 * mol.get("Ca", 0))
    anions = mol.get("NO3_N", 0) + mol.get("Cl", 0) + 2 * mol.get("S", 0)
    return (cations - anions) / p


def tank_contents(plan: BatchPlan) -> dict[str, dict[str, float]]:
    """mg/L je Element in jedem Tank (bzw. in der fertigen Lösung beim direkten Ansatz)."""
    out: dict[str, dict[str, float]] = {}
    for ln in plan.lines:
        t = out.setdefault(ln.tank, {})
        for k, pct in ln.fertilizer.composition.items():
            t[k] = t.get(k, 0.0) + ln.tank_conc * pct * 10
    return out


def precipitation_risks(plan: BatchPlan) -> list[Risk]:
    risks = []
    for tank, mg in sorted(tank_contents(plan).items()):
        mol = {k: v / 1000 / IONS[k][0] for k, v in mg.items() if k in IONS}
        ratio = phosphate_ratio(mol)
        for pair in PAIRS:
            prod = mol.get(pair.a, 0.0) * mol.get(pair.b, 0.0)
            if prod <= pair.limit:
                continue
            ammonium = basic = False
            limit = pair.limit
            if pair.a == "Mg":
                ammonium = mol.get("NH4_N", 0) > 0
                basic = ratio is not None and ratio > BASIC_RATIO
                if not (ammonium or basic):
                    limit = MG_P_ACID_LIMIT
                    if prod <= limit:
                        continue
            safe = plan.factor * math.sqrt(limit / prod)
            risks.append(Risk(tank, pair, prod, safe, ammonium, basic))
    return risks


def _risk_text(r: Risk, n_tanks: int) -> str:
    where = f"Tank {r.tank}" if r.tank else "Konzentrat"
    a, b = BY_KEY[r.pair.a].label, BY_KEY[r.pair.b].label
    text = f"{where}: Ausfällungsgefahr {r.level} – {a} und {b} können {r.pair.product} bilden"
    if r.ammonium:
        text += ", mit Ammonium auch Struvit"
    if r.basic:
        text += " (Phosphat eher alkalisch, mehr Kalium je Phosphat als bei MKP)"
    tips = []
    if r.pair.strict:
        tips.append("A/B-Aufteilung wählen" if n_tanks < 2 else
                    "Tankzuordnung prüfen (ein Dünger enthält beides oder ist fest zugeordnet)")
    else:
        if n_tanks < 3:
            tips.append("A/B/C-Aufteilung wählen (Magnesium in Tank C)")
        if r.safe_factor >= 2:
            tips.append(f"Faktor auf etwa {r.safe_factor:.0f}× senken")
        tips.append("Tank ansäuern (pH 4–5)")
    return f"{text}. Abhilfe: " + " oder ".join(tips) + "."


def _line(f, dose, volume_l, conc):
    grams = dose * volume_l
    ml = grams / f.density if f.liquid and f.density else None
    return BatchLine(f, "", grams, ml, conc)


def plan_direct(sol: Solution, volume_l: float) -> BatchPlan:
    if volume_l <= 0:
        raise ValueError("Das Volumen muss größer als 0 sein.")
    plan = BatchPlan(DIRECT, volume_l)
    for f, x in zip(sol.fertilizers, sol.dose):
        if x > 0:
            plan.lines.append(_line(f, x, volume_l, x))
    _liquid_warnings(plan)
    return plan


def plan_concentrate(sol: Solution, factor: int, tank_volume_l: float, n_tanks: int = 2) -> BatchPlan:
    if factor < 1 or tank_volume_l <= 0:
        raise ValueError("Faktor und Tankvolumen müssen größer als 0 sein.")
    if n_tanks not in (1, 2, 3):
        raise ValueError("Es gibt 1, 2 oder 3 Tanks.")
    plan = BatchPlan(CONCENTRATE, tank_volume_l, factor, n_tanks)
    limits = []
    for f, x in zip(sol.fertilizers, sol.dose):
        if x <= 0:
            continue
        conc = x * factor
        ln = _line(f, conc, tank_volume_l, conc)
        ln.tank = assign_tank(f, n_tanks)
        plan.lines.append(ln)
        if f.solubility and not f.liquid:
            limits.append(f.solubility / x)
            if conc > f.solubility:
                plan.warnings.append(
                    f"{f.name}: {conc:.0f} g/L im Tank übersteigt die Löslichkeit "
                    f"({f.solubility:.0f} g/L). Faktor verringern.")
            elif conc > 0.8 * f.solubility:
                plan.warnings.append(f"{f.name}: nahe an der Löslichkeitsgrenze – warmes Wasser verwenden.")
    plan.max_factor = min(limits) if limits else None
    plan.lines.sort(key=lambda ln: (ln.tank, ln.fertilizer.name.lower()))
    plan.risks = precipitation_risks(plan)
    plan.warnings += [_risk_text(r, n_tanks) for r in plan.risks]
    _liquid_warnings(plan)
    return plan


def _liquid_warnings(plan: BatchPlan):
    for ln in plan.lines:
        if ln.fertilizer.liquid and not ln.fertilizer.density:
            plan.warnings.append(f"{ln.fertilizer.name}: keine Dichte hinterlegt, Menge in g statt mL.")


def estimate_ec(total: dict[str, float]) -> float:
    """Geschätzte Leitfähigkeit in mS/cm bei 25 °C.

    Summe der Ionenkonzentrationen × molare Grenzleitfähigkeit, korrigiert um die
    Ionenstärke (vereinfachter Kohlrausch-Ansatz). Spurenelemente werden vernachlässigt.
    """
    ideal = 0.0       # µS/cm
    ionic = 0.0       # mol/L
    for key, (molar_mass, charge, lam) in IONS.items():
        mmol = total.get(key, 0.0) / molar_mass
        ideal += mmol * lam
        ionic += 0.5 * (mmol / 1000) * charge ** 2
    factor = max(0.5, 1 - 0.9 * math.sqrt(ionic))
    return ideal * factor / 1000
