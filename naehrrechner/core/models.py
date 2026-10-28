"""Datenobjekte für Dünger, Wasserprofile und Rezepte."""
from dataclasses import dataclass, field


@dataclass
class Fertilizer:
    name: str
    composition: dict[str, float] = field(default_factory=dict)  # Massenanteil Element in %
    formula: str = ""
    liquid: bool = False
    density: float | None = None      # g/mL, nur bei flüssigen Düngern
    solubility: float | None = None   # g/L bei ca. 20 °C
    tank: str = "auto"                # "auto", "A" oder "B"
    available: bool = True
    note: str = ""
    id: int | None = None


@dataclass
class WaterProfile:
    name: str
    values: dict[str, float] = field(default_factory=dict)  # mg/L
    id: int | None = None


@dataclass
class Recipe:
    name: str
    targets: dict[str, float] = field(default_factory=dict)  # mg/L, nur gesetzte Werte
    description: str = ""
    fertilizer_ids: list[int] = field(default_factory=list)  # optional gespeicherte Auswahl
    priorities: dict[str, str] = field(default_factory=dict)  # nur abweichend von "normal"
    id: int | None = None


VE_WATER = WaterProfile("VE-Wasser (Osmose / destilliert)", {})
