"""Bounded retrieval restricted to official HTTPS hosts, including redirects."""
from dataclasses import dataclass
import math
import time
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_BYTES = 2_000_000
MAX_REDIRECTS = 5


class SourceError(ValueError):
    """An input or response cannot safely establish source freshness."""


def official_url(value):
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        raise SourceError('invalid source URL')
    try:
        parts = urlsplit(value)
        valid = (parts.scheme == 'https' and parts.hostname in {'mid.ru', 'www.mid.ru'}
                 and parts.username is None and parts.password is None
                 and parts.port in {None, 443} and '\\' not in value)
    except ValueError as error:
        raise SourceError('invalid source URL') from error
    if not valid:
        raise SourceError('source URL must use HTTPS on mid.ru or www.mid.ru without credentials')
    return urlunsplit(('https', parts.hostname, parts.path or '/', parts.query, ''))


class OfficialRedirectHandler(HTTPRedirectHandler):
    def __init__(self, initial_url):
        super().__init__()
        self.seen = {official_url(initial_url)}

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = official_url(newurl)
        if target in self.seen or len(self.seen) > MAX_REDIRECTS:
            raise SourceError('redirect loop or redirect limit exceeded')
        self.seen.add(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


@dataclass
class Capture:
    url: str
    body: bytes
    charset: str


def retrieve(url, timeout=15, opener=None):
    url = official_url(url)
    if not math.isfinite(timeout) or not 0 < timeout <= 120:
        raise SourceError('timeout must be greater than 0 and at most 120 seconds')
    opener = opener or build_opener(OfficialRedirectHandler(url))
    request = Request(url, headers={'User-Agent': 'Ammitto RU source checker', 'Accept': 'text/html'})
    deadline = time.monotonic() + timeout
    with opener.open(request, timeout=timeout) as response:
        final_url = official_url(response.geturl())
        if response.status != 200:
            raise SourceError(f'expected HTTP 200, received {response.status}')
        if response.headers.get_content_type() != 'text/html':
            raise SourceError('response is not HTML')
        length = response.headers.get('Content-Length')
        if length is not None:
            try:
                if int(length) < 0 or int(length) > MAX_BYTES:
                    raise SourceError('response exceeds byte limit')
            except ValueError as error:
                raise SourceError('invalid or excessive Content-Length') from error
        chunks = []
        size = 0
        while True:
            if time.monotonic() >= deadline:
                raise SourceError('retrieval deadline exceeded')
            # HTTPResponse.read(n) may repeatedly wait for n bytes when a peer
            # trickles data. read1 returns after one underlying buffered read,
            # allowing the deadline to be checked between network reads.
            reader = getattr(response, 'read1', response.read)
            chunk = reader(min(65536, MAX_BYTES + 1 - size))
            if time.monotonic() >= deadline:
                raise SourceError('retrieval deadline exceeded')
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BYTES:
                raise SourceError('response exceeds byte limit')
            chunks.append(chunk)
        return Capture(final_url, b''.join(chunks), response.headers.get_content_charset() or 'utf-8')
