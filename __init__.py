"""EvalForge Lite.

The modules in this project use flat imports (``import config``) so they run straight from a
checkout. When installed as a package (see pyproject.toml) they all live in this directory, so
put it on ``sys.path`` and the flat imports keep resolving.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
