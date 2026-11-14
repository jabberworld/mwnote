"""SQLite-хранилище рабочих данных mwnote."""

import os
import sqlite3
import time

SCHEMA = (
    'CREATE TABLE IF NOT EXISTS settings ('
    ' key TEXT PRIMARY KEY,'
    ' value TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS pages ('
    ' scope TEXT PRIMARY KEY,'
    ' title TEXT NOT NULL,'
    ' updated_at INTEGER NOT NULL)',
    'CREATE TABLE IF NOT EXISTS rooms ('
    ' room TEXT PRIMARY KEY,'
    ' nick TEXT NOT NULL,'
    ' joined_at INTEGER NOT NULL)',
)


class Storage:

    def __init__(self, path):
        self.path = os.path.abspath(path)
        directory = os.path.dirname(self.path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=15)
        self.conn.row_factory = sqlite3.Row
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        for statement in SCHEMA:
            self.conn.execute(statement)
        self.conn.execute('PRAGMA user_version = 1')
        self.conn.commit()

    def close(self):
        self.conn.close()

    def get_setting(self, key, default=None):
        row = self.conn.execute(
            'SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row['value'] if row is not None else default

    def set_setting(self, key, value):
        self.conn.execute(
            'INSERT INTO settings (key, value) VALUES (?, ?) '
            'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            (key, '' if value is None else str(value)))
        self.conn.commit()

    def set_settings(self, values):
        for key, value in values.items():
            self.conn.execute(
                'INSERT INTO settings (key, value) VALUES (?, ?) '
                'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                (key, '' if value is None else str(value)))
        self.conn.commit()

    def wiki_settings(self):
        return {
            'url': self.get_setting('wiki_url', '') or '',
            'user': self.get_setting('wiki_user', '') or '',
            'password': self.get_setting('wiki_password', '') or '',
        }

    def save_wiki(self, url, user, password):
        self.set_settings({
            'wiki_url': url,
            'wiki_user': user,
            'wiki_password': password,
        })

    def seed_wiki(self, url, user, password):
        if self.get_setting('wiki_url'):
            return
        if not url:
            return
        self.save_wiki(url, user, password)

    def get_page(self, scope):
        row = self.conn.execute(
            'SELECT title FROM pages WHERE scope=?', (scope,)).fetchone()
        return row['title'] if row is not None else None

    def set_page(self, scope, title):
        self.conn.execute(
            'INSERT INTO pages (scope, title, updated_at) VALUES (?, ?, ?) '
            'ON CONFLICT(scope) DO UPDATE SET '
            'title=excluded.title, updated_at=excluded.updated_at',
            (scope, title, int(time.time())))
        self.conn.commit()

    def list_rooms(self):
        rows = self.conn.execute(
            'SELECT room, nick FROM rooms ORDER BY joined_at, room').fetchall()
        return [(row['room'], row['nick']) for row in rows]

    def get_room(self, room):
        row = self.conn.execute(
            'SELECT nick FROM rooms WHERE room=?', (room,)).fetchone()
        return row['nick'] if row is not None else None

    def add_room(self, room, nick):
        self.conn.execute(
            'INSERT INTO rooms (room, nick, joined_at) VALUES (?, ?, ?) '
            'ON CONFLICT(room) DO UPDATE SET '
            'nick=excluded.nick, joined_at=excluded.joined_at',
            (room, nick, int(time.time())))
        self.conn.commit()

    def remove_room(self, room):
        self.conn.execute('DELETE FROM rooms WHERE room=?', (room,))
        self.conn.commit()
