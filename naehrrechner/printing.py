"""Merkzettel im Format DIN A5 quer."""
from dataclasses import dataclass
from datetime import date
from html import escape

from PySide6.QtCore import QMarginsF, QSizeF
from PySide6.QtGui import QFont, QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter

from .core.batch import CONCENTRATE, BatchPlan
from .core.elements import BY_KEY, NUTRIENT_KEYS
from .core.numbers import format_amount_g, format_amount_ml, format_number
from .core.solver import Solution


@dataclass
class SheetData:
    title: str
    water_name: str
    solution: Solution
    plan: BatchPlan
    ec: float
    note: str = ""


def _amount(line) -> str:
    if line.ml is not None:
        v, u = format_amount_ml(line.ml)
    else:
        v, u = format_amount_g(line.grams)
    return f"{v}&nbsp;{u}"


def _tank_table(title: str, lines) -> str:
    rows = "".join(
        f"<tr><td>{escape(ln.fertilizer.name)}</td><td align='right'><b>{_amount(ln)}</b></td>"
        f"<td width='18'>&#9744;</td></tr>" for ln in lines)
    head = f"<p class='h'>{escape(title)}</p>" if title else ""
    return f"{head}<table width='100%' cellspacing='0' cellpadding='2' class='t'>{rows}</table>"


def build_html(d: SheetData) -> str:
    p, s = d.plan, d.solution
    if p.mode == CONCENTRATE:
        what = (f"Konzentrat {p.factor}× &nbsp;·&nbsp; je Tank {format_number(p.volume_l, 1, True)} L")
        dosing = (f"Dosierung: je <b>{format_number(p.ml_per_liter, 2, True)} mL</b> "
                  + p.tank_label + " pro Liter Wasser")
    else:
        what = f"Direkter Ansatz für {format_number(p.volume_l, 1, True)} L"
        dosing = "Dünger nacheinander vollständig im Wasser lösen."

    if p.mode == CONCENTRATE and p.split:
        width = 100 // p.n_tanks
        cells = "".join(
            f"<td width='{width}%' valign='top'>"
            f"{_tank_table(f'Tank {t}', [ln for ln in p.lines if ln.tank == t])}</td>"
            for t in p.tank_names)
        tanks = f"<table width='100%' cellspacing='6'><tr>{cells}</tr></table>"
    else:
        tanks = _tank_table("", p.lines)

    keys = [k for k in NUTRIENT_KEYS if k in s.targets or s.total.get(k, 0) > 1e-6]
    head = "".join(f"<th>{escape(BY_KEY[k].label)}</th>" for k in keys)

    def val(v):
        return format_number(v, 2 if v < 10 else 0)
    target = "".join(f"<td align='center'>{val(s.targets[k]) if k in s.targets else '–'}</td>" for k in keys)
    actual = "".join(f"<td align='center'>{val(s.total.get(k, 0))}</td>" for k in keys)

    note = f"<p class='s'>{escape(d.note)}</p>" if d.note else ""
    return f"""
<html><head><style>
 body {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: 9pt; }}
 .h {{ font-weight: bold; font-size: 10pt; margin: 0; }}
 .t td {{ border-bottom: 1px solid #bbb; }}
 .n th {{ background: #e8e8e8; font-size: 8pt; }}
 .n td {{ font-size: 8pt; border-bottom: 1px solid #ddd; }}
 .s {{ font-size: 8pt; color: #444; margin: 2px 0; }}
</style></head><body>
<table width='100%'><tr>
 <td><span style='font-size:15pt; font-weight:bold'>{escape(d.title)}</span></td>
 <td align='right' valign='top'>{date.today().strftime('%d.%m.%Y')}</td>
</tr></table>
<p style='margin:2px 0 6px 0'>{what} &nbsp;·&nbsp; Wasser: {escape(d.water_name)}<br/>{dosing}</p>
{tanks}
<p class='s' style='margin-top:8px'>Nährstoffe in mg/L &nbsp;·&nbsp; geschätzte EC:
 <b>{format_number(d.ec, 2)} mS/cm</b> (25 °C)</p>
<table width='100%' cellspacing='0' cellpadding='2' class='n'>
 <tr><th align='left'></th>{head}</tr>
 <tr><td>Ziel</td>{target}</tr>
 <tr><td>Ist</td>{actual}</tr>
</table>
{note}
</body></html>"""


def a5_printer(printer: QPrinter | None = None) -> QPrinter:
    printer = printer or QPrinter(QPrinter.HighResolution)
    printer.setPageLayout(QPageLayout(QPageSize(QPageSize.A5), QPageLayout.Landscape,
                                      QMarginsF(10, 8, 10, 8), QPageLayout.Millimeter))
    return printer


def render(html: str, printer: QPrinter):
    doc = QTextDocument()
    doc.setDefaultFont(QFont("Segoe UI", 9))
    doc.setHtml(html)
    rect = printer.pageLayout().paintRectPoints()
    doc.setPageSize(QSizeF(rect.width(), rect.height()))
    doc.print_(printer)


def save_pdf(html: str, path: str):
    printer = a5_printer()
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(path)
    render(html, printer)
