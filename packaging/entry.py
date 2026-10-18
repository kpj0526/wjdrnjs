"""PyInstaller entry point (a plain script; the package itself is imported normally)."""
import sys

from r2clicker.__main__ import run

if __name__ == "__main__":
    sys.exit(run())
