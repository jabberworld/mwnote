"""Тексты ответов mwnote."""

UNAUTHORIZED = 'Не авторизован'

HELP_DIRECT = (
    'mwnote — заметки на MediaWiki.\n'
    'Команды:\n'
    '  switch <страница>  выбрать или создать страницу\n'
    '  + <текст>          добавить пункт\n'
    '  list               показать пункты\n'
    '  - <номер>          удалить пункт\n'
    '  wiki               настроить MediaWiki\n'
    '  add [JID]          добавить администратора\n'
    '  del [JID]          удалить администратора\n'
    '  join <комната> [ник]  войти в конференцию\n'
    '  leave [комната]    выйти из конференции\n'
    '  help               эта справка\n'
    'В конференции доступны только switch, +, list и -.'
)

HELP_MUC = (
    'В конференции доступны команды:\n'
    '  switch <страница>\n'
    '  + <текст>\n'
    '  list\n'
    '  - <номер>'
)

ASK_ADMIN_ADD = 'Кого добавляем?'
ASK_ADMIN_DEL = 'Кого удаляем? Отправьте номер или JID.'
ADMIN_ADDED = 'Адрес добавлен'
ADMIN_DELETED = 'Адрес удалён: %s'
ADMIN_ALREADY = 'Этот адрес уже в списке администраторов.'
ADMIN_NOT_FOUND = 'Адрес не найден в списке администраторов.'
ADMIN_LAST = 'Нельзя удалить последнего администратора.'
ADMIN_INVALID = 'Некорректный JID: %s'
ADMIN_LIST_EMPTY = 'Список администраторов пуст.'
ADMIN_LIST_HEADER = 'Администраторы:'

ASK_JOIN = 'Укажите конференцию: join адрес@конференции [ник]'
JOINED = 'Вошёл в конференцию %s под ником %s.'
JOIN_ERROR = 'Не удалось войти в %s: %s'
ALREADY_JOINED = 'Уже нахожусь в %s.'
LEAVE_LIST_HEADER = 'Нахожусь в следующих конференциях, выберите вариант:'
LEAVE_NONE = 'Нет активных конференций.'
LEFT = 'Вышел из %s.'
LEAVE_NOT_JOINED = 'Не нахожусь в %s.'
LEAVE_ERROR = 'Не удалось выйти из %s: %s'
ROOM_INVALID = 'Некорректный адрес конференции: %s'

ASK_WIKI_URL = 'Введите URL MediaWiki (например, https://wiki.example.com):'
ASK_WIKI_USER = 'Введите имя пользователя MediaWiki:'
ASK_WIKI_PASSWORD = 'Введите пароль MediaWiki:'
WIKI_LOGIN_FAILED = 'Не удалось подключиться к MediaWiki: %s'
WIKI_SAVED = 'MediaWiki настроена: %s (пользователь %s).'
WIKI_CURRENT = ('Текущая MediaWiki: %s. Введите новый URL '
                'или 0 для отмены.')
WIKI_CANCELLED = 'Настройка MediaWiki отменена.'
WIKI_NOT_CONFIGURED = ('MediaWiki ещё не настроена. '
                       'Выполните команду wiki.')
WIKI_EMPTY_URL = 'URL не может быть пустым. Введите URL или 0 для отмены.'
WIKI_EMPTY_USER = 'Имя пользователя не может быть пустым. Введите имя:'
WIKI_EMPTY_PASSWORD = 'Пароль не может быть пустым. Введите пароль:'

ASK_SWITCH = 'Введите адрес страницы:'
SWITCHED = 'Переключился на страницу "%s"'
SWITCH_ERROR = 'Не удалось переключиться на страницу "%s": %s'
PAGE_TITLE_EMPTY = 'Адрес страницы не может быть пустым. Введите адрес:'
PAGE_NOT_SELECTED = 'Сначала выберите страницу: switch <название>.'

ASK_DELETE_NOTE = 'Какой пункт удалить? Отправьте номер.'
NOTE_ADDED = 'Добавлен пункт %d: "%s"'
NOTE_LIST_HEADER = 'На странице "%s" следующие заметки:'
NOTE_LIST_EMPTY = 'На странице "%s" пока нет заметок.'
NOTE_DELETED = 'Удален пункт %d "%s"'
NOTE_BAD_NUMBER = 'Нет пункта с номером %d (доступно 1-%d).'
NOTE_NONE_DELETE = 'На странице нет заметок для удаления.'
NOTE_EMPTY = 'Текст заметки не может быть пустым.'

UNKNOWN = 'Не понял команду. Отправьте help для справки.'
MUC_ONLY = 'В конференции доступны только команды switch, +, list, - и help.'
WIKI_ERROR = 'Ошибка MediaWiki: %s'
INTERNAL_ERROR = 'Внутренняя ошибка. Подробности в логе.'
CANCELLED = 'Отменено.'
INVALID_JID = 'Некорректный JID: %s'

ASK_NOTE_ADD = 'Введите текст заметки:'
LEAVE_BAD_NUMBER = 'Нет конференции с номером %d.'
