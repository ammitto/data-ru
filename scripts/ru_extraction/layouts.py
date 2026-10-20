"""Structural layout handlers. Dates, filenames and announced totals are not selectors."""
from .rows import NUMBER, INLINE_NUMBER, valid_name, split_pair, groups, trim_span

TABLE_COLUMN_HEADINGS = {'имя,фамилия', 'имя,фамилиянарусскомязыке',
                         'нарусскомязыке', 'местоработы/должность'}

CLOSING = ('В условиях,', 'С учетом', 'С учётом', 'Работа над', 'С полным списком',
           'Со сводным списком', 'С общим перечнем', 'В ближайшее время', 'Враждебные действия',
           'Также в список внесен', 'Хотели бы вновь подчеркнуть')


def diagnostic(code, line, detail=None):
    value = {'code': code, 'line': line + 1}
    if detail is not None:
        value['detail'] = detail
    return value


def row(lines, start, end, ru, latin, title, ordinal=None, warnings=()):
    start, end = trim_span(lines, start, end)
    return {'ru': ru, 'latin': latin, 'title': title, 'start': start, 'end': end,
            'ordinal': ordinal, 'warnings': list(warnings)}


def list_boundary(lines, start, end):
    for i in range(start, end):
        text = lines[i]
        if ('Ниже' in text or 'ниже следует поименный' in text or
                'обнародованием данного перечня' in text or 'По состоянию на ' in text):
            return i + 1
    return None


def content_end(lines, start, end):
    for i in range(start, end):
        if lines[i].strip().startswith(CLOSING):
            return i
    return end


def inline_rows(lines, start, end):
    rows, errors, warnings = [], [], []
    pending = None
    section = None

    def flush(stop):
        nonlocal pending
        if pending is None:
            return
        a, b = trim_span(lines, pending, stop)
        raw = '\n'.join(lines[a:b])
        # The pending source row starts with an explicit number or a name before its parenthesis.
        pair = split_pair(raw, recover=True)
        if pair:
            ru, latin, title, warning = pair
            ordinal_match = INLINE_NUMBER.match(lines[a].strip())
            item = row(lines, a, b, ru, latin, title,
                       int(ordinal_match.group(1)) if ordinal_match else None,
                       [warning] if warning else [])
            if section:
                item['group_evidence'] = section
            rows.append(item)
            if item['ordinal'] is not None and item['ordinal'] != len(rows):
                warnings.append(diagnostic('nonconsecutive_row_number', a,
                                           {'actual': item['ordinal'], 'expected': len(rows)}))
            if warning:
                warnings.append(diagnostic(warning, a, raw))
        else:
            errors.append(diagnostic('unparsed_parenthesized_line', a, raw))
        pending = None

    end = content_end(lines, start, end)
    for i in range(start, end):
        text = lines[i].strip()
        if not text:
            continue
        if text.startswith('Члены фракции '):
            flush(i)
            section = {'line': i + 1, 'raw': lines[i]}
            continue
        before = INLINE_NUMBER.sub('', text, count=1).split('(', 1)[0].strip()
        candidate = '(' in text and valid_name(before, 'Cyrl')
        if INLINE_NUMBER.match(text) or candidate:
            flush(i)
            pending = i
        elif pending is not None:
            current = '\n'.join(lines[pending:i])
            if split_pair(current, recover=True):
                flush(i)
                errors.append(diagnostic('unclassified_list_continuation_or_prose', i, lines[i]))
            # Otherwise this line continues an explicitly started name pair.
        else:
            errors.append(diagnostic('unclassified_list_continuation_or_prose', i, lines[i]))
    flush(end)
    return rows, errors, warnings


def dash_rows(lines, start, end):
    rows, errors, warnings = [], [], []
    end = content_end(lines, start, end)
    dashes = [i for i in range(start, end) if lines[i].strip() in ('–', '—', '-')]
    starts = []
    floor = start
    for dash in dashes:
        match = None
        for i in range(floor, dash):
            if not lines[i].strip():
                continue
            pair = split_pair('\n'.join(lines[i:dash]))
            if pair and not pair[2].strip():
                match = (i, dash, pair)
                break
        if match is None:
            errors.append(diagnostic('malformed_dash_name_block', dash))
        else:
            starts.append(match)
        floor = dash + 1
    if any(lines[i].strip() for i in range(start, starts[0][0] if starts else end)):
        errors.append(diagnostic('unclassified_list_prefix', start))
    for n, (a, dash, pair) in enumerate(starts):
        stop = starts[n + 1][0] if n + 1 < len(starts) else end
        ta, tb = trim_span(lines, dash + 1, stop)
        if ta == tb:
            errors.append(diagnostic('missing_dash_title', dash))
        rows.append(row(lines, a, stop, pair[0], pair[1], '\n'.join(lines[ta:tb])))
    return rows, errors, warnings


def vertical_rows(lines, header, end):
    rows, errors, warnings = [], [], []
    # Table columns are declared in the header; Latin/Russian cells stay within that section.
    start = header + 1
    end = content_end(lines, start, end)
    mixed = '\t' in lines[header]
    if mixed:
        starts = []
        for i in range(start, end):
            text = lines[i].strip()
            cells = text.split('\t')
            if len(cells) == 2 and valid_name(cells[0], 'Latn') and valid_name(cells[1], 'Cyrl'):
                starts.append(i)
            elif valid_name(text, 'Latn'):
                later = next((j for j in range(i + 1, end) if lines[j].strip()), end)
                if later < end:
                    cell_end = next((j for j in range(later, end) if not lines[j].strip()), end)
                    if valid_name('\n'.join(lines[later:cell_end]), 'Cyrl'):
                        starts.append(i)
        boundaries = []
        for i in starts:
            previous = next((j for j in range(i - 1, header, -1) if lines[j].strip()), header)
            marker = NUMBER.fullmatch(lines[previous].strip())
            boundaries.append((previous if marker else i, i, int(marker.group(1)) if marker else None))
    else:
        boundaries = [(i, i + 1, int(NUMBER.fullmatch(lines[i].strip()).group(1)))
                      for i in range(start, end) if NUMBER.fullmatch(lines[i].strip())]
    if not boundaries:
        errors.append(diagnostic('no_numbered_rows' if not mixed else 'no_table_rows', header))
        return rows, errors, warnings
    for i in range(start, boundaries[0][0]):
        heading = ''.join(lines[i].casefold().split())
        if heading and heading not in TABLE_COLUMN_HEADINGS:
            errors.append(diagnostic('unclassified_list_prefix', i, lines[i]))
    for n, (a, data_start, ordinal) in enumerate(boundaries):
        stop = boundaries[n + 1][0] if n + 1 < len(boundaries) else end
        if mixed and '\t' in lines[data_start]:
            latin, ru = lines[data_start].split('\t')
            ta, tb = trim_span(lines, data_start + 1, stop)
        else:
            cells = groups(lines, data_start, stop)
            if len(cells) < 3:
                errors.append(diagnostic('malformed_vertical_row', a)); continue
            latin = '\n'.join(lines[j] for j in cells[0])
            ru = '\n'.join(lines[j] for j in cells[1])
            ta, tb = trim_span(lines, cells[2][0], stop)
        if not valid_name(latin, 'Latn') or not valid_name(ru, 'Cyrl'):
            errors.append(diagnostic('ambiguous_vertical_name_cells', a)); continue
        if ta == tb:
            errors.append(diagnostic('missing_vertical_title', a))
        if not mixed:
            # A lost ordinal must not turn the next bilingual row into a role.
            title_cells = groups(lines, ta, tb)
            for latin_cell, ru_cell in zip(title_cells, title_cells[1:]):
                possible_latin = '\n'.join(lines[j] for j in latin_cell)
                possible_ru = '\n'.join(lines[j] for j in ru_cell)
                if valid_name(possible_latin, 'Latn') and valid_name(possible_ru, 'Cyrl'):
                    errors.append(diagnostic('unclassified_possible_table_row', latin_cell[0],
                                             {'latin_cell': possible_latin, 'russian_cell': possible_ru}))
        if mixed:
            for j in range(ta, tb):
                if valid_name(lines[j].strip(), 'Latn'):
                    errors.append(diagnostic('unclassified_possible_table_row', j, lines[j]))
        rows.append(row(lines, a, stop, ru, latin, '\n'.join(lines[ta:tb]), ordinal))
        if ordinal is None:
            warnings.append(diagnostic('missing_source_ordinal', a))
        elif ordinal != n + 1:
            warnings.append(diagnostic('nonconsecutive_row_number', a,
                                       {'actual': ordinal, 'expected': n + 1}))
    return rows, errors, warnings


def extract(lines, start, end):
    header = next((i for i in range(start, end) if '№ п/п' in lines[i]), None)
    if header is not None:
        family = 'mixed_tab_vertical_cells' if '\t' in lines[header] else 'numbered_vertical_cells'
        return family, *vertical_rows(lines, header, end)
    boundary = list_boundary(lines, start, end)
    if boundary is None:
        return None, [], [diagnostic('unestablished_list_boundary', start)], []
    if any(lines[i].strip() in ('–', '—', '-') for i in range(boundary, end)):
        return 'unnumbered_dash_blocks', *dash_rows(lines, boundary, end)
    return 'same_line_name_pair', *inline_rows(lines, boundary, end)
