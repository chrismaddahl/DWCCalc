# Nährlösungsrechner

Desktop-Programm zur Berechnung von Nährlösungen für Hydrokultur – eine schlanke Neuentwicklung nach dem Vorbild von HydroBuddy.

<img width="1956" height="1189" alt="grafik" src="https://github.com/user-attachments/assets/24798ca5-d9b7-4c97-8b4f-e3d0d3af671b" />


> **Mit KI erstellt.** Der Programmcode dieses Projekts wurde vollständig von einer KI (Claude von Anthropic)
> geschrieben. Idee, Anforderungen, Entscheidungen und Praxistests stammen vom Menschen. Ergebnisse ohne Gewähr –
> Details unter [Mit KI erstellt](#mit-ki-erstellt).

## Starten

**Ohne Python:** unter *Releases* die Datei `Naehrloesungsrechner-…-windows.zip` herunterladen, entpacken und
`Naehrloesungsrechner.exe` starten. Windows warnt beim ersten Start („Der Computer wurde durch Windows geschützt“),
weil die exe nicht signiert ist: *Weitere Informationen* → *Trotzdem ausführen*. Beispiel-Dünger zum Importieren
liegen im Ordner `Beispiele`.

**Mit Python:** `start.bat` doppelklicken. Beim ersten Start wird eine Python-Umgebung eingerichtet (Python 3.10 oder neuer muss installiert sein).

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

## exe bauen

Lokal (Ergebnis in `dist/`, inklusive ZIP und Selbsttest der exe):

```
.venv\Scripts\python -m pip install -r requirements-build.txt
.venv\Scripts\python packaginguild_exe.py
```

Auf GitHub baut `.github/workflows/release.yml` die exe automatisch. Neue Version veröffentlichen:
`__version__` in `naehrrechner/__init__.py` erhöhen, committen, dann

```
git tag v0.2.0
git push origin main --tags
```

Der Tag muss zur Version passen. Danach liegt die ZIP-Datei unter *Releases*. Ohne Tag lässt sich der Build unter
*Actions → Windows-Build → Run workflow* starten; die ZIP-Datei steht dann unter *Artifacts*.

## Mit KI erstellt

Dieses Programm ist im Oktober und November 2026 in Zusammenarbeit zwischen einem Menschen
([chrismaddahl](https://github.com/chrismaddahl)) und der KI **Claude Opus 5.5** von Anthropic entstanden,
im Programm Claude Code. Die Arbeit war so aufgeteilt:

**Mensch**
- Idee: HydroBuddy auf das Wesentliche verschlanken und seine Schwächen beheben (z. B. Komma als Dezimalzeichen).
- Anforderungen und Entscheidungen: Funktionsumfang, nur mg/L, CSV statt Altdaten, Merkzettel DIN A5 quer,
  Herkunft der Nährstoffe, Prioritäten, Varianten nebeneinander, A/B/C-Aufteilung, exe zum Weitergeben.
- Testen in der Praxis: echte Ansätze gemischt, Fehler gemeldet (z. B. Absturz beim Drucken, Ausfällung in Tank B),
  Ergebnisse mit HydroBuddy verglichen.
- Daten: Dünger mit ihren Gehalten, Fotos der Etiketten.

**KI (Claude)**
- Konzept und Aufbau des Programms.
- Den gesamten Programmcode: Rechenkern und Optimierer (gewichtete NNLS, MILP für die automatische Düngerauswahl),
  SQLite-Datenbank, CSV-Import und -Export, Oberfläche mit PySide6, Merkzettel und PDF.
- Die fachlichen Modelle im Code: Oxid-Umrechnung, Tankzuordnung, EC-Schätzung, Ausfällungsprüfung,
  Umrechnung von g/100 mL in Massen-%.
- 52 automatische Tests sowie Fehlersuche und Korrekturen zu den gemeldeten Problemen.
- Den Build der Windows-exe, den GitHub-Workflow und diese Dokumentation, einschließlich dieses Hinweises.

Quellcode von HydroBuddy wurde nicht übernommen; das Programm ist eine eigenständige Neuentwicklung, deren
Funktionsumfang sich an HydroBuddy orientiert.

**Grenzen und Haftung**
- KI kann Fehler machen, auch solche, die Tests und Praxistests nicht aufdecken. Eine fachliche Prüfung der
  Rechenwege durch Agrarchemiker oder vergleichbare Fachleute hat nicht stattgefunden.
- Die EC ist eine Schätzung. Die Ausfällungsprüfung arbeitet mit groben Richtwerten, weil der pH-Wert im Tank
  nicht bekannt ist; eine fehlende Warnung ist keine Garantie.
- Die Ergebnisse hängen von den eingetragenen Düngerdaten ab. Gehalte vom Etikett übernehmen (Massen-%),
  fertige Lösungen nachmessen (EC, pH).
- Nutzung auf eigene Verantwortung, ohne Gewähr für Richtigkeit oder Eignung.
