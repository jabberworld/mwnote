"""Диалоги и команды mwnote, не зависящие от XMPP."""

import asyncio
import time

from slixmpp import JID

import texts
from mediawiki import MediaWikiClient, MediaWikiError
from notes import NoteEmptyError, NoteIndexError, NoteService

STATE_TTL = 600
ROOM_COMMANDS = {'help', '?', 'switch', 'list', '+', '-'}
ROOM_STATES = {'switch_page', 'note_add', 'note_delete'}
CANCEL_WORDS = {'0', 'отмена', 'cancel', 'выход', 'exit', 'quit'}


class WikiNotConfigured(Exception):
    pass


class MwnoteCore:

    def __init__(self, cfg, storage, default_nick,
                 join_room=None, leave_room=None):
        self.cfg = cfg
        self.storage = storage
        self.default_nick = default_nick
        self.join_room = join_room
        self.leave_room = leave_room
        self.states = {}
        self._notes = None
        self._wiki_client = None
        self._wiki_key = None
        settings = storage.wiki_settings()
        if not settings['url'] and cfg.wiki_url:
            storage.seed_wiki(cfg.wiki_url, cfg.wiki_user, cfg.wiki_password)

    async def handle_direct(self, user, text):
        scope = 'user:%s' % user
        text = (text or '').strip()
        if not text:
            return texts.HELP_DIRECT
        state = self._state(scope, user)
        if state is not None:
            if (text.casefold() in CANCEL_WORDS
                    and state['cmd'] != 'wiki_url'):
                self.states.pop(scope, None)
                return texts.CANCELLED
            handler = getattr(self, '_state_' + state['cmd'], None)
            if handler is not None:
                return await handler(scope, user, state, text, room=False)
            self.states.pop(scope, None)
        return await self._dispatch(scope, user, text, room=False)

    async def handle_room(self, room, user, text):
        scope = 'room:%s' % room
        text = (text or '').strip()
        if not text:
            return None
        state = self._state(scope, user)
        if state is not None and state['cmd'] not in ROOM_STATES:
            self.states.pop(scope, None)
            state = None
        if state is not None:
            if (text.casefold() in CANCEL_WORDS
                    and state['cmd'] != 'wiki_url'):
                self.states.pop(scope, None)
                return texts.CANCELLED
            handler = getattr(self, '_state_' + state['cmd'], None)
            if handler is not None:
                return await handler(scope, user, state, text, room=True)
            self.states.pop(scope, None)
        command = text.split(None, 1)[0].lower()
        if command not in ROOM_COMMANDS:
            return texts.MUC_ONLY
        return await self._dispatch(scope, user, text, room=True)

    def _state(self, scope, user):
        state = self.states.get(scope)
        if state is None:
            return None
        if state.get('expires', 0) < time.time():
            self.states.pop(scope, None)
            return None
        if state.get('initiator') != user:
            return None
        return state

    def _set_state(self, scope, user, command, **data):
        state = {
            'cmd': command,
            'initiator': user,
            'expires': time.time() + STATE_TTL,
        }
        state.update(data)
        self.states[scope] = state
        return state

    async def _dispatch(self, scope, user, text, room):
        command, _, rest = text.partition(' ')
        command = command.lower()
        rest = rest.strip()
        if command in ('help', '?'):
            return texts.HELP_MUC if room else texts.HELP_DIRECT
        if command == 'switch':
            if not rest:
                self._set_state(scope, user, 'switch_page')
                return texts.ASK_SWITCH
            return await self._switch(scope, rest, user)
        if command == 'list':
            return await self._list_notes(scope, user)
        if command.startswith('+'):
            note = text[1:].strip()
            if not note:
                self._set_state(scope, user, 'note_add')
                return texts.ASK_NOTE_ADD
            return await self._add_note(scope, note, user)
        if command.startswith('-'):
            number = text[1:].strip()
            if number.isdigit():
                return await self._delete_note(scope, int(number), user)
            return await self._prompt_delete(scope, user)
        if room:
            return texts.MUC_ONLY
        if command in ('add', 'admin'):
            if rest:
                return self._add_admin(rest)
            self._set_state(scope, user, 'admin_add')
            return texts.ASK_ADMIN_ADD
        if command in ('del', 'delete', 'remove'):
            if rest:
                return self._delete_admin(rest, self.cfg.admins)
            admins = self.cfg.admins
            if not admins:
                return texts.ADMIN_LIST_EMPTY
            self._set_state(scope, user, 'admin_del', admins=admins)
            return self._admin_list(admins) + '\n' + texts.ASK_ADMIN_DEL
        if command == 'join':
            if not rest:
                self._set_state(scope, user, 'join')
                return texts.ASK_JOIN
            return await self._join(rest)
        if command == 'leave':
            if not rest:
                return await self._prompt_leave(scope, user)
            return await self._leave(rest)
        if command == 'wiki':
            current = self.storage.wiki_settings()['url']
            self._set_state(scope, user, 'wiki_url')
            if current:
                return texts.WIKI_CURRENT % current
            return texts.ASK_WIKI_URL
        if command == 'cancel':
            return texts.CANCELLED
        return texts.UNKNOWN

    async def _state_admin_add(self, scope, user, state, text, room):
        self.states.pop(scope, None)
        return self._add_admin(text)

    async def _state_admin_del(self, scope, user, state, text, room):
        self.states.pop(scope, None)
        return self._delete_admin(text, state.get('admins') or self.cfg.admins)

    async def _state_join(self, scope, user, state, text, room):
        self.states.pop(scope, None)
        return await self._join(text)

    async def _state_leave(self, scope, user, state, text, room):
        self.states.pop(scope, None)
        rooms = state.get('rooms') or []
        return await self._leave(text, rooms)

    async def _state_wiki_url(self, scope, user, state, text, room):
        if text.casefold() in CANCEL_WORDS:
            self.states.pop(scope, None)
            return texts.WIKI_CANCELLED
        if not text.strip():
            return texts.WIKI_EMPTY_URL
        try:
            MediaWikiClient(text.strip())
        except MediaWikiError as exc:
            return texts.WIKI_LOGIN_FAILED % exc
        state['url'] = text.strip()
        state['cmd'] = 'wiki_user'
        state['expires'] = time.time() + STATE_TTL
        return texts.ASK_WIKI_USER

    async def _state_wiki_user(self, scope, user, state, text, room):
        if not text.strip():
            return texts.WIKI_EMPTY_USER
        state['user'] = text.strip()
        state['cmd'] = 'wiki_password'
        state['expires'] = time.time() + STATE_TTL
        return texts.ASK_WIKI_PASSWORD

    async def _state_wiki_password(self, scope, user, state, text, room):
        password = text.strip('\r\n')
        if not password.strip():
            return texts.WIKI_EMPTY_PASSWORD
        url = state['url']
        wiki_user = state['user']
        self.states.pop(scope, None)
        client = MediaWikiClient(url)
        try:
            await asyncio.to_thread(client.login, wiki_user, password)
        except MediaWikiError as exc:
            return texts.WIKI_LOGIN_FAILED % exc
        self.storage.save_wiki(url, wiki_user, password)
        self._wiki_client = client
        self._wiki_key = (url, wiki_user, password)
        self._notes = NoteService(client)
        return texts.WIKI_SAVED % (url, wiki_user)

    async def _state_switch_page(self, scope, user, state, text, room):
        if not text.strip():
            return texts.PAGE_TITLE_EMPTY
        self.states.pop(scope, None)
        return await self._switch(scope, text.strip(), user)

    async def _state_note_add(self, scope, user, state, text, room):
        note = text.strip()
        if not note:
            return texts.NOTE_EMPTY
        self.states.pop(scope, None)
        return await self._add_note(scope, note, user)

    async def _state_note_delete(self, scope, user, state, text, room):
        value = text.strip()
        if not value.isdigit():
            return texts.ASK_DELETE_NOTE
        self.states.pop(scope, None)
        return await self._delete_note(scope, int(value), user)

    def _add_admin(self, raw):
        jid = self._valid_jid(raw)
        if jid is None:
            return texts.ADMIN_INVALID % raw
        admins = self.cfg.admins
        if any(item.casefold() == jid.casefold() for item in admins):
            return texts.ADMIN_ALREADY
        admins.append(jid)
        self.cfg.set_admins(admins)
        return texts.ADMIN_ADDED

    def _delete_admin(self, raw, admins):
        admins = list(admins or [])
        target = None
        value = raw.strip()
        if value.isdigit():
            index = int(value)
            if 1 <= index <= len(admins):
                target = admins[index - 1]
        else:
            jid = self._valid_jid(value)
            if jid is not None:
                for item in admins:
                    if item.casefold() == jid.casefold():
                        target = item
                        break
        if target is None:
            return texts.ADMIN_NOT_FOUND
        if len(admins) <= 1:
            return texts.ADMIN_LAST
        remaining = [item for item in admins if item != target]
        self.cfg.set_admins(remaining)
        return texts.ADMIN_DELETED % target

    @staticmethod
    def _admin_list(admins):
        lines = [texts.ADMIN_LIST_HEADER]
        for index, jid in enumerate(admins, 1):
            lines.append('%d. %s' % (index, jid))
        return '\n'.join(lines)

    @staticmethod
    def _valid_jid(raw):
        try:
            jid = JID((raw or '').strip())
        except Exception:
            return None
        if not jid.user or not jid.domain or jid.resource:
            return None
        return str(jid.bare)

    @staticmethod
    def _valid_room(raw):
        try:
            jid = JID((raw or '').strip())
        except Exception:
            return None
        if not jid.user or not jid.domain:
            return None
        return str(jid.bare)

    @staticmethod
    def _actor(user):
        try:
            jid = JID(str(user))
        except Exception:
            return str(user)
        return jid.resource or jid.user or str(user)

    async def _join(self, text):
        parts = text.split(None, 1)
        room = self._valid_room(parts[0])
        if room is None:
            return texts.ROOM_INVALID % parts[0]
        nick = parts[1].strip() if len(parts) > 1 else ''
        nick = nick or self.cfg.muc_default_nick or self.default_nick
        if self.storage.get_room(room):
            return texts.ALREADY_JOINED % room
        if self.join_room is None:
            self.storage.add_room(room, nick)
            return texts.JOINED % (room, nick)
        ok, value = await self.join_room(room, nick)
        if not ok:
            return texts.JOIN_ERROR % (room, value)
        self.storage.add_room(room, value)
        return texts.JOINED % (room, value)

    async def _prompt_leave(self, scope, user):
        rooms = [room for room, _ in self.storage.list_rooms()]
        if not rooms:
            return texts.LEAVE_NONE
        self._set_state(scope, user, 'leave', rooms=rooms)
        lines = [texts.LEAVE_LIST_HEADER]
        for index, room in enumerate(rooms, 1):
            lines.append('%d. %s' % (index, room))
        return '\n'.join(lines)

    async def _leave(self, text, rooms=None):
        rooms = list(rooms or [room for room, _ in self.storage.list_rooms()])
        room = None
        value = text.strip()
        if value.isdigit():
            index = int(value)
            if 1 <= index <= len(rooms):
                room = rooms[index - 1]
            else:
                return texts.LEAVE_BAD_NUMBER % index
        else:
            normalized = self._valid_room(value)
            if normalized is None:
                return texts.ROOM_INVALID % value
            if normalized in rooms:
                room = normalized
        if room is None:
            return texts.LEAVE_NOT_JOINED % value
        if not self.storage.get_room(room):
            return texts.LEAVE_NOT_JOINED % room
        if self.leave_room is not None:
            ok, error = await self.leave_room(room)
            if not ok:
                return texts.LEAVE_ERROR % (room, error)
        self.storage.remove_room(room)
        return texts.LEFT % room

    async def _switch(self, scope, title, user):
        title = title.strip()
        try:
            service = await self._wiki_service()
            page = await service.ensure_page(title, self._actor(user))
        except WikiNotConfigured:
            return texts.WIKI_NOT_CONFIGURED
        except MediaWikiError as exc:
            return texts.SWITCH_ERROR % (title, exc)
        self.storage.set_page(scope, page.title)
        return texts.SWITCHED % page.title

    async def _current_page(self, scope):
        page = self.storage.get_page(scope)
        if not page:
            return None
        return page

    async def _add_note(self, scope, note, user):
        page = await self._current_page(scope)
        if page is None:
            return texts.PAGE_NOT_SELECTED
        try:
            service = await self._wiki_service()
            page_title, number, value = await service.add_note(
                page, note, self._actor(user))
        except WikiNotConfigured:
            return texts.WIKI_NOT_CONFIGURED
        except NoteEmptyError:
            return texts.NOTE_EMPTY
        except MediaWikiError as exc:
            return texts.WIKI_ERROR % exc
        self.storage.set_page(scope, page_title)
        return texts.NOTE_ADDED % (number, value)

    async def _list_notes(self, scope, user):
        page = await self._current_page(scope)
        if page is None:
            return texts.PAGE_NOT_SELECTED
        try:
            service = await self._wiki_service()
            page_title, items = await service.list_notes(
                page, self._actor(user))
        except WikiNotConfigured:
            return texts.WIKI_NOT_CONFIGURED
        except MediaWikiError as exc:
            return texts.WIKI_ERROR % exc
        self.storage.set_page(scope, page_title)
        if not items:
            return texts.NOTE_LIST_EMPTY % page_title
        lines = [texts.NOTE_LIST_HEADER % page_title]
        for index, item in enumerate(items, 1):
            lines.append('%d. %s' % (index, item))
        return '\n'.join(lines)

    async def _prompt_delete(self, scope, user):
        page = await self._current_page(scope)
        if page is None:
            return texts.PAGE_NOT_SELECTED
        try:
            service = await self._wiki_service()
            page_title, items = await service.list_notes(
                page, self._actor(user))
        except WikiNotConfigured:
            return texts.WIKI_NOT_CONFIGURED
        except MediaWikiError as exc:
            return texts.WIKI_ERROR % exc
        self.storage.set_page(scope, page_title)
        if not items:
            return texts.NOTE_NONE_DELETE
        self._set_state(scope, user, 'note_delete')
        lines = [texts.NOTE_LIST_HEADER % page_title]
        for index, item in enumerate(items, 1):
            lines.append('%d. %s' % (index, item))
        lines.append(texts.ASK_DELETE_NOTE)
        return '\n'.join(lines)

    async def _delete_note(self, scope, number, user):
        page = await self._current_page(scope)
        if page is None:
            return texts.PAGE_NOT_SELECTED
        try:
            service = await self._wiki_service()
            page_title, number, value = await service.delete_note(
                page, number, self._actor(user))
        except WikiNotConfigured:
            return texts.WIKI_NOT_CONFIGURED
        except NoteIndexError as exc:
            return texts.NOTE_BAD_NUMBER % (exc.number, exc.count)
        except MediaWikiError as exc:
            return texts.WIKI_ERROR % exc
        self.storage.set_page(scope, page_title)
        return texts.NOTE_DELETED % (number, value)

    async def _wiki_service(self):
        settings = self.storage.wiki_settings()
        if not settings['url']:
            raise WikiNotConfigured()
        key = (settings['url'], settings['user'], settings['password'])
        if self._notes is not None and self._wiki_key == key:
            return self._notes
        client = MediaWikiClient(settings['url'])
        try:
            await asyncio.to_thread(
                client.login, settings['user'], settings['password'])
        except MediaWikiError:
            self._wiki_client = None
            self._wiki_key = None
            self._notes = None
            raise
        self._wiki_client = client
        self._wiki_key = key
        self._notes = NoteService(client)
        return self._notes
