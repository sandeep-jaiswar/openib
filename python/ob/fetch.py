"""The landing zone: the only part of the system allowed to touch the network.

Determinism rule D1. Fetch writes content-addressed bytes plus a manifest.
Every transform downstream reads the manifest and never the network, which is
what makes a rebuild of 2024 in 2027 produce 2024's answer.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from . import canonical
from .sources import Source

USER_AGENT = "openib/0.1 (+https://github.com/sandeep-jaiswar/openib)"


@dataclass(frozen=True)
class Blob:
    source_id: str
    source_version: str
    endpoint_key: str
    url: str
    sha256: str
    bytes: int
    # fetched_at is provenance, never an input to a transform. Nothing
    # downstream may read it, or the output would depend on wall clock (D4).
    fetched_at: str


class FetchError(RuntimeError):
    pass


def landing_path(root: Path, sha256: str) -> Path:
    return root / "raw" / sha256[:2] / sha256


def manifest_path(root: Path, logical_date: str, source_id: str) -> Path:
    return root / "manifests" / logical_date / f"{source_id}.json"


def fetch_source(
    source: Source,
    *,
    data_root: Path,
    repo_root: Path,
    logical_date: str,
    fetched_at: str,
    offline: bool = False,
) -> list[Blob]:
    blobs: list[Blob] = []
    for endpoint in source.endpoints:
        if source.transport == "file":
            payload = _read_file(repo_root, source, endpoint)
        elif source.transport == "https":
            if offline:
                raise FetchError(
                    f"{source.id}: --offline refuses network transport "
                    f"'{source.transport}'"
                )
            payload = _read_https(endpoint.url)
        else:
            raise FetchError(f"{source.id}: unknown transport {source.transport!r}")

        sha = canonical.sha256_bytes(payload)
        target = landing_path(data_root, sha)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            # Content-addressed, so an existing file with this name already has
            # these exact bytes. Re-fetching the same document is a no-op.
            target.write_bytes(payload)
        blobs.append(
            Blob(
                source_id=source.id,
                source_version=source.source_version,
                endpoint_key=endpoint.key,
                url=endpoint.url,
                sha256=sha,
                bytes=len(payload),
                fetched_at=fetched_at,
            )
        )

    out = manifest_path(data_root, logical_date, source.id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "logical_date": logical_date,
                "source_id": source.id,
                "source_version": source.source_version,
                "blobs": [asdict(b) for b in blobs],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return blobs


def _read_file(repo_root: Path, source: Source, endpoint) -> bytes:
    if not source.root:
        raise FetchError(f"{source.id}: transport 'file' requires a root")
    path = (repo_root / source.root / endpoint.url).resolve()
    fixture_root = (repo_root / source.root).resolve()
    if not path.is_relative_to(fixture_root):
        raise FetchError(f"{source.id}: endpoint {endpoint.key} escapes its root")
    if not path.exists():
        raise FetchError(f"{source.id}: missing fixture {path}")
    return path.read_bytes()


def _read_https(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except urllib.error.URLError as exc:
        raise FetchError(f"{url}: {exc}") from exc


def read_manifests(data_root: Path, logical_date: str) -> list[dict]:
    directory = data_root / "manifests" / logical_date
    if not directory.exists():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.json"))]


def load_blob(data_root: Path, sha256: str) -> bytes:
    path = landing_path(data_root, sha256)
    if not path.exists():
        raise FetchError(f"blob {sha256} is not in the landing zone")
    actual = canonical.sha256_file(path)
    if actual != sha256:
        # The landing zone is immutable by construction; a mismatch means it was
        # edited underneath us and nothing downstream can be trusted.
        raise FetchError(f"blob {sha256} is corrupt (hashes to {actual})")
    return path.read_bytes()
