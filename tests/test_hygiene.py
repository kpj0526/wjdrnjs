"""Source files are clean UTF-8: no U+FFFD replacement characters, and GUI strings are ASCII
(so labels never turn into mojibake when files are viewed or edited under a non-UTF-8 code page)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTS = {".py", ".md", ".txt", ".ps1", ".spec", ".bat", ".json"}
SKIP = {".venv", ".build-venv", "build", "dist", ".git", "__pycache__"}


def _sources():
    for p in ROOT.rglob("*"):
        if p.is_file() and p.suffix in EXTS and not SKIP & set(p.relative_to(ROOT).parts):
            yield p


REPLACEMENT = chr(0xFFFD)  # built at runtime so this file does not contain the character itself
INVISIBLE = {chr(0xFEFF): "BOM", chr(0x200B): "zero-width space"}


def test_no_replacement_chars_and_valid_utf8():
    bad = []
    for p in _sources():
        text = p.read_bytes().decode("utf-8")  # raises if not UTF-8
        bad += [f"{p.relative_to(ROOT)}:{i}" for i, line in enumerate(text.splitlines(), 1) if REPLACEMENT in line]
    assert not bad, bad


def test_gui_strings_are_ascii():
    text = (ROOT / "r2clicker" / "gui.py").read_text(encoding="utf-8")
    bad = [f"{i}: {line.strip()}" for i, line in enumerate(text.splitlines(), 1) if any(ord(c) > 127 for c in line)]
    assert not bad, bad


def test_no_invisible_characters():
    # tools sometimes turn an escape like "\ufeff" into the real, invisible character
    bad = []
    for p in _sources():
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            bad += [f"{p.relative_to(ROOT)}:{i} {name}" for ch, name in INVISIBLE.items() if ch in line]
    assert not bad, bad
