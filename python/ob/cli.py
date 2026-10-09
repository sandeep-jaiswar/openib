"""`ob` — the whole pipeline, one command.

No Postgres, no Kafka, no object store, no credentials. The scheduler is
optional and only ever shells out to this CLI, which is what keeps `cron` on a
laptop and CI on a runner producing the same bytes.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from . import canonical, fetch, ontology as ontology_mod, sources, warehouse

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = REPO_ROOT / "data"
ONTOLOGY_PATH = REPO_ROOT / "ontology" / "v1.toml"
SOURCES_DIR = REPO_ROOT / "sources"
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"


def _git_sha() -> str:
    git = shutil.which("git")
    if not git:
        return "unknown"
    try:
        out = subprocess.run(
            [git, "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def _logical_date(raw: str | None) -> str:
    if raw:
        try:
            return date.fromisoformat(raw).isoformat()
        except ValueError:
            raise SystemExit(f"--date must be YYYY-MM-DD, got {raw!r}")
    # The logical date is injected, never read from the clock inside a
    # transform. Defaulting it here, at the edge, is the one place a wall-clock
    # read is allowed (D4).
    return date.today().isoformat()


def _receipt_path(data_root: Path, logical_date: str) -> Path:
    return data_root / "runs" / f"{logical_date}.json"


def cmd_run(args: argparse.Namespace) -> int:
    data_root = Path(args.data_root)
    logical_date = _logical_date(args.date)
    onto = ontology_mod.load(ONTOLOGY_PATH)
    selected = sources.for_profile(SOURCES_DIR, args.profile)

    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    manifest_hashes: dict[str, list[str]] = {}
    skipped: list[str] = []
    for source in selected:
        if source.requires_credential and not args.allow_credentialed:
            # Off by default, and does nothing unless the operator already has
            # the entitlement. A pipeline other people can run cannot depend on
            # a seat they do not have.
            skipped.append(source.id)
            continue
        blobs = fetch.fetch_source(
            source,
            data_root=data_root,
            repo_root=REPO_ROOT,
            logical_date=logical_date,
            fetched_at=fetched_at,
            offline=args.offline,
        )
        manifest_hashes[source.id] = sorted(b.sha256 for b in blobs)
        print(f"fetched {source.id}: {len(blobs)} blob(s)")

    table_hashes = warehouse.build(
        data_root=data_root, logical_date=logical_date, ontology=onto
    )

    receipt = {
        # Pinned inputs, rule D3. Everything needed to explain this output.
        "logical_date": logical_date,
        "profile": args.profile,
        "git_sha": _git_sha(),
        "ontology_version": onto.version,
        "source_versions": {s.id: s.source_version for s in selected},
        "manifest_sha256": manifest_hashes,
        "skipped_sources": sorted(skipped),
        "table_sha256": table_hashes,
        "run_sha256": canonical.sha256_bytes(
            canonical.dumps(dict(sorted(table_hashes.items()))).encode("utf-8")
        ),
    }
    out = _receipt_path(data_root, logical_date)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for table, digest in sorted(table_hashes.items()):
        print(f"  {table:<28} {digest}")
    print(f"run {logical_date} -> {receipt['run_sha256']}")
    if skipped:
        print(f"skipped (needs credentials): {', '.join(sorted(skipped))}")
    return 0


def cmd_rebuild(args: argparse.Namespace) -> int:
    """Re-run transforms over existing manifests. Never re-fetches.

    This is the command that proves D1: the landing zone is the input, so a
    rebuild cannot produce a different answer just because a publisher changed
    a document after the fact.
    """
    data_root = Path(args.data_root)
    onto = ontology_mod.load(ONTOLOGY_PATH)
    dates = sorted(p.name for p in (data_root / "manifests").glob("*") if p.is_dir())
    if args.since:
        dates = [d for d in dates if d >= args.since]
    if not dates:
        print("nothing to rebuild: no manifests found", file=sys.stderr)
        return 1
    for logical_date in dates:
        hashes = warehouse.build(
            data_root=data_root, logical_date=logical_date, ontology=onto
        )
        run_sha = canonical.sha256_bytes(
            canonical.dumps(dict(sorted(hashes.items()))).encode("utf-8")
        )
        print(f"rebuilt {logical_date} -> {run_sha}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Golden-hash determinism check (D5).

    Rebuilds the date from the landing zone and compares every table hash to
    the committed golden file. A drifting hash is a build failure, not a
    discussion.
    """
    data_root = Path(args.data_root)
    logical_date = _logical_date(args.date)
    onto = ontology_mod.load(ONTOLOGY_PATH)
    actual = warehouse.build(
        data_root=data_root, logical_date=logical_date, ontology=onto
    )

    golden_file = GOLDEN_DIR / f"{args.profile}-{logical_date}.json"
    if args.update:
        golden_file.parent.mkdir(parents=True, exist_ok=True)
        golden_file.write_text(
            json.dumps(dict(sorted(actual.items())), indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote golden hashes to {golden_file.relative_to(REPO_ROOT)}")
        return 0

    if not golden_file.exists():
        print(
            f"no golden file at {golden_file.relative_to(REPO_ROOT)}; "
            "create it with `ob verify --update`",
            file=sys.stderr,
        )
        return 1

    expected = json.loads(golden_file.read_text(encoding="utf-8"))
    drifted = sorted(
        set(expected) | set(actual),
        key=str,
    )
    failures = [t for t in drifted if expected.get(t) != actual.get(t)]
    for table in drifted:
        mark = "FAIL" if table in failures else "ok"
        print(f"  [{mark:>4}] {table}")
        if table in failures:
            print(f"         expected {expected.get(table)}")
            print(f"         actual   {actual.get(table)}")
    if failures:
        print(f"\n{len(failures)} table(s) drifted from the golden hashes", file=sys.stderr)
        return 1
    print(f"\nall {len(drifted)} table(s) byte-identical to golden")
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    """Point-in-time read of the ontology.

    P0 answers the one query bitemporality exists for. The DataFusion/DuckDB
    engine and Flight SQL serving layer are P2.
    """
    data_root = Path(args.data_root)
    facts = canonical.read_table(
        data_root / "warehouse" / "silver" / "financial_fact.jsonl"
    )
    if not facts:
        print("warehouse is empty; run `ob run` first", file=sys.stderr)
        return 1
    rows = warehouse.as_of(facts, knowledge_date=args.as_of or date.today().isoformat())
    if args.issuer:
        rows = [r for r in rows if r["issuer_key"] == args.issuer]
    if args.concept:
        rows = [r for r in rows if r["concept"] == args.concept]
    for row in rows[: args.limit]:
        print(
            f"{row['issuer_key']:<18} {row['concept']:<34} "
            f"{row['valid_from']}..{row['valid_to']} "
            f"{row['value']:>22} {row['unit']:<6} "
            f"(knew {row['knowledge_time']}, {row['accession_number']})"
        )
    print(f"\n{len(rows)} fact(s) as of {args.as_of or 'today'}")
    return 0


def cmd_ontology(args: argparse.Namespace) -> int:
    onto = ontology_mod.load(ONTOLOGY_PATH)
    print(ontology_mod.describe(onto))
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    for source in sources.load(SOURCES_DIR):
        flags = []
        if source.requires_credential:
            flags.append("needs-credential")
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        print(
            f"{source.id:<28} {source.transport:<6} "
            f"profiles={','.join(source.profiles) or '-':<14} "
            f"{len(source.endpoints)} endpoint(s){suffix}"
        )
        print(f"{'':<28} {source.name} — {source.publisher}")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    data_root = Path(args.data_root)
    if data_root.exists():
        shutil.rmtree(data_root)
        print(f"removed {data_root}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ob", description="Open Investment Bank pipeline"
    )
    parser.add_argument(
        "--data-root",
        default=os.environ.get("OB_DATA_ROOT", str(DEFAULT_DATA_ROOT)),
        help="warehouse and landing-zone root (default: ./data)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="fetch and transform one logical date")
    run.add_argument("--date")
    run.add_argument("--profile", default="fixture")
    run.add_argument(
        "--offline",
        action="store_true",
        help="refuse network transports; fixture sources only",
    )
    run.add_argument(
        "--allow-credentialed",
        action="store_true",
        help="include sources that need an entitlement the operator must already hold",
    )
    run.set_defaults(func=cmd_run)

    rebuild = sub.add_parser("rebuild", help="re-run transforms from the landing zone")
    rebuild.add_argument("--since", help="earliest logical date to rebuild")
    rebuild.set_defaults(func=cmd_rebuild)

    verify = sub.add_parser("verify", help="golden-hash determinism check")
    verify.add_argument("--date")
    verify.add_argument("--profile", default="fixture")
    verify.add_argument("--update", action="store_true", help="rewrite the golden file")
    verify.set_defaults(func=cmd_verify)

    query = sub.add_parser("query", help="point-in-time read of the ontology")
    query.add_argument("--as-of", help="knowledge date, YYYY-MM-DD")
    query.add_argument("--issuer")
    query.add_argument("--concept")
    query.add_argument("--limit", type=int, default=25)
    query.set_defaults(func=cmd_query)

    sub.add_parser("ontology", help="describe the ontology").set_defaults(
        func=cmd_ontology
    )
    sub.add_parser("sources", help="list the source registry").set_defaults(
        func=cmd_sources
    )
    sub.add_parser("reset", help="delete the data root").set_defaults(func=cmd_reset)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (fetch.FetchError, warehouse.TransformError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
