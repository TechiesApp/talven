"""Bounded sequential UTF-16 LSP edits; no parsing or filesystem access."""

import re

MAX_CHANGES = 128
MAX_DOCUMENT_BYTES = 1024 * 1024


def edit_offset(source, point):
    if not isinstance(point, dict):
        raise ValueError('Invalid edit position')
    line, character = point.get('line'), point.get('character')
    if any(type(value) is not int or not 0 <= value <= 2147483647 for value in (line, character)):
        raise ValueError('Edit positions require unsigned line/character integers')
    start, number, end = 0, 0, len(source)
    for match in re.finditer(r'\r\n|\r|\n', source):
        if number == line:
            end = match.start()
            break
        start, number = match.end(), number + 1
    else:
        if number != line:
            raise ValueError('Edit line is outside the current document')
    units = 0
    for index in range(start, end):
        if units == character:
            return index
        units += 2 if ord(source[index]) > 0xffff else 1
        if units > character:
            raise ValueError('Edit position splits a UTF-16 surrogate pair')
    return end  # LSP columns beyond line length clamp to the end of that line.


def apply_changes(source, changes):
    """Build a candidate locally; None requires an initial full replacement."""
    if not isinstance(changes, list) or len(changes) > MAX_CHANGES:
        raise ValueError('Content changes require a list of at most 128 edits')
    for change in changes:
        if not isinstance(change, dict) or not isinstance(change.get('text'), str):
            raise ValueError('Content changes require string text')
        text = change['text']
        if len(text.encode('utf-8')) > MAX_DOCUMENT_BYTES:
            raise ValueError('Edit text exceeds the 1 MiB document mirror limit')
        if 'range' not in change:
            if 'rangeLength' in change:
                raise ValueError('rangeLength requires a range')
            source = text
        else:
            if source is None:
                raise ValueError('Document requires a full replacement after a rejected change')
            selected = change['range']
            if not isinstance(selected, dict):
                raise ValueError('Edit range must be an object')
            start = edit_offset(source, selected.get('start'))
            end = edit_offset(source, selected.get('end'))
            if start > end:
                raise ValueError('Edit range is reversed')
            if 'rangeLength' in change:
                length = change['rangeLength']
                if type(length) is not int or not 0 <= length <= 2147483647 or length != len(source[start:end].encode('utf-16-le')) // 2:
                    raise ValueError('rangeLength does not match the replaced UTF-16 text')
            source = source[:start] + text + source[end:]
        if len(source.encode('utf-8')) > MAX_DOCUMENT_BYTES:
            raise ValueError('Reconstructed text exceeds the 1 MiB document mirror limit')
    if source is None:
        raise ValueError('Document requires a full replacement after a rejected change')
    return source
