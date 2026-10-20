import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/prepare_import_review.py'
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location('prepare_review', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ImportReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'repo'
        self.references = self.root / 'reference-docs/announcements'
        self.manual = self.root / 'sources/announcements'
        self.references.mkdir(parents=True)
        self.manual.mkdir(parents=True)
        self.candidates = self.base / 'candidates'
        self.candidates.mkdir()
        self.output = self.base / 'review'
        self.url = 'https://mid.ru/ru/foreign_policy/news/12345/'
        self.reference = self.references / 'sample.md'
        self.reference.write_text(self.url + '\n## Russian\n01.01.2024 10:00\nЗаявление МИД России\nНиже перечень:\n1. Пётр Иванов (Peter Ivanov) – исследователь\n2. Иван Петров (Ivan Petrov) – советник\n')
        self.original = b'hand-maintained: preserve every byte\n'
        (self.manual / 'sample.yml').write_bytes(self.original)
        self.document = m.parse_document(self.reference)
        self.assertTrue(self.document['extraction_complete'])
        self.candidate_file = self.candidates / 'sample.review-candidates.json'
        self.save()

    def save(self):
        self.candidate_file.write_text(json.dumps(self.document, ensure_ascii=False))

    def run_review(self, state=None):
        return m.prepare_review(self.root, self.candidates, self.output, state)

    def test_preserves_manual_data_and_requires_review(self):
        report = self.run_review()
        self.assertEqual((self.manual / 'sample.yml').read_bytes(), self.original)
        self.assertEqual((self.output / 'originals/sample.yml').read_bytes(), self.original)
        self.assertEqual(report['sources'][0]['original_manual_sha256'], hashlib.sha256(self.original).hexdigest())
        self.assertEqual(report['status'], 'REVIEW_REQUIRED')
        self.assertFalse(report['publication_ready'])
        self.assertEqual(report['sources'][0]['source_warnings'], self.document['source_warnings'])
        self.assertIsNone(report['sources'][0]['last_imported_at'])
        self.assertIsNone(report['sources'][0]['last_source_checked_at'])

    def test_retains_recorded_dates_without_stamping_an_import(self):
        state = self.base / 'state.json'
        prior = {'sources': [{'source_url': self.url, 'last_imported_at': '2024-01-02T00:00:00Z',
                            'last_source_checked_at': '2024-01-03T00:00:00Z',
                            'official_updated_at': '2023-12-31'}]}
        state.write_text(json.dumps(prior)); original = state.read_bytes()
        report = self.run_review(state)
        self.assertEqual(report['sources'][0]['last_imported_at'], prior['sources'][0]['last_imported_at'])
        self.assertEqual(report['sources'][0]['official_updated_at'], '2023-12-31')
        self.assertEqual(state.read_bytes(), original)

    def test_incomplete_extraction_refuses_entire_bundle(self):
        self.document['extraction_complete'] = False; self.save()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.run_review()
        self.assertFalse(self.output.exists())

    def test_missing_reference_candidate_refuses_entire_bundle(self):
        (self.references / 'other.md').write_text(self.reference.read_text())
        with self.assertRaisesRegex(ValueError, 'exactly all'):
            self.run_review()
        self.assertFalse(self.output.exists())

    def test_extra_candidate_is_not_silently_ignored(self):
        (self.candidates / 'extra.review-candidates.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'exactly all'):
            self.run_review()

    def test_stale_reference_hash_is_rejected(self):
        self.reference.write_text(self.reference.read_text() + 'changed source\n')
        with self.assertRaisesRegex(ValueError, 'hash differs'):
            self.run_review()

    def test_name_not_in_source_is_rejected(self):
        self.document['parties'][0]['names'][0]['raw'] = 'Invented Person'; self.save()
        with self.assertRaisesRegex(ValueError, 'name absent'):
            self.run_review()

    def test_false_provenance_is_rejected(self):
        self.document['parties'][0]['provenance']['raw_lines'] = ['different text']; self.save()
        with self.assertRaisesRegex(ValueError, 'source text differs'):
            self.run_review()

    def test_existing_bundle_is_preserved(self):
        self.output.mkdir(); sentinel = self.output / 'previous'; sentinel.write_text('keep')
        with self.assertRaisesRegex(ValueError, 'must be new'):
            self.run_review()
        self.assertEqual(sentinel.read_text(), 'keep')

    def test_output_inside_corpus_is_rejected(self):
        self.output = self.root / 'generated'
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.run_review()

    def test_import_date_without_timezone_is_rejected(self):
        state = self.base / 'state.json'
        state.write_text(json.dumps({'sources': [{'source_url': self.url,
                                                'last_imported_at': '2024-01-01T00:00:00'}]}))
        with self.assertRaisesRegex(ValueError, 'timezone'):
            self.run_review(state)
        self.assertFalse(self.output.exists())

    def test_publishable_candidate_is_refused(self):
        self.document['publication_ready'] = True; self.save()
        with self.assertRaisesRegex(ValueError, 'nonpublishable'):
            self.run_review()

    def test_manual_symlink_outside_source_is_refused(self):
        outside = self.base / 'other.yml'; outside.write_text('outside')
        (self.manual / 'sample.yml').unlink()
        (self.manual / 'sample.yml').symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.run_review()

    def test_candidate_or_reference_change_after_validation_rejects_bundle(self):
        for target in ('candidate', 'reference'):
            with self.subTest(target=target):
                self.output = self.base / ('race-' + target)
                original_candidate = self.candidate_file.read_bytes()
                original_reference = self.reference.read_bytes()
                validate = m.validated_document
                def change_after_validation(*args, **kwargs):
                    candidate = validate(*args, **kwargs)
                    path = self.candidate_file if target == 'candidate' else self.reference
                    path.write_bytes(path.read_bytes() + b'\n')
                    return candidate
                with patch.object(m, 'validated_document', side_effect=change_after_validation):
                    with self.assertRaisesRegex(ValueError, 'input changed'):
                        self.run_review()
                self.assertFalse((self.output / 'manifest.json').exists())
                self.assertEqual((self.output / 'candidates/sample.review-candidates.json').read_bytes(), original_candidate)
                self.assertEqual((self.output / 'references/sample.md').read_bytes(), original_reference)
                # Restore only files created by this test.
                self.candidate_file.write_bytes(original_candidate)
                self.reference.write_bytes(original_reference)

    def test_state_snapshot_is_preserved_with_hash(self):
        state = self.base / 'state.json'
        state.write_text(json.dumps({'sources': [{'source_url': self.url,
                                                 'last_imported_at': '2024-01-02T00:00:00Z'}]}))
        original = state.read_bytes()
        report = self.run_review(state)
        self.assertEqual((self.output / report['source_state_file']).read_bytes(), original)
        self.assertEqual(report['source_state_sha256'], hashlib.sha256(original).hexdigest())

    def test_changes_to_state_and_manual_data_during_validation_are_rejected(self):
        state = self.base / 'state.json'
        state.write_text('{"sources": []}')
        validate = m.validated_document
        def change_inputs(*args, **kwargs):
            candidate = validate(*args, **kwargs)
            state.write_text('{"sources": [], "changed": true}')
            (self.manual / 'sample.yml').write_bytes(self.original + b'changed\n')
            return candidate
        with patch.object(m, 'validated_document', side_effect=change_inputs):
            with self.assertRaisesRegex(ValueError, 'input changed'):
                self.run_review(state)
        self.assertFalse((self.output / 'manifest.json').exists())
        self.assertEqual((self.output / 'source-state.json').read_text(), '{"sources": []}')
        self.assertEqual((self.output / 'originals/sample.yml').read_bytes(), self.original)

    def test_fabricated_title_and_source_dates_are_rejected(self):
        for key in ('raw_title', 'publication_timestamp_evidence', 'as_of_date_evidence', 'source_title', 'document_id_evidence'):
            with self.subTest(key=key):
                original = json.loads(json.dumps(self.document))
                if key == 'raw_title':
                    self.document['parties'][0][key] = 'Invented Prime Minister'
                else:
                    self.document[key] = {'line': 6, 'raw': '01.01.2099 00:00'}
                self.save()
                with self.assertRaisesRegex(ValueError, 'absent|differs'):
                    self.run_review()
                self.assertFalse(self.output.exists())
                self.document = original

    def test_removed_duplicated_or_reordered_parties_rejected_despite_counts(self):
        for change in ('remove', 'duplicate', 'reorder'):
            with self.subTest(change=change):
                original = json.loads(json.dumps(self.document))
                if change == 'remove':
                    self.document['parties'] = self.document['parties'][:1]
                elif change == 'duplicate':
                    self.document['parties'].append(self.document['parties'][0])
                else:
                    self.document['parties'].reverse()
                self.document['counts']['extracted'] = len(self.document['parties'])
                self.document['extraction_complete'] = True
                self.save()
                with self.assertRaisesRegex(ValueError, 'parties differs'):
                    self.run_review()
                self.assertFalse(self.output.exists())
                self.document = original

    def test_complete_source_duplicate_warnings_survive_json_roundtrip(self):
        self.reference.write_text(self.reference.read_text() +
                                  '3. Пётр Иванов (Peter Ivanov) – исследователь\n')
        self.document = m.parse_document(self.reference)
        self.save()
        self.assertTrue(self.document['source_warnings'])
        report = self.run_review()
        self.assertEqual(report['sources'][0]['candidate_count'], 3)
        self.assertEqual(report['sources'][0]['source_warnings'], json.loads(self.candidate_file.read_text())['source_warnings'])

    def test_unsourced_extra_top_level_metadata_is_rejected(self):
        for key, value in [('effective_date', '2099-01-01'),
                           ('publication_date', '2099-01-01'), ('nationality', 'GB')]:
            with self.subTest(key=key):
                self.document[key] = value
                self.save()
                with self.assertRaisesRegex(ValueError, 'unexpected candidate fields'):
                    self.run_review()
                self.assertFalse(self.output.exists())
                self.document.pop(key)

    def test_extractor_optional_existing_corpus_comparison_is_allowed(self):
        self.document['existing_corpus_comparison'] = {'status': 'unavailable', 'error': 'optional dependency absent'}
        self.save()
        self.assertEqual(self.run_review()['sources'][0]['candidate_count'], 2)

    def test_official_url_canonicalization_retains_known_import_time(self):
        canonical_url = self.url
        self.url = self.url.replace('mid.ru/', 'mid.ru:443/')
        self.reference.write_text(self.reference.read_text().replace(canonical_url, self.url))
        self.document = m.parse_document(self.reference)
        self.save()
        state = self.base / 'state.json'
        state.write_text(json.dumps({'sources': [{'source_url': canonical_url,
                                                 'last_imported_at': '2024-01-02T00:00:00Z'}]}))
        self.assertEqual(self.run_review(state)['sources'][0]['last_imported_at'], '2024-01-02T00:00:00Z')

    def test_invalid_state_urls_and_canonical_duplicates_are_rejected(self):
        invalid = [{'sources': [{'source_url': 'https://evil.test/a'}]},
                   {'sources': [{'source_url': self.url}, {'source_url': self.url.replace('mid.ru/', 'mid.ru:443/')}]}]
        for document in invalid:
            with self.subTest(document=document):
                state = self.base / 'state.json'; state.write_text(json.dumps(document))
                with self.assertRaises(ValueError):
                    self.run_review(state)
                self.assertFalse(self.output.exists())

    def test_malformed_json_shapes_produce_controlled_errors(self):
        command = [sys.executable, '-S', str(SCRIPT), '--source-root', str(self.root),
                   '--candidates-dir', str(self.candidates), '--output-dir', str(self.output)]
        state = self.base / 'state.json'; state.write_text('[]')
        result = subprocess.run(command + ['--state-file', str(state)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        for malformed in (None, [], 'not an object'):
            with self.subTest(malformed=malformed):
                self.document['parties'][0]['provenance'] = malformed; self.save()
                result = subprocess.run(command, text=True, capture_output=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
