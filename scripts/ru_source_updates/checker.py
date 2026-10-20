"""Build a review manifest; existing ledgers and hand-curated sources stay read-only."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from .evidence import article_evidence, discover_links, normalized_date
from .transport import SourceError, official_url, retrieve

VERIFIED_FIELDS = ('content_hash', 'content_hash_basis', 'published_at', 'published_at_evidence',
                   'official_updated_at', 'official_updated_at_evidence',
                   'last_source_checked_at', 'last_imported_at', 'title')


def load_state(path):
    if path is None:
        return {}
    document = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(document, dict) or not isinstance(document.get('sources'), list):
        raise SourceError('state file must contain a sources array')
    records = {}
    for item in document['sources']:
        if not isinstance(item, dict):
            raise SourceError('state source must be an object')
        url = official_url(item.get('source_url'))
        if url in records:
            raise SourceError('duplicate source URL in state')
        for key in ('last_source_checked_at', 'last_imported_at'):
            if item.get(key) is not None:
                normalized_date(item[key], timestamp_only=True)
        for key in ('published_at', 'official_updated_at'):
            if item.get(key) is not None:
                normalized_date(item[key])
        content_hash = item.get('content_hash')
        if content_hash is not None and (not isinstance(content_hash, str) or not re.fullmatch('[a-f0-9]{64}', content_hash)):
            raise SourceError('state content_hash must be a SHA-256 hex digest')
        records[url] = {key: item.get(key) for key in VERIFIED_FIELDS}
    return records


def reference_sources(root):
    directory = Path(root) / 'reference-docs' / 'announcements'
    if not directory.is_dir():
        raise SourceError('reference-docs/announcements directory does not exist')
    paths = sorted(directory.glob('*.md'))
    if not paths:
        raise SourceError('no tracked reference announcements found')
    results = []
    seen = set()
    for path in paths:
        raw = path.read_bytes()
        lines = raw.decode('utf-8').splitlines()
        if not lines:
            raise SourceError(f'empty reference file: {path.name}')
        url = official_url(lines[0].strip())
        if url in seen:
            raise SourceError('duplicate source URL in reference announcements')
        seen.add(url)
        published = None
        evidence = None
        # Only the explicit date at the beginning of the saved source section.
        for number, line in enumerate(lines[1:10], 2):
            if re.fullmatch(r'\d{2}\.\d{2}\.\d{4}(?:\s+\d{2}:\d{2})?', line.strip()):
                published = normalized_date(line)
                evidence = {'kind': 'saved_reference_publication_line',
                            'file': str(path.relative_to(root)), 'line': number, 'raw': line}
                break
        results.append({'source_url': url, 'reference_file': str(path.relative_to(root)),
                        'reference_sha256': hashlib.sha256(raw).hexdigest(),
                        'reference_published_at': published,
                        'reference_published_at_evidence': evidence})
    return results


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def decode(capture):
    try:
        return capture.body.decode(capture.charset)
    except (UnicodeError, LookupError) as error:
        raise SourceError('source HTML encoding cannot be decoded') from error


def same_announcement(requested_url, response_url):
    """Language and host aliases may change; the official article ID may not."""
    requested = re.search(r'/(\d+)/?$', urlsplit(official_url(requested_url)).path)
    returned = re.search(r'/(\d+)/?$', urlsplit(official_url(response_url)).path)
    return requested is not None and returned is not None and requested[1] == returned[1]


def run_check(source_root, output_dir, state_file=None, offline=False, timeout=15,
              index_url=None, fetch=retrieve, now=utc_now):
    root = Path(source_root).resolve()
    references = reference_sources(root)
    state = load_state(state_file)
    if index_url is not None:
        index_url = official_url(index_url)
    output = Path(output_dir).resolve()
    for protected in (root / 'sources', root / 'reference-docs'):
        if output == protected or protected in output.parents:
            raise SourceError('output directory must be outside source and reference data')
    # Refuse to reuse or replace even a partially populated previous run.
    output.mkdir(parents=True, exist_ok=False)
    checked_at = now()
    normalized_date(checked_at, timestamp_only=True)
    records = []
    failures = 0
    for number, reference in enumerate(references, 1):
        url = reference['source_url']
        previous = state.get(url, {})
        record = {**reference, **{key: previous.get(key) for key in VERIFIED_FIELDS}}
        record.update(check_status='offline_not_checked' if offline else 'failed',
                      content_status='unknown', attempt=None, artifacts=None)
        if record['published_at'] is None:
            record['published_at'] = reference['reference_published_at']
            record['published_at_evidence'] = reference['reference_published_at_evidence']
        if not offline:
            record['attempt'] = {'attempted_at': now(), 'source_url': url,
                                 'status': 'failed', 'error_type': None, 'error': None}
            try:
                capture = fetch(url, timeout=timeout)
                raw_path = f'{number:03d}.html'
                (output / raw_path).write_bytes(capture.body)
                record['artifacts'] = {'raw_html': raw_path,
                                       'raw_sha256': hashlib.sha256(capture.body).hexdigest(),
                                       'response_url': capture.url}
                if not same_announcement(url, capture.url):
                    raise SourceError('response URL does not identify the requested announcement')
                evidence = article_evidence(decode(capture))
                text_path = f'{number:03d}.txt'
                (output / text_path).write_text(evidence.pop('article_text') + '\n', encoding='utf-8')
                record['artifacts']['article_text'] = text_path
                previous_hash = previous.get('content_hash')
                comparable = previous.get('content_hash_basis') == evidence['content_hash_basis']
                record['content_status'] = ('first_check' if previous_hash is None else
                                            'unknown' if not comparable else
                                            'unchanged' if previous_hash == evidence['content_hash'] else 'changed')
                if previous_hash is not None and not comparable:
                    evidence['metadata_warnings'].append('incomparable_previous_content_hash_basis')
                record.update(evidence)
                record['last_source_checked_at'] = now()
                record['check_status'] = 'confirmed_announcement'
                record['attempt']['status'] = 'confirmed_announcement'
            except (OSError, ValueError) as error:
                failures += 1
                record['attempt'].update(error_type=type(error).__name__, error=str(error))
        records.append(record)
    discovery = {'scope': 'optional_index_review_queue', 'index_url': index_url,
                 'status': 'not_requested', 'attempted_at': None, 'candidate_urls': [],
                 'completeness': 'not_established', 'eligibility': 'requires_review'}
    if index_url is not None:
        discovery['status'] = 'offline_not_checked' if offline else 'failed'
        if not offline:
            discovery['attempted_at'] = now()
            try:
                capture = fetch(index_url, timeout=timeout)
                (output / 'index.html').write_bytes(capture.body)
                discovery['raw_html'] = 'index.html'
                html = decode(capture)
                links = discover_links(html, capture.url)
                if not links or re.search(r'<title[^>]*>[^<]*(?:captcha|just a moment|access denied)', html, re.I):
                    raise SourceError('index did not provide usable official article links')
                tracked = {r['source_url'] for r in references}
                # Host aliases may refer to the same tracked article.
                tracked_paths = {url.partition('mid.ru')[2] for url in tracked}
                discovery['candidate_urls'] = [url for url in links if url.partition('mid.ru')[2] not in tracked_paths]
                discovery['status'] = 'review_queue_captured'
            except (OSError, ValueError) as error:
                failures += 1
                discovery.update(error_type=type(error).__name__, error=str(error))
    dates = [r['reference_published_at'][:10] for r in records if r['reference_published_at']]
    manifest = {'schema_version': 1, 'scope': 'tracked_announcements_only',
                'mode': 'offline' if offline else 'official_check',
                'run_started_at': checked_at, 'publication_ready': False,
                'site_freshness': 'unknown', 'last_imported_at': None,
                'latest_included_publication_date': max(dates) if dates else None,
                'latest_included_publication_date_basis': 'explicit_saved_reference_publication_dates',
                'source_count': len(records), 'failed_attempt_count': failures,
                'sources': records, 'discovery': discovery}
    (output / 'check-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return manifest
