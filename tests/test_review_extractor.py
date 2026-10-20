import importlib.util
from pathlib import Path
import tempfile
import unittest

MODULE=Path(__file__).resolve().parents[1]/'scripts'/'extract_review_candidates.py'
spec=importlib.util.spec_from_file_location('extractor',MODULE)
e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)
SOURCE=Path(__file__).resolve().parents[1]/'reference-docs'/'announcements'

class ExtractionTests(unittest.TestCase):
    def test_real_inline_row(self):
        ru,latin,title=e.paired_line('1        Скотт Моррисон (Scott Morrison)    премьер-министр')
        self.assertEqual((ru,latin),('Скотт Моррисон','Scott Morrison'))
        self.assertEqual(title,'    премьер-министр')

    def test_title_organisations_are_not_parties(self):
        value='Иэн Роланд ГАРНЕР (Ian Roland Garner), научный сотрудник Института Пилецкого (Pilecki Institute, Польша);'
        ru,latin,title=e.paired_line(value)
        self.assertEqual(latin,'Ian Roland Garner')
        self.assertIn('(Pilecki Institute, Польша)',title)

    def test_dates_and_generic_parentheses_rejected(self):
        for value in ['(c 2018 г. по настоящее время)', 'Бывший премьер (2013-2015 гг.)',
                      'Список граждан (235 persons)', 'Документ (List of persons)',
                      'Дата публикации (17.04.2024)', 'Кто-то (John Smith)extra']:
            with self.subTest(value=value):self.assertIsNone(e.paired_line(value))

    def test_comma_order_names_preserved(self):
        pair=e.paired_line('1. Бирн, Джеймс (Byrne, James), основатель;')
        self.assertEqual(pair[:2],('Бирн, Джеймс','Byrne, James'))

    def test_mixed_script_name_flag(self):
        p=e.party('Джон Смит','John Н. Smith','',1,1,['Джон Смит (John Н. Smith)'],'test',None)
        self.assertEqual(p['flags'],['mixed_script_name_needs_review'])

    def test_real_20220407(self):
        doc=e.parse_document(SOURCE/'20220407.md')
        self.assertEqual(doc['parties'][0]['names'][1]['raw'],'Scott Morrison')
        self.assertEqual(doc['parties'][0]['provenance']['line_start'],19)
        self.assertEqual(len(doc['parties']),228)
        self.assertTrue(doc['extraction_complete'])
        self.assertIn('Concetta\n\nFierravanti-Wells', [p['names'][1]['raw'] for p in doc['parties']])

    def test_20250820_keeps_only_named_people(self):
        doc=e.parse_document(SOURCE/'20250820.md')
        self.assertEqual(len(doc['parties']),21)
        self.assertEqual(doc['parties'][0]['names'][1]['raw'],'Ian Roland Garner')
        self.assertFalse(any(p['names'][1]['raw']=='Pilecki Institute, Польша' for p in doc['parties']))

    def test_vertical_table_real_first_row(self):
        doc=e.parse_document(SOURCE/'20220721.md')
        self.assertEqual(doc['parties'][0]['names'][1]['raw'],'Marc Ablong')
        self.assertEqual(doc['parties'][0]['names'][0]['raw'],'Марк Эблонг')
        self.assertEqual(doc['parties'][0]['provenance']['line_start'],22)
        self.assertEqual(len(doc['parties']),39)

    def test_irregular_layout_source_rows_extracted(self):
        doc=e.parse_document(SOURCE/'20240417.md')
        self.assertTrue(doc['extraction_complete'])
        self.assertEqual(len(doc['parties']),235)
        self.assertEqual(doc['parties'][0]['names'][1]['raw'],'Juliana Addison')
        self.assertIn(235,[x['value'] for x in doc['claimed_counts']])

    def test_translated_header_ends_russian_section(self):
        doc=e.parse_document(SOURCE/'20220427.md')
        self.assertTrue(all(p['provenance']['line_end']<310 for p in doc['parties']))
        self.assertEqual(len(doc['parties']),287)

    def test_20230412_no_cross_language_shift(self):
        doc=e.parse_document(SOURCE/'20230412.md')
        self.assertEqual(doc['parties'][0]['names'][1]['raw'],'Mary Jeannie May Simon')
        self.assertEqual(doc['parties'][-1]['names'][1]['raw'],'Scott Gillingham')
        self.assertTrue(all(p['provenance']['line_end']<352 for p in doc['parties']))

    def test_unclassified_continuation_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'test.md'
            p.write_text('## Russian\nНиже перечень граждан:\nДжон Смит (John Smith) – министр\nпродолжение должности\n')
            doc=e.parse_document(p)
            self.assertIn('unclassified_list_continuation_or_prose',[i['code'] for i in doc['issues']])
            self.assertEqual(doc['support'],'partial')

    def test_malformed_first_declared_list_row_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'test.md'
            p.write_text('## Russian\nНиже перечень граждан:\nДжон Смит (John Smith – министр;\nИван Иванов (Ivan Ivanov) – советник;\n')
            doc=e.parse_document(p)
            self.assertEqual(len(doc['parties']),2)
            self.assertTrue(doc['extraction_complete'])
            self.assertEqual(doc['parties'][0]['names'][1]['raw'],'John Smith')
            self.assertTrue(any(i['code']=='missing_name_closing_parenthesis' and i['line']==3
                                for i in doc['source_warnings']))

    def test_filename_not_used_as_publication_date(self):
        doc=e.parse_document(SOURCE/'20260109.md')
        self.assertEqual(doc['publication_timestamp_evidence']['raw'],'05.01.2026 17:52')

    def test_closing_prose_not_title(self):
        doc=e.parse_document(SOURCE/'20220721.md')
        self.assertNotIn('В условиях',doc['parties'][-1]['raw_title'])

    def test_unnamed_people_flagged(self):
        doc=e.parse_document(SOURCE/'20250926.md')
        self.assertEqual(len(doc['parties']),7)
        self.assertIn('unnamed_parties_declared',[i['code'] for i in doc['issues']])

    def test_ambiguous_vertical_cell_not_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'test.md'
            p.write_text('## Russian\nНиже перечень граждан:\n№ п/п\n\n1\n\n(2013-2015)\n\nДжон Смит\n\nминистр\n')
            doc=e.parse_document(p)
            self.assertEqual(doc['parties'],[])
            self.assertIn('ambiguous_vertical_name_cells',[i['code'] for i in doc['issues']])

    def test_all_candidates_remain_traceable_and_nonpublishable(self):
        import hashlib
        for path in sorted(SOURCE.glob('*.md')):
            with self.subTest(source=path.name):
                doc=e.parse_document(path)
                self.assertFalse(doc['publication_ready'])
                self.assertTrue(doc['extraction_complete'])
                self.assertEqual(doc['extraction_errors'], [])
                self.assertEqual(doc['status'],'REVIEW-CANDIDATE')
                self.assertEqual(doc['source_sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
                lines=path.read_text().splitlines()
                for party in doc['parties']:
                    proof=party['provenance']
                    self.assertEqual(proof['raw_lines'],lines[proof['line_start']-1:proof['line_end']])
                    self.assertIn(party['raw_title'], '\n'.join(proof['raw_lines']))
                    raw=' '.join(' '.join(proof['raw_lines']).split())
                    for name in party['names']:
                        self.assertIn(' '.join(name['raw'].split()),raw)

if __name__=='__main__':unittest.main()
