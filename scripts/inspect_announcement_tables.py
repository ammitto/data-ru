"""Local HTML table diagnostic. Raw cells only; not production entities."""
import argparse,json,hashlib,collections
from html.parser import HTMLParser
from pathlib import Path
class Tables(HTMLParser):
 def __init__(self):super().__init__();self.tables=[];self.stack=[];self.row=None;self.cell=None
 def handle_starttag(self,t,a):
  if t=='table':self.stack.append([])
  elif t=='tr' and self.stack:self.row=[]
  elif t in ['td','th'] and self.row is not None:self.cell=[]
 def handle_data(self,d):
  if self.cell is not None:self.cell.append(d)
 def handle_endtag(self,t):
  if t in ['td','th'] and self.cell is not None:
   self.row.append(' '.join(' '.join(self.cell).split()));self.cell=None
  elif t=='tr' and self.row is not None:
   self.stack[-1].append(self.row);self.row=None
  elif t=='table' and self.stack:self.tables.append(self.stack.pop())
p=argparse.ArgumentParser();p.add_argument('html',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();raw=a.html.read_bytes();parser=Tables();parser.feed(raw.decode('utf-8'))
r={'status':'REVIEW-CANDIDATE','publication_ready':False,'input':str(a.html),'input_sha256':hashlib.sha256(raw).hexdigest(),'limitations':['Raw table cells only; no identity/type mapping, live discovery, completeness or semantic correctness claim. Nested tables unsupported.'],'tables':[{'rows':len(t),'cell_count_distribution':dict(collections.Counter(map(len,t))),'raw_cells':t} for t in parser.tables]}
a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'table_row_counts':[t['rows'] for t in r['tables']],'publication_ready':False}))
