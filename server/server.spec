# PyInstaller one-directory build for the Windows portable release.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
SERVER = ROOT / "server"

DATA_FILES = [
    (SERVER / "report.html", "server"),
    (SERVER / "report.css", "server"),
    (SERVER / "report.js", "server"),
    (SERVER / "cacert.pem", "server"),
    (SERVER / "config.example.json", "server"),
]

a = Analysis(
    [str(SERVER / "server.py")],
    pathex=[str(SERVER)],
    binaries=[],
    datas=[(str(source), target) for source, target in DATA_FILES],
    hiddenimports=collect_submodules("encodings"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SansongAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="SansongAI",
)
