"""Lexical row evidence, with no identity or transliteration corrections."""
import re
import unicodedata

NUMBER = re.compile(r'^(\d+)\.?$')
INLINE_NUMBER = re.compile(r'^(\d+)[.)]?\s+')
PARTICLES = {'van', 'von', 'de', 'der', 'den', 'da', 'del', 'di', 'du', 'of', 'the',
             'ван', 'де', 'дель', 'дю', 'руа'}


def script(value):
    found = set()
    for char in value:
        if char.isalpha():
            name = unicodedata.name(char, '')
            found.add('Cyrl' if 'CYRILLIC' in name else 'Latn' if 'LATIN' in name else 'Other')
    return next(iter(found)) if len(found) == 1 else 'Mixed' if found else 'Unknown'


def valid_name(value, expected):
    # Punctuation and particles occur in the source. They are preserved, not repaired.
    if not value or len(value) > 240:
        return False
    if any(not (c.isalpha() or c.isspace() or c in ".,‘’'`\"“”«»-/‐‑–") for c in value):
        return False
    words = re.findall(r'[^\W\d_]+', value, re.UNICODE)
    if len(words) < 2 or not words[0][0].isupper():
        return False
    tokens = [token.strip(".,‘’'`\"“”«»") for token in value.split()]
    def proper_token(token):
        if token and (token[0].isupper() or token.casefold() in PARTICLES):
            return True
        # Source-provided lower-case surname prefixes, e.g. д`Амбросио.
        return bool(re.fullmatch(r"[dдl]['’`][^\W\d_].*", token))
    if not all(proper_token(token) for token in tokens):
        return False
    return any(('CYRILLIC' if expected == 'Cyrl' else 'LATIN') in unicodedata.name(c, '')
               for c in value)


def split_pair(value, recover=False):
    """Return literal source name/title slices; recovery needs an explicit row boundary."""
    value = INLINE_NUMBER.sub('', value.lstrip(), count=1)
    if '(' not in value:
        return None
    ru, rest = value.split('(', 1)
    if not valid_name(ru.strip(), 'Cyrl'):
        return None
    warning = None
    if ')' in rest:
        latin, title = rest.split(')', 1)
        # A missing ')' may otherwise consume a later role's parenthesis.
        if not valid_name(latin.strip(), 'Latn'):
            if not recover:
                return None
            separator = re.search(r'\s+[–—]\s+', rest)
            if not separator or not valid_name(rest[:separator.start()].strip(), 'Latn'):
                return None
            latin, title = rest[:separator.start()], rest[separator.start():]
            warning = 'missing_name_closing_parenthesis'
        elif title.strip() and title.lstrip()[0] not in '–—-,;.' and not title[0].isspace():
            return None
    elif recover:
        separator = re.search(r'\s+[–—]\s+', rest)
        if not separator:
            return None
        latin, title = rest[:separator.start()], rest[separator.start():]
        warning = 'missing_name_closing_parenthesis'
    else:
        return None
    if not valid_name(latin.strip(), 'Latn'):
        return None
    return ru.strip(), latin.strip(), title, warning


def paired_line(value):
    pair = split_pair(value)
    return pair[:3] if pair else None


def trim_span(lines, start, end):
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return start, end


def groups(lines, start, end):
    result, current = [], []
    for index in range(start, end):
        if lines[index].strip():
            current.append(index)
        elif current:
            result.append(current)
            current = []
    if current:
        result.append(current)
    return result
