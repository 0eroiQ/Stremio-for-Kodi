"""Kodi entry-point bootstrap for the organized core runtime."""
from pathlib import Path
import runpy
import sys

CORE = Path(__file__).resolve().parent / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))
runpy.run_path(str(CORE / Path(__file__).name), run_name="__main__")
