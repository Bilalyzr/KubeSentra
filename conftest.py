"""Repository-root conftest: make the repo root importable for pytest.

The project is also installed editable (pip install -e .[dev]); this keeps
tests working even when run from a checkout without installation.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
