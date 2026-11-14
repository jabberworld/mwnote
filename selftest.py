#!/usr/bin/env python3
"""Офлайн-тесты mwnote: конфиг, sqlite, MediaWiki, диалоги, MUC-права."""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from slixmpp import JID

from bot import MwnoteBot, match_addressed, split_chunks
from config import Config
from core import MwnoteCore
from mediawiki import MediaWikiClient, MediaWikiError
from notes import NoteService, make_summary, parse_items
from storage import Storage
import texts

FAILED = []


def check(name, condition, extra=''):
    status = 'ok' if condition else 'FAIL'
    print('[%s] %s %s' % (status, name, extra))
    if not condition:
        FAILED.append(name)


CONFIG_TEXT = '''# mwnote test config
[jabber]
jid = bot@example.com
password = secret
resource = test
host =
port =

[admins]
# keep this comment
list = admin@example.com

[muc]
min_role = moderator
default_nick =
autojoin = true

[wiki]
url =
user =
password =

[storage]
db_path = test.sqlite3

[interface]
language = ru
chat_markers = true
'''


class FakeWiki:

    def __init__(self):
        self.pages = {}
        self.revision = 0
        self.logged_in = False
        self.requests = []
        self.summaries = []

    @staticmethod
    def _get(params, key, default=''):
        values = params.get(key)
        return values[0] if values else default

    def handle(self, method, path, query, form):
        self.requests.append((method, path, query, form))
        if path != '/w/api.php':
            return 404, {'error': {'code': 'http404', 'info': 'not found'}}
        params = form if method == 'POST' else query
        action = self._get(params, 'action')
        if action == 'query':
            meta = self._get(params, 'meta')
            if meta == 'siteinfo':
                return 200, {'query': {'general': {'sitename': 'Fake'}}}
            if meta == 'tokens':
                if self._get(params, 'type') == 'login':
                    return 200, {'query': {'tokens': {
                        'logintoken': 'LOGIN'}}}
                return 200, {'query': {'tokens': {'csrftoken': 'CSRF'}}}
            if self._get(params, 'prop') == 'revisions':
                title = self._get(params, 'titles')
                page = self.pages.get(title)
                if page is None:
                    return 200, {'query': {'pages': {'-1': {
                        'title': title, 'missing': ''}}}}
                return 200, {'query': {'pages': {'1': {
                    'pageid': 1,
                    'title': page['title'],
                    'revisions': [{
                        'timestamp': page['timestamp'],
                        'slots': {'main': {'content': page['text']}},
                    }],
                }}}}
        if action == 'login':
            user = self._get(params, 'lgname')
            password = self._get(params, 'lgpassword')
            token = self._get(params, 'lgtoken')
            if token != 'LOGIN':
                return 200, {'login': {'result': 'NeedToken',
                                       'token': 'LOGIN'}}
            if user == 'admin' and password == 'secret':
                self.logged_in = True
                return 200, {'login': {'result': 'Success'}}
            return 200, {'login': {'result': 'Failed',
                                   'reason': 'bad password'}}
        if action == 'edit':
            if self._get(params, 'token') != 'CSRF':
                return 200, {'error': {'code': 'badtoken',
                                       'info': 'bad token'}}
            title = self._get(params, 'title')
            text = self._get(params, 'text')
            createonly = self._get(params, 'createonly') == '1'
            basetimestamp = self._get(params, 'basetimestamp')
            if createonly and title in self.pages:
                return 200, {'error': {'code': 'articleexists',
                                       'info': 'exists'}}
            if basetimestamp and title in self.pages:
                if self.pages[title]['timestamp'] != basetimestamp:
                    return 200, {'error': {'code': 'editconflict',
                                           'info': 'conflict'}}
            self.summaries.append(
                (title, self._get(params, 'summary'), createonly))
            self.revision += 1
            timestamp = '2026-01-01T00:00:%02dZ' % self.revision
            self.pages[title] = {
                'title': title,
                'text': text,
                'timestamp': timestamp,
            }
            return 200, {'edit': {'result': 'Success', 'title': title}}
        return 200, {'error': {'code': 'unknown', 'info': str(params)}}


class FakeHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        self._serve('GET')

    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        body = self.rfile.read(length).decode('utf-8') if length else ''
        self._serve('POST', body)

    def _serve(self, method, body=''):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        form = parse_qs(body, keep_blank_values=True) if body else {}
        status, payload = self.server.state.handle(
            method, parsed.path, query, form)
        data = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class FakeServer:

    def __init__(self):
        self.state = FakeWiki()
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), FakeHandler)
        self.httpd.state = self.state
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:%d' % self.httpd.server_port

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


async def test_config_and_storage(tmp):
    config_path = os.path.join(tmp, 'mwnote.conf')
    with open(config_path, 'w', encoding='utf-8') as handle:
        handle.write(CONFIG_TEXT)
    cfg = Config(config_path)
    check('config: jid', cfg.jabber_jid == 'bot@example.com')
    check('config: admins', cfg.admins == ['admin@example.com'])
    check('config: db path absolute', os.path.isabs(cfg.db_path))
    check('config: min role', cfg.muc_min_role == 'moderator')
    cfg.set_admins(['admin@example.com', 'second@example.com'])
    with open(config_path, 'r', encoding='utf-8') as handle:
        text = handle.read()
    check('config: comment preserved', '# keep this comment' in text)
    cfg2 = Config(config_path)
    check('config: admins persisted',
          cfg2.admins == ['admin@example.com', 'second@example.com'])

    storage = Storage(cfg2.db_path)
    storage.save_wiki('https://wiki.example.com', 'admin', 'secret')
    settings = storage.wiki_settings()
    check('storage: wiki settings', settings['user'] == 'admin')
    storage.set_page('user:admin@example.com', 'Page')
    check('storage: page', storage.get_page('user:admin@example.com') == 'Page')
    storage.add_room('room@conf.example.com', 'bot')
    check('storage: room list',
          storage.list_rooms() == [('room@conf.example.com', 'bot')])
    storage.remove_room('room@conf.example.com')
    check('storage: room removed', storage.list_rooms() == [])
    mode = oct(os.stat(cfg2.db_path).st_mode & 0o777)
    check('storage: db mode 600', mode == '0o600', mode)
    storage.save_wiki('', '', '')
    storage.close()


async def test_notes_and_mediawiki(tmp, server):
    client = MediaWikiClient(server.url)
    ok = await asyncio.to_thread(client.login, 'admin', 'secret')
    check('mediawiki: login', ok is True)
    check('mediawiki: api discovery', client.api_url.endswith('/w/api.php'),
          client.api_url)
    page = await asyncio.to_thread(client.get_page, 'Test page')
    check('mediawiki: missing page', not page.exists)
    await asyncio.to_thread(client.edit_page, 'Test page', 'hello',
                            'create', True)
    page = await asyncio.to_thread(client.get_page, 'Test page')
    check('mediawiki: created page', page.exists and page.text == 'hello')
    await asyncio.to_thread(client.edit_page, 'Test page', 'hello world',
                            'update', False, page.timestamp)
    page = await asyncio.to_thread(client.get_page, 'Test page')
    check('mediawiki: edited page', page.text == 'hello world')

    bad = MediaWikiClient(server.url)
    try:
        await asyncio.to_thread(bad.login, 'admin', 'wrong')
        failed = False
    except MediaWikiError:
        failed = True
    check('mediawiki: wrong password rejected', failed)

    check('notes: summary without actor',
          make_summary('изменение заметок') == 'mwnote: изменение заметок')
    check('notes: summary normalized actor',
          make_summary('добавление заметки', ' bad\n nick ')
          == 'mwnote: добавление заметки (bad nick)')

    service = NoteService(client)
    title, items = await service.list_notes('Note page', actor='testnick')
    check('notes: new page empty', title == 'Note page' and items == [])
    check('notes: creation summary actor',
          server.state.summaries[-1] == (
              'Note page',
              'mwnote: создана страница заметок (testnick)', True),
          server.state.summaries[-1])
    _, number, value = await service.add_note(
        'Note page', 'Первая', actor='testnick')
    check('notes: add first', (number, value) == (1, 'Первая'))
    check('notes: add summary actor',
          server.state.summaries[-1][1]
          == 'mwnote: добавление заметки (testnick)',
          server.state.summaries[-1])
    _, number, _ = await service.add_note('Note page', 'Вторая')
    check('notes: add second', number == 2)
    check('notes: add summary without actor',
          server.state.summaries[-1][1] == 'mwnote: добавление заметки',
          server.state.summaries[-1])
    _, items = await service.list_notes('Note page')
    check('notes: list', items == ['Первая', 'Вторая'], items)
    _, number, value = await service.delete_note(
        'Note page', 2, actor='testnick')
    check('notes: delete', (number, value) == (2, 'Вторая'))
    check('notes: delete summary actor',
          server.state.summaries[-1][1]
          == 'mwnote: удаление заметки (testnick)',
          server.state.summaries[-1])
    _, items = await service.list_notes('Note page')
    check('notes: list after delete', items == ['Первая'], items)

    server.state.pages['Preserve'] = {
        'title': 'Preserve',
        'text': '== Заголовок ==\n# one\n## nested\n# two\n\nХвост\n',
        'timestamp': '2026-01-01T00:00:00Z',
    }
    await service.add_note('Preserve', 'three')
    text = server.state.pages['Preserve']['text']
    check('notes: heading preserved', '== Заголовок ==' in text)
    check('notes: nested list preserved', '## nested' in text)
    check('notes: tail preserved', 'Хвост' in text)
    check('notes: added after list', text.index('# three') < text.index('Хвост'))
    await service.delete_note('Preserve', 2)
    text = server.state.pages['Preserve']['text']
    check('notes: deleted line', '# two' not in text)
    check('notes: delete preserved heading', '== Заголовок ==' in text)
    parsed = parse_items('# a\n## nested\n# b\n')
    check('notes: parser ignores nested',
          [item.text for item in parsed] == ['a', 'b'])


async def test_core_dialogs(tmp, cfg, storage, server):
    async def join_room(room, nick):
        return True, nick

    async def leave_room(room):
        return True, None

    core = MwnoteCore(cfg, storage, 'bot', join_room=join_room,
                      leave_room=leave_room)
    user = 'admin@example.com'

    answer = await core.handle_direct(user, 'wiki')
    check('core: wiki prompt', answer == texts.ASK_WIKI_URL, answer)
    answer = await core.handle_direct(user, server.url)
    check('core: wiki user prompt', answer == texts.ASK_WIKI_USER, answer)
    answer = await core.handle_direct(user, 'admin')
    check('core: wiki password prompt', answer == texts.ASK_WIKI_PASSWORD,
          answer)
    answer = await core.handle_direct(user, 'secret')
    check('core: wiki saved', answer == texts.WIKI_SAVED % (
        server.url, 'admin'), answer)
    check('core: wiki persisted',
          storage.wiki_settings()['url'] == server.url)

    answer = await core.handle_direct(user, 'switch')
    check('core: switch prompt', answer == texts.ASK_SWITCH, answer)
    answer = await core.handle_direct(user, 'Заметки')
    check('core: switch page',
          answer == texts.SWITCHED % 'Заметки', answer)
    check('core: page stored',
          storage.get_page('user:%s' % user) == 'Заметки')
    check('core: summary direct switch',
          server.state.summaries[-1][1]
          == 'mwnote: создана страница заметок (admin)',
          server.state.summaries[-1])

    answer = await core.handle_direct(user, '+ Сходить в магазин')
    check('core: add note', answer == texts.NOTE_ADDED % (1,
          'Сходить в магазин'), answer)
    check('core: summary direct add',
          server.state.summaries[-1][1]
          == 'mwnote: добавление заметки (admin)',
          server.state.summaries[-1])
    answer = await core.handle_direct(user, '+ Убрать в доме')
    check('core: add second note', 'Добавлен пункт 2' in answer, answer)
    answer = await core.handle_direct(user, 'list')
    check('core: list header', answer.startswith(
        texts.NOTE_LIST_HEADER % 'Заметки'), answer)
    check('core: list items', '1. Сходить в магазин' in answer
          and '2. Убрать в доме' in answer, answer)
    answer = await core.handle_direct(user, '- 2')
    check('core: delete note',
          answer == texts.NOTE_DELETED % (2, 'Убрать в доме'), answer)
    check('core: summary direct delete',
          server.state.summaries[-1][1]
          == 'mwnote: удаление заметки (admin)',
          server.state.summaries[-1])
    answer = await core.handle_direct(user, 'list')
    check('core: list after delete',
          'Убрать в доме' not in answer, answer)

    answer = await core.handle_direct(user, 'add')
    check('core: add admin prompt', answer == texts.ASK_ADMIN_ADD, answer)
    answer = await core.handle_direct(user, 'second@example.com')
    check('core: add admin', answer == texts.ADMIN_ADDED, answer)
    cfg2 = Config(cfg.config_file)
    check('core: admin persisted', 'second@example.com' in cfg2.admins,
          cfg2.admins)
    answer = await core.handle_direct(user, 'del')
    check('core: del admin list', '1.' in answer and '2.' in answer, answer)
    answer = await core.handle_direct(user, '1')
    check('core: del admin', 'Адрес удалён' in answer, answer)
    answer = await core.handle_direct(user, 'del')
    answer = await core.handle_direct(user, '1')
    check('core: last admin protected', answer == texts.ADMIN_LAST, answer)

    if 'second@example.com' not in cfg.admins:
        cfg.set_admins(['admin@example.com'])

    answer = await core.handle_direct(user, 'join')
    check('core: join prompt', answer == texts.ASK_JOIN, answer)
    answer = await core.handle_direct(user, 'room@conf.example.com')
    check('core: join default nick', 'под ником bot' in answer, answer)
    check('core: room stored', storage.list_rooms() == [
        ('room@conf.example.com', 'bot')])
    answer = await core.handle_direct(user, 'join room@conf.example.com')
    check('core: already joined', answer == texts.ALREADY_JOINED %
          'room@conf.example.com', answer)
    answer = await core.handle_direct(user, 'leave')
    check('core: leave list', '1. room@conf.example.com' in answer, answer)
    answer = await core.handle_direct(user, '1')
    check('core: leave', answer == texts.LEFT % 'room@conf.example.com',
          answer)
    check('core: room removed', storage.list_rooms() == [])

    answer = await core.handle_direct(user, 'wiki')
    check('core: wiki current', answer == texts.WIKI_CURRENT % server.url,
          answer)
    answer = await core.handle_direct(user, '0')
    check('core: wiki cancel', answer == texts.WIKI_CANCELLED, answer)

    answer = await core.handle_direct(user, 'switch')
    answer = await core.handle_direct(user, 'Заметки 2')
    check('core: switch again', answer == texts.SWITCHED % 'Заметки 2',
          answer)
    answer = await core.handle_direct(user, '+ Погулять с собакой')
    check('core: add again', 'Добавлен пункт 1' in answer, answer)

    room = 'room@conf.example.com'
    answer = await core.handle_room(room, room + '/admin', 'switch MUC page')
    check('core: room switch', answer == texts.SWITCHED % 'MUC page', answer)
    check('core: room page scope',
          storage.get_page('room:%s' % room) == 'MUC page')
    check('core: summary room switch',
          server.state.summaries[-1][1]
          == 'mwnote: создана страница заметок (admin)',
          server.state.summaries[-1])
    answer = await core.handle_room(room, room + '/admin', '+ Заметка в MUC')
    check('core: room add', 'Добавлен пункт 1' in answer, answer)
    check('core: summary room add',
          server.state.summaries[-1][1]
          == 'mwnote: добавление заметки (admin)',
          server.state.summaries[-1])
    answer = await core.handle_room(room, room + '/admin', 'list')
    check('core: room list', '1. Заметка в MUC' in answer, answer)
    answer = await core.handle_room(room, room + '/admin', '- 1')
    check('core: room delete', answer == texts.NOTE_DELETED % (
        1, 'Заметка в MUC'), answer)
    check('core: summary room delete',
          server.state.summaries[-1][1]
          == 'mwnote: удаление заметки (admin)',
          server.state.summaries[-1])
    answer = await core.handle_room(room, room + '/alice', 'switch')
    check('core: room switch prompt', answer == texts.ASK_SWITCH, answer)
    answer = await core.handle_room(room, room + '/bob', 'list')
    check('core: other user list works',
          answer == texts.NOTE_LIST_EMPTY % 'MUC page', answer)
    answer = await core.handle_room(room, room + '/alice', 'MUC page 2')
    check('core: other user state preserved',
          answer == texts.SWITCHED % 'MUC page 2', answer)
    check('core: summary room actor',
          server.state.summaries[-1][1]
          == 'mwnote: создана страница заметок (alice)',
          server.state.summaries[-1])
    answer = await core.handle_room(room, room + '/admin', 'add')
    check('core: room admin command blocked', answer == texts.MUC_ONLY, answer)

    answer = await core.handle_direct(user, 'unknown')
    check('core: unknown command', answer == texts.UNKNOWN, answer)


async def test_bot_helpers(tmp, cfg, storage, server):
    async def join_room(room, nick):
        return True, nick

    async def leave_room(room):
        return True, None

    core = MwnoteCore(cfg, storage, 'bot', join_room=join_room,
                      leave_room=leave_room)
    bot = MwnoteBot(cfg, storage, core, 'bot')
    check('bot: addressed with colon',
          match_addressed('бот: list', 'бот') == 'list')
    check('bot: addressed with comma',
          match_addressed('бот, switch X', 'бот') == 'switch X')
    check('bot: not addressed', match_addressed('list', 'бот') is None)
    check('bot: another bot', match_addressed('other: list', 'бот') is None)

    role = {'role': 'participant', 'affiliation': 'none'}
    bot['xep_0045'].get_jid_property = (
        lambda room, nick, prop, pfrom=None: role.get(prop))
    check('bot: participant denied',
          not bot._allowed_in_room(JID('room@conf'), 'user'))
    role.update({'role': 'moderator'})
    check('bot: moderator allowed',
          bot._allowed_in_room(JID('room@conf'), 'user'))
    role.update({'role': 'participant', 'affiliation': 'admin'})
    check('bot: admin affiliation allowed',
          bot._allowed_in_room(JID('room@conf'), 'user'))

    chunks = split_chunks('x' * 7000, 3000)
    check('bot: chunking', len(chunks) >= 3 and all(
        len(chunk) <= 3000 for chunk in chunks), len(chunks))


async def main():
    tmp = tempfile.mkdtemp(prefix='mwnote-selftest-')
    server = FakeServer()
    try:
        config_path = os.path.join(tmp, 'mwnote.conf')
        with open(config_path, 'w', encoding='utf-8') as handle:
            handle.write(CONFIG_TEXT)
        cfg = Config(config_path)
        storage = Storage(cfg.db_path)
        await test_config_and_storage(tmp)
        cfg.set_admins(['admin@example.com'])
        await test_notes_and_mediawiki(tmp, server)
        await test_core_dialogs(tmp, cfg, storage, server)
        await test_bot_helpers(tmp, cfg, storage, server)
        storage.close()
    finally:
        server.close()
        shutil.rmtree(tmp, ignore_errors=True)

    if FAILED:
        print('\nFAILED: %d' % len(FAILED))
        for name in FAILED:
            print('  - %s' % name)
        return 1
    print('\nAll checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
