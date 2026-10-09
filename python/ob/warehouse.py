"""Transforms: landing zone -> bronze -> silver -> ontology.

Nothing in this module may open a socket, read the clock, or read the
environment. Everything it needs arrives as an argument (D1, D4). That
restriction is what makes `ob rebuild` in 2027 reproduce 2024 byte for byte.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import canonical, fetch
from .ontology import Ontology

BRONZE = "bronze"
SILVER = "silver"
OBJECTS = "objects"
LINKS = "links"


class TransformError(RuntimeError):
    pass


def issuer_key(*, lei: str | None, cik: str | None) -> str:
    """Rule-based identity resolution.

    Deliberately boring: prefer the LEI, fall back to the CIK, and refuse to
    guess. A fuzzy name match would resolve more issuers and make the pipeline
    irreproducible, so ambiguous cases belong in a review queue instead
    (docs/adr/0004-rule-based-identity-resolution.md).
    """
    if lei:
        return f"lei:{lei.strip().upper()}"
    if cik:
        return f"cik:{str(cik).strip().lstrip('0').zfill(10)}"
    raise TransformError("cannot key an issuer with neither LEI nor CIK")


def _decimal(value) -> Decimal:
    if isinstance(value, bool):
        raise TransformError(f"boolean is not a measure: {value!r}")
    try:
        # str() first: Decimal(float) would bake in binary rounding error.
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise TransformError(f"not a decimal value: {value!r}") from exc


def extract_companyfacts(payload: bytes, *, provenance_sha256: str) -> list[dict]:
    """Flatten one SEC `companyfacts` document into bronze fact occurrences.

    This is the real SEC shape, so the same code path serves the vendored
    fixture and the live endpoint.
    """
    document = json.loads(payload)
    cik = document.get("cik")
    entity_name = document.get("entityName")
    if cik is None or not entity_name:
        raise TransformError("companyfacts document has no cik/entityName")

    key = issuer_key(lei=document.get("lei"), cik=cik)
    rows: list[dict] = []
    for taxonomy, concepts in sorted(document.get("facts", {}).items()):
        for concept, spec in sorted(concepts.items()):
            for unit, observations in sorted(spec.get("units", {}).items()):
                for obs in observations:
                    accession = obs.get("accn")
                    filed = obs.get("filed")
                    end = obs.get("end")
                    if not (accession and filed and end):
                        # Without an accession and a filed date we cannot say
                        # when this became knowable, so it cannot be loaded
                        # bitemporally. Dropping it is the honest option.
                        continue
                    rows.append(
                        {
                            "issuer_key": key,
                            "entity_name": entity_name,
                            "cik": str(cik),
                            "taxonomy": taxonomy,
                            "concept": concept,
                            "unit": unit,
                            "value": _decimal(obs["val"]),
                            "valid_from": obs.get("start") or end,
                            "valid_to": end,
                            "knowledge_time": filed,
                            "accession_number": accession,
                            "form": obs.get("form"),
                            "fiscal_year": obs.get("fy"),
                            "fiscal_period": obs.get("fp"),
                            "periodicity": "duration" if obs.get("start") else "instant",
                            "provenance_sha256": provenance_sha256,
                        }
                    )
    return rows


def build(
    *,
    data_root: Path,
    logical_date: str,
    ontology: Ontology,
) -> dict[str, str]:
    """Run every transform for one logical date. Returns table -> SHA-256."""
    manifests = fetch.read_manifests(data_root, logical_date)
    if not manifests:
        raise TransformError(
            f"no manifests for {logical_date}; run the fetch step first"
        )

    bronze_facts: list[dict] = []
    for manifest in manifests:
        if manifest["source_id"] not in {"sec-edgar-companyfacts", "fixture-companyfacts"}:
            # P1 adds GLEIF, OpenFIGI, FRED, Treasury and ECB transforms. A
            # manifest with no transform is skipped loudly rather than
            # silently: the run receipt records what was and was not consumed.
            continue
        for blob in manifest["blobs"]:
            payload = fetch.load_blob(data_root, blob["sha256"])
            bronze_facts.extend(
                extract_companyfacts(payload, provenance_sha256=blob["sha256"])
            )

    warehouse = data_root / "warehouse"
    hashes: dict[str, str] = {}

    hashes[f"{BRONZE}.companyfacts"] = canonical.write_table(
        warehouse / BRONZE / "companyfacts.jsonl",
        bronze_facts,
        ["issuer_key", "taxonomy", "concept", "unit", "valid_from", "valid_to",
         "knowledge_time", "accession_number"],
    )

    spec = ontology.objects["FinancialFact"]
    silver_facts = [
        {prop.name: row[prop.name] for prop in spec.properties if prop.name in row}
        | {
            "valid_from": row["valid_from"],
            "valid_to": row["valid_to"],
            "knowledge_time": row["knowledge_time"],
        }
        for row in bronze_facts
    ]
    hashes[f"{SILVER}.financial_fact"] = canonical.write_table(
        warehouse / SILVER / "financial_fact.jsonl",
        _dedupe(silver_facts, spec.primary_key),
        list(spec.sort_key),
    )

    issuers = _dedupe(
        [
            {
                "issuer_key": row["issuer_key"],
                "name": row["entity_name"],
                "cik": row["cik"],
                "lei": None,
                "jurisdiction": None,
            }
            for row in bronze_facts
        ],
        ("issuer_key",),
    )
    hashes[f"{OBJECTS}.issuer"] = canonical.write_table(
        warehouse / OBJECTS / "issuer.jsonl", issuers, ["issuer_key"]
    )

    filings = _dedupe(
        [
            {
                "accession_number": row["accession_number"],
                "issuer_key": row["issuer_key"],
                "form": row["form"],
                "filed_date": row["knowledge_time"],
                "fiscal_year": row["fiscal_year"],
                "fiscal_period": row["fiscal_period"],
            }
            for row in bronze_facts
        ],
        ("accession_number",),
    )
    hashes[f"{OBJECTS}.filing"] = canonical.write_table(
        warehouse / OBJECTS / "filing.jsonl", filings, ["accession_number"]
    )

    hashes[f"{LINKS}.filedBy"] = canonical.write_table(
        warehouse / LINKS / "filed_by.jsonl",
        _dedupe(
            [
                {"accession_number": f["accession_number"], "issuer_key": f["issuer_key"]}
                for f in filings
            ],
            ("accession_number", "issuer_key"),
        ),
        ["accession_number", "issuer_key"],
    )

    hashes[f"{LINKS}.reportsFact"] = canonical.write_table(
        warehouse / LINKS / "reports_fact.jsonl",
        _dedupe(
            [
                {
                    "accession_number": row["accession_number"],
                    "issuer_key": row["issuer_key"],
                    "concept": row["concept"],
                    "unit": row["unit"],
                    "valid_to": row["valid_to"],
                }
                for row in bronze_facts
            ],
            ("accession_number", "issuer_key", "concept", "unit", "valid_to"),
        ),
        ["accession_number", "issuer_key", "concept", "unit", "valid_to"],
    )

    return hashes


def _dedupe(rows: list[dict], key: tuple[str, ...]) -> list[dict]:
    """Last-write-wins on an explicit key, with a deterministic ordering first.

    Two identical keys from one run mean the source repeated itself; sorting
    before the collapse means which copy survives does not depend on
    dict or filesystem iteration order.
    """
    seen: dict[tuple, dict] = {}
    for row in sorted(rows, key=lambda r: canonical.sort_key(r, key)):
        seen[tuple(canonical.orderable(row.get(k)) for k in key)] = row
    return list(seen.values())


def as_of(
    facts: list[dict], *, knowledge_date: str
) -> list[dict]:
    """"As we knew it on date X."

    The query that bitemporality exists to answer: for each
    (issuer, concept, unit, period), the latest value whose knowledge_time is
    on or before X. A restatement filed after X is invisible here, which is the
    whole point (D2).
    """
    latest: dict[tuple, dict] = {}
    for fact in sorted(
        (f for f in facts if f["knowledge_time"] <= knowledge_date),
        key=lambda f: (f["knowledge_time"], f["accession_number"]),
    ):
        latest[
            (fact["issuer_key"], fact["concept"], fact["unit"],
             fact["valid_from"], fact["valid_to"])
        ] = fact
    return sorted(
        latest.values(),
        key=lambda f: canonical.sort_key(
            f, ["issuer_key", "concept", "unit", "valid_from", "valid_to"]
        ),
    )
