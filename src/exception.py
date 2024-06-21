"""Global exceptions used by the TMS."""

import json
from typing import Any


class TLSError(RuntimeError):
    """Base Class for TLS communication related exceptions."""

    def __init__(self, message: str, detail: Any | None = None):
        """Pretty-printing error message constructor."""
        if detail is None:
            super().__init__(f"{message}")
            return

        try:
            detail = json.loads(detail.content)["detail"]
            super().__init__(f"{message}: {detail}")
        except Exception:
            super().__init__(f"{message} - {detail}")


class TLSCriticalError(TLSError):
    """Critical TLS related errors which should prevent further operation of the TMS."""

    pass
