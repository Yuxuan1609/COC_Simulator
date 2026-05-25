"""frontend/routers/files.py — File browser API for navigating project directories."""
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, Query, HTTPException

router = APIRouter(prefix="/api/files", tags=["files"])

ALLOWED_EXTENSIONS = {".json", ".docx", ".txt", ".pdf", ".md"}
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _safe_dir(directory: str) -> Path:
    raw = (PROJECT_ROOT / directory).resolve()
    if not str(raw).startswith(str(PROJECT_ROOT.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal denied")
    if not raw.is_dir():
        raise HTTPException(status_code=404, detail=f"Not a directory: {directory}")
    return raw


@router.get("")
async def list_files(dir: str = Query(default="data")):
    base = _safe_dir(dir)
    items = list(base.iterdir())
    dirs = sorted(
        [{"name": d.name, "path": str(d.relative_to(PROJECT_ROOT)), "ext": d.suffix}
         for d in items if d.is_dir() and not d.name.startswith(".")],
        key=lambda x: x["name"],
    )
    files = sorted(
        [{"name": f.name, "path": str(f.relative_to(PROJECT_ROOT)), "ext": f.suffix}
         for f in items if f.is_file() and f.suffix in ALLOWED_EXTENSIONS],
        key=lambda x: x["name"],
    )
    parent = str(base.parent.relative_to(PROJECT_ROOT)) if base != PROJECT_ROOT else None
    current = str(base.relative_to(PROJECT_ROOT))
    return {"dirs": dirs, "files": files, "parent": parent, "current": current}
