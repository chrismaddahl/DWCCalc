"""Baut den Ordner dist/Naehrloesungsrechner mit der exe, prüft ihn und packt ihn als ZIP.

Aufruf aus dem Projektordner:  .venv\\Scripts\\python packaging\\build_exe.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent
NAME = "Naehrloesungsrechner"
ICON = ROOT / "naehrrechner" / "icon.ico"
DIST = ROOT / "dist"
# Qt-Teile, die das Programm nicht braucht und die sonst nur Platz kosten
EXCLUDE = ["tkinter", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf",
           "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtMultimedia",
           "PySide6.QtOpenGL", "PySide6.QtSvg",
           # scipy: gebraucht werden nur optimize (nnls, milp) samt linalg/sparse/special
           "scipy.stats", "scipy.signal", "scipy.io", "scipy.ndimage", "scipy.interpolate",
           "scipy.odr", "scipy.cluster", "scipy.datasets", "scipy.misc", "scipy.fftpack"]
# Dateien, die die Qt-Hooks mitnehmen, die ein reines Widgets-Programm aber nicht lädt
PRUNE = ["opengl32sw.dll", "Qt6Quick*.dll", "Qt6Qml*.dll", "Qt6Pdf*.dll", "Qt6VirtualKeyboard*.dll",
         "plugins/platforminputcontexts", "plugins/imageformats/qpdf.dll"]


def prune(qt: Path):
    for pattern in PRUNE:
        for p in qt.glob(pattern):
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    for qm in (qt / "translations").glob("*.qm"):
        if not qm.stem.endswith("_de"):
            qm.unlink()


def version() -> str:
    sys.path.insert(0, str(ROOT))
    from naehrrechner import __version__
    return __version__


def main():
    if not ICON.exists():
        subprocess.run([sys.executable, str(ROOT / "packaging" / "make_icon.py")], check=True)
    args = [str(ROOT / "packaging" / "launcher.py"), "--name", NAME, "--windowed", "--onedir",
            "--noconfirm", "--clean", "--icon", str(ICON),
            "--add-data", f"{ICON}{';' if sys.platform == 'win32' else ':'}naehrrechner",
            "--distpath", str(DIST), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
            "--paths", str(ROOT)]
    for mod in EXCLUDE:
        args += ["--exclude-module", mod]
    PyInstaller.__main__.run(args)

    target = DIST / NAME
    prune(target / "_internal" / "PySide6")
    shutil.copytree(ROOT / "beispiele", target / "Beispiele", dirs_exist_ok=True)
    exe = target / f"{NAME}.exe"
    code = subprocess.run([str(exe), "--selftest"], timeout=120).returncode
    if code != 0:
        sys.exit(f"Selbsttest der exe fehlgeschlagen (Code {code}).")
    print("Selbsttest in Ordnung.")

    zip_base = DIST / f"{NAME}-{version()}-windows"
    archive = shutil.make_archive(str(zip_base), "zip", DIST, NAME)
    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    print(f"Ordner: {target} ({size / 1e6:.0f} MB)")
    print(f"ZIP:    {archive} ({Path(archive).stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
