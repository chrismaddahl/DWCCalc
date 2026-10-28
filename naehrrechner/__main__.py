"""Start: python -m naehrrechner"""
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QLocale, QStandardPaths
from PySide6.QtWidgets import QApplication, QMessageBox

from .db import Database
from .ui.main_window import MainWindow


def database_path() -> Path:
    if os.environ.get("NAEHRRECHNER_DB"):
        return Path(os.environ["NAEHRRECHNER_DB"])
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    return Path(base) / "naehrrechner.db"


def main():
    QLocale.setDefault(QLocale(QLocale.German, QLocale.Germany))
    app = QApplication(sys.argv)
    app.setApplicationName("Naehrloesungsrechner")
    app.setStyle("Fusion")

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
