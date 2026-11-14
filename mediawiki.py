"""Минимальный клиент MediaWiki API на стандартной библиотеке."""

import json
import logging
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import (
    HTTPCookieProcessor, Request, build_opener)

log = logging.getLogger('mwnote.mediawiki')

USER_AGENT = 'mwnote/1.0 (XMPP notes bot)'


class MediaWikiError(Exception):

    def __init__(self, code, info=''):
        self.code = code
        self.info = info
        super().__init__(('%s: %s' % (code, info)).strip(': '))


class Page:

    def __init__(self, title, exists, text='', timestamp=None):
        self.title = title
        self.exists = exists
        self.text = text
        self.timestamp = timestamp

    def __repr__(self):
        return 'Page(%r, exists=%r)' % (self.title, self.exists)


def _candidate_api_urls(raw):
    raw = (raw or '').strip()
    if not raw:
        raise MediaWikiError('badurl', 'пустой URL')
    if '://' not in raw:
        raw = 'https://' + raw
    parsed = urlsplit(raw)
    if not parsed.netloc:
        raise MediaWikiError('badurl', 'не удалось разобрать URL')
    path = parsed.path or '/'
    if path.endswith('index.php'):
        path = path[:-len('index.php')] + 'api.php'
    if path.endswith('api.php'):
        return [urlunsplit((parsed.scheme, parsed.netloc, path,
                            parsed.query, ''))]
    base = path.rstrip('/')
    candidates = []
    if not base:
        candidates.append('/api.php')
    else:
        candidates.append(base + '/api.php')
    if not base.lower().endswith('/w'):
        candidates.append('/w/api.php')
    candidates.append('/api.php')
    result = []
    for candidate in candidates:
        full = urlunsplit((parsed.scheme, parsed.netloc, candidate, '', ''))
        if full not in result:
            result.append(full)
    return result


class MediaWikiClient:

    def __init__(self, url, timeout=20):
        self.timeout = timeout
        self.raw_url = url
        self.api_candidates = _candidate_api_urls(url)
        self.api_url = None
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))
        self.user = None
        self.logged_in = False
        self._csrf_token = None

    def _http(self, url, params=None, data=None):
        if params:
            separator = '&' if '?' in url else '?'
            url += separator + urlencode(params)
        body = urlencode(data).encode('utf-8') if data is not None else None
        request = Request(url, data=body, headers={
            'User-Agent': USER_AGENT,
            'Accept': 'application/json',
        })
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            raw = exc.read()
            parsed = self._parse(raw)
            if parsed and parsed.get('error'):
                error = parsed['error']
                raise MediaWikiError(error.get('code', 'http'),
                                     error.get('info', ''))
            raise MediaWikiError('http%d' % exc.code, str(exc.reason))
        except (URLError, OSError) as exc:
            reason = getattr(exc, 'reason', exc)
            raise MediaWikiError('network', str(reason))
        parsed = self._parse(raw)
        if parsed is None:
            raise MediaWikiError('badresponse', 'ответ не является JSON')
        if parsed.get('error'):
            error = parsed['error']
            raise MediaWikiError(error.get('code', 'api'),
                                 error.get('info', ''))
        return parsed

    @staticmethod
    def _parse(raw):
        try:
            return json.loads(raw.decode('utf-8', 'replace'))
        except (ValueError, AttributeError):
            return None

    def _discover_api(self):
        for candidate in self.api_candidates:
            try:
                parsed = self._http(candidate, {
                    'action': 'query', 'meta': 'siteinfo', 'format': 'json',
                })
            except MediaWikiError as exc:
                log.debug('MediaWiki API candidate %s failed: %s',
                          candidate, exc)
                continue
            if parsed.get('query'):
                self.api_url = candidate
                return
        raise MediaWikiError(
            'noapi', 'не удалось найти api.php по адресу %s' % self.raw_url)

    def _api(self, params, post=False):
        if self.api_url is None:
            self._discover_api()
        params = dict(params)
        params.setdefault('format', 'json')
        if post:
            return self._http(self.api_url, data=params)
        return self._http(self.api_url, params=params)

    def login(self, user, password):
        self.user = user
        self.logged_in = False
        self._csrf_token = None
        token_data = self._api({
            'action': 'query', 'meta': 'tokens', 'type': 'login',
        })
        token = ((token_data.get('query') or {}).get('tokens') or {}).get(
            'logintoken')
        if not token:
            raise MediaWikiError('notoken', 'сервер не выдал login token')
        data = {
            'action': 'login',
            'lgname': user,
            'lgpassword': password,
            'lgtoken': token,
        }
        result = self._api(data, post=True)
        login = result.get('login') or {}
        state = login.get('result')
        if state == 'NeedToken':
            data['lgtoken'] = login.get('token') or token
            result = self._api(data, post=True)
            login = result.get('login') or {}
            state = login.get('result')
        if state != 'Success':
            reason = login.get('reason') or state or 'неизвестная ошибка'
            raise MediaWikiError(
                'login', '%s (проверьте логин/пароль; для 2FA используйте '
                'bot-password)' % reason)
        self.logged_in = True
        return True

    def _csrf(self):
        if self._csrf_token:
            return self._csrf_token
        data = self._api({'action': 'query', 'meta': 'tokens'})
        token = ((data.get('query') or {}).get('tokens') or {}).get(
            'csrftoken')
        if not token:
            raise MediaWikiError('notoken', 'сервер не выдал CSRF token')
        self._csrf_token = token
        return token

    @staticmethod
    def _pages(response):
        pages = ((response.get('query') or {}).get('pages') or {})
        if isinstance(pages, list):
            return pages
        return list(pages.values())

    def get_page(self, title):
        data = self._api({
            'action': 'query',
            'prop': 'revisions',
            'rvprop': 'content|timestamp',
            'rvslots': 'main',
            'titles': title,
            'redirects': '1',
        })
        pages = self._pages(data)
        if not pages:
            return Page(title, False)
        page = pages[0]
        page_title = page.get('title') or title
        if ('missing' in page or 'invalid' in page
                or page.get('pageid') == -1):
            return Page(page_title, False)
        revisions = page.get('revisions') or []
        if not revisions:
            return Page(page_title, True, '')
        revision = revisions[0]
        slots = revision.get('slots') or {}
        if slots:
            main = slots.get('main') or {}
            text = main.get('content') or main.get('*') or ''
        else:
            text = revision.get('content') or revision.get('*') or ''
        return Page(page_title, True, text,
                    revision.get('timestamp'))

    def edit_page(self, title, text, summary, create=False,
                  basetimestamp=None):
        for attempt in (0, 1):
            token = self._csrf()
            data = {
                'action': 'edit',
                'title': title,
                'text': text,
                'summary': summary,
                'token': token,
                'bot': '1',
                'watchlist': 'nochange',
                'assert': 'user',
            }
            if create:
                data['createonly'] = '1'
            if basetimestamp:
                data['basetimestamp'] = basetimestamp
            try:
                result = self._api(data, post=True)
            except MediaWikiError as exc:
                if attempt == 0 and exc.code in (
                        'badtoken', 'notoken', 'mustpostparams'):
                    self._csrf_token = None
                    continue
                raise
            edit = result.get('edit') or {}
            if edit.get('result') == 'Success':
                return edit
            raise MediaWikiError('edit', str(edit))
        raise MediaWikiError('edit', 'не удалось выполнить правку')
