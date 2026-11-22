# mwnote — правила проекта

## Назначение

`mwnote` — XMPP-бот на Python 3 + slixmpp 1.10, который служит интерфейсом
редактирования страниц-заметок MediaWiki. Бот работает в личных сообщениях
(только администраторы из конфига) и в многопользовательских конференциях
(только модераторы и выше, только команды заметок и `switch`).

Полная спецификация — в [SPEC.md](SPEC.md), журнал работы — в [NOTES.md](NOTES.md).

## Обязательные правила

1. **Коммит после изменений кода.** После каждого завершённого блока изменений
   в build-сессии делать коммит в локальный git.
2. **Автор коммита** — `opencode` с указанием реально используемой в текущей
   сессии модели: `opencode (deepseek-v4.1-flash) <opencode@localhost>`.
   Не переносить имя модели из старых сессий. Настраивать через локальный
   `git config` и/или `git commit --author`.
3. **Пояснения для пользователя — на русском языке.** Код, команды, имена
   переменных и идентификаторы не переводить.
4. **Сохранять промежуточные результаты.** Вести `NOTES.md`: рассуждения,
   принятые решения, вопросы и ответы пользователя, прогресс, результаты
   тестов, следующий шаг. Это позволяет продолжить работу после сжатия
   сессии или перезапуска. Секреты и пароли в `NOTES.md` не записывать.
5. **Тестовые зависимости** можно устанавливать в скрытый каталог проекта
   `.testlibs/` (или `.venv/`); он исключён из git.
6. **Не коммитить секреты и рабочие данные:** `mwnote.conf`, `*.sqlite3`,
   `*.key`, `.testlibs/`, `.venv*/`, `__pycache__/`, логи.
7. **Code Brain MCP** (из корневого `AGENTS.md`): в начале существенной работы
   использовать `start_task(runIntake=true)` или `neural_sync`, в конце —
   `memory_store`; при сбоях MCP продолжать работу и фиксировать это в
   `NOTES.md`.

## Конвенции кода

- Python 3.11+; код должен оставаться совместимым с Python 3.13.
- Стиль соседних проектов: `%`-форматирование в пользовательских текстах,
  `logging`, sqlite3 из stdlib, без лишних зависимостей.
- Внешняя зависимость только `slixmpp==1.10.0`; HTTP к MediaWiki — через
  `urllib` из стандартной библиотеки.
- Пользовательские ответы — на русском, в `texts.py`.
- Сетевые вызовы MediaWiki выполнять через `asyncio.to_thread`, чтобы не
  блокировать XMPP-event-loop.
- SQLite-файл создавать с правами `0600`.

## Проверка

```bash
python3 -m compileall .
python3 selftest.py
```

`selftest.py` работает без XMPP-сервера и использует фейковый MediaWiki
HTTP-сервер. При наличии реальных доступов допускается отдельный smoke-тест.

<!-- CODE_BRAIN_MANDATORY -->
## Code Brain MCP - Mandatory when loaded

Use Code Brain MCP first for substantive tasks in this project.

- Start with `start_task(runIntake=true)` or `neural_sync`.
- Use `agent_plan` before `agent_code` for chunk and deep work.
- Use `memory_retrieve` at intake and `memory_store` at task end.
- Use `uncertainty_guard` before storing conclusions.
- Disable duplicate MCPs with `get_superseded_mcps`.
<!-- CODE_BRAIN_MANDATORY -->
