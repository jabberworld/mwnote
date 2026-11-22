"""Работа с пунктами заметок в вики-тексте MediaWiki."""

import asyncio
import re

from mediawiki import MediaWikiError

NOTE_RE = re.compile(r'^[ \t]*#(?!#)[ \t]*(.*?)[ \t]*$')
DELETED_RE = re.compile(r'^<s>(.*)</s>$', re.IGNORECASE | re.DOTALL)
NEW_PAGE_TEXT = '<!-- mwnote: страница заметок -->\n'


class NoteError(Exception):
    pass


class NoteIndexError(NoteError):

    def __init__(self, number, count):
        self.number = number
        self.count = count
        super().__init__('пункт %d не найден (всего %d)' % (number, count))


class NoteEmptyError(NoteError):
    pass


class NoteAlreadyDeletedError(NoteError):

    def __init__(self, number):
        self.number = number
        super().__init__('пункт %d уже удалён' % number)


class NoteItem:

    def __init__(self, number, line_index, text, deleted=False):
        self.number = number
        self.line_index = line_index
        self.text = text
        self.deleted = deleted


def parse_items(text):
    items = []
    for line_index, line in enumerate((text or '').splitlines()):
        match = NOTE_RE.match(line)
        if match is None:
            continue
        value = match.group(1).strip()
        deleted_match = DELETED_RE.match(value)
        deleted = deleted_match is not None
        if deleted:
            value = deleted_match.group(1).strip()
        items.append(NoteItem(len(items) + 1, line_index, value, deleted))
    return items


def normalize_note(text):
    value = ' '.join((text or '').split())
    if not value:
        raise NoteEmptyError('пустой текст заметки')
    return value


def make_summary(action, actor=None):
    actor = ' '.join(str(actor or '').split())[:120]
    if actor:
        return 'mwnote: %s (%s)' % (action, actor)
    return 'mwnote: %s' % action


def _split(text):
    return (text or '').splitlines()


def _join(lines):
    if not lines:
        return ''
    return '\n'.join(lines).rstrip('\n') + '\n'


def _add_line(text, value):
    lines = _split(text)
    items = parse_items(text)
    new_line = '# %s' % value
    if items:
        lines.insert(items[-1].line_index + 1, new_line)
    else:
        if lines and lines[-1].strip():
            lines.append('')
        lines.append(new_line)
    return _join(lines)


def _delete_line(text, number):
    items = parse_items(text)
    if not 1 <= number <= len(items):
        raise NoteIndexError(number, len(items))
    item = items[number - 1]
    if item.deleted:
        raise NoteAlreadyDeletedError(number)
    lines = _split(text)
    line = lines[item.line_index]
    match = NOTE_RE.match(line)
    indent = line[:match.start(1)]
    lines[item.line_index] = '%s<s>%s</s>' % (indent, item.text)
    return _join(lines), item.text


class NoteService:

    def __init__(self, client):
        self.client = client
        self._lock = asyncio.Lock()

    async def _call(self, func, *args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    async def ensure_page(self, title, actor=None):
        async with self._lock:
            page = await self._call(self.client.get_page, title)
            if page.exists:
                return page
            try:
                await self._call(
                    self.client.edit_page, title, NEW_PAGE_TEXT,
                    make_summary('создана страница заметок', actor), True)
            except MediaWikiError as exc:
                if exc.code != 'articleexists':
                    raise
            return await self._call(self.client.get_page, title)

    async def _mutate(self, title, mutate, actor=None,
                      action='изменение заметок'):
        async with self._lock:
            for attempt in (0, 1):
                page = await self._call(self.client.get_page, title)
                if not page.exists:
                    try:
                        await self._call(
                            self.client.edit_page, title, NEW_PAGE_TEXT,
                            make_summary('создана страница заметок', actor),
                            True)
                    except MediaWikiError as exc:
                        if exc.code != 'articleexists':
                            raise
                    page = await self._call(self.client.get_page, title)
                new_text, result = mutate(page.text)
                if new_text == page.text:
                    return page.title, result
                try:
                    await self._call(
                        self.client.edit_page, page.title, new_text,
                        make_summary(action, actor), False,
                        page.timestamp)
                except MediaWikiError as exc:
                    if exc.code == 'editconflict' and attempt == 0:
                        continue
                    raise
                return page.title, result
        raise NoteError('не удалось сохранить страницу после конфликта правок')

    async def list_notes(self, title, actor=None, full=False):
        page = await self.ensure_page(title, actor)
        items = parse_items(page.text)
        if not full:
            items = [item for item in items if not item.deleted]
        return page.title, items

    async def add_note(self, title, text, actor=None):
        value = normalize_note(text)
        page_title, number = await self._mutate(
            title, lambda current: (
                _add_line(current, value),
                len(parse_items(current)) + 1),
            actor=actor, action='добавление заметки')
        return page_title, number, value

    async def delete_note(self, title, number, actor=None):
        page_title, deleted = await self._mutate(
            title, lambda current: _delete_line(current, number),
            actor=actor, action='удаление заметки')
        return page_title, number, deleted
