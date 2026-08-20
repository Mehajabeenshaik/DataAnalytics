"""
DataAnalytics backend application package.

The flat modules (auth.py, config.py, agent_phase2.py, ...) were moved here
during the frontend/backend restructure. They use absolute imports like
``from config import ...`` and ``from tenant import ...``, so this package
adds its own directory to ``sys.path`` to keep those imports working without
rewriting every module (behavior preserved).
"""

import os
import sys

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)