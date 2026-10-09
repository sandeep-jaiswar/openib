"""The ontology definition layer.

Object types, link types and properties are declared once, in
ontology/v1.toml, with units, currency and periodicity attached. This module
loads and validates that declaration.

P0 validates and serves the declaration. Code generation — typed Rust/Python
accessors, Iceberg DDL and the serving schema all emitted from this one file —
is P2 and belongs to the Ontology Engineer. The point of landing the
declaration first is that the schema stops living in people's heads before
anyone writes a transform against it.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

SCALAR_TYPES = {"string", "integer", "decimal", "date", "timestamp", "boolean"}
PERIODICITIES = {"instant", "duration", "daily", "monthly", "quarterly", "annual"}


@dataclass(frozen=True)
class Property:
    name: str
    type: str
    required: bool = False
    unit: str | None = None
    currency: bool = False
    periodicity: str | None = None


@dataclass(frozen=True)
class ObjectType:
    name: str
    primary_key: tuple[str, ...]
    identity_anchor: str | None
    properties: tuple[Property, ...]
    sort_key: tuple[str, ...]
    bitemporal: bool = False


@dataclass(frozen=True)
class LinkType:
    name: str
    source: str
    target: str
    cardinality: str


@dataclass(frozen=True)
class Ontology:
    version: str
    objects: dict[str, ObjectType]
    links: dict[str, LinkType]


def load(path: Path) -> Ontology:
    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    objects: dict[str, ObjectType] = {}
    for name, spec in raw.get("object", {}).items():
        props = tuple(
            Property(
                name=p["name"],
                type=p["type"],
                required=bool(p.get("required", False)),
                unit=p.get("unit"),
                currency=bool(p.get("currency", False)),
                periodicity=p.get("periodicity"),
            )
            for p in spec.get("property", [])
        )
        for prop in props:
            if prop.type not in SCALAR_TYPES:
                raise ValueError(f"{name}.{prop.name}: unknown type {prop.type!r}")
            if prop.periodicity and prop.periodicity not in PERIODICITIES:
                raise ValueError(
                    f"{name}.{prop.name}: unknown periodicity {prop.periodicity!r}"
                )
        primary_key = tuple(spec["primary_key"])
        declared = {p.name for p in props}
        bitemporal = bool(spec.get("bitemporal", False))
        temporal = {"valid_from", "valid_to", "knowledge_time"} if bitemporal else set()
        for key in primary_key:
            if key not in declared | temporal:
                raise ValueError(f"{name}: primary key {key!r} is not a declared property")
        objects[name] = ObjectType(
            name=name,
            primary_key=primary_key,
            identity_anchor=spec.get("identity_anchor"),
            properties=props,
            sort_key=tuple(spec.get("sort_key", primary_key)),
            bitemporal=bitemporal,
        )

    links: dict[str, LinkType] = {}
    for name, spec in raw.get("link", {}).items():
        for end in ("source", "target"):
            if spec[end] not in objects:
                raise ValueError(f"link {name}: {end} {spec[end]!r} is not an object type")
        links[name] = LinkType(
            name=name,
            source=spec["source"],
            target=spec["target"],
            cardinality=spec.get("cardinality", "many_to_many"),
        )

    if not objects:
        raise ValueError(f"{path}: no object types declared")
    return Ontology(version=raw["version"], objects=objects, links=links)


def describe(ontology: Ontology) -> str:
    lines = [f"ontology v{ontology.version}", ""]
    lines.append(f"{len(ontology.objects)} object types:")
    for name, obj in sorted(ontology.objects.items()):
        anchor = f" anchor={obj.identity_anchor}" if obj.identity_anchor else ""
        temporal = " bitemporal" if obj.bitemporal else ""
        lines.append(
            f"  {name:<16} pk=({', '.join(obj.primary_key)})"
            f" props={len(obj.properties)}{anchor}{temporal}"
        )
    lines.append("")
    lines.append(f"{len(ontology.links)} link types:")
    for name, link in sorted(ontology.links.items()):
        lines.append(f"  {name:<16} {link.source} -> {link.target} ({link.cardinality})")
    return "\n".join(lines)
