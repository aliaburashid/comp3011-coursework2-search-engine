"""Put ``src`` on the path so tests can ``import indexer`` without installing the package."""

# allows newer type hint styles to work on older Python versions
# Docs: https://peps.python.org/pep-0563/
from __future__ import annotations

# sys.path is the list of folders Python searches when you do an import
# Docs: https://docs.python.org/3/library/sys.html#sys.path
import sys

# Path gives us a clean way to work with file and folder paths
# Docs: https://docs.python.org/3/library/pathlib.html
from pathlib import Path


def _find_src_dir() -> Path:
    """
    Resolve ``src/`` relative to this file, not the process cwd.

    Walk upward from ``tests/`` until we see ``src/indexer.py`` so imports stay
    correct whether pytest is started from the repo root, ``tests/``, or elsewhere.
    """
    # start from the folder that contains this conftest.py file
    # .resolve() gives us the absolute path so there are no surprises
    # Docs: https://docs.python.org/3/library/pathlib.html#pathlib.Path.resolve
    start = Path(__file__).resolve().parent

    # walk upward through parent folders until we find one that contains src/indexer.py
    for root in (start, *start.parents):
        candidate = root / "src" / "indexer.py"
        # .is_file() returns True if the file exists at that path
        # Docs: https://docs.python.org/3/library/pathlib.html#pathlib.Path.is_file
        if candidate.is_file():
            return root / "src"

    # if we reach the top of the filesystem without finding it, raise a clear error
    raise RuntimeError(
        "tests/conftest.py: could not locate project src/ (expected src/indexer.py in a parent directory)."
    )


# find the src/ folder and store its path
_SRC = _find_src_dir()

# only add it to sys.path if it is not already there, to avoid duplicates
if str(_SRC) not in sys.path:
    # insert at position 0 so our src/ folder is checked before any installed packages
    # Docs: https://docs.python.org/3/library/sys.html#sys.path
    sys.path.insert(0, str(_SRC))