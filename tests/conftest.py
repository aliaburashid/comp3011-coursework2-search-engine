"""Put ``src`` on the path so tests can ``import indexer`` without installing the package."""
# When pytest runs, also look inside the src folder for Python files.

from __future__ import annotations

import sys
from pathlib import Path

# gets the location of conftest.py, then goes up from tests/ to the project root, then into src
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    # adds that folder to Python’s import path if it is not already there
    sys.path.insert(0, str(_SRC))
