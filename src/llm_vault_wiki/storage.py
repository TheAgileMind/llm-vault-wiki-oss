from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_state_dirs(state_dir: Path) -> None:
    for name in ("manifests", "generated", "runs"):
        (state_dir / name).mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=_json_default) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def create_run_dir(state_dir: Path, prefix: str) -> Path:
    base = state_dir / "runs"
    base.mkdir(parents=True, exist_ok=True)
    stamp = utc_stamp()
    run_dir = base / f"{stamp}-{prefix}"
    counter = 1
    while run_dir.exists():
        counter += 1
        run_dir = base / f"{stamp}-{prefix}-{counter}"
    run_dir.mkdir(parents=True)
    return run_dir
