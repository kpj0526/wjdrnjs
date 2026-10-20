# PyInstaller spec: one-folder, windowed build of the R2 target helper.
# Built by packaging/build.ps1; paths are relative to the repository root (SPECPATH/..).
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(ROOT, "packaging", "entry.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "assets", "sample_1600x900.png"), "assets")],
    hiddenimports=[],
    excludes=["pytest", "_pytest", "pyflakes", "unittest", "pydoc", "doctest", "IPython", "matplotlib", "scipy"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="R2TargetHelper",
    console=False,          # GUI app; --selftest writes its result to a file instead of stdout
    debug=False,
    strip=False,
    upx=False,              # UPX-packed exes trigger more antivirus false positives
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="R2TargetHelper")
