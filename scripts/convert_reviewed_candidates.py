#!/usr/bin/env python3
"""Convert exact saved source rows into minimal ingestion YAML and an evidence manifest.

This is automated source-consistency verification, not a claim of human identity
review. Literal source ambiguities are retained with explicit dispositions.
"""
import argparse
import json
from pathlib import Path

from extract_review_candidates import parse_document
from prepare_import_review import validated_document
from ru_conversion.policy import convert_document, digest, encoded


def convert_sources(source_root, output_dir):
    root = Path(source_root).resolve()
    output = Path(output_dir).resolve()
    protected_roots = [root/'sources', root/'reference-docs']
    if any(output == p or output.is_relative_to(p) for p in protected_roots):
        raise ValueError('output cannot be inside preserved manual source/reference data')
    if output.exists() and (output != root/'processed' or any(p.name != '.gitkeep' for p in output.iterdir())):
        raise ValueError('output must be new or the untouched processed placeholder directory')
    references = sorted((root/'reference-docs/announcements').glob('*.md'))
    if not references:
        raise ValueError('no source announcements found')
    protected = {p: p.read_bytes() for folder in ('sources', 'reference-docs')
                 for p in (root/folder).rglob('*') if p.is_file()}
    records = []
    for reference in references:
        if not reference.resolve().is_relative_to(root):
            raise ValueError('reference resolves outside source root')
        raw = protected[reference]
        candidate = json.loads(encoded(parse_document(reference, raw=raw)))
        # Reuse the strict source proof: hashes, exact ordered rows, title/date
        # evidence and every original warning/flag must match frozen bytes.
        validated_document(reference, reference, candidate_raw=encoded(candidate), reference_raw=raw)
        converted, review = convert_document(candidate, raw)
        records.append((reference.stem + '.yml', encoded(converted), review))
    if any(not p.is_file() or p.read_bytes() != raw for p, raw in protected.items()):
        raise ValueError('preserved input changed during conversion')
    manifest = {'schema': 'ru-source-backed-conversion/v1', 'reviewed_by': 'automated source-consistency verification',
                'scope': 'named_occurrences_in_saved_russian_reference_sections',
                'conversion_policy': 'literal_source_evidence_with_explicit_unknowns/v1',
                'identity_resolution': 'not_performed',
                'limits': ['No claim of human identity adjudication, complete unnamed population or current site-wide coverage.',
                           'Original candidate REVIEW-CANDIDATE flags remain unchanged in source proof.',
                           'Missing nationality, effective dates, translations, measures and legal citations are omitted.'],
                'protected_inputs': [{'file': str(p.relative_to(root)), 'sha256': digest(raw)}
                                     for p, raw in sorted(protected.items())],
                'documents': []}
    output.mkdir(parents=True, exist_ok=True)
    for name, raw, review in records:
        with (output/name).open('xb') as handle:
            handle.write(raw)
        manifest['documents'].append({'output_file': name, 'output_sha256': digest(raw),
                                      'named_occurrences': len(review['parties']), **review})
    if any(not p.is_file() or p.read_bytes() != raw for p, raw in protected.items()):
        raise ValueError('preserved input changed while writing; output is incomplete without manifest')
    manifest['totals'] = {'documents': len(records), 'named_occurrences': sum(len(r[2]['parties']) for r in records)}
    with (output/'conversion-manifest.json').open('xb') as handle:
        handle.write(encoded(manifest))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = convert_sources(args.source_root, args.output_dir)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, f'Source conversion refused: {error}\n')
    print(json.dumps(report['totals']))


if __name__ == '__main__':
    main()
