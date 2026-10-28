"""Berechnung der Düngermengen.

Alle Dosen werden in g Dünger pro Liter fertiger Nährlösung gerechnet.
Matrix A: Elementzeilen × Düngerspalten, Eintrag = mg Element je g Dünger.
Gesucht ist x >= 0, sodass A·x möglichst nahe an (Ziel − Wasser) liegt.
Abweichungen werden relativ zum Zielwert gewichtet, damit 10 % zu wenig Molybdän
genauso zählt wie 10 % zu wenig Stickstoff.
"""
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp, nnls

from .elements import BY_KEY, ELEMENT_KEYS, NUTRIENT_KEYS, weight_floor
from .models import Fertilizer, WaterProfile
from .numbers import format_number


class CalculationError(Exception):
    pass


@dataclass
class Solution:
    fertilizers: list[Fertilizer]
    dose: list[float]                    # g/L fertige Lösung, gleiche Reihenfolge wie fertilizers
    targets: dict[str, float]
    water: dict[str, float]
    supplied: dict[str, float]           # mg/L aus Düngern
    total: dict[str, float]              # mg/L inkl. Wasser
    score: float                         # mittlere relative Abweichung in %
    warnings: list[str] = field(default_factory=list)

    def contributions(self) -> list[tuple[str, dict[str, float]]]:
        """mg/L je Element nach Herkunft: eine Zeile je verwendetem Dünger, zuletzt das Wasser."""
        rows = [(f.name, {k: pct * 10.0 * x for k, pct in f.composition.items() if pct})
                for f, x in zip(self.fertilizers, self.dose) if x > 0]
        rows.append(("Wasser", {k: v for k, v in self.water.items() if v}))
        return rows

    def deviation(self, key: str) -> float | None:
        """Abweichung vom Ziel in %, None wenn kein Ziel gesetzt ist."""
        if key not in self.targets:
            return None
        t = self.targets[key]
        if t <= 0:
            return 0.0 if self.total.get(key, 0) <= 1e-9 else float("inf")
        return (self.total.get(key, 0) - t) / t * 100


def _matrix(keys, fertilizers):
    return np.array([[f.composition.get(k, 0.0) * 10.0 for f in fertilizers] for k in keys],
                    dtype=float).reshape(len(keys), len(fertilizers))


PRIORITIES = {"hoch": 10.0, "normal": 1.0, "niedrig": 0.1}
PRIORITY_NAMES = tuple(PRIORITIES)


def priority_factor(priorities: dict[str, str] | None, key: str) -> float:
    return PRIORITIES.get((priorities or {}).get(key, "normal"), 1.0)


def _prepare(targets, water, priorities=None):
    keys = [k for k in NUTRIENT_KEYS if k in targets]
    if not keys:
        raise CalculationError("Es sind keine Zielwerte angegeben.")
    t = np.array([targets[k] for k in keys])
    w_in = np.array([water.get(k, 0.0) for k in keys])
    b = np.maximum(t - w_in, 0.0)
    weights = 1.0 / np.maximum(t, [weight_floor(k) for k in keys])
    weights *= [priority_factor(priorities, k) for k in keys]
    warnings = [f"{BY_KEY[k].label}: Das Wasser enthält bereits mehr als den Zielwert "
                f"({water[k]:.4g} statt {targets[k]:.4g} mg/L)."
                for k, ti, wi in zip(keys, t, w_in) if wi > ti]
    return keys, b, weights, warnings


def _build_solution(fertilizers, dose, targets, water, keys, warnings) -> Solution:
    supplied = {k: 0.0 for k in ELEMENT_KEYS}
    for f, x in zip(fertilizers, dose):
        for k, pct in f.composition.items():
            if k in supplied:
                supplied[k] += pct * 10.0 * x
    total = {k: supplied[k] + water.get(k, 0.0) for k in ELEMENT_KEYS}
    rel = []
    for k in keys:
        denom = max(targets[k], weight_floor(k))
        rel.append(abs(total[k] - targets[k]) / denom)
    score = float(np.mean(rel) * 100) if rel else 0.0
    return Solution(list(fertilizers), [float(x) for x in dose], dict(targets), dict(water),
                    supplied, total, score, list(warnings))


def _shortfall_warnings(sol: Solution, pool: list[Fertilizer], pool_word: str,
                        priorities: dict[str, str] | None = None) -> list[str]:
    """Erklärt, warum ein Nährstoff weit (mehr als 50 %) unter dem Ziel bleibt.

    Für jeden Dünger aus pool, der das Element enthält, wird geprüft, welchen anderen
    Zielwert er am stärksten überschreiten würde, wenn er die Lücke allein schließen müsste –
    gewichtet mit den Prioritäten, genau wie im Löser.
    """
    out = []
    for k, target in sol.targets.items():
        dev = sol.deviation(k)
        if dev is None or dev >= -50 or target <= sol.water.get(k, 0):
            continue
        label = BY_KEY[k].label
        sources = [f for f in pool if f.composition.get(k, 0) > 0]
        if not sources:
            out.append(f"{label}: Kein {pool_word} Dünger enthält dieses Element.")
            continue
        gap = target - sol.total[k]
        reasons = []
        for f in sources:
            dose = gap / (f.composition[k] * 10)
            worst = None
            for j, tj in sol.targets.items():
                add = f.composition.get(j, 0) * 10 * dose
                if j == k or add <= 0:
                    continue
                new = sol.total[j] + add
                over = (new - tj) / max(tj, weight_floor(j)) * priority_factor(priorities, j)
                if over > 0.15 and (worst is None or over > worst[1]):
                    worst = (j, over, new, tj)
            if worst:
                j, _, new, tj = worst
                reasons.append(f"{f.name} ({BY_KEY[j].label} {format_number(new, 1 if new >= 1 else 3, True)} statt "
                               f"{format_number(tj, 3, True)} mg/L)")
        if reasons:
            out.append(f"{label} bleibt {format_number(-dev, 0)} % unter dem Ziel: Die {label}-Dünger würden "
                       f"andere Nährstoffe stark überdosieren – " + "; ".join(reasons)
                       + f". Priorität von {label} auf „hoch“ setzen, Zielwerte prüfen oder einen "
                       f"anderen {label}-Dünger ergänzen.")
        else:
            out.append(f"{label} bleibt {format_number(-dev, 0)} % unter dem Ziel, obwohl "
                       + ", ".join(f.name for f in sources) + f" {label} enthält. "
                       "Evtl. die Höchstzahl an Düngern erhöhen.")
    return out


def solve_manual(targets: dict[str, float], water: WaterProfile | dict,
                 fertilizers: list[Fertilizer], pool: list[Fertilizer] | None = None,
                 pool_word: str = "ausgewählter", priorities: dict[str, str] | None = None) -> Solution:
    """Beste Mengen für eine fest vorgegebene Düngerauswahl (gewichteter NNLS).

    pool: Dünger, die für Hinweise zu fehlenden Nährstoffen betrachtet werden
    (bei der automatischen Suche alle vorhandenen statt nur der gewählten).
    priorities: Element -> "hoch" / "normal" / "niedrig", gewichtet die Abweichungen.
    """
    water = water.values if isinstance(water, WaterProfile) else water
    if not fertilizers:
        raise CalculationError("Es ist kein Dünger ausgewählt.")
    keys, b, weights, warnings = _prepare(targets, water, priorities)
    A = _matrix(keys, fertilizers)
    x, _ = nnls(A * weights[:, None], b * weights, maxiter=50 * max(len(fertilizers), 10))
    x[x < 1e-9] = 0.0
    sol = _build_solution(fertilizers, x, targets, water, keys, warnings)
    sol.warnings += _shortfall_warnings(sol, pool if pool is not None else fertilizers, pool_word, priorities)
    unused = [f.name for f, xi in zip(fertilizers, x) if xi == 0]
    if unused:
        sol.warnings.append("Nicht benötigt: " + ", ".join(unused))
    return sol


def solve_auto(targets: dict[str, float], water: WaterProfile | dict,
               fertilizers: list[Fertilizer], max_count: int = 12,
               alternatives: int = 3, penalty: float = 0.02,
               time_limit: float = 10.0, priorities: dict[str, str] | None = None) -> list[Solution]:
    """Sucht aus allen Düngern die beste Kombination mit höchstens max_count Düngern.

    Ganzzahliges lineares Programm: minimiert die gewichtete absolute Abweichung plus
    einen kleinen Aufschlag je verwendetem Dünger. Danach werden die Mengen der
    gefundenen Kombination mit dem gleichen Verfahren wie bei der manuellen Auswahl
    nachgerechnet. Weitere Kombinationen werden durch Ausschluss der vorherigen gefunden.
    """
    water = water.values if isinstance(water, WaterProfile) else water
    keys, b, weights, _ = _prepare(targets, water, priorities)
    A_all = _matrix(keys, fertilizers)

    # Obergrenze je Dünger (nur als Schranke für das Optimierungsproblem): so viel, dass das
    # Element mit dem größten Bedarf dreifach gedeckt wäre. Ob eine Überdosierung anderer
    # Elemente sich lohnt, entscheidet allein die Gewichtung (Prioritäten).
    floors = np.array([weight_floor(k) for k in keys])
    cap_need = 3 * np.maximum(b, floors)
    upper = []
    for j in range(len(fertilizers)):
        col = A_all[:, j]
        mask = col > 0
        upper.append(float(np.max(cap_need[mask] / col[mask])) if mask.any() else 0.0)
    cand = [j for j, u in enumerate(upper) if u > 0]
    if not cand:
        raise CalculationError("Kein Dünger in der Datenbank liefert die gewünschten Nährstoffe.")
    ferts = [fertilizers[j] for j in cand]
    A = A_all[:, cand]
    U = np.array([upper[j] for j in cand])
    n, m = len(ferts), len(keys)

    # Variablen: x (n), y (n, binär), e_plus (m), e_minus (m)
    c = np.concatenate([np.zeros(n), np.full(n, penalty), weights, weights])
    lo = np.zeros(2 * n + 2 * m)
    hi = np.concatenate([U, np.ones(n), np.full(2 * m, np.inf)])
    integrality = np.concatenate([np.zeros(n), np.ones(n), np.zeros(2 * m)])

    rows, lbs, ubs = [], [], []
    for i in range(m):                                   # A·x − e⁺ + e⁻ = b
        r = np.zeros(2 * n + 2 * m)
        r[:n] = A[i]
        r[2 * n + i] = -1
        r[2 * n + m + i] = 1
        rows.append(r); lbs.append(b[i]); ubs.append(b[i])
    for j in range(n):                                   # x_j ≤ U_j · y_j
        r = np.zeros(2 * n + 2 * m)
        r[j] = 1
        r[n + j] = -U[j]
        rows.append(r); lbs.append(-np.inf); ubs.append(0)
    r = np.zeros(2 * n + 2 * m)                          # Σ y ≤ max_count
    r[n:2 * n] = 1
    rows.append(r); lbs.append(0); ubs.append(max_count)

    solutions, seen = [], []
    for _ in range(max(1, alternatives) * 2):
        res = milp(c, constraints=LinearConstraint(np.array(rows), lbs, ubs),
                   integrality=integrality, bounds=Bounds(lo, hi),
                   options={"time_limit": time_limit})
        if res.x is None:
            break
        chosen = [j for j in range(n) if res.x[n + j] > 0.5 and res.x[j] > 1e-9]
        if not chosen or set(chosen) in seen:
            break
        seen.append(set(chosen))
        sol = solve_manual(targets, water, [ferts[j] for j in chosen], pool=fertilizers, pool_word="vorhandener",
                           priorities=priorities)
        keep = [(f, x) for f, x in zip(sol.fertilizers, sol.dose) if x > 0]
        sol.fertilizers = [f for f, _ in keep]
        sol.dose = [x for _, x in keep]
        sol.warnings = [w for w in sol.warnings if not w.startswith("Nicht benötigt")]
        if not any(set(f.id or id(f) for f in s.fertilizers) ==
                   set(f.id or id(f) for f in sol.fertilizers) for s in solutions):
            solutions.append(sol)
        if len(solutions) >= alternatives:
            break
        # Diese Kombination für die nächste Runde ausschließen
        r = np.zeros(2 * n + 2 * m)
        r[[n + j for j in chosen]] = 1
        rows.append(r); lbs.append(-np.inf); ubs.append(len(chosen) - 1)
    if not solutions:
        raise CalculationError("Es wurde keine passende Düngerkombination gefunden.")
    solutions.sort(key=lambda s: s.score + penalty * 100 * len(s.fertilizers))
    return solutions
