"""The determinism contract, as tests.

Each test names the rule from docs/determinism.md that it pins down. These use
unittest so they run under `python -m unittest` with no dependencies at all,
and under pytest in CI.
"""

from __future__ import annotations

import ast
import json
import shutil
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))

from ob import canonical, fetch, ontology as ontology_mod, sources, warehouse  # noqa: E402
from ob.cli import main  # noqa: E402

LOGICAL_DATE = "2026-10-09"


class RunHarness(unittest.TestCase):
    """Runs the real pipeline into a throwaway data root."""

    def setUp(self) -> None:
        self.data_root = Path(tempfile.mkdtemp(prefix="ob-test-"))
        self.addCleanup(shutil.rmtree, self.data_root, ignore_errors=True)
        self.ontology = ontology_mod.load(REPO_ROOT / "ontology" / "v1.toml")

    def run_pipeline(self, fetched_at: str = "2026-10-09T06:15:00+00:00") -> dict[str, str]:
        for source in sources.for_profile(REPO_ROOT / "sources", "fixture"):
            fetch.fetch_source(
                source,
                data_root=self.data_root,
                repo_root=REPO_ROOT,
                logical_date=LOGICAL_DATE,
                fetched_at=fetched_at,
            )
        return warehouse.build(
            data_root=self.data_root,
            logical_date=LOGICAL_DATE,
            ontology=self.ontology,
        )


class TestD1RawImmutability(RunHarness):
    def test_landing_zone_is_content_addressed(self) -> None:
        self.run_pipeline()
        blobs = sorted((self.data_root / "raw").rglob("*"))
        files = [b for b in blobs if b.is_file()]
        self.assertTrue(files)
        for blob in files:
            self.assertEqual(blob.name, canonical.sha256_file(blob))

    def test_corrupt_blob_is_refused(self) -> None:
        self.run_pipeline()
        blob = next(p for p in (self.data_root / "raw").rglob("*") if p.is_file())
        blob.write_bytes(b'{"cik": 1, "entityName": "TAMPERED", "facts": {}}')
        with self.assertRaises(fetch.FetchError):
            warehouse.build(
                data_root=self.data_root,
                logical_date=LOGICAL_DATE,
                ontology=self.ontology,
            )

    def test_transform_module_cannot_reach_the_network(self) -> None:
        """Static guard, because a runtime test cannot prove absence.

        The transform layer is only allowed the two landing-zone readers. If
        someone adds `urllib` or `requests` to warehouse.py, the determinism
        contract is broken whether or not the current fixtures notice.
        """
        source = (REPO_ROOT / "python" / "ob" / "warehouse.py").read_text()
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        forbidden = {"urllib", "http", "socket", "requests", "httpx", "os", "time", "random"}
        self.assertEqual(imported & forbidden, set())

    def test_transform_reads_only_the_landing_zone(self) -> None:
        source = (REPO_ROOT / "python" / "ob" / "warehouse.py").read_text()
        used = {
            node.attr
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "fetch"
        }
        self.assertTrue(used, "transform no longer reads the landing zone at all")
        self.assertLessEqual(used, {"read_manifests", "load_blob", "FetchError"})


class TestD2Bitemporality(RunHarness):
    def test_restatement_does_not_rewrite_history(self) -> None:
        self.run_pipeline()
        facts = canonical.read_table(
            self.data_root / "warehouse" / "silver" / "financial_fact.jsonl"
        )
        fy2024 = [
            f
            for f in facts
            if f["issuer_key"] == "cik:0000320193"
            and f["concept"] == "Revenues"
            and f["valid_to"] == "2024-09-28"
        ]
        # The original 10-K and the 2026 10-K/A are both retained.
        self.assertEqual(len(fy2024), 2)

        knew_in_2025 = warehouse.as_of(facts, knowledge_date="2025-06-30")
        original = next(
            f
            for f in knew_in_2025
            if f["concept"] == "Revenues" and f["valid_to"] == "2024-09-28"
        )
        self.assertEqual(original["value"], "391035000000")
        self.assertEqual(original["knowledge_time"], "2024-11-01")

        knew_today = warehouse.as_of(facts, knowledge_date="2026-10-09")
        restated = next(
            f
            for f in knew_today
            if f["concept"] == "Revenues" and f["valid_to"] == "2024-09-28"
        )
        self.assertEqual(restated["value"], "390912000000")
        self.assertEqual(restated["knowledge_time"], "2026-02-17")

    def test_knowledge_time_comes_from_the_filing_not_the_clock(self) -> None:
        self.run_pipeline()
        facts = canonical.read_table(
            self.data_root / "warehouse" / "silver" / "financial_fact.jsonl"
        )
        self.assertTrue(facts)
        for fact in facts:
            # Every knowledge_time is a filing date from the source document.
            self.assertRegex(fact["knowledge_time"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertLess(fact["knowledge_time"], "2026-12-31")


class TestD3PinnedInputs(RunHarness):
    def test_run_receipt_pins_every_input(self) -> None:
        code = main(
            [
                "--data-root",
                str(self.data_root),
                "run",
                "--date",
                LOGICAL_DATE,
                "--profile",
                "fixture",
                "--offline",
            ]
        )
        self.assertEqual(code, 0)
        receipt = json.loads(
            (self.data_root / "runs" / f"{LOGICAL_DATE}.json").read_text()
        )
        for field in (
            "git_sha",
            "ontology_version",
            "source_versions",
            "manifest_sha256",
            "table_sha256",
            "run_sha256",
        ):
            self.assertIn(field, receipt)
        self.assertEqual(receipt["logical_date"], LOGICAL_DATE)


class TestD4NoAmbientNondeterminism(RunHarness):
    def test_fetched_at_does_not_reach_the_output(self) -> None:
        first = self.run_pipeline(fetched_at="2026-10-09T06:15:00+00:00")
        shutil.rmtree(self.data_root / "warehouse")
        second = self.run_pipeline(fetched_at="2031-01-01T23:59:59+00:00")
        # Provenance changed; the warehouse did not.
        self.assertEqual(first, second)

    def test_floats_cannot_be_written(self) -> None:
        with self.assertRaises(TypeError):
            canonical.dumps({"value": 0.1 + 0.2})

    def test_money_round_trips_exactly(self) -> None:
        line = canonical.dumps({"value": Decimal("391035000000.07")})
        self.assertEqual(line, '{"value":"391035000000.07"}')

    def test_sort_is_total_over_mixed_and_missing_values(self) -> None:
        rows = [
            {"k": "b"},
            {"k": None},
            {"k": 2},
            {},
            {"k": "a"},
            {"k": 1},
        ]
        ordered = sorted(rows, key=lambda r: canonical.sort_key(r, ["k"]))
        self.assertEqual([r.get("k") for r in ordered], [None, None, 1, 2, "a", "b"])


class TestD5ByteReproducible(RunHarness):
    def test_two_runs_agree(self) -> None:
        first = self.run_pipeline()
        second = self.run_pipeline()
        self.assertEqual(first, second)

    def test_matches_committed_golden_hashes(self) -> None:
        golden_path = REPO_ROOT / "tests" / "golden" / f"fixture-{LOGICAL_DATE}.json"
        golden = json.loads(golden_path.read_text(encoding="utf-8"))
        self.assertEqual(self.run_pipeline(), golden)


class TestD6Lineage(RunHarness):
    def test_every_fact_traces_to_a_landed_blob(self) -> None:
        self.run_pipeline()
        facts = canonical.read_table(
            self.data_root / "warehouse" / "silver" / "financial_fact.jsonl"
        )
        landed = {
            p.name for p in (self.data_root / "raw").rglob("*") if p.is_file()
        }
        self.assertTrue(facts)
        for fact in facts:
            self.assertIn(fact["provenance_sha256"], landed)


class TestIdentityResolution(unittest.TestCase):
    def test_lei_wins_over_cik(self) -> None:
        self.assertEqual(
            warehouse.issuer_key(lei="549300nf6npegwfyac41", cik="320193"),
            "lei:549300NF6NPEGWFYAC41",
        )

    def test_cik_is_zero_padded_consistently(self) -> None:
        self.assertEqual(
            warehouse.issuer_key(lei=None, cik="320193"),
            warehouse.issuer_key(lei=None, cik="0000320193"),
        )

    def test_refuses_to_guess(self) -> None:
        with self.assertRaises(warehouse.TransformError):
            warehouse.issuer_key(lei=None, cik=None)


class TestSourceRegistry(unittest.TestCase):
    def test_every_source_parses(self) -> None:
        registry = sources.load(REPO_ROOT / "sources")
        self.assertGreaterEqual(len(registry), 6)
        for source in registry:
            self.assertIn(source.transport, {"file", "https"})
            self.assertTrue(source.endpoints, f"{source.id} declares no endpoints")

    def test_credentialed_sources_are_not_in_the_default_profile(self) -> None:
        # A clean VM with no accounts anywhere must still complete a daily run.
        for source in sources.for_profile(REPO_ROOT / "sources", "fixture"):
            self.assertFalse(source.requires_credential, source.id)

    def test_offline_refuses_network_transports(self) -> None:
        network = next(
            s for s in sources.load(REPO_ROOT / "sources") if s.transport == "https"
        )
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(fetch.FetchError):
            fetch.fetch_source(
                network,
                data_root=Path(tmp),
                repo_root=REPO_ROOT,
                logical_date=LOGICAL_DATE,
                fetched_at="2026-10-09T06:15:00+00:00",
                offline=True,
            )


class TestOntology(unittest.TestCase):
    def test_v1_loads_and_validates(self) -> None:
        onto = ontology_mod.load(REPO_ROOT / "ontology" / "v1.toml")
        self.assertEqual(onto.version, "1.0.0-p0")
        self.assertIn("Issuer", onto.objects)
        self.assertTrue(onto.objects["FinancialFact"].bitemporal)
        for link in onto.links.values():
            self.assertIn(link.source, onto.objects)
            self.assertIn(link.target, onto.objects)

    def test_no_trading_object_types(self) -> None:
        # Non-goal, enforced rather than documented: this is an information
        # layer, so nothing downstream of a decision belongs in the ontology.
        onto = ontology_mod.load(REPO_ROOT / "ontology" / "v1.toml")
        forbidden = {"Portfolio", "Position", "Order", "Trade", "Signal", "Strategy"}
        self.assertEqual(forbidden & set(onto.objects), set())


if __name__ == "__main__":
    unittest.main()
