#!/usr/bin/env python3
"""Extract saved source evidence into nonpublishable review candidates.

Only a Russian section is parsed. Latin names there are source-provided forms,
not translations. English sections are intentionally not joined by row number.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

STATUS = 'REVIEW-CANDIDATE'
# Importable both as a CLI and through importlib in the repository tests.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ru_extraction.rows import script, valid_name, paired_line
from ru_extraction.layouts import extract


def issue(code, line=None, detail=None):
    result = {'code': code}
    if line is not None: result['line'] = line
    if detail is not None: result['detail'] = detail
    return result


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


def parse_document(path, raw=None):
    # Callers validating a snapshot can supply exactly the bytes they preserved.
    if raw is None:
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
                              'Only explicitly bounded source rows are extracted; source inconsistencies remain review warnings.']}
    bounds = russian_range(lines)
    if bounds is None:
        result.update(support='unsupported', extraction_family=None, extraction_complete=False,
                      extraction_errors=[issue('missing_or_duplicate_russian_section')], source_warnings=[])
        result['issues'].append(issue('missing_or_duplicate_russian_section'))
        return result
    start, end = bounds
    result['publication_timestamp_evidence'] = next(({'raw': lines[i], 'line': i+1}
        for i in range(start, min(start+8, end))
        if re.fullmatch(r'\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}', lines[i].strip())), None)
    result['source_title'] = next(({'raw': lines[i], 'line': i+1} for i in range(start, end)
                                   if lines[i].startswith(('Заявление', 'Граждане'))), None)
    result['as_of_date_evidence'] = next(({'raw': lines[i], 'line': i+1}
        for i in range(start, end) if lines[i].startswith('По состоянию на ')), None)
    result['document_id_evidence'] = next(({'raw': lines[i], 'line': i+1}
        for i in range(start, min(start+12, end))
        if re.fullmatch(r'\d+-\d{2}-\d{2}-\d{4}', lines[i].strip())), None)
    decl = declaration_evidence(lines, start, end)
    family, rows, errors, warnings = extract(lines, start, end)
    result['extraction_family'] = family
    result['extraction_errors'] = errors
    result['source_warnings'] = warnings
    result['source_url'] = next((line.strip() for line in lines[:start]
                                 if re.fullmatch(r'https?://\S+', line.strip())), None)
    first = rows[0]['start'] + 1 if rows else None
    for index, row in enumerate(rows, 1):
        item = party(row['ru'], row['latin'], row['title'], row['start'] + 1,
                     row['end'], lines, family, decl)
        item['source_ordinal'] = row['ordinal']
        item['source_row_index'] = index
        item['flags'].extend(row['warnings'])
        item['support'] = 'flagged' if item['flags'] else 'supported_pattern'
        if row.get('group_evidence'):
            item['group_evidence'] = row['group_evidence']
        item['provenance'].update(source_url=result['source_url'],
                                  source_sha256=result['source_sha256'])
        result['parties'].append(item)
    if not rows:
        errors.append(issue('no_supported_name_pairs'))
    result['support'] = 'partial' if errors and rows else 'unsupported' if errors else 'supported_pattern'
    result['issues'] = [*errors, *warnings]
    result['claimed_counts']=count_claims(lines,start,end,first)
    for claim in result['claimed_counts']:
        if claim['value']!=len(result['parties']):
            result['source_warnings'].append(issue('claimed_count_mismatch',claim['line'],
                                          {'claimed':claim['value'],'extracted':len(result['parties'])}))
    duplicates={}
    for p in result['parties']:
        key=tuple(n['raw'] for n in p['names'])
        duplicates.setdefault(key,[]).append(p['provenance']['line_start'])
    for key, row_lines in duplicates.items():
        if len(row_lines)>1:result['source_warnings'].append(issue('duplicate_raw_name_pair',detail={'names':key,'lines':row_lines}))
    # Publicly unnamed representatives cannot be recovered as identities.
    for i in range(start,end):
        if lines[i].startswith('Также в список внесен'):
            result['source_warnings'].append(issue('unnamed_parties_declared',i+1,lines[i]))
    result['issues'] = [*result['extraction_errors'], *result['source_warnings']]
    result['extraction_complete'] = not result['extraction_errors']
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
    parser.add_argument('--allow-partial', action='store_true',
                        help='diagnostic mode: write partial evidence without a failing exit status')
    args=parser.parse_args()
    root=args.source_root.resolve(); output=args.output_dir.resolve()
    if output==root or root in output.parents:
        parser.error('output-dir must be outside the frozen source root')
    sources=sorted((root/'reference-docs'/'announcements').glob('*.md'))
    if not sources:parser.error('no announcement markdown inputs found')
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error('output-dir must be new; existing extraction evidence is preserved')
    summary={'status':STATUS,'publication_ready':False,'extraction_complete':True,'source_root':str(root),'documents':[],
             'limitations':['Extracted means pattern-supported candidates; it does not establish identity correctness.',
                            'Flagged means document has issues or flagged names; unsupported has no extracted candidates.',
                            'Counts in the title or body and current YAML are comparison evidence only.']}
    for path in sources:
        doc=parse_document(path)
        doc['existing_corpus_comparison']=existing_count(root,path.stem)
        destination=output/(path.stem+'.review-candidates.json')
        destination.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
        summary['documents'].append({'file':path.name,'support':doc['support'],
                                    'extraction_complete':doc['extraction_complete'],
                                    **doc.get('counts',{'extracted':0,'flagged_parties':0,'issues':len(doc['issues'])}),
                                    'claimed_counts':[x['value'] for x in doc.get('claimed_counts',[])],
                                    'existing_corpus_comparison':doc['existing_corpus_comparison'],
                                    'output':str(destination)})
    docs=summary['documents']
    summary['extraction_complete'] = all(d['extraction_complete'] for d in docs)
    summary['totals']={'documents':len(docs),'extracted_parties':sum(d['extracted'] for d in docs),
                       'flagged_parties':sum(d['flagged_parties'] for d in docs),
                       'flagged_documents':sum(bool(d['issues'] or d['flagged_parties']) for d in docs),
                       'unsupported_documents':sum(d['support']=='unsupported' for d in docs),
                       'document_issues':sum(d['issues'] for d in docs)}
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary['totals'],ensure_ascii=False))
    return 0 if summary['extraction_complete'] or args.allow_partial else 1

if __name__=='__main__':raise SystemExit(main())
