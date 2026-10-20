"""Acceptance against independently inspected saved-source evidence.

The fixture records row spans, source hashes and critical literal fields. It is
not regenerated from extractor output, source YAML, title counts or a live site.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reference-docs" / "announcements"
FIXTURE = ROOT / "tests" / "fixtures" / "ru-reference-manifest.json"
SCRIPT = ROOT / "scripts" / "extract_review_candidates.py"
SPEC = importlib.util.spec_from_file_location("source_acceptance_extractor", SCRIPT)
EXTRACTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXTRACTOR)


def source_spans(document):
    """Expand only the static fixture encoding; no parser heuristics here."""
    return [
        (start + index * stride, end + index * stride)
        for start, end, count, stride in document["row_span_runs"]
        for index in range(count)
    ]


def input_hashes():
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for directory in ("reference-docs", "sources")
        for path in sorted((ROOT / directory).rglob("*"))
        if path.is_file()
    }


class SourceAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.documents = {
            item["file"]: item for item in cls.manifest["documents"]
        }
        cls.results = {
            name: EXTRACTOR.parse_document(SOURCE / name)
            for name in cls.documents
        }

    def party_at(self, filename, source_line):
        matches = [
            party for party in self.results[filename]["parties"]
            if party["provenance"]["line_start"]
            <= source_line
            <= party["provenance"]["line_end"]
        ]
        self.assertEqual(len(matches), 1, (filename, source_line))
        return matches[0]

    def test_frozen_manifest_covers_every_saved_announcement(self):
        self.assertEqual(
            sorted(self.documents),
            sorted(path.name for path in SOURCE.glob("*.md")),
        )
        self.assertEqual(
            len(self.documents), self.manifest["expected_document_count"]
        )
        total = 0
        for name, expected in self.documents.items():
            with self.subTest(file=name):
                path = SOURCE / name
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    expected["source_sha256"],
                    "Saved source changed: review the evidence before updating the fixture.",
                )
                spans = source_spans(expected)
                self.assertEqual(len(spans), expected["expected_named_row_count"])
                self.assertEqual(len({start for start, _ in spans}), len(spans))
                self.assertTrue(all(start <= end for start, end in spans))
                self.assertTrue(all(
                    earlier[1] < later[0]
                    for earlier, later in zip(spans, spans[1:])
                ))
                total += len(spans)
        self.assertEqual(total, self.manifest["expected_named_row_occurrences"])

    def test_every_source_row_has_one_complete_candidate_in_source_order(self):
        total = 0
        for name, expected in self.documents.items():
            with self.subTest(file=name):
                actual = self.results[name]
                self.assertTrue(actual["extraction_complete"])
                self.assertEqual(actual["extraction_errors"], [])
                self.assertEqual(
                    len(actual["parties"]), expected["expected_named_row_count"]
                )
                prefixes = {
                    item["name_line"]: item["ordinal_line"]
                    for item in expected.get("optional_ordinal_prefixes", [])
                }
                for index, ((start, end), party) in enumerate(
                    zip(source_spans(expected), actual["parties"]), 1
                ):
                    provenance = party["provenance"]
                    self.assertIn(
                        provenance["line_start"], {start, prefixes.get(start, start)}
                    )
                    self.assertEqual(provenance["line_end"], end, (name, start))
                    self.assertEqual(party["source_row_index"], index)
                total += len(actual["parties"])
        self.assertEqual(total, self.manifest["expected_named_row_occurrences"])

    def test_every_candidate_keeps_literal_source_provenance_and_raw_fields(self):
        for name, expected in self.documents.items():
            lines = (SOURCE / name).read_text(encoding="utf-8").splitlines()
            with self.subTest(file=name):
                actual = self.results[name]
                self.assertEqual(actual["source_sha256"], expected["source_sha256"])
                self.assertEqual(Path(actual["source_file"]).resolve(), SOURCE / name)
                for party in actual["parties"]:
                    provenance = party["provenance"]
                    start, end = provenance["line_start"], provenance["line_end"]
                    self.assertGreater(start, expected["source_section"][0])
                    self.assertLessEqual(end, expected["source_section"][1])
                    self.assertEqual(provenance["raw_lines"], lines[start - 1:end])
                    self.assertEqual(provenance["section_language"], "ru")
                    self.assertEqual(provenance["source_url"], expected["source_url"])
                    self.assertEqual(
                        provenance["source_sha256"], expected["source_sha256"]
                    )
                    raw = "\n".join(provenance["raw_lines"])
                    self.assertEqual(len(party["names"]), 2, (name, start))
                    for form in party["names"]:
                        self.assertTrue(form["raw"])
                        self.assertIn(form["raw"], raw, (name, start, form))
                    self.assertIn(party["raw_title"], raw, (name, start))

    def test_critical_names_preserve_spelling_scripts_aliases_and_wrapping(self):
        for name, expected in self.documents.items():
            for anchor in expected["critical_names"]:
                with self.subTest(file=name, line=anchor["line"]):
                    party = self.party_at(name, anchor["line"])
                    self.assertEqual(
                        [form["raw"] for form in party["names"]],
                        [anchor["primary_name"], anchor["latin_name"]],
                    )

    def test_critical_roles_keep_continuations_and_stop_before_next_row_or_footer(self):
        for name, expected in self.documents.items():
            for anchor in expected["critical_titles"]:
                with self.subTest(file=name, line=anchor["line"]):
                    self.assertEqual(
                        self.party_at(name, anchor["line"])["raw_title"],
                        anchor["raw_title"],
                    )

    def test_metadata_matches_source_evidence_without_filename_dates(self):
        fields = (
            "publication_timestamp_evidence", "as_of_date_evidence",
            "document_id_evidence", "source_title",
        )
        for name, expected in self.documents.items():
            with self.subTest(file=name):
                actual = self.results[name]
                lines = (SOURCE / name).read_text(encoding="utf-8").splitlines()
                self.assertEqual(actual["source_url"], expected["source_url"])
                for field in fields:
                    self.assertEqual(actual[field], expected[field])
                    if expected[field] is not None:
                        evidence = expected[field]
                        self.assertEqual(lines[evidence["line"] - 1], evidence["raw"])
                self.assertFalse(actual["publication_ready"])
                self.assertEqual(actual["status"], "REVIEW-CANDIDATE")
        snapshot = self.results["20220801.md"]
        self.assertEqual(snapshot["publication_timestamp_evidence"]["raw"], "01.08.2022 10:37")
        self.assertEqual(
            snapshot["as_of_date_evidence"]["raw"],
            "По состоянию на 10 апреля 2024 года",
        )
        self.assertIsNone(snapshot["document_id_evidence"])
        self.assertEqual(
            self.results["20260109.md"]["publication_timestamp_evidence"]["raw"],
            "05.01.2026 17:52",
        )

    def test_no_inferred_party_metadata_or_import_capture_effective_dates(self):
        forbidden = {
            "nationality", "citizenship", "birth_date", "date_of_birth",
            "effective_date", "effective_from", "start_date", "end_date",
            "imposed_date", "import_date", "imported_at", "capture_date",
            "captured_at", "reason", "sanction_reason",
        }
        for name, actual in self.results.items():
            with self.subTest(file=name):
                lines = (SOURCE / name).read_text(encoding="utf-8").splitlines()
                for item in [actual, *actual["parties"]]:
                    self.assertFalse(
                        {
                            key for key in forbidden
                            if key in item and item[key] is not None
                        },
                        (name, "Unsourced structured metadata was introduced."),
                    )
                for party in actual["parties"]:
                    declaration = party["declared_party_type"]
                    if declaration is not None:
                        self.assertEqual(declaration["value"], "person")
                        evidence = declaration["basis"]
                        self.assertEqual(lines[evidence["line"] - 1], evidence["raw"])

    def test_source_ordinals_are_evidence_not_reconstructed_row_positions(self):
        for name, expected in self.documents.items():
            with self.subTest(file=name):
                if "source_ordinals" in expected:
                    ordinals = expected["source_ordinals"]
                else:
                    explicit = {
                        item["name_line"]: item["value"]
                        for item in expected.get("optional_ordinal_prefixes", [])
                    }
                    ordinals = [
                        explicit.get(start) for start, _ in source_spans(expected)
                    ]
                self.assertEqual(
                    [party["source_ordinal"] for party in self.results[name]["parties"]],
                    ordinals,
                )
        repeated = self.results["20220721.md"]
        self.assertEqual(repeated["parties"][26]["source_ordinal"], 27)
        self.assertEqual(repeated["parties"][27]["source_ordinal"], 27)
        self.assertNotEqual(
            repeated["parties"][26]["names"], repeated["parties"][27]["names"]
        )
        self.assertIn(
            "nonconsecutive_row_number",
            [warning["code"] for warning in repeated["source_warnings"]],
        )

    def test_complete_extraction_retains_source_anomalies_for_review(self):
        total_mixed = 0
        for name, expected in self.documents.items():
            with self.subTest(file=name):
                actual_mixed = [
                    start
                    for (start, _), party in zip(
                        source_spans(expected), self.results[name]["parties"]
                    )
                    if "mixed_script_name_needs_review" in party["flags"]
                ]
                self.assertEqual(actual_mixed, expected["mixed_script_row_starts"])
                total_mixed += len(actual_mixed)
        self.assertEqual(
            total_mixed, self.manifest["expected_mixed_script_row_occurrences"]
        )
        self.assertIn(
            "missing_name_closing_parenthesis",
            self.party_at("20221111.md", 120)["flags"],
        )
        self.assertIn(
            "unnamed_parties_declared",
            [warning["code"] for warning in self.results["20250926.md"]["source_warnings"]],
        )
        self.assertEqual(len(self.results["20250926.md"]["parties"]), 7)
        irregular = self.results["20240417.md"]
        self.assertIn(
            "missing_source_ordinal",
            [warning["code"] for warning in irregular["source_warnings"]],
        )
        # A separate identity must survive even though the English table repeats Foley.
        self.assertEqual(
            self.party_at("20240417.md", 649)["names"][1]["raw"], "Will Fowles"
        )
        self.assertFalse(irregular["publication_ready"])

    def test_other_language_sections_never_supply_or_relabel_candidate_fields(self):
        for name, expected in self.documents.items():
            with self.subTest(file=name):
                self.assertEqual(
                    self.results[name]["ignored_sections"],
                    [
                        {
                            "raw_header": header["raw"],
                            "line": header["line"],
                            "translation_label_present": "TRANSLATED" in header["raw"],
                        }
                        for header in expected["headings"][1:]
                    ],
                )
                for party in self.results[name]["parties"]:
                    self.assertEqual(party["names"][0]["language"], "ru")
                    self.assertEqual(party["names"][1]["language"], "und")

    def test_cli_writes_review_artifacts_without_mutating_reference_or_yaml_corpus(self):
        before = input_hashes()
        self.assertTrue(any(name.startswith("sources/") for name in before))
        self.assertTrue(any(name.startswith("reference-docs/") for name in before))
        with tempfile.TemporaryDirectory(prefix="ru-source-acceptance-") as directory:
            output = Path(directory) / "review"
            result = subprocess.run(
                [
                    sys.executable, "-S", str(SCRIPT),
                    "--source-root", str(ROOT), "--output-dir", str(output),
                ],
                text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(input_hashes(), before)
            self.assertEqual(
                sorted(path.name for path in output.glob("*.review-candidates.json")),
                sorted(
                    Path(name).stem + ".review-candidates.json"
                    for name in self.documents
                ),
            )
            for name, expected in self.documents.items():
                candidate = json.loads(
                    (output / (Path(name).stem + ".review-candidates.json"))
                    .read_text(encoding="utf-8")
                )
                self.assertEqual(candidate["source_sha256"], expected["source_sha256"])
                self.assertEqual(
                    len(candidate["parties"]), expected["expected_named_row_count"]
                )
                self.assertTrue(candidate["extraction_complete"])
                self.assertFalse(candidate["publication_ready"])


if __name__ == "__main__":
    unittest.main()
