"""Path safety helpers."""
from pathlib import Path

from app.config import OUTPUT_DIR


# ------------------------------------------------------------------- endpoints
def inside_outputs(raw: str) -> Path:
    p = Path(raw).resolve()
    p.relative_to(OUTPUT_DIR.resolve())
    return p
