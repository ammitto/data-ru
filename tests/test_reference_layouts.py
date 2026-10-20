"""Layout regressions independent of announcement dates and filename selection."""
import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('layout_extractor', ROOT/'scripts/extract_review_candidates.py')
e = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(e)
SOURCE = ROOT/'reference-docs/announcements'


class ReferenceLayoutTests(unittest.TestCase):
    def parse(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'arbitrary-date-free-name.md'
            path.write_text('https://example.test/statement\n\n## Russian\n' + text)
            return e.parse_document(path)

    def test_dash_rows_keep_wrapped_names_and_roles(self):
        doc = self.parse('Ниже поименный перечень:\n\nДжон Смит\n(John\nSmith)\n\n–\n\nминистр\nведомства\n\nИван Иванов (Ivan Ivanov)\n\n–\n\nсоветник\n')
        self.assertTrue(doc['extraction_complete'])
        self.assertEqual(len(doc['parties']), 2)
        self.assertEqual(doc['parties'][0]['names'][1]['raw'], 'John\nSmith')
        self.assertEqual(doc['parties'][0]['raw_title'], 'министр\nведомства')
        self.assertEqual(doc['parties'][1]['raw_title'], 'советник')

    def test_real_dash_layouts_source_anchors(self):
        for file, first, last in [('20220628', 'Jill Tracy Jacobs Biden', 'Benjamin Schmidt'),
                                  ('20220905', 'Matthew S. Axelrod', 'W. Anthony Will')]:
            with self.subTest(file=file):
                doc = e.parse_document(SOURCE/(file+'.md'))
                self.assertTrue(doc['extraction_complete'])
                self.assertEqual(len(doc['parties']), 25)
                self.assertEqual(doc['parties'][0]['names'][1]['raw'], first)
                self.assertEqual(doc['parties'][-1]['names'][1]['raw'], last)
                self.assertNotIn('перечнем', doc['parties'][-1]['raw_title'])
                self.assertNotIn('Враждебные действия', doc['parties'][-1]['raw_title'])

    def test_mixed_tab_vertical_rows_keep_missing_ordinals_as_missing(self):
        doc = self.parse('№ п/п\tИмя, фамилия\tИмя на русском языке\tДолжность\n\nJohn Smith\tДжон Смит\nминистр\n\n(с 2018 г.)\n\n2.\n\nIvan Ivanov\n\nИван\nИванов\n\nсоветник\n')
        self.assertTrue(doc['extraction_complete'])
        self.assertEqual(len(doc['parties']), 2)
        self.assertEqual([p['source_ordinal'] for p in doc['parties']], [None, 2])
        self.assertEqual(doc['parties'][0]['raw_title'], 'министр\n\n(с 2018 г.)')
        self.assertEqual(doc['parties'][1]['names'][0]['raw'], 'Иван\nИванов')

    def test_real_mixed_table_wrapped_name_and_role_parentheses(self):
        doc = e.parse_document(SOURCE/'20240417.md')
        self.assertEqual(len(doc['parties']), 235)
        by_name = {p['names'][1]['raw']: p for p in doc['parties']}
        self.assertEqual(by_name['Daniela De Martino']['names'][0]['raw'], 'Даниэла\nДе Мартино')
        self.assertEqual(by_name['Lily D`Ambrosio']['names'][0]['raw'], 'Лили д`Амбросио')
        self.assertIn('(с 1999 по 2022 гг.)', by_name['Richard Wynne']['raw_title'])
        self.assertEqual(doc['parties'][0]['source_ordinal'], None)
        self.assertEqual(doc['parties'][1]['source_ordinal'], 2)
        self.assertEqual([(p['provenance']['line_start'], p['provenance']['line_end'])
                          for p in doc['parties'][:4]], [(16, 19), (21, 30), (32, 37), (39, 44)])

    def test_six_previously_omitted_source_rows(self):
        cases = [('20220407', 'Concetta\n\nFierravanti-Wells', 'Кончетта Фиерраванти-Уэллс'),
                 ('20220413-2', 'Marie-Françoise Mégie', 'Мари-Франсуа.Межи'),
                 ('20220801', 'Thomas Galloway Dunlop du Roy de Blicquy GALBRAITH',
                  'Томас Гэллоуэй Данлоп дю Руа де Блики ГЕЛБРЕЙТ'),
                 ('20221111', 'Christopher Gerard Cavoli', 'Кристофер Каволи'),
                 ('20230519', 'Carlos del Того', 'Карлос дель Торо'),
                 ('20260109', 'Walter/Volodymyr Kish', 'Вальтер/Володимир Киш')]
        for file, latin, ru in cases:
            with self.subTest(file=file):
                doc = e.parse_document(SOURCE/(file+'.md'))
                found = [p for p in doc['parties'] if p['names'][1]['raw'] == latin]
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]['names'][0]['raw'], ru)
                self.assertTrue(doc['extraction_complete'])
                if file == '20221111':
                    self.assertIn('missing_name_closing_parenthesis', found[0]['flags'])
                if file == '20230519':
                    self.assertIn('mixed_script_name_needs_review', found[0]['flags'])

    def test_closing_prose_is_excluded_from_final_name_and_title(self):
        doc = self.parse('Ниже перечень:\n1. Джон Смит (John Smith) – министр;\n\nРабота над расширением списка будет продолжена.\n')
        self.assertTrue(doc['extraction_complete'])
        self.assertEqual(doc['parties'][0]['raw_title'], ' – министр;')
        self.assertEqual(doc['parties'][0]['provenance']['line_end'], 5)

    def test_real_vertical_final_role_stops_before_closing_prose(self):
        doc = e.parse_document(SOURCE/'20230621.md')
        self.assertEqual(doc['parties'][-1]['provenance']['line_end'], 469)
        self.assertEqual(doc['parties'][-1]['raw_title'],
                         'член правления совета\nЮжной Австралии по проведению\nДня Австралии')

    def test_vertical_prefix_accepts_only_declared_column_labels(self):
        header = ('№ п/п\n\nИмя, фамилия\n\nИмя, фамилия\nна русском языке\n\n'
                  'Место работы / Должность\n\n')
        row = '1\n\nJohn Smith\n\nДжон Смит\n\nминистр\n'
        valid = self.parse(header + row)
        self.assertTrue(valid['extraction_complete'])
        for prefix in ['Неподдерживаемая строка\n\n',
                       'Иван Иванов (Ivan Ivanov) – советник\n\n']:
            with self.subTest(prefix=prefix):
                doc = self.parse(header + prefix + row)
                self.assertFalse(doc['extraction_complete'])
                self.assertEqual(len(doc['parties']), 1)
                self.assertTrue(any(error['code'] == 'unclassified_list_prefix'
                                    and error['detail'] == prefix.splitlines()[0]
                                    for error in doc['extraction_errors']))

    def test_missing_numbered_marker_cannot_silently_swallow_next_party(self):
        path = SOURCE/'20220721.md'
        lines = path.read_text().splitlines()
        self.assertEqual(lines[29], '2')
        lines[29] = ''
        doc = e.parse_document(path, raw=('\n'.join(lines) + '\n').encode('utf-8'))
        self.assertFalse(doc['extraction_complete'])
        self.assertEqual(len(doc['parties']), 38)
        self.assertTrue(any(error['code'] == 'unclassified_possible_table_row'
                            and error.get('detail', {}).get('latin_cell') == 'Ben Bayot'
                            and error['detail']['russian_cell'] == 'Бэн Бэйот'
                            for error in doc['extraction_errors']))
        self.assertIn('Ben Bayot', doc['parties'][0]['raw_title'])
        self.assertEqual(doc['parties'][0]['source_ordinal'], 1)

    def test_unknown_layout_and_partial_row_are_incomplete(self):
        for text in ['Ниже перечень:\nJohn Smith | Джон Смит | министр\n',
                     'Ниже перечень:\n1. Джон Смит (John Smith) – министр\n2. неразобранная строка\n',
                     '№ п/п\tИмя\tДолжность\nJohn Smith\t???\n']:
            with self.subTest(text=text):
                doc = self.parse(text)
                self.assertFalse(doc['extraction_complete'])
                self.assertTrue(doc['extraction_errors'])

    def test_cli_fails_unknown_layout_unless_diagnostic_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'root'
            refs = root/'reference-docs/announcements'
            refs.mkdir(parents=True)
            (refs/'unknown.md').write_text('## Russian\nНиже перечень:\nunknown layout\n')
            output = Path(directory)/'output'
            command = [sys.executable, '-S', str(ROOT/'scripts/extract_review_candidates.py'),
                       '--source-root', str(root), '--output-dir', str(output)]
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            summary = json.loads((output/'summary.json').read_text())
            self.assertFalse(summary['extraction_complete'])
            diagnostic = Path(directory)/'diagnostic'
            result = subprocess.run(command[:-1]+[str(diagnostic), '--allow-partial'],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(json.loads((diagnostic/'summary.json').read_text())['extraction_complete'])

    def test_existing_output_evidence_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'previous-evidence'
            output.mkdir()
            summary = output/'summary.json'
            summary.write_bytes(b'preserve previous summary exactly')
            candidate = output/'20220407.review-candidates.json'
            candidate.write_bytes(b'preserve previous candidate exactly')
            command = [sys.executable, '-S', str(ROOT/'scripts/extract_review_candidates.py'),
                       '--source-root', str(ROOT), '--output-dir', str(output)]
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn('output-dir must be new', result.stderr)
            self.assertEqual(summary.read_bytes(), b'preserve previous summary exactly')
            self.assertEqual(candidate.read_bytes(), b'preserve previous candidate exactly')
            self.assertEqual(sorted(p.name for p in output.iterdir()),
                             ['20220407.review-candidates.json', 'summary.json'])

    def test_supplied_source_snapshot_is_parsed_without_rereading(self):
        raw = ('https://mid.ru/ru/foreign_policy/news/123/\n## Russian\n'
               'Ниже перечень граждан:\nДжон Смит (John Smith) – министр\n').encode('utf-8')
        path = Path('/nonexistent/snapshot-only-reference.md')
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('unexpected source reread')):
            doc = e.parse_document(path, raw=raw)
        self.assertTrue(doc['extraction_complete'])
        self.assertEqual(doc['source_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(doc['source_file'], str(path))
        self.assertEqual(doc['parties'][0]['names'][1]['raw'], 'John Smith')
        self.assertEqual(doc['parties'][0]['provenance']['raw_lines'],
                         ['Джон Смит (John Smith) – министр'])

    def test_literal_spelling_dates_and_source_hash_are_preserved(self):
        doc = self.parse('Ниже перечень:\n1. Карлос дель Торо (Carlos del Того) – министр;  \n')
        person = doc['parties'][0]
        self.assertEqual(person['raw_title'], ' – министр;  ')
        self.assertEqual(person['names'][1]['raw'], 'Carlos del Того')
        self.assertEqual(person['provenance']['source_url'], 'https://example.test/statement')
        self.assertEqual(person['provenance']['source_sha256'], doc['source_sha256'])
        snapshot = e.parse_document(SOURCE/'20220801.md')
        self.assertEqual(snapshot['as_of_date_evidence']['raw'], 'По состоянию на 10 апреля 2024 года')
        self.assertEqual(snapshot['publication_timestamp_evidence']['raw'], '01.08.2022 10:37')
        self.assertIsNone(snapshot['document_id_evidence'])
        january = e.parse_document(SOURCE/'20260109.md')
        self.assertEqual(january['document_id_evidence']['raw'], '9-05-01-2026')
        self.assertEqual(january['publication_timestamp_evidence']['raw'], '05.01.2026 17:52')


if __name__ == '__main__':
    unittest.main()
