from __future__ import annotations

from pathlib import Path


def to_posix(path: str | Path) -> str:
    return str(path).replace("\\", "/").strip("/")


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def vault_relative(path: Path, vault_root: Path) -> str:
    resolved = path.resolve()
    root = vault_root.resolve()
    if not is_relative_to(resolved, root):
        raise ValueError(f"Path escapes vault root: {path}")
    return to_posix(resolved.relative_to(root))


def resolve_vault_path(value: str | Path, vault_root: Path) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = vault_root / candidate
    resolved = candidate.resolve()
    if not is_relative_to(resolved, vault_root.resolve()):
        raise ValueError(f"Path escapes vault root: {value}")
    return resolved
