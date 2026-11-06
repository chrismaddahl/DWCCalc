"""Start: python -m naehrrechner"""
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QLocale, QStandardPaths
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .db import Database
from .ui.main_window import MainWindow


def database_path() -> Path:
    if os.environ.get("NAEHRRECHNER_DB"):
        return Path(os.environ["NAEHRRECHNER_DB"])
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    return Path(base) / "naehrrechner.db"


def selftest() -> int:
    """Prüft die gepackte exe ohne Fenster: Optimierer, Oberfläche, Druckmodul. 0 = in Ordnung."""
    from .core.batch import plan_concentrate
    from .core.models import VE_WATER, Fertilizer
    from .core.solver import solve_auto
    from .printing import a5_printer
    ferts = [Fertilizer("Calciumnitrat", {"NO3_N": 14.4, "NH4_N": 1.1, "Ca": 18.6}, id=1),
             Fertilizer("MKP", {"P": 22.7, "K": 28.2}, id=2),
             Fertilizer("Bittersalz", {"Mg": 9.6, "S": 13}, id=3)]
    sol = solve_auto({"NO3_N": 100, "Ca": 120, "P": 40, "Mg": 30}, VE_WATER, ferts)[0]
    plan_concentrate(sol, 100, 10, 3)
    win = MainWindow(Database(":memory:"))
    a5_printer()
    win.close()
    return 0 if len(sol.fertilizers) == 3 else 1


def main():
    QLocale.setDefault(QLocale(QLocale.German, QLocale.Germany))
    app = QApplication(sys.argv)
    app.setApplicationName("Naehrloesungsrechner")
    app.setStyle("Fusion")
    icon = Path(__file__).parent / "icon.ico"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    if "--selftest" in sys.argv:
        sys.exit(selftest())

    def excepthook(exc_type, exc, tb):
        traceback.print_exception(exc_type, exc, tb)
        QMessageBox.critical(None, "Unerwarteter Fehler", f"{exc_type.__name__}: {exc}")
    sys.excepthook = excepthook

    db = Database(database_path())
    win = MainWindow(db)
    win.show()
    code = app.exec()
    db.close()
    sys.exit(code)


if __name__ == "__main__":
    main()
