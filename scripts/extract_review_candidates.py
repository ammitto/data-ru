#!/usr/bin/env python3
"""Local feasibility extractor. Output is evidence for review, never publishable data.

Only a Russian section is parsed. Latin names there are source-provided forms,
not translations. English sections are intentionally not joined by row number.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import unicodedata

STATUS = 'REVIEW-CANDIDATE'
UNSUPPORTED = {'20220628': 'unnumbered multiline dash table',
               '20220905': 'unnumbered multiline dash table',
               '20240417': 'irregular mixed tab/vertical table with missing row markers'}
CYR = re.compile('[А-Яа-яЁё]')
LAT = re.compile('[A-Za-z]')
NUMBER = re.compile(r'^(\d+)\.?$')


def script(value):
    scripts = set()
    for c in value:
        if c.isalpha():
            n = unicodedata.name(c, '')
            scripts.add('Cyrl' if 'CYRILLIC' in n else 'Latn' if 'LATIN' in n else 'Other')
    return next(iter(scripts)) if len(scripts) == 1 else 'Mixed' if scripts else 'Unknown'


def valid_name(value, expected):
    """Deliberately restrictive: no dates, digits, prose clauses or parentheses."""
    if not 2 <= len(value.split()) <= 12 or len(value) > 160:
        return False
    if any(not (c.isalpha() or c.isspace() or c in ".,‘’'`\"“”«»-‐‑–") for c in value):
        return False
    words = re.findall(r'[^\W\d_]+', value, re.UNICODE)
    particles = {'van', 'von', 'de', 'der', 'den', 'da', 'del', 'di', 'of', 'the', 'ван', 'де'}
    tokens = [w.strip(".,‘’'`\"“”«»") for w in value.split()]
    if len(words) < 2 or not all(w and (w[0].isupper() or w in particles) for w in tokens):
        return False
    return bool(CYR.search(value)) if expected == 'Cyrl' else bool(LAT.search(value))


def issue(code, line=None, detail=None):
    result = {'code': code}
    if line is not None: result['line'] = line
    if detail is not None: result['detail'] = detail
    return result


def paired_line(value):
    """Parse exactly the first name parenthesis, never title organisation parentheses."""
    value = re.sub(r'^\d+[.)]?\s+', '', value.strip())
    if '(' not in value or ')' not in value:
        return None
    before, rest = value.split('(', 1)
    latin, title = rest.split(')', 1)
    ru = before.strip()
    if not valid_name(ru, 'Cyrl') or not valid_name(latin, 'Latn'):
        return None
    if title.strip() and title.lstrip()[0] not in '–—-,;.' and not title[0].isspace():
        return None
    return ru, latin, title


def names(ru, latin):
    return [{'raw': ru, 'language': 'ru', 'script': script(ru)},
            {'raw': latin, 'language': 'und', 'script': script(latin)}]


def party(ru, latin, title, start, end, lines, family, declaration):
    flags = []
    if script(ru) != 'Cyrl' or script(latin) != 'Latn':
        flags.append('mixed_script_name_needs_review')
    return {'status': STATUS, 'support': 'flagged' if flags else 'supported_pattern',
            'flags': flags, 'names': names(ru, latin), 'raw_title': title,
            'declared_party_type': {'value': 'person', 'basis': declaration} if declaration else None,
            'provenance': {'line_start': start, 'line_end': end,
                           'raw_lines': lines[start-1:end], 'section_language': 'ru',
                           'extraction_family': family}}


def russian_range(lines):
    starts = [i for i, line in enumerate(lines) if line.strip() == '## Russian']
    if len(starts) != 1: return None
    start = starts[0] + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith('## ')), len(lines))
    return start, end


def count_claims(lines, start, end, first_party):
    # Capture several distinct bounded phrasings; never select every number in prose.
    claims = []
    pattern = re.compile(r'(\d+)\s+(?:австралий\w*|новозеланд\w*|американских граждан|канадских граждан|граждан Канады|человек|членов Палаты|чел\.)|(?:списка[-–« ]*)(\d+)')
    for i in range(start, min(end, first_party-1 if first_party else end)):
        for match in pattern.finditer(lines[i]):
            claims.append({'value': int(match.group(1) or match.group(2)), 'line': i+1,
                           'raw_claim': match.group(0)})
    return claims


def declaration_evidence(lines, start, end):
    # Record declaration verbatim; this is document-level, not inferred nationality.
    pat = re.compile(r'граждан|австралийц|новозеландц|человек|сенатор|конгрессмен|парламентар|подданных|перечень лиц')
    for i in range(start, min(start+18, end)):
        if pat.search(lines[i]): return {'line': i+1, 'raw': lines[i]}
    return None


def parse_document(path):
    raw = path.read_bytes()
    lines = raw.decode('utf-8').splitlines()
    result = {'status': STATUS, 'publication_ready': False, 'source_file': str(path),
              'source_sha256': hashlib.sha256(raw).hexdigest(),
              'parties': [], 'issues': [],
              'ignored_sections': [{'raw_header': line, 'line': i+1,
                                    'translation_label_present': 'TRANSLATED' in line}
                                   for i, line in enumerate(lines)
                                   if line.startswith('## ') and line.strip() != '## Russian'],
              'limitations': ['No identity reconciliation, deduplication, translation or English-section alignment.',
                              'Same-line raw_title ends on that source line; separate continuation text is flagged, not silently attached.']}
    bounds = russian_range(lines)
    if bounds is None:
        result.update(support='unsupported', extraction_family=None)
        result['issues'].append(issue('missing_or_duplicate_russian_section'))
        return result
    start, end = bounds
    result['publication_timestamp_evidence'] = next(({'raw': lines[i], 'line': i+1}
        for i in range(start, min(start+8, end))
        if re.fullmatch(r'\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}', lines[i].strip())), None)
    result['source_title'] = next(({'raw': lines[i], 'line': i+1} for i in range(start, end)
                                   if lines[i].startswith(('Заявление', 'Граждане'))), None)
    decl = declaration_evidence(lines, start, end)
    first = None
    if path.stem in UNSUPPORTED:
        result.update(support='unsupported', extraction_family=None)
        result['issues'].append(issue('unsupported_layout', detail=UNSUPPORTED[path.stem]))
    elif any('№ п/п' in line for line in lines[start:end]):
        result['extraction_family'] = 'numbered_vertical_cells'
        header = next(i for i in range(start, end) if '№ п/п' in lines[i])
        markers = [(i, int(lines[i].strip().rstrip('.'))) for i in range(header+1, end)
                   if NUMBER.fullmatch(lines[i].strip())]
        if not markers: result['issues'].append(issue('no_numbered_rows'))
        for pos, (i, ordinal) in enumerate(markers):
            stop = markers[pos+1][0] if pos+1 < len(markers) else end
            if ordinal != pos+1:
                result['issues'].append(issue('nonconsecutive_row_number', i+1, {'actual': ordinal, 'expected': pos+1}))
            # Blank-separated cells preserve multiline cell boundaries.
            groups=[]; current=[]
            for j in range(i+1, stop):
                if lines[j].strip(): current.append(j)
                elif current: groups.append(current); current=[]
            if current: groups.append(current)
            # Known closing prose is not the final person's title.
            prose = next((k for k, group in enumerate(groups)
                          if lines[group[0]].startswith(('В условиях,', 'С учетом того,', 'Работа над'))), None)
            if prose is not None:
                result['issues'].append(issue('closing_prose_excluded', groups[prose][0]+1))
                groups = groups[:prose]
            if len(groups) < 3:
                result['issues'].append(issue('malformed_vertical_row', i+1)); continue
            latin='\n'.join(lines[j].strip() for j in groups[0])
            ru='\n'.join(lines[j].strip() for j in groups[1])
            if not valid_name(latin, 'Latn') or not valid_name(ru, 'Cyrl'):
                result['issues'].append(issue('ambiguous_vertical_name_cells', i+1)); continue
            title='\n'.join(lines[j] for group in groups[2:] for j in group)
            last=groups[-1][-1]+1
            result['parties'].append(party(ru,latin,title,i+1,last,lines,'numbered_vertical_cells',decl))
            result['parties'][-1]['source_ordinal']=ordinal
            first=first or i+1
        result['support']='partial' if result['issues'] else 'supported_pattern'
    else:
        result['extraction_family']='same_line_name_pair'
        begun=False
        for i in range(start,end):
            text=lines[i].strip()
            preceding='\n'.join(lines[start:i])
            list_boundary = ('Ниже' in preceding or 'переч' in preceding or
                             (path.stem=='20220801' and 'По состоянию на ' in preceding))
            found=paired_line(text)
            if found:
                # No broad free text matching before a source list announcement.
                if not list_boundary:
                    result['issues'].append(issue('unestablished_list_boundary',i+1));continue
                begun=True;first=first or i+1
                result['parties'].append(party(*found,i+1,i+1,lines,'same_line_name_pair',decl))
            elif (begun or list_boundary) and '(' in text and not text.startswith(('С учетом','Работа','С полным')):
                result['issues'].append(issue('unparsed_parenthesized_line',i+1,text))
            elif (begun or list_boundary) and re.match(r'^\d+[.)]\s',text):
                result['issues'].append(issue('unparsed_numbered_row',i+1,text))
            elif (begun or list_boundary) and text:
                result['issues'].append(issue('unclassified_list_continuation_or_prose',i+1,text))
        result['support']='partial' if result['issues'] else 'supported_pattern'
        if not result['parties']:
            result['support']='unsupported'
            result['issues'].append(issue('no_supported_name_pairs'))
    result['claimed_counts']=count_claims(lines,start,end,first)
    for claim in result['claimed_counts']:
        if claim['value']!=len(result['parties']):
            result['issues'].append(issue('claimed_count_mismatch',claim['line'],
                                          {'claimed':claim['value'],'extracted':len(result['parties'])}))
    duplicates={}
    for p in result['parties']:
        key=tuple(n['raw'] for n in p['names'])
        duplicates.setdefault(key,[]).append(p['provenance']['line_start'])
    for key, row_lines in duplicates.items():
        if len(row_lines)>1:result['issues'].append(issue('duplicate_raw_name_pair',detail={'names':key,'lines':row_lines}))
    # Publicly unnamed representatives cannot be recovered as identities.
    for i in range(start,end):
        if lines[i].startswith('Также в список внесен'):
            result['issues'].append(issue('unnamed_parties_declared',i+1,lines[i]))
    if result['issues'] and result['support'] != 'unsupported':
        result['support'] = 'partial'
    result['counts']={'extracted':len(result['parties']),
                       'flagged_parties':sum(bool(p['flags']) for p in result['parties']),
                       'issues':len(result['issues'])}
    return result


def existing_count(source_root, stem):
    path=source_root/'sources'/'announcements'/(stem+'.yml')
    if not path.is_file():return {'status':'absent','path':str(path)}
    try:
        import yaml
        loader = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)
        data=yaml.load(path.read_text(), Loader=loader)
        return {'status':'comparison_only_not_oracle', 'path':str(path),
                'count':len(data.get('sanction_details',{}).get('entities',[])),
                'loader':'preinstalled PyYAML safe loader'}
    except (ImportError, ValueError, AttributeError, TypeError) as exc:
        return {'status':'unavailable','path':str(path),'error':str(exc)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args=parser.parse_args()
    root=args.source_root.resolve(); output=args.output_dir.resolve()
    if output==root or root in output.parents:
        parser.error('output-dir must be outside the frozen source root')
    sources=sorted((root/'reference-docs'/'announcements').glob('*.md'))
    if not sources:parser.error('no announcement markdown inputs found')
    output.mkdir(parents=True,exist_ok=True)
    summary={'status':STATUS,'publication_ready':False,'source_root':str(root),'documents':[],
             'limitations':['Extracted means pattern-supported candidates; it does not establish identity correctness.',
                            'Flagged means document has issues or flagged names; unsupported has no extracted candidates.',
                            'Counts in the title or body and current YAML are comparison evidence only.']}
    for path in sources:
        doc=parse_document(path)
        doc['existing_corpus_comparison']=existing_count(root,path.stem)
        destination=output/(path.stem+'.review-candidates.json')
        destination.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
        summary['documents'].append({'file':path.name,'support':doc['support'],
                                    **doc.get('counts',{'extracted':0,'flagged_parties':0,'issues':len(doc['issues'])}),
                                    'claimed_counts':[x['value'] for x in doc.get('claimed_counts',[])],
                                    'existing_corpus_comparison':doc['existing_corpus_comparison'],
                                    'output':str(destination)})
    docs=summary['documents']
    summary['totals']={'documents':len(docs),'extracted_parties':sum(d['extracted'] for d in docs),
                       'flagged_parties':sum(d['flagged_parties'] for d in docs),
                       'flagged_documents':sum(bool(d['issues'] or d['flagged_parties']) for d in docs),
                       'unsupported_documents':sum(d['support']=='unsupported' for d in docs),
                       'document_issues':sum(d['issues'] for d in docs)}
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary['totals'],ensure_ascii=False))

if __name__=='__main__':main()
