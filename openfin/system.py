from __future__ import annotations

from openfin.storage import OpenFinStore
from openfin.ui import console


def init() -> None:
    """Create the local OpenFin plain-text store."""
    store = OpenFinStore.from_env()
    store.ensure_layout()
    console.print(f"OpenFin ready at {store.root}")
