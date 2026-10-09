"""Declarative source registry.

A source is a TOML file in sources/. Nothing about a source lives in code: the
transport, the endpoints, the version string and the profiles it belongs to are
all data, so adding a source is a reviewable diff rather than a patch to the
ingest engine.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Endpoint:
    key: str
    url: str


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    publisher: str
    transport: str
    version: str
    profiles: tuple[str, ...]
    endpoints: tuple[Endpoint, ...]
    # Recorded for provenance and for the licensing question we have
    # deliberately deferred (see docs/non-goals.md). Nothing gates on it.
    terms_url: str | None = None
    root: str | None = None
    requires_credential: bool = False

    @property
    def source_version(self) -> str:
        return f"{self.id}@{self.version}"


def load(registry_dir: Path) -> list[Source]:
    sources: list[Source] = []
    for path in sorted(registry_dir.glob("*.toml")):
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
        missing = {"id", "name", "publisher", "transport", "version"} - raw.keys()
        if missing:
            raise ValueError(f"{path.name}: missing required keys {sorted(missing)}")
        if raw["id"] != path.stem:
            raise ValueError(f"{path.name}: id {raw['id']!r} must match the filename")
        sources.append(
            Source(
                id=raw["id"],
                name=raw["name"],
                publisher=raw["publisher"],
                transport=raw["transport"],
                version=raw["version"],
                profiles=tuple(raw.get("profiles", ())),
                endpoints=tuple(
                    Endpoint(key=e["key"], url=e["url"]) for e in raw.get("endpoints", ())
                ),
                terms_url=raw.get("terms_url"),
                root=raw.get("root"),
                requires_credential=bool(raw.get("requires_credential", False)),
            )
        )
    if not sources:
        raise ValueError(f"no sources found in {registry_dir}")
    return sources


def for_profile(registry_dir: Path, profile: str) -> list[Source]:
    selected = [s for s in load(registry_dir) if profile in s.profiles]
    if not selected:
        known = sorted({p for s in load(registry_dir) for p in s.profiles})
        raise ValueError(f"profile {profile!r} selects no sources; known profiles: {known}")
    return selected
