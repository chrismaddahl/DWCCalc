"""Nährelemente, Oxid-Umrechnung und Ionendaten."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Element:
    key: str                    # interner Schlüssel, auch Spaltenname in CSV-Dateien
    label: str                  # Anzeige in der Oberfläche
    micro: bool = False         # Spurenelement
    oxide: str | None = None    # Oxidform, wie sie auf Düngersäcken steht
    oxide_ascii: str | None = None
    oxide_factor: float = 1.0   # Element = Oxid * Faktor
    water_only: bool = False    # nur im Wasserprofil relevant (z. B. Hydrogencarbonat)


ELEMENTS: tuple[Element, ...] = (
    Element("NO3_N", "N (NO₃)"),
    Element("NH4_N", "N (NH₄)"),
    Element("P", "P", oxide="P₂O₅", oxide_ascii="P2O5", oxide_factor=0.4364),
    Element("K", "K", oxide="K₂O", oxide_ascii="K2O", oxide_factor=0.8301),
    Element("Ca", "Ca", oxide="CaO", oxide_ascii="CaO", oxide_factor=0.7147),
    Element("Mg", "Mg", oxide="MgO", oxide_ascii="MgO", oxide_factor=0.6030),
    Element("S", "S", oxide="SO₃", oxide_ascii="SO3", oxide_factor=0.4005),
    Element("Fe", "Fe", micro=True),
    Element("Mn", "Mn", micro=True),
    Element("Zn", "Zn", micro=True),
    Element("B", "B", micro=True),
    Element("Cu", "Cu", micro=True),
    Element("Mo", "Mo", micro=True),
    Element("Na", "Na", oxide="Na₂O", oxide_ascii="Na2O", oxide_factor=0.7419),
    Element("Cl", "Cl"),
    Element("Si", "Si", oxide="SiO₂", oxide_ascii="SiO2", oxide_factor=0.4675),
    Element("HCO3", "HCO₃", water_only=True),
)

BY_KEY = {e.key: e for e in ELEMENTS}
NUTRIENTS = tuple(e for e in ELEMENTS if not e.water_only)   # in Düngern und Rezepten
NUTRIENT_KEYS = tuple(e.key for e in NUTRIENTS)
ELEMENT_KEYS = tuple(e.key for e in ELEMENTS)

# Untergrenze für die relative Gewichtung von Abweichungen in mg/L
WEIGHT_FLOOR_MACRO = 1.0
WEIGHT_FLOOR_MICRO = 0.01


def weight_floor(key: str) -> float:
    return WEIGHT_FLOOR_MICRO if BY_KEY[key].micro else WEIGHT_FLOOR_MACRO


# Ionen für die EC-Schätzung: Molmasse des Elements, Ladung, molare Grenzleitfähigkeit
# des Ions in S·cm²/mol (25 °C). Phosphat wird als H₂PO₄⁻ angenommen (pH 5,5–6,5).
IONS = {
    "NO3_N": (14.007, 1, 71.4),
    "NH4_N": (14.007, 1, 73.5),
    "P": (30.974, 1, 36.0),
    "K": (39.098, 1, 73.5),
    "Ca": (40.078, 2, 119.0),
    "Mg": (24.305, 2, 106.0),
    "S": (32.06, 2, 160.0),
    "Na": (22.990, 1, 50.1),
    "Cl": (35.45, 1, 76.3),
    "HCO3": (61.017, 1, 44.5),
}


def lookup_column(name: str) -> tuple[str, float] | None:
    """Ordnet einen Spaltennamen (z. B. "NO3-N [%]", "K2O", "Ca") einem Element zu.

    Gibt (Elementschlüssel, Umrechnungsfaktor) zurück, bei Oxid-Spalten mit dem Oxidfaktor.
    """
    n = name.split("[")[0].strip().lower().replace(" ", "")
    for e in ELEMENTS:
        aliases = {e.key.lower(), e.label.lower().replace(" ", "")}
        if e.key == "NO3_N":
            aliases |= {"no3-n", "n-no3", "n(no3)", "nitrat-n"}
        if e.key == "NH4_N":
            aliases |= {"nh4-n", "n-nh4", "n(nh4)", "ammonium-n"}
        if e.key == "HCO3":
            aliases |= {"hco3", "hydrogencarbonat"}
        if n in aliases:
            return e.key, 1.0
        if e.oxide_ascii and n in {e.oxide_ascii.lower(), e.oxide.lower()}:
            return e.key, e.oxide_factor
    return None
