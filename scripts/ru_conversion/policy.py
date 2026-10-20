"""Explicit dispositions for preserved source anomalies and unknown metadata."""
import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urlsplit

DISPOSITIONS = {
    'mixed_script_name_needs_review': 'literal_source_spelling_preserved_without_identity_correction',
    'missing_name_closing_parenthesis': 'name_role_boundary_recovered_from_explicit_source_row_without_inventing_characters',
    'duplicate_raw_name_pair': 'all_named_source_occurrences_retained_without_asserting_distinct_identities',
    'nonconsecutive_row_number': 'literal_source_ordinal_retained_without_renumbering',
    'missing_source_ordinal': 'source_ordinal_kept_null_and_occurrence_index_not_treated_as_official_number',
    'unnamed_parties_declared': 'unnamed_group_preserved_in_official_content_without_fabricated_person_records',
    'claimed_count_mismatch': 'literal_named_rows_preserved_without_forcing_a_prose_claim_total',
}


def encoded(value):
    """JSON is also valid YAML; use no optional YAML dependency or invented scalars."""
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def evidence_at(evidence, lines):
    if not isinstance(evidence, dict):
        raise ValueError('missing source declaration evidence')
    line, raw = evidence.get('line'), evidence.get('raw')
    if type(line) is not int or not 1 <= line <= len(lines) or lines[line - 1] != raw:
        raise ValueError('source declaration evidence does not match the frozen source')
    return evidence


def disposition(code):
    if code not in DISPOSITIONS:
        raise ValueError(f'unresolved conversion warning: {code}')
    return {'code': code, 'disposition': DISPOSITIONS[code],
            'reviewed_by': 'automated source-consistency verification'}


def person_basis(party, candidate, lines):
    declaration = party.get('declared_party_type')
    if declaration and declaration.get('value') == 'person':
        return evidence_at(declaration.get('basis'), lines)
    # A published list headed "Citizens" explicitly declares people. Do not
    # infer their nationality, individual effective dates or a document number.
    title = evidence_at(candidate.get('source_title'), lines)
    if re.match(r'^Граждане\b', title['raw']):
        return title
    raise ValueError('source does not explicitly support an individual party type')


def convert_document(candidate, raw):
    lines = raw.decode('utf-8').splitlines()
    if not candidate.get('extraction_complete') or candidate.get('extraction_errors'):
        raise ValueError('incomplete extraction cannot be converted')
    title = evidence_at(candidate.get('source_title'), lines)
    timestamp = evidence_at(candidate.get('publication_timestamp_evidence'), lines)
    stamp = datetime.strptime(timestamp['raw'].strip(), '%d.%m.%Y %H:%M')
    starts = [i for i, line in enumerate(lines) if line.strip() == '## Russian']
    if len(starts) != 1:
        raise ValueError('exactly one authoritative Russian section is required')
    start = starts[0] + 1
    stop = next((i for i in range(start, len(lines)) if lines[i].startswith('## ')), len(lines))
    content = '\n'.join(lines[start:stop])
    announcement = {'title': {'ru': title['raw']}, 'url': candidate['source_url'],
                    'lang': 'ru', 'publish_date': stamp.strftime('%Y-%m-%d'),
                    'publish_time': stamp.strftime('%H:%M'), 'content': {'ru': content}}
    identifier = candidate.get('document_id_evidence')
    if identifier:
        announcement['document_id'] = evidence_at(identifier, lines)['raw']
    else:
        url = urlsplit(candidate['source_url'])
        if url.query or url.fragment or not re.fullmatch(r'/(?:ru|en)/detail-material-page/\d+/', url.path):
            raise ValueError('missing official document ID has no supported official-source identity')
    as_of = candidate.get('as_of_date_evidence')
    if as_of:
        evidence_at(as_of, lines)
    # List names are copied only when literally present. A general sanctions
    # heading does not supply an unstated list identifier or sanction effect.
    list_name = next((label for label in ('стоп-лист', 'черного списка', 'чёрного списка',
                                         'черный список', 'чёрный список')
                      if label in content.casefold()), None)
    entities, proofs = [], []
    for index, party in enumerate(candidate['parties'], 1):
        basis = person_basis(party, candidate, lines)
        forms = party['names']
        if len(forms) != 2 or forms[0]['language'] != 'ru' or forms[1]['language'] != 'und':
            raise ValueError('unrecognized source name form contract')
        entity = {'name': {'ru': forms[0]['raw'], 'en': forms[1]['raw']}, 'type': 'individual'}
        role = party['raw_title']
        if any(char.isalpha() for char in role):
            entity['title'] = {'ru': role}
        if list_name:
            entity['sanction_list'] = list_name
        entities.append(entity)
        proofs.append({'source_row_index': index, 'source_ordinal': party['source_ordinal'],
                       'entity_sha256': digest(encoded(entity)), 'names': forms,
                       'raw_role': role, 'party_type_basis': basis,
                       'candidate_flags': party['flags'],
                       'dispositions': [disposition(code) for code in party['flags']],
                       'provenance': party['provenance']})
    output = {'version': '1.1.0', 'announcement': announcement,
              'sanction_details': {'entities': entities}}
    review = {'source_url': candidate['source_url'], 'source_sha256': digest(raw),
              'original_candidate_status': candidate['status'],
              'original_candidate_publication_ready': candidate['publication_ready'],
              'source_publication_evidence': timestamp, 'source_as_of_evidence': as_of,
              'source_document_id_evidence': identifier,
              'document_identity_basis': 'official_document_id' if identifier else 'official_source_url',
              'source_warnings': candidate['source_warnings'],
              'dispositions': [disposition(item['code']) for item in candidate['source_warnings']],
              'parties': proofs}
    return output, review
