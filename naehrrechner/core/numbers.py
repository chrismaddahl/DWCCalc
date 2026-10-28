"""Zahlen lesen und ausgeben – Komma und Punkt werden als Dezimalzeichen akzeptiert."""
import math


def parse_number(text) -> float | None:
    """Liest eine Zahl wie "1,5", "1.5", "1.234,5" oder "1,234.5".

    Leerer Text ergibt None. Steht sowohl Komma als auch Punkt in der Zahl, ist das
    hintere Zeichen das Dezimalzeichen und das vordere Tausendertrennzeichen.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip().replace(" ", "").replace(" ", "").replace("'", "")
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif s.count(",") > 1 or s.count(".") > 1:
        raise ValueError(f"Keine gültige Zahl: {text!r}")
    else:
        s = s.replace(",", ".")
    try:
        value = float(s)
    except ValueError:
        raise ValueError(f"Keine gültige Zahl: {text!r}") from None
    if not math.isfinite(value):
        raise ValueError(f"Keine gültige Zahl: {text!r}")
    return value


def format_number(value: float | None, decimals: int = 2, trim: bool = False) -> str:
    """Gibt eine Zahl mit Komma als Dezimalzeichen aus (ohne Tausendertrennzeichen)."""
    if value is None:
        return ""
    s = f"{value:.{decimals}f}"
    if trim and "." in s:
        s = s.rstrip("0").rstrip(".")
    if s in ("-0", "-0.0") or (s.startswith("-") and float(s) == 0):
        s = s[1:]
    return s.replace(".", ",")


def format_plain(value: float | None) -> str:
    """Volle Genauigkeit für Dateien, ohne Exponentenschreibweise."""
    return format_number(value, decimals=8, trim=True)


def format_amount_g(grams: float) -> tuple[str, str]:
    """Wiegemenge passend gerundet: kleine Mengen in mg."""
    if grams < 0.1:
        return format_number(grams * 1000, 1 if grams * 1000 < 10 else 0), "mg"
    if grams < 10:
        return format_number(grams, 2), "g"
    if grams < 1000:
        return format_number(grams, 1), "g"
    return format_number(grams, 0), "g"


def format_amount_ml(ml: float) -> tuple[str, str]:
    if ml < 10:
        return format_number(ml, 2), "mL"
    if ml < 1000:
        return format_number(ml, 1), "mL"
    return format_number(ml, 0), "mL"
