"""Nachbau des gemeldeten Falls: Rezept "Test1" mit Ca-Ziel, aber wenig Nitrat."""
from naehrrechner.core.models import Fertilizer

FERTS = [
    Fertilizer("Canna MONO Trace Mix", {"B": .03, "Cu": .003, "Fe": .056, "Mn": .05, "Mo": .007, "Zn": .03}, liquid=True, id=1),
    Fertilizer("EPSO Top Magnesiumsulfat", {"Mg": 9.6, "S": 13}, id=2),
    Fertilizer("Haifa MKP Monokaliumphosphat (0-52-34)", {"P": 22.69, "K": 28.22}, id=3),
    Fertilizer("Haifa SOP Kaliumsulfat", {"K": 43.16, "S": 18}, id=4),
    Fertilizer("Hakaphos Soft Elite 24-6-12(+2)", {"NO3_N": 13, "NH4_N": 11, "P": 2.62, "K": 9.96, "Mg": 1.2, "B": .01,
                                                  "Cu": .02, "Fe": .1, "Mn": .05, "Mo": .001, "Zn": .015}, id=5),
    Fertilizer("Wuxal Calcium", {"Ca": 14.48, "Mn": .675, "Mo": .675}, liquid=True, id=6),
    Fertilizer("Wuxal Eisen", {"NO3_N": 5, "S": 3, "Fe": 5}, liquid=True, id=7),
    Fertilizer("YaraTera CALCINIT", {"NO3_N": 14.4, "NH4_N": 1.1, "Ca": 18.59}, id=8),
]
TARGETS = {"NO3_N": 10, "NH4_N": 10, "P": 30, "K": 100, "Ca": 70, "Mg": 30, "Fe": 2.5, "Mn": 0.6, "Zn": 0.4,
           "B": 0.4, "Cu": 0.03}
