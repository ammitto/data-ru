"""Extract only article-specific text and explicit publication/update evidence."""
from datetime import date, datetime
import hashlib
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit

from .transport import SourceError, official_url

MONTHS = dict(zip(('january february march april may june july august september october november december').split(), range(1, 13)))
MONTHS.update(dict(zip(('января февраля марта апреля мая июня июля августа сентября октября ноября декабря').split(), range(1, 13))))
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
IGNORED = {'script', 'style', 'nav', 'header', 'footer', 'button', 'form', 'svg', 'noscript'}


def normalized_date(value, timestamp_only=False):
    """Never infer a timezone, a date from an identifier, or a date from a filename."""
    if not isinstance(value, str):
        raise SourceError('date must be a string')
    value = value.strip()
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) and not timestamp_only:
            return date.fromisoformat(value).isoformat()
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is not None and stamp.utcoffset() is not None:
            return stamp.isoformat()
    except ValueError:
        pass
    if not timestamp_only:
        match = re.fullmatch(r'(\d{1,2})\s+([^\W\d_]+)\s+(\d{4})(?:\s*г\.?)?', value.lower())
        if match and match[2] in MONTHS:
            try:
                return date(int(match[3]), MONTHS[match[2]], int(match[1])).isoformat()
            except ValueError:
                pass
        match = re.fullmatch(r'(\d{2})\.(\d{2})\.(\d{4})(?:\s+\d{2}:\d{2})?', value)
        if match:
            try:
                return date(int(match[3]), int(match[2]), int(match[1])).isoformat()
            except ValueError:
                pass
    raise SourceError('date has no supported explicit source value or timezone')


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.body = []
        self.title = []
        self.dates = []
        self.date_classes = set()
        self.meta = {}
        self.links = []
        self.body_count = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get('class', '').split()
        inherited = self.stack[-1][1:] if self.stack else (False, False, False, False)
        body, title, published, ignored = inherited
        ignored = ignored or tag in IGNORED or 'hidden' in attrs or attrs.get('aria-hidden') == 'true'
        if 'article-content' in classes and not ignored:
            self.body_count += 1
            body = True
        title = title or (tag == 'h1' and bool({'photo-content__title', 'audio-content__title'} & set(classes)))
        date_classes = {'photo-content__date', 'audio-content__date'} & set(classes)
        published = published or bool(date_classes)
        if date_classes and not ignored:
            self.date_classes.update(date_classes)
        if tag == 'meta':
            key = attrs.get('property', '')
            if key in {'article:published_time', 'article:modified_time'}:
                self.meta.setdefault(key, []).append(attrs.get('content', ''))
        if tag == 'a' and not ignored and len(self.links) < 1000:
            self.links.append(attrs.get('href', ''))
        if body and not ignored and tag in {'p', 'div', 'tr', 'td', 'th', 'li', 'br'}:
            self.body.append('\n')
        if tag not in VOID:
            self.stack.append((tag, body, title, published, ignored))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                if self.stack[i][1] and not self.stack[i][4]:
                    self.body.append('\n')
                del self.stack[i:]
                break

    def handle_data(self, value):
        if not self.stack:
            return
        _, body, title, published, ignored = self.stack[-1]
        if ignored:
            return
        if body:
            self.body.append(value)
        if title:
            self.title.append(value)
        if published:
            self.dates.append(value)


def parse_page(html):
    page = Page()
    page.feed(html)
    page.close()
    return page


def article_evidence(html):
    page = parse_page(html)
    title = ' '.join(''.join(page.title).split())
    body = ' '.join(' '.join(page.body).split())
    if (page.body_count != 1 or len(body) < 80 or not title
            or re.search(r'captcha|verify (?:you|your)|access denied|just a moment|проверка браузера', title + ' ' + body, re.I)
            or not re.search(r'sanction|санкц|deny entry|въезд|stop.list|стоп.лист', title + ' ' + body, re.I)):
        raise SourceError('HTML does not confirm an accessible sanctions announcement body')
    warnings = []

    def explicit_date(key, fallback=None):
        raw = page.meta.get(key, []) or ([fallback] if fallback else [])
        if not raw:
            return None, None
        try:
            dates = {normalized_date(v) for v in raw}
            if len(dates) != 1:
                raise SourceError('conflicting source dates')
            return next(iter(dates)), {'kind': key if key in page.meta else '+'.join(sorted(page.date_classes)), 'raw': raw}
        except SourceError:
            warnings.append('unusable_' + key.replace(':', '_'))
            return None, {'kind': key, 'raw': raw}

    published, published_evidence = explicit_date('article:published_time', ''.join(page.dates).strip())
    updated, updated_evidence = explicit_date('article:modified_time')
    # The official title supplies context (for example the target country) and
    # is part of the announcement even when the table/body stays identical.
    canonical_content = title + '\n' + body
    return {'title': title, 'article_text': body,
            'content_hash': hashlib.sha256(canonical_content.encode('utf-8')).hexdigest(),
            'content_hash_basis': 'normalized_article_title_and_body_sha256',
            'published_at': published, 'published_at_evidence': published_evidence,
            'official_updated_at': updated, 'official_updated_at_evidence': updated_evidence,
            'metadata_warnings': warnings}


def discover_links(html, base_url, limit=100):
    """A bounded review queue, never a claim to index completeness or eligibility."""
    urls = set()
    for href in parse_page(html).links:
        try:
            url = official_url(urljoin(base_url, href))
        except SourceError:
            continue
        if re.fullmatch(r'/(?:ru|en)/(?:foreign_policy/news|maps/[^/]+|detail-material-page)/\d+/', urlsplit(url).path):
            urls.add(url)
        if len(urls) >= limit:
            break
    return sorted(urls)
