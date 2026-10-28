# Nährlösungsrechner

Desktop-Programm zur Berechnung von Nährlösungen für Hydrokultur – eine schlanke Neuentwicklung nach dem Vorbild von HydroBuddy.

<img width="1956" height="1189" alt="grafik" src="https://github.com/user-attachments/assets/24798ca5-d9b7-4c97-8b4f-e3d0d3af671b" />


## Starten

`start.bat` doppelklicken. Beim ersten Start wird eine Python-Umgebung eingerichtet (Python 3.10 oder neuer muss installiert sein).

Die Daten liegen in `%APPDATA%\Naehrloesungsrechner\naehrrechner.db` (siehe *Datei → Speicherort der Datenbank*).

## Funktionen

- **Dünger**: Gehalte in Massen-%, wahlweise als Element oder Oxid (P₂O₅, K₂O, CaO, MgO, SO₃, Na₂O, SiO₂). Fest oder flüssig (mit Dichte → Angabe in mL), Löslichkeit, Tank-Zuordnung, „vorhanden“.
- **Wasser**: eigene Wasserprofile in mg/L; VE-Wasser ist immer verfügbar.
- **Rezepte**: Zielwerte in mg/L, optional mit gespeicherter Düngerauswahl. Leeres Feld = egal, 0 = soll nicht enthalten sein.
- **Priorität je Nährstoff** (hoch / normal / niedrig): Abweichungen zählen 10-fach, einfach oder nur zu einem Zehntel. Beispiel: Ca „hoch“ und N (NO₃) „niedrig“ – dann wird Ca getroffen, auch wenn dafür mehr Nitrat in die Lösung kommt. Wird im Rezept, im CSV-Export (Spalte „Priorität“, z. B. `Ca: hoch | NO3_N: niedrig`) und im Sitzungsstand gespeichert.
- **Berechnung**: mit selbst gewählten Düngern oder automatischer Suche der besten Kombination (bis zu drei Varianten).
- **Ansatz**: direkt (Volumen) oder als Konzentrat (Faktor, Tankvolumen, Aufteilung: ein Konzentrat, A/B oder A/B/C; mit Löslichkeits- und Ausfällungsprüfung).
- **EC-Schätzung** in mS/cm.
- **Merkzettel** im Format DIN A5 quer drucken oder als PDF speichern.
- **CSV-Export/-Import** (Datei-Menü): `duenger.csv`, `wasser.csv`, `rezepte.csv`. Semikolon und Dezimalkomma, Excel-kompatibel. Beim Import werden auch Komma-getrennte Dateien und Dezimalpunkte erkannt; gleiche Namen werden überschrieben.

Alle Zahlenfelder akzeptieren **Komma und Punkt** als Dezimalzeichen.

Im Ordner `beispiele` liegen optionale Beispieldaten (12 gängige Nährsalze, ein Rezept) zum Ausprobieren per CSV-Import.

## Berechnung

- Bedarf = Zielwert − Gehalt im Wasser.
- Manuelle Auswahl: nicht-negative Ausgleichsrechnung, Abweichungen relativ zum Zielwert gewichtet.
- Automatisch: ganzzahlige lineare Optimierung (höchstens *n* Dünger, kleiner Aufschlag je Dünger), danach Feinberechnung wie bei manueller Auswahl.
- Tank-Zuordnung automatisch: Calcium → A, Sulfat/Phosphat → B, reines Eisenchelat → A, übrige Spurenelemente → B.
  Bei A/B/C: Phosphat → B, Magnesium und Sulfat → C, übrige Spurenelemente → C. Im Dünger fest eingestelltes „Tank C“ landet bei A/B in Tank B.
- Ausfällungsprüfung je Tank über das Ionenprodukt (mol/L)²: Ca + Sulfat (Gips), Ca + Phosphat, Mg + Phosphat
  (Magnesiumphosphat, mit Ammonium Struvit). Mg + Phosphat gilt als „hoch“, wenn Ammonium im Tank ist oder das Phosphat
  laut Ladungsbilanz eher alkalisch ist (mehr als 1,25 Kationen-Äquivalente je Phosphat, MKP liegt bei 1). Die Grenzen sind
  grobe Richtwerte, der echte pH-Wert im Tank ist unbekannt. Die Warnung nennt Abhilfen und einen Faktor, bis zu dem es
  unkritisch bleiben sollte.
- EC: Ionen × molare Grenzleitfähigkeit, korrigiert über die Ionenstärke. Ein Richtwert, kein Ersatz für die Messung.

## Entwicklung

```
.venv\Scripts\python -m pytest tests
```
