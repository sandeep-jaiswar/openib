"""Canonical serialisation primitives.

Everything the pipeline writes goes through this module. The determinism
contract (docs/determinism.md, rules D4 and D5) depends on there being exactly
one way to turn a record into bytes.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any, Iterable, Mapping


class CanonicalEncoder(json.JSONEncoder):
    """Rejects anything whose byte representation is not pinned.

    Floats are refused outright: 0.1 + 0.2 is not a number we are willing to
    write to disk and then hash. Money and quantities arrive as Decimal and
    leave as their exact decimal string (D4).
    """

    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return format(o, "f")
        raise TypeError(f"{type(o).__name__} has no canonical form: {o!r}")

    def encode(self, o: Any) -> str:
        _reject_floats(o)
        return super().encode(o)


def _reject_floats(o: Any, path: str = "$") -> None:
    if isinstance(o, float):
        raise TypeError(
            f"float at {path} is not canonically representable; "
            "use decimal.Decimal for money and quantities"
        )
    if isinstance(o, Mapping):
        for k, v in o.items():
            _reject_floats(v, f"{path}.{k}")
    elif isinstance(o, (list, tuple)):
        for i, v in enumerate(o):
            _reject_floats(v, f"{path}[{i}]")


def dumps(record: Mapping[str, Any]) -> str:
    """One record, one line, keys sorted, no insignificant whitespace."""
    return json.dumps(record, cls=CanonicalEncoder, sort_keys=True, separators=(",", ":"))


def sort_key(record: Mapping[str, Any], keys: Iterable[str]) -> tuple:
    """Total order over records.

    Dict iteration order, filesystem order and set order are all unstable
    across runs and Python versions. Every table declares an explicit sort key
    and we sort on it before writing, so the output byte stream is a function of
    the record set alone.
    """
    return tuple(orderable(record.get(k)) for k in keys)


def orderable(value: Any) -> tuple[int, Any]:
    # Tag by type so None and mixed types never raise on comparison.
    if value is None:
        return (0, "")
    if isinstance(value, bool):
        return (1, int(value))
    if isinstance(value, int):
        return (2, value)
    if isinstance(value, Decimal):
        return (2, value)
    return (3, str(value))


def write_table(path, records: Iterable[Mapping[str, Any]], sort_keys: list[str]) -> str:
    """Write a sorted canonical JSONL table. Returns its SHA-256.

    JSONL is the P0 sink, not the destination. See
    docs/adr/0006-jsonl-sink-before-parquet.md: the canonical-bytes guarantee
    lives here so that swapping in Parquet/Iceberg is a sink change rather than
    a determinism change.
    """
    rows = sorted(records, key=lambda r: sort_key(r, sort_keys))
    digest = hashlib.sha256()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        for row in rows:
            line = (dumps(row) + "\n").encode("utf-8")
            digest.update(line)
            fh.write(line)
    return digest.hexdigest()


def read_table(path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
