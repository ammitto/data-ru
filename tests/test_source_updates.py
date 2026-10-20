from email.message import Message
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from ru_source_updates.checker import load_state, reference_sources, run_check
from ru_source_updates.evidence import article_evidence, discover_links, normalized_date
from ru_source_updates.transport import Capture, MAX_BYTES, OfficialRedirectHandler, SourceError, official_url, retrieve

FIXTURES = Path(__file__).parent / 'fixtures' / 'source-updates'
ARTICLE = (FIXTURES / 'announcement.html').read_text()
CHALLENGE = (FIXTURES / 'challenge.html').read_text()
URL = 'https://mid.ru/en/foreign_policy/news/1944697/'
OLD = '2026-10-01T01:02:03+00:00'
NOW = '2026-10-20T01:02:03+00:00'


class Response(io.BytesIO):
    def __init__(self, body=ARTICLE.encode(), url=URL, status=200, content_type='text/html; charset=utf-8', length=None):
        super().__init__(body)
        self.url, self.status = url, status
        self.headers = Message()
        self.headers['Content-Type'] = content_type
        if length is not None:
            self.headers['Content-Length'] = str(length)

    def geturl(self):
        return self.url


class Opener:
    def __init__(self, response=None, error=None):
        self.response, self.error = response, error
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.error:
            raise self.error
        return self.response


class TransportTests(unittest.TestCase):
    def test_rejects_nonofficial_private_http_and_credentials(self):
        for url in ('http://mid.ru/a', 'https://mid.ru.evil/a', 'https://user@mid.ru/a',
                    'https://mid.ru:secret@evil.test/a', 'https://127.0.0.1/a',
                    'https://192.168.0.1/a', 'https://localhost/a', 'https://[::1]/a',
                    'https://mid.ru:444/a', 'https://mid.ru/a\nb', 'https://mid.ru\\@evil/a'):
            with self.subTest(url=url), self.assertRaises(SourceError):
                official_url(url)

    def test_allowed_url_normalizes_default_port_and_fragment(self):
        self.assertEqual(official_url('https://www.mid.ru:443/a#b'), 'https://www.mid.ru/a')

    def test_outside_redirect_rejected_before_request(self):
        handler = OfficialRedirectHandler(URL)
        for target in ('https://example.org/a', 'http://mid.ru/a', 'https://127.0.0.1/a'):
            with self.subTest(target=target), self.assertRaises(SourceError):
                handler.redirect_request(Request(URL), None, 302, 'redirect', {}, target)

    def test_redirect_loop_and_bounded_hops(self):
        handler = OfficialRedirectHandler(URL)
        with self.assertRaises(SourceError):
            handler.redirect_request(Request(URL), None, 302, '', {}, URL)
        for n in range(5):
            handler.redirect_request(Request(URL), None, 302, '', {}, f'https://mid.ru/a{n}')
        with self.assertRaises(SourceError):
            handler.redirect_request(Request(URL), None, 302, '', {}, 'https://mid.ru/too-far')

    def test_checks_final_url_defensively(self):
        with self.assertRaises(SourceError):
            retrieve(URL, opener=Opener(Response(url='https://evil.test/a')))

    def test_bounded_bytes_declared_and_actual(self):
        for response in (Response(length=MAX_BYTES + 1), Response(body=b'x' * (MAX_BYTES + 1)), Response(length='bad')):
            with self.subTest(response=response), self.assertRaises(SourceError):
                retrieve(URL, opener=Opener(response))

    def test_timeout_propagated_and_deadline_checked(self):
        with self.assertRaises(socket.timeout):
            retrieve(URL, opener=Opener(error=socket.timeout('timed out')))
        with patch('ru_source_updates.transport.time.monotonic', side_effect=[0, 16]):
            with self.assertRaisesRegex(SourceError, 'deadline'):
                retrieve(URL, opener=Opener(Response()), timeout=15)

    def test_content_type_and_status_checked(self):
        for response in (Response(content_type='application/json'), Response(status=403)):
            with self.subTest(response=response), self.assertRaises(SourceError):
                retrieve(URL, opener=Opener(response))

    def test_timeout_bounds(self):
        for timeout in (0, -1, 121, float('nan'), float('inf')):
            with self.subTest(timeout=timeout), self.assertRaises(SourceError):
                retrieve(URL, timeout=timeout)

    def test_captures_html_without_implying_announcement(self):
        capture = retrieve(URL, opener=Opener(Response(body=CHALLENGE.encode())))
        with self.assertRaisesRegex(SourceError, 'announcement body'):
            article_evidence(capture.body.decode())


class EvidenceTests(unittest.TestCase):
    def test_explicit_article_date_ignores_recent_navigation(self):
        result = article_evidence(ARTICLE)
        self.assertEqual(result['published_at'], '2024-04-17')
        self.assertIsNone(result['official_updated_at'])
        self.assertEqual(result['published_at_evidence']['kind'], 'photo-content__date')
        self.assertNotIn('2026', result['article_text'])

    def test_audio_article_layout_uses_its_own_title_and_date(self):
        # Official /maps/ pages use audio-content, alongside unrelated country headers.
        html = ARTICLE.replace('photo-content__title', 'audio-content__title').replace(
            'photo-content__date', 'audio-content__date').replace(
            '<body>', '<body><h1 class="page-header__title">Canada</h1>')
        result = article_evidence(html)
        self.assertEqual(result['title'], article_evidence(ARTICLE)['title'])
        self.assertEqual(result['published_at'], '2024-04-17')
        self.assertEqual(result['published_at_evidence']['kind'], 'audio-content__date')
        self.assertEqual(result['content_hash'], article_evidence(ARTICLE)['content_hash'])

    def test_body_hash_ignores_navigation_and_scripts(self):
        original = article_evidence(ARTICLE)['content_hash']
        self.assertEqual(original, article_evidence(ARTICLE.replace('20 October 2026', '21 October 2026').replace('dynamicCounter=123', 'dynamicCounter=999'))['content_hash'])
        self.assertNotEqual(original, article_evidence(ARTICLE.replace('Jane Doe', 'John Smith'))['content_hash'])

    def test_body_hash_ignores_attributes_and_whitespace(self):
        original = article_evidence(ARTICLE)['content_hash']
        changed = ARTICLE.replace('<td>', '<td class="changed">').replace('Jane Doe', 'Jane  \n Doe')
        self.assertEqual(original, article_evidence(changed)['content_hash'])

    def test_official_title_change_is_a_content_change(self):
        changed = ARTICLE.replace('Foreign Ministry statement on personal sanctions',
                                  'Foreign Ministry statement on personal sanctions against Canada')
        self.assertNotEqual(article_evidence(ARTICLE)['content_hash'], article_evidence(changed)['content_hash'])

    def test_requires_single_article_body_title_and_sanctions_context(self):
        for html in (CHALLENGE, ARTICLE.replace('article-content', 'other'),
                     ARTICLE.replace('photo-content__title', 'other'), ARTICLE + ARTICLE):
            with self.subTest(html=html[:60]), self.assertRaises(SourceError):
                article_evidence(html)

    def test_explicit_modified_metadata_only(self):
        html = ARTICLE.replace('</head>', '<meta property="article:modified_time" content="2024-04-18T08:30:00+03:00"></head>')
        result = article_evidence(html)
        self.assertEqual(result['official_updated_at'], '2024-04-18T08:30:00+03:00')
        self.assertEqual(result['official_updated_at_evidence']['kind'], 'article:modified_time')

    def test_missing_unsupported_or_conflicting_dates_stay_unknown(self):
        html = ARTICLE.replace('17 April 2024', 'unknown')
        result = article_evidence(html)
        self.assertIsNone(result['published_at'])
        self.assertTrue(result['metadata_warnings'])
        html = ARTICLE.replace('</head>', '<meta property="article:modified_time" content="2024-04-18T08:30:00"></head>')
        self.assertIsNone(article_evidence(html)['official_updated_at'])
        html = ARTICLE.replace('</head>', '<meta property="article:published_time" content="2024-01-01"><meta property="article:published_time" content="2024-02-01"></head>')
        self.assertIsNone(article_evidence(html)['published_at'])

    def test_dates_do_not_infer_timezone(self):
        self.assertEqual(normalized_date('17 апреля 2024'), '2024-04-17')
        self.assertEqual(normalized_date('05.01.2026 17:52'), '2026-01-05')
        for value in ('2024-01-01T10:00:00', '2024-99-99', '20240101', 'yesterday'):
            with self.subTest(value=value), self.assertRaises(SourceError):
                normalized_date(value)

    def test_discovery_is_allowlisted_deduplicated_and_bounded(self):
        html = ''.join(f'<a href="/ru/foreign_policy/news/{i}/">link</a>' for i in range(150))
        html += '<a href="https://evil.test/ru/foreign_policy/news/1/">bad</a>'
        links = discover_links(html, URL)
        self.assertEqual(len(links), 100)
        self.assertTrue(all(link.startswith('https://mid.ru/') for link in links))


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.refs = self.root / 'reference-docs' / 'announcements'
        self.refs.mkdir(parents=True)
        self.reference = self.refs / '20991231.md'
        self.reference.write_text(URL + '\n\n## Russian\n\n17.04.2024 11:23\nЗаявление\n', encoding='utf-8')
        self.state_path = self.root / 'state.json'

    def ledger(self, **updates):
        record = {'source_url': URL, 'last_source_checked_at': OLD,
                  'last_imported_at': OLD, 'content_hash': 'a' * 64,
                  'published_at': '2024-04-17', 'official_updated_at': '2024-04-18'}
        record.update(updates)
        self.state_path.write_text(json.dumps({'sources': [record]}))
        return record

    def check(self, **kwargs):
        return run_check(self.root, self.root / 'output', now=lambda: NOW, **kwargs)

    def test_real_reference_inventory_uses_publication_line_not_filename(self):
        refs = reference_sources(SCRIPTS.parent)
        january = next(r for r in refs if r['reference_file'].endswith('20260109.md'))
        self.assertEqual(january['reference_published_at'], '2026-01-05')

    def test_confirmed_capture_records_check_not_import_or_update_date(self):
        manifest = self.check(fetch=lambda *a, **k: Capture(URL, ARTICLE.encode(), 'utf-8'))
        item = manifest['sources'][0]
        self.assertEqual(item['last_source_checked_at'], NOW)
        self.assertIsNone(item['official_updated_at'])
        self.assertIsNone(item['last_imported_at'])
        self.assertEqual(item['published_at'], '2024-04-17')
        self.assertEqual(item['check_status'], 'confirmed_announcement')
        self.assertEqual(manifest['latest_included_publication_date'], '2024-04-17')
        self.assertEqual(manifest['scope'], 'tracked_announcements_only')
        self.assertEqual(manifest['site_freshness'], 'unknown')
        self.assertFalse(manifest['publication_ready'])
        self.assertEqual((self.root / 'output' / '001.html').read_bytes(), ARTICLE.encode())

    def test_failure_preserves_verified_state_and_captures_challenge(self):
        previous = self.ledger()
        original = self.state_path.read_bytes()
        manifest = self.check(state_file=self.state_path, fetch=lambda *a, **k: Capture(URL, CHALLENGE.encode(), 'utf-8'))
        item = manifest['sources'][0]
        for key in ('last_source_checked_at', 'last_imported_at', 'content_hash', 'official_updated_at'):
            self.assertEqual(item[key], previous[key])
        self.assertEqual(item['attempt']['attempted_at'], NOW)
        self.assertEqual(item['attempt']['status'], 'failed')
        self.assertEqual(manifest['failed_attempt_count'], 1)
        self.assertEqual(self.state_path.read_bytes(), original)
        self.assertEqual((self.root / 'output' / '001.html').read_bytes(), CHALLENGE.encode())

    def test_network_timeout_preserves_old_check(self):
        self.ledger()
        def fail(*args, **kwargs):
            raise socket.timeout('test timeout')
        manifest = self.check(state_file=self.state_path, fetch=fail)
        self.assertEqual(manifest['sources'][0]['last_source_checked_at'], OLD)
        self.assertEqual(manifest['sources'][0]['attempt']['error_type'], 'TimeoutError')
        self.assertIsNone(manifest['sources'][0]['artifacts'])

    def test_redirect_to_another_official_article_cannot_refresh_check(self):
        self.ledger()
        manifest = self.check(state_file=self.state_path, fetch=lambda *a, **k: Capture(
            'https://www.mid.ru/en/foreign_policy/news/9999999/', ARTICLE.encode(), 'utf-8'))
        item = manifest['sources'][0]
        self.assertEqual(item['last_source_checked_at'], OLD)
        self.assertEqual(item['check_status'], 'failed')
        self.assertIn('requested announcement', item['attempt']['error'])

    def test_official_host_and_language_alias_can_confirm_same_article(self):
        manifest = self.check(fetch=lambda *a, **k: Capture(
            'https://www.mid.ru/ru/foreign_policy/news/1944697/', ARTICLE.encode(), 'utf-8'))
        self.assertEqual(manifest['sources'][0]['check_status'], 'confirmed_announcement')

    def test_invalid_html_encoding_is_a_preserved_failed_attempt(self):
        self.ledger()
        item = self.check(state_file=self.state_path, fetch=lambda *a, **k: Capture(URL, b'\xff', 'utf-8'))['sources'][0]
        self.assertEqual(item['last_source_checked_at'], OLD)
        self.assertEqual(item['attempt']['status'], 'failed')
        self.assertTrue(item['artifacts']['raw_html'])

    def test_offline_does_not_call_network_or_invent_freshness(self):
        def forbidden(*args, **kwargs):
            self.fail('offline mode called network')
        manifest = self.check(offline=True, fetch=forbidden)
        item = manifest['sources'][0]
        self.assertEqual(item['check_status'], 'offline_not_checked')
        self.assertIsNone(item['attempt'])
        self.assertIsNone(item['last_source_checked_at'])
        self.assertIsNone(item['last_imported_at'])
        self.assertIsNone(item['official_updated_at'])
        self.assertEqual(manifest['site_freshness'], 'unknown')

    def test_offline_keeps_prior_verified_values(self):
        previous = self.ledger()
        item = self.check(offline=True, state_file=self.state_path)['sources'][0]
        for key in ('last_source_checked_at', 'last_imported_at', 'content_hash', 'official_updated_at'):
            self.assertEqual(item[key], previous[key])

    def test_unchanged_and_changed_body_comparison(self):
        for changed in (False, True):
            with self.subTest(changed=changed):
                self.ledger(content_hash=article_evidence(ARTICLE)['content_hash'],
                            content_hash_basis=article_evidence(ARTICLE)['content_hash_basis'])
                html = ARTICLE.replace('Jane Doe', 'John Smith') if changed else ARTICLE.replace('20 October', '21 October')
                output = self.root / ('changed' if changed else 'unchanged')
                item = run_check(self.root, output, state_file=self.state_path, now=lambda: NOW,
                                 fetch=lambda *a, **k: Capture(URL, html.encode(), 'utf-8'))['sources'][0]
                self.assertEqual(item['content_status'], 'changed' if changed else 'unchanged')
                self.assertEqual(item['last_imported_at'], OLD)

    def test_incomparable_hash_basis_does_not_claim_source_change(self):
        for basis in (None, 'raw_html_sha256'):
            with self.subTest(basis=basis):
                self.ledger(content_hash='a' * 64, content_hash_basis=basis)
                output = self.root / ('unknown-basis' if basis is None else 'other-basis')
                item = run_check(self.root, output, self.state_path,
                    fetch=lambda *a, **k: Capture(URL, ARTICLE.encode(), 'utf-8'))['sources'][0]
                self.assertEqual(item['content_status'], 'unknown')
                self.assertIn('incomparable_previous_content_hash_basis', item['metadata_warnings'])
                self.assertEqual(item['content_hash_basis'], article_evidence(ARTICLE)['content_hash_basis'])
                self.assertEqual(item['check_status'], 'confirmed_announcement')

    def test_title_only_change_is_recorded_as_changed(self):
        self.ledger(content_hash=article_evidence(ARTICLE)['content_hash'],
                            content_hash_basis=article_evidence(ARTICLE)['content_hash_basis'])
        changed = ARTICLE.replace('Foreign Ministry statement on personal sanctions',
                                  'Foreign Ministry statement on personal sanctions against Canada')
        item = self.check(state_file=self.state_path,
                          fetch=lambda *a, **k: Capture(URL, changed.encode(), 'utf-8'))['sources'][0]
        self.assertEqual(item['content_status'], 'changed')
        self.assertEqual(item['last_imported_at'], OLD)

    def test_invalid_ledger_urls_timestamps_and_hashes_fail_before_output(self):
        invalid = ({'source_url': 'http://mid.ru/a'}, {'last_imported_at': '2026-01-01'},
                   {'last_source_checked_at': '2026-10-20T10:00:00'}, {'published_at': '2026-13-01'},
                   {'official_updated_at': 'yesterday'}, {'content_hash': 'bad'})
        for updates in invalid:
            with self.subTest(updates=updates):
                self.ledger(**updates)
                with self.assertRaises(SourceError):
                    self.check(offline=True, state_file=self.state_path)
                self.assertFalse((self.root / 'output').exists())

    def test_ledger_format_and_duplicates_rejected(self):
        for document in ([], {}, {'sources': [None]}, {'sources': [{'source_url': URL}, {'source_url': URL}]}):
            with self.subTest(document=document):
                self.state_path.write_text(json.dumps(document))
                with self.assertRaises(SourceError):
                    load_state(self.state_path)

    def test_existing_output_refused_and_corpus_preserved(self):
        original = self.reference.read_bytes()
        self.check(offline=True)
        (self.root / 'output' / 'keep.txt').write_text('keep')
        with self.assertRaises(FileExistsError):
            self.check(offline=True)
        self.assertEqual(self.reference.read_bytes(), original)
        self.assertEqual((self.root / 'output' / 'keep.txt').read_text(), 'keep')
        with self.assertRaises(SourceError):
            run_check(self.root, self.refs / 'new', offline=True)

    def test_missing_empty_or_invalid_references_are_explicit_errors(self):
        for path in (self.root / 'missing', self.root / 'empty'):
            with self.subTest(path=path), self.assertRaises(SourceError):
                reference_sources(path)
        self.reference.write_text('https://evil.test/a\n')
        with self.assertRaises(SourceError):
            self.check(offline=True)

    def test_index_only_adds_review_queue_and_never_freshness(self):
        index_url = 'https://mid.ru/en/foreign_policy/news/'
        index = f'<a href="{URL}">tracked</a><a href="/en/foreign_policy/news/1234567/">new</a>'
        def fetch(url, **kwargs):
            return Capture(url, (index if url == index_url else ARTICLE).encode(), 'utf-8')
        manifest = self.check(index_url=index_url, fetch=fetch)
        self.assertEqual(manifest['discovery']['candidate_urls'], ['https://mid.ru/en/foreign_policy/news/1234567/'])
        self.assertEqual(manifest['discovery']['completeness'], 'not_established')
        self.assertEqual(manifest['discovery']['eligibility'], 'requires_review')
        self.assertEqual(manifest['site_freshness'], 'unknown')

    def test_invalid_index_rejected_before_any_network_or_output(self):
        with self.assertRaises(SourceError):
            self.check(index_url='http://mid.ru/index', fetch=lambda *a, **k: self.fail('called network'))
        self.assertFalse((self.root / 'output').exists())

    def test_cli_offline_and_error_exit_codes(self):
        command = [sys.executable, str(SCRIPTS / 'check_source_updates.py'), '--source-root', str(self.root), '--output-dir', str(self.root / 'cli'), '--offline']
        run = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)['mode'], 'offline')
        run = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)
        run = subprocess.run(command + ['--timeout', 'nan'], capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)


if __name__ == '__main__':
    unittest.main()
