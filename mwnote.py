#!/usr/bin/env python3
"""mwnote — XMPP-бот для заметок на MediaWiki."""

import argparse
import asyncio
import logging
import signal
import sys

from slixmpp import JID

from bot import MwnoteBot
from config import Config, ConfigError, DEFAULT_CONFIG_FILE
from core import MwnoteCore
from storage import Storage

log = logging.getLogger('mwnote')

VERSION = '1.0.0'


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog='mwnote', description='XMPP-бот заметок MediaWiki')
    parser.add_argument('-c', '--config', dest='config_file', default=None,
                        help='путь к конфиг-файлу (по умолчанию mwnote.conf)')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='подробное логирование')
    parser.add_argument('--version', action='version',
                        version='mwnote %s' % VERSION)
    return parser.parse_args(argv)


def setup_logging(debug=False):
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format='%(asctime)s %(levelname)-8s %(name)s: %(message)s')
    if debug:
        for name in ('slixmpp', 'aiodns', 'dnspython'):
            logging.getLogger(name).setLevel(logging.WARNING)


async def run(config_file):
    cfg = Config(config_file)
    cfg.validate()
    storage = Storage(cfg.db_path)
    default_nick = cfg.muc_default_nick or JID(cfg.jabber_jid).user or 'mwnote'
    bot = MwnoteBot(cfg, storage, core=None, default_nick=default_nick)
    core = MwnoteCore(cfg, storage, default_nick,
                      join_room=bot._join_room, leave_room=bot._leave_room)
    bot.core = core

    loop = asyncio.get_running_loop()
    stopping = False

    def stop():
        nonlocal stopping
        if stopping:
            return
        stopping = True
        log.info('Получен сигнал завершения')
        asyncio.create_task(bot.disconnect())

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop)
        except NotImplementedError:
            pass

    host = cfg.jabber_host
    port = cfg.jabber_port
    try:
        if host and port:
            log.info('Подключение к %s:%s как %s', host, port, cfg.jabber_jid)
            bot.connect(host=host, port=port)
        else:
            log.info('Подключение как %s (SRV/DNS)', cfg.jabber_jid)
            bot.connect()
        await bot.disconnected
    finally:
        storage.close()
        log.info('mwnote остановлен')


def main(argv=None):
    args = parse_args(argv)
    setup_logging(args.debug)
    try:
        asyncio.run(run(args.config_file or DEFAULT_CONFIG_FILE))
    except ConfigError as exc:
        print('Ошибка конфигурации: %s' % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    except Exception:
        log.exception('Фатальная ошибка')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
