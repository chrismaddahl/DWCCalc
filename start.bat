@echo off
rem Startet den Naehrloesungsrechner. Beim ersten Start wird die Umgebung eingerichtet.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Richte Python-Umgebung ein, bitte warten...
    python -m venv .venv || goto :fehler
    ".venv\Scripts\python" -m pip install -r requirements.txt || goto :fehler
)
start "" ".venv\Scripts\pythonw.exe" -m naehrrechner
exit /b 0
:fehler
echo Einrichtung fehlgeschlagen. Ist Python 3.10 oder neuer installiert?
pause
