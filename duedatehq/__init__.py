from __future__ import annotations

from pathlib import Path
from pkgutil import extend_path

_ROOT = Path(__file__).resolve().parent
_SRC_PACKAGE = _ROOT.parent / "src" / "duedatehq"

__path__ = extend_path(__path__, __name__)
if _SRC_PACKAGE.exists():
    __path__.append(str(_SRC_PACKAGE))

from .app import create_app  # noqa: E402

__all__ = ["create_app"]

