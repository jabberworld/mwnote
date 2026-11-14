"""XMPP-слой mwnote: маршрутизация, права, конференции."""

import asyncio
import logging
import re

from slixmpp import JID, ClientXMPP

import texts

log = logging.getLogger('mwnote.bot')

ROLE_RANK = {'none': 0, 'visitor': 1, 'participant': 2, 'moderator': 3}
AFFILIATION_MODERATORS = {'owner', 'admin'}
CHUNK_LIMIT = 3000


class MwnoteBot(ClientXMPP):

    def __init__(self, cfg, storage, core, default_nick):
        jid = cfg.jabber_jid
        if '/' not in jid:
            jid = '%s/%s' % (jid, cfg.jabber_resource)
        super().__init__(jid, cfg.jabber_password)
        self.cfg = cfg
        self.storage = storage
        self.core = core
        self.default_nick = default_nick
        self.register_plugin('xep_0030')
        self.register_plugin('xep_0045')
        self.register_plugin('xep_0085')
        self.register_plugin('xep_0184')
        self.register_plugin('xep_0199')
        self['xep_0184'].auto_ack = False
        self.add_event_handler('session_start', self._on_session_start)
        self.add_event_handler('message', self._on_message)
        self.add_event_handler('groupchat_message', self._on_groupchat)
        self.add_event_handler('presence_subscribe', self._on_subscribe)

    async def _on_session_start(self, event):
        log.info('Подключился как %s', self.boundjid)
        self.send_presence(pstatus='mwnote: заметки MediaWiki. help — справка')
        if self.cfg.muc_autojoin:
            for room, nick in self.storage.list_rooms():
                asyncio.create_task(self._autojoin(room, nick))

    async def _autojoin(self, room, nick):
        try:
            ok, value = await self._join_room(room, nick)
            if ok:
                self.storage.add_room(room, value)
                log.info('Автовход в конференцию %s выполнен', room)
            else:
                log.warning('Не удалось автоматически войти в %s: %s',
                            room, value)
        except Exception:
            log.exception('Не удалось автоматически войти в %s', room)

    async def _on_subscribe(self, pres):
        try:
            self.send_presence(ptype='subscribed', pto=pres['from'].bare)
        except Exception:
            log.exception('Не удалось подтвердить подписку %s', pres['from'])

    def _is_admin(self, jid):
        value = str(jid).casefold()
        return any(item.casefold() == value for item in self.cfg.admins)

    async def _on_message(self, msg):
        if msg['type'] not in ('chat', 'normal'):
            return
        sender = msg['from']
        if sender is None or sender.bare == self.boundjid.bare:
            return
        if msg['receipt']:
            return
        body = (msg['body'] or '').strip()
        if not body:
            return
        user = str(sender.bare)
        if not self._is_admin(user):
            self._direct_reply(msg, texts.UNAUTHORIZED)
            return
        if self.cfg.chat_markers:
            self.send_message(mto=msg['from'], mbody=None, mtype='chat',
                              mchat_state='composing')
        try:
            answer = await self.core.handle_direct(user, body)
        except Exception:
            log.exception('Ошибка обработки сообщения от %s', user)
            answer = texts.INTERNAL_ERROR
        if answer:
            self._direct_reply(msg, answer)

    async def _on_groupchat(self, msg):
        if msg['type'] != 'groupchat':
            return
        try:
            if msg.get_plugin('delay', check=True) is not None:
                return
        except Exception:
            pass
        room = msg['from'].bare
        nick = msg['from'].resource
        if not room or not nick:
            return
        room_jid = JID(room)
        our_nick = self['xep_0045'].our_nicks.get(None, {}).get(room_jid)
        if not our_nick or nick == our_nick:
            return
        body = (msg['body'] or '').strip()
        if not body:
            return
        command = match_addressed(body, our_nick)
        if not command:
            return
        if not self._allowed_in_room(room_jid, nick):
            return
        try:
            answer = await self.core.handle_room(
                str(room), str(msg['from']), command)
        except Exception:
            log.exception('Ошибка обработки команды в %s от %s', room, nick)
            answer = texts.INTERNAL_ERROR
        if answer:
            self._send_groupchat(room, answer)

    def _allowed_in_room(self, room_jid, nick):
        xep = self['xep_0045']
        affiliation = xep.get_jid_property(room_jid, nick, 'affiliation')
        if affiliation in AFFILIATION_MODERATORS:
            return True
        role = xep.get_jid_property(room_jid, nick, 'role')
        need = ROLE_RANK.get(self.cfg.muc_min_role, 3)
        return ROLE_RANK.get(role, 0) >= need

    async def _join_room(self, room, nick):
        room_jid = JID(room)
        try:
            await self['xep_0045'].join_muc_wait(
                room_jid, nick, maxchars=0, timeout=30)
        except Exception as exc:
            log.warning('Не удалось войти в %s как %s: %s', room, nick, exc)
            return False, str(exc) or type(exc).__name__
        actual = self['xep_0045'].our_nicks.get(None, {}).get(room_jid) or nick
        return True, actual

    async def _leave_room(self, room):
        room_jid = JID(room)
        nick = self.storage.get_room(room)
        if not nick:
            nick = self['xep_0045'].our_nicks.get(None, {}).get(room_jid)
        if not nick:
            return False, 'ник неизвестен'
        try:
            self['xep_0045'].leave_muc(room_jid, nick)
        except Exception as exc:
            log.warning('Не удалось выйти из %s: %s', room, exc)
            return False, str(exc) or type(exc).__name__
        return True, None

    def _direct_reply(self, msg, text):
        chunks = split_chunks(text)
        for index, chunk in enumerate(chunks):
            if index == 0:
                reply = msg.reply()
            else:
                reply = self.make_message(mto=msg['from'], mtype='chat')
            reply['body'] = chunk
            if self.cfg.chat_markers:
                reply['chat_state'] = 'active'
                if index == 0:
                    reply['request_receipt'] = True
            reply.send()

    def _send_groupchat(self, room, text):
        for chunk in split_chunks(text):
            self.send_message(mto=room, mbody=chunk, mtype='groupchat')


def match_addressed(text, nick):
    pattern = r'^\s*%s\s*[:,]\s*(.*)$' % re.escape(nick)
    match = re.match(pattern, text or '', re.IGNORECASE | re.DOTALL)
    if match is None:
        return None
    return match.group(1).strip()


def split_chunks(text, limit=CHUNK_LIMIT):
    text = text or ''
    if len(text) <= limit:
        return [text]
    chunks = []
    current = []
    size = 0
    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            if current:
                chunks.append(''.join(current).rstrip('\n'))
                current = []
                size = 0
            for start in range(0, len(line), limit):
                chunks.append(line[start:start + limit].rstrip('\n'))
            continue
        if size + len(line) > limit and current:
            chunks.append(''.join(current).rstrip('\n'))
            current = []
            size = 0
        current.append(line)
        size += len(line)
    if current:
        chunks.append(''.join(current).rstrip('\n'))
    return [chunk for chunk in chunks if chunk] or ['']
