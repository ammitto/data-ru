"""Focused conversion policy and all saved source-row proof; no harmonization."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from extract_review_candidates import parse_document
from ru_conversion.policy import convert_document, encoded
from convert_reviewed_candidates import convert_sources


class ConversionPolicyTests(unittest.TestCase):
    def candidate(self, filename):
        path = ROOT/'reference-docs/announcements'/filename
        raw = path.read_bytes()
        return parse_document(path, raw=raw), raw

    def test_snapshot_uses_real_title_for_people_and_no_fabricated_document_id(self):
        candidate, raw = self.candidate('20220801.md')
        output, proof = convert_document(candidate, raw)
        block = output['announcement']
        self.assertNotIn('document_id', block)
        self.assertEqual(block['url'], 'https://www.mid.ru/ru/detail-material-page/1817739/')
        self.assertEqual((block['publish_date'], block['publish_time']), ('2022-08-01', '10:37'))
        self.assertEqual(proof['source_as_of_evidence']['raw'], 'По состоянию на 10 апреля 2024 года')
        self.assertTrue(proof['parties'][0]['party_type_basis']['raw'].startswith('Граждане Великобритании'))
        self.assertEqual(len(output['sanction_details']['entities']), 277)

    def test_flags_and_source_spellings_are_retained_with_truthful_dispositions(self):
        candidate, raw = self.candidate('20230519.md')
        original = encoded(candidate)
        output, proof = convert_document(candidate, raw)
        index = next(i for i, p in enumerate(candidate['parties']) if p['names'][1]['raw'] == 'Carlos del Того')
        self.assertEqual(output['sanction_details']['entities'][index]['name']['en'], 'Carlos del Того')
        self.assertEqual(proof['parties'][index]['names'][1]['language'], 'und')
        self.assertEqual(proof['parties'][index]['candidate_flags'], ['mixed_script_name_needs_review'])
        self.assertEqual(proof['parties'][index]['dispositions'][0]['reviewed_by'],
                         'automated source-consistency verification')
        self.assertEqual(encoded(candidate), original)
        self.assertFalse(candidate['publication_ready'])

    def test_unknown_flags_and_unverifiable_type_basis_fail(self):
        candidate, raw = self.candidate('20220407.md')
        candidate['parties'][0]['flags'].append('unresolved_identity_conflict')
        with self.assertRaisesRegex(ValueError, 'unresolved conversion warning'):
            convert_document(candidate, raw)
        candidate, raw = self.candidate('20220801.md')
        candidate['source_title']['raw'] = 'invented people declaration'
        with self.assertRaisesRegex(ValueError, 'does not match'):
            convert_document(candidate, raw)

    def test_missing_fields_are_omitted_rather_than_inferred(self):
        candidate, raw = self.candidate('20250820.md')
        output, proof = convert_document(candidate, raw)
        self.assertNotIn('instruments', output['sanction_details'])
        for entity, item in zip(output['sanction_details']['entities'], proof['parties']):
            for field in ('effective_date', 'nationality', 'reason', 'measures'):
                self.assertNotIn(field, entity)
            self.assertEqual(entity['title'], {'ru': item['raw_role']})
        self.assertNotIn('en', output['announcement']['title'])
        self.assertNotIn('en', output['announcement']['content'])

    def test_names_only_rows_do_not_get_punctuation_as_a_title(self):
        candidate, raw = self.candidate('20220413-2.md')
        output, proof = convert_document(candidate, raw)
        self.assertNotIn('title', output['sanction_details']['entities'][0])
        self.assertEqual(proof['parties'][0]['raw_role'], ';')


class CompleteConversionProofTests(unittest.TestCase):
    def test_all_source_rows_deterministic_preserved_and_accounted_for(self):
        fixture = json.loads((ROOT/'tests/fixtures/ru-reference-manifest.json').read_text())
        inputs = [p for directory in ('sources', 'reference-docs') for p in (ROOT/directory).rglob('*') if p.is_file()]
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'converted'
            manifest = convert_sources(ROOT, output)
            self.assertEqual(manifest['totals'], {'documents': 21, 'named_occurrences': 3185})
            self.assertEqual(len(list(output.glob('*.yml'))), 21)
            for expected, record in zip(fixture['documents'], manifest['documents']):
                self.assertEqual(record['output_file'], Path(expected['file']).with_suffix('.yml').name)
                self.assertEqual(record['source_sha256'], expected['source_sha256'])
                self.assertEqual(record['named_occurrences'], expected['expected_named_row_count'])
                data = json.loads((output/record['output_file']).read_text())
                self.assertEqual(len(data['sanction_details']['entities']), len(record['parties']))
                for row, entity in zip(record['parties'], data['sanction_details']['entities']):
                    self.assertEqual(row['entity_sha256'], hashlib.sha256(encoded(entity)).hexdigest())
                    self.assertEqual(entity['name'], {'ru': row['names'][0]['raw'], 'en': row['names'][1]['raw']})
            expected_files = {p.name: p.read_bytes() for p in output.iterdir()}
            shipped = ROOT/'processed'
            self.assertTrue(all(p.is_file() for p in shipped.iterdir()))
            shipped_files = {p.name: p.read_bytes() for p in shipped.iterdir() if p.name != '.gitkeep'}
            self.assertEqual(expected_files, shipped_files,
                             'checked-in processed YAML and provenance must exactly match source regeneration')
            with self.assertRaisesRegex(ValueError, 'output must be new'):
                convert_sources(ROOT, output)
            self.assertEqual(expected_files, {p.name: p.read_bytes() for p in output.iterdir()})
            second = Path(directory)/'again'
            convert_sources(ROOT, second)
            self.assertEqual(expected_files, {p.name: p.read_bytes() for p in second.iterdir()})
        self.assertEqual(before, {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs})


if __name__ == '__main__':
    unittest.main()
