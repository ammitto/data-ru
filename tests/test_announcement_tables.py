import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'inspect_announcement_tables.py'

class TableDiagnosticTests(unittest.TestCase):
    def inspect_html(self,html):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source.html';output=Path(tmp)/'result.json'
            source.write_text(html)
            subprocess.run(['python3',str(SCRIPT),str(source),'--output',str(output)],check=True,capture_output=True)
            return json.loads(output.read_text())

    def test_cells_are_preserved_without_entity_inference(self):
        result=self.inspect_html('<table><tr><td>1</td><td>Jane <b>Doe</b></td><td>Researcher &amp; editor</td></tr></table>')
        self.assertEqual(result['tables'][0]['raw_cells'],[['1','Jane Doe','Researcher & editor']])
        self.assertFalse(result['publication_ready'])
        self.assertEqual(result['status'],'REVIEW-CANDIDATE')

    def test_page_without_tables_produces_no_candidate_rows(self):
        result=self.inspect_html('<html><body>Access unavailable</body></html>')
        self.assertEqual(result['tables'],[])
        self.assertFalse(result['publication_ready'])

if __name__=='__main__':unittest.main()
