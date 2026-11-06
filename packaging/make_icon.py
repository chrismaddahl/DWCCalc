"""Erzeugt naehrrechner/icon.ico: ein grüner Tropfen mit Blatt."""
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen

OUT = Path(__file__).resolve().parent.parent / "naehrrechner" / "icon.ico"


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 256, size / 256)
    drop = QPainterPath()
    drop.moveTo(128, 14)
    drop.cubicTo(128, 14, 40, 120, 40, 160)
    drop.cubicTo(40, 210, 80, 244, 128, 244)
    drop.cubicTo(176, 244, 216, 210, 216, 160)
    drop.cubicTo(216, 120, 128, 14, 128, 14)
    p.fillPath(drop, QBrush(QColor("#2a7fc1")))
    leaf = QPainterPath()
    leaf.moveTo(QPointF(92, 200))
    leaf.cubicTo(92, 140, 130, 112, 178, 110)
    leaf.cubicTo(176, 160, 150, 196, 92, 200)
    p.fillPath(leaf, QBrush(QColor("#7ccf5a")))
    p.setPen(QPen(QColor("#3e8f2c"), 6, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(96, 196), QPointF(160, 128))
    p.end()
    return img


def main():
    QGuiApplication(sys.argv)
    # Qt schreibt ICO mit einer Größe; 256 px wird von Windows auf alle Größen skaliert
    if not draw(256).save(str(OUT), "ICO"):
        sys.exit("Symbol konnte nicht gespeichert werden.")
    print(OUT)


if __name__ == "__main__":
    main()
