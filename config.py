"""INI-конфигурация mwnote."""

import os
import re
import tempfile
from configparser import ConfigParser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_FILE = os.path.join(BASE_DIR, 'mwnote.conf')

MUC_ROLES = ('visitor', 'participant', 'moderator')


class ConfigError(Exception):
    pass


class Config:

    def __init__(self, config_file=None):
        self.config_file = os.path.abspath(config_file or DEFAULT_CONFIG_FILE)
        self.parser = ConfigParser(interpolation=None)
        if not os.path.isfile(self.config_file):
            raise ConfigError('Не найден конфиг-файл: %s' % self.config_file)
        try:
            self.parser.read(self.config_file, encoding='utf-8')
        except Exception as exc:
            raise ConfigError('Не удалось прочитать конфиг %s: %s'
                              % (self.config_file, exc))
        self._set_defaults()

    def _set_defaults(self):
        sections = {
            'jabber': {
                'jid': '', 'password': '', 'resource': 'mwnote',
                'host': '', 'port': '',
            },
            'admins': {'list': ''},
            'muc': {
                'min_role': 'moderator', 'default_nick': '',
                'autojoin': 'true', 'editor_hat_title': '',
            },
            'wiki': {'url': '', 'user': '', 'password': ''},
            'storage': {'db_path': 'mwnote.sqlite3'},
            'interface': {'language': 'ru', 'chat_markers': 'true'},
        }
        for section, options in sections.items():
            if not self.parser.has_section(section):
                self.parser.add_section(section)
            for option, value in options.items():
                if not self.parser.has_option(section, option):
                    self.parser.set(section, option, value)

    def get(self, section, option, fallback=''):
        return self.parser.get(section, option, fallback=fallback)

    def get_boolean(self, section, option, fallback=False):
        try:
            return self.parser.getboolean(section, option, fallback=fallback)
        except ValueError:
            return fallback

    def get_int(self, section, option, fallback=0):
        try:
            return self.parser.getint(section, option, fallback=fallback)
        except ValueError:
            return fallback

    @property
    def jabber_jid(self):
        return self.get('jabber', 'jid').strip()

    @property
    def jabber_password(self):
        return self.get('jabber', 'password')

    @property
    def jabber_resource(self):
        return self.get('jabber', 'resource').strip() or 'mwnote'

    @property
    def jabber_host(self):
        value = self.get('jabber', 'host').strip()
        return value or None

    @property
    def jabber_port(self):
        value = self.get('jabber', 'port').strip()
        if not value:
            return None
        try:
            port = int(value)
        except ValueError:
            raise ConfigError('Некорректный порт в [jabber]: %s' % value)
        if not 1 <= port <= 65535:
            raise ConfigError('Порт вне диапазона: %s' % value)
        return port

    @property
    def admins(self):
        raw = self.get('admins', 'list')
        return [item.strip() for item in re.split(r'[,\n]+', raw)
                if item.strip()]

    @property
    def muc_min_role(self):
        value = self.get('muc', 'min_role').strip().lower()
        return value if value in MUC_ROLES else 'moderator'

    @property
    def muc_default_nick(self):
        return self.get('muc', 'default_nick').strip()

    @property
    def muc_editor_hat_title(self):
        return self.get('muc', 'editor_hat_title').strip()

    @property
    def muc_autojoin(self):
        return self.get_boolean('muc', 'autojoin', fallback=True)

    @property
    def wiki_url(self):
        return self.get('wiki', 'url').strip()

    @property
    def wiki_user(self):
        return self.get('wiki', 'user').strip()

    @property
    def wiki_password(self):
        return self.get('wiki', 'password')

    @property
    def db_path(self):
        raw = self.get('storage', 'db_path').strip() or 'mwnote.sqlite3'
        if os.path.isabs(raw):
            return raw
        return os.path.join(os.path.dirname(self.config_file), raw)

    @property
    def language(self):
        return self.get('interface', 'language').strip().lower() or 'ru'

    @property
    def chat_markers(self):
        return self.get_boolean('interface', 'chat_markers', fallback=True)

    def validate(self):
        if not self.jabber_jid:
            raise ConfigError('В [jabber] не задан jid')
        if not self.jabber_password:
            raise ConfigError('В [jabber] не задан password')
        self.jabber_port

    def set_admins(self, admins):
        values = []
        seen = set()
        for jid in admins:
            jid = jid.strip()
            key = jid.casefold()
            if not jid or key in seen:
                continue
            seen.add(key)
            values.append(jid)
        line = 'list = %s' % ', '.join(values)
        self._rewrite_admins(line)
        if not self.parser.has_section('admins'):
            self.parser.add_section('admins')
        self.parser.set('admins', 'list', ', '.join(values))

    def _read_lines(self):
        with open(self.config_file, 'r', encoding='utf-8') as handle:
            return handle.readlines()

    def _rewrite_admins(self, new_line):
        lines = self._read_lines()
        section_re = re.compile(r'^\s*\[([^\]]+)\]\s*$')
        in_admins = False
        section_found = False
        option_found = False
        insert_at = None
        for index, raw in enumerate(lines):
            match = section_re.match(raw)
            if match:
                if in_admins and insert_at is None:
                    insert_at = index
                in_admins = match.group(1).strip().lower() == 'admins'
                if in_admins:
                    section_found = True
                    insert_at = index + 1
                continue
            if in_admins and re.match(r'^\s*list\s*[:=]', raw, re.IGNORECASE):
                newline = '\r\n' if raw.endswith('\r\n') else '\n'
                lines[index] = new_line + newline
                option_found = True
                break
        if not section_found:
            if lines and not lines[-1].endswith('\n'):
                lines[-1] += '\n'
            lines.extend(['\n', '[admins]\n', new_line + '\n'])
        elif not option_found:
            newline = '\r\n' if any(
                line.endswith('\r\n') for line in lines) else '\n'
            if insert_at is None:
                insert_at = len(lines)
            lines.insert(insert_at, new_line + newline)
        self._atomic_write(lines)

    def _atomic_write(self, lines):
        directory = os.path.dirname(self.config_file) or '.'
        fd, tmp = tempfile.mkstemp(prefix='.mwnote-conf-', dir=directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                handle.writelines(lines)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.config_file)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
