from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml

from .paths import to_posix

DEFAULT_EXCLUDES = [
    "**/.git/**",
    "**/node_modules/**",
    "**/__pycache__/**",
    "**/.venv/**",
    "**/.env",
    "**/.env.*",
]


@dataclass(frozen=True)
class FolderPolicy:
    prefix: str
    role: str
    include: bool | str
    risk: str
    allowed_ops: tuple[str, ...] = ()
    review_required_for: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApplyPolicy:
    mode: str = "dry_run_required"
    require_second_command: bool = True
    direct_edit_allowed_risk_bands: tuple[str, ...] = ("low",)
    high_risk_requires_review: bool = True


@dataclass(frozen=True)
class SearchPolicy:
    generic_anchor_terms: tuple[str, ...] = ("ai", "system", "systems", "intent")
    phrase_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchEvaluationProfile:
    query: str
    relevance_patterns: tuple[str, ...]
    limit: int = 10000
    precision_points: tuple[int, ...] = (10, 25, 50, 100)
    fail_on_misses: bool = False
    min_precision_at: dict[int, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Config:
    path: Path
    vault_root: Path
    state_dir: Path
    apply_policy: ApplyPolicy
    search_policy: SearchPolicy
    search_evaluations: dict[str, SearchEvaluationProfile]
    folders: tuple[FolderPolicy, ...]
    excludes: tuple[str, ...] = field(default_factory=tuple)

    def classify(self, rel_path: str) -> FolderPolicy | None:
        rel = to_posix(rel_path)
        matches = [p for p in self.folders if rel == p.prefix or rel.startswith(p.prefix + "/")]
        if not matches:
            return None
        return sorted(matches, key=lambda p: len(p.prefix), reverse=True)[0]

    def is_excluded(self, rel_path: str) -> bool:
        rel = to_posix(rel_path)
        if Path(rel).name.startswith(".env"):
            return True
        for pattern in self.excludes:
            pat = to_posix(pattern)
            if fnmatch(rel, pat) or fnmatch("/" + rel, pat):
                return True
            if pat.endswith("/**") and (rel == pat[:-3] or rel.startswith(pat[:-3] + "/")):
                return True
        return False

    def is_included(self, rel_path: str) -> bool:
        if self.is_excluded(rel_path):
            return False
        policy = self.classify(rel_path)
        return bool(policy and policy.include in (True, "partial"))


def _tuple(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(str(v) for v in value)


def _int_tuple(value: Any, *, default: tuple[int, ...], context: str) -> tuple[int, ...]:
    if value is None:
        return default
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list of integers")
    return tuple(int(v) for v in value)


def _load_search_evaluations(data: dict[str, Any]) -> dict[str, SearchEvaluationProfile]:
    raw_profiles = data.get("search_evaluations", {}) or {}
    if not isinstance(raw_profiles, dict):
        raise ValueError("search_evaluations must be a mapping of profile names to settings")

    profiles: dict[str, SearchEvaluationProfile] = {}
    for name, raw_profile in raw_profiles.items():
        profile_name = str(name)
        if not profile_name.strip():
            raise ValueError("search_evaluations profile names cannot be blank")
        if not isinstance(raw_profile, dict):
            raise ValueError(f"search_evaluations.{profile_name} must be a mapping")

        query = str(raw_profile.get("query", "")).strip()
        if not query:
            raise ValueError(f"search_evaluations.{profile_name}.query is required")

        relevance_patterns = _tuple(raw_profile.get("relevance_patterns", []))
        if not relevance_patterns:
            raise ValueError(f"search_evaluations.{profile_name}.relevance_patterns must include at least one pattern")

        raw_precision_gates = raw_profile.get("min_precision_at", {}) or {}
        if not isinstance(raw_precision_gates, dict):
            raise ValueError(f"search_evaluations.{profile_name}.min_precision_at must be a mapping")
        min_precision_at = {int(point): float(value) for point, value in raw_precision_gates.items()}
        for point, minimum in min_precision_at.items():
            if point <= 0:
                raise ValueError(f"search_evaluations.{profile_name}.min_precision_at cutoffs must be positive integers")
            if minimum < 0 or minimum > 1:
                raise ValueError(f"search_evaluations.{profile_name}.min_precision_at values must be between 0 and 1")

        profiles[profile_name] = SearchEvaluationProfile(
            query=query,
            relevance_patterns=relevance_patterns,
            limit=int(raw_profile.get("limit", 10000)),
            precision_points=_int_tuple(
                raw_profile.get("precision_points"),
                default=(10, 25, 50, 100),
                context=f"search_evaluations.{profile_name}.precision_points",
            ),
            fail_on_misses=bool(raw_profile.get("fail_on_misses", False)),
            min_precision_at=min_precision_at,
        )
    return profiles


def load_config(path: str | Path) -> Config:
    config_path = Path(path).resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    vault_root = Path(data["vault_root"]).expanduser().resolve()
    state_raw = Path(data.get("state_dir", ".llm-vault-wiki"))
    state_dir = state_raw if state_raw.is_absolute() else (config_path.parent / state_raw)
    apply_data = data.get("apply_policy", {}) or {}
    apply_policy = ApplyPolicy(
        mode=str(apply_data.get("mode", "dry_run_required")),
        require_second_command=bool(apply_data.get("require_second_command", True)),
        direct_edit_allowed_risk_bands=_tuple(apply_data.get("direct_edit_allowed_risk_bands", ["low"])),
        high_risk_requires_review=bool(apply_data.get("high_risk_requires_review", True)),
    )
    search_data = data.get("search_policy", {}) or {}
    search_policy = SearchPolicy(
        generic_anchor_terms=tuple(
            dict.fromkeys(str(term).lower() for term in search_data.get("generic_anchor_terms", SearchPolicy.generic_anchor_terms))
        ),
        phrase_terms=tuple(
            dict.fromkeys(str(term).lower() for term in search_data.get("phrase_terms", SearchPolicy.phrase_terms))
        ),
    )
    folders = []
    for prefix, entry in (data.get("folders", {}) or {}).items():
        entry = entry or {}
        folders.append(FolderPolicy(
            prefix=to_posix(prefix),
            role=str(entry.get("role", prefix)),
            include=entry.get("include", True),
            risk=str(entry.get("risk", "medium")),
            allowed_ops=_tuple(entry.get("allowed_ops", [])),
            review_required_for=_tuple(entry.get("review_required_for", [])),
        ))
    excludes = tuple(dict.fromkeys([*DEFAULT_EXCLUDES, *[to_posix(e) for e in data.get("exclude", []) or []]]))
    return Config(
        path=config_path,
        vault_root=vault_root,
        state_dir=state_dir.resolve(),
        apply_policy=apply_policy,
        search_policy=search_policy,
        search_evaluations=_load_search_evaluations(data),
        folders=tuple(sorted(folders, key=lambda p: p.prefix)),
        excludes=excludes,
    )
