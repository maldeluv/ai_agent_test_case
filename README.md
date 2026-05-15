# browser_ai_agent

CLI-прототип автономного браузерного AI-агента. Агент запускает видимый Chromium через Playwright, принимает задачу на естественном языке, вызывает браузерные tools через LLM tool-use loop, ищет элементы через компактный DOM-анализ и останавливается перед рискованными действиями.

## Стек

- Python 3.12+
- Playwright async API
- OpenAI Responses API по умолчанию
- Anthropic Claude как переключаемый provider
- Typer CLI
- Rich terminal output
- Pydantic v2 / pydantic-settings
- pytest / pytest-asyncio

## Архитектура

```text
CLI / Typer + Rich
  -> MainAgentLoop
     -> LLM provider client: OpenAI or Anthropic
     -> ToolRegistry
        -> SafetyGuard
        -> Browser tools
        -> DOM query tool
           -> DOMExtractor
           -> DOMSubAgent
        -> Content observation tool
           -> ContentExtractor
           -> ContentSubAgent
  -> BrowserSession
     -> Playwright persistent Chromium context
```

Основной принцип: агент не знает DOM сайта заранее и не использует site-specific сценарии. Он получает компактные наблюдения, выбирает tool, исполняет действие, получает структурированный результат и продолжает цикл до `finish_task`, лимита шагов, пользовательского подтверждения или ошибки.

## Запуск

```powershell
cd C:\Users\mvideo\Desktop\ai_agent_test_case\browser_ai_agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m playwright install chromium
Copy-Item .env.example .env
notepad .env
```

В `.env` для OpenAI:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.4-mini
```

Запуск агента:

```powershell
browser-ai-agent "Открой https://example.com и кратко опиши страницу"
```

Быстрый запуск без ожидания Enter перед закрытием браузера:

```powershell
browser-ai-agent "Открой https://example.com и заверши задачу" --no-wait
```

Запуск модулем:

```powershell
python -m app.main "Открой https://example.com и заверши задачу"
```

## Persistent Session

Браузер запускается в headful mode через `launch_persistent_context`. Профиль хранится в локальной папке:

```text
browser_profile/
```

Эта папка игнорируется git. Cookies и логины сохраняются между запусками. Для ручного входа в аккаунт запусти агента, войди в открытом Chromium вручную, затем закрой CLI через Enter. Следующие запуски будут использовать тот же профиль.

## Tools

Зарегистрированные tools:

- `navigate_to_url` - переход на `http(s)` URL.
- `go_back` - возврат на предыдущую страницу по browser history.
- `get_current_page_info` - URL, title и короткий видимый текст страницы.
- `query_dom` - поиск релевантных интерактивных элементов через DOM Extractor и DOM Sub-Agent.
- `extract_visible_items` - чтение и семантический анализ видимых списков, строк, карточек, писем и таблиц через Content Extractor и Content Sub-Agent.
- `click_element` - клик по CSS selector.
- `type_text` - ввод текста и optional Enter.
- `scroll_page` - прокрутка страницы.
- `scroll_element` - прокрутка внутреннего scroll-container, например inbox, table, feed или chat pane.
- `wait` - короткое ожидание.
- `take_screenshot` - сохранение screenshot в `screenshots/`.
- `ask_user_confirmation` - явное подтверждение рискованного действия.
- `finish_task` - финальный статус и summary.

Каждый tool возвращает `ToolResult`:

```json
{
  "ok": true,
  "tool_name": "get_current_page_info",
  "message": "Current page info collected",
  "data": {}
}
```

Ошибки не роняют приложение. Они возвращаются в LLM как структурированный `tool_result` с `error_code` и `next_hint`.

## DOM Sub-Agent

`query_dom` не отправляет полный HTML. Он делает `page.evaluate` и собирает только видимые интерактивные кандидаты:

- `button`
- `a`
- `input`
- `textarea`
- `select`
- `[role=button]`
- `[contenteditable]`

Для каждого кандидата собираются:

- `tag`
- `selector`
- `text`
- `aria_label`
- `placeholder`
- `name`
- `title`
- `id`
- `role`
- `disabled`
- `visible`
- `nearby_text`

`SelectorBuilder` строит selectors из универсальных признаков: `id`, `name`, `aria-label`, `placeholder`, `title`, `role`, `type`, `data-testid`, затем использует DOM path fallback. Site-specific selectors не прописываются.

DOM Sub-Agent получает только query и компактный список candidates. Он обязан вернуть строгий JSON и может выбирать selectors только из предоставленного списка.

## Content Sub-Agent

`extract_visible_items` закрывает другой класс задач: не нажать конкретную кнопку, а прочитать и структурировать видимое содержимое страницы. Это важно для почты, таблиц, маркетплейсов, CRM, результатов поиска и любых повторяющихся списков.

Инструмент не отправляет полный HTML. Он через `page.evaluate` собирает компактные видимые item-кандидаты:

- `li`, `article`, `tr`;
- элементы с `role=listitem`, `role=row`, `role=article`, `role=option`, `role=treeitem`;
- повторяющиеся sibling-блоки с похожей структурой;
- query-matched текстовые блоки, если они нужны для анализа контента.

Для каждого item собираются:

- `index`;
- `selector`;
- `tag`, `role`, `source_kind`;
- компактный `text`;
- координаты и размер;
- nearby controls внутри строки: checkbox, buttons, links, menu controls.

Content Sub-Agent получает query и список visible items, затем возвращает строгий JSON с `fields`, `summary`, `classification`, `reason`, `recommended_action` и `confidence`. Например, для почтовой задачи он может разложить строку на `sender`, `subject`, `snippet`, классифицировать письмо как `spam`, `normal`, `important` или `suspicious`, но не может invent-ить элементы, которых нет в extracted items.

Типовой mail-flow:

1. Открыть почту и папку входящих.
2. Вызвать `extract_visible_items` для последних писем.
3. Классифицировать письма по видимым sender/subject/snippet.
4. Если данных мало, открыть конкретное письмо и вернуться через `go_back`.
5. Перед удалением или пометкой spam вызвать `ask_user_confirmation` с batch-описанием.
6. После подтверждения использовать row controls/selectors и дать финальный отчёт.

## Context Management

Полный HTML и бесконечная история tool results в LLM не отправляются.

Лимиты задаются в `.env`:

```env
AGENT_RECENT_ACTIONS_LIMIT=8
AGENT_EXECUTION_SUMMARY_MAX_CHARS=3000
AGENT_ACTION_MAX_CHARS=600
TOOL_RESULT_MAX_CHARS=6000
SHORT_VISIBLE_TEXT_CHARS=2000
DOM_MAX_ELEMENTS=80
DOM_MAX_TEXT_CHARS=160
DOM_MAX_TOTAL_CHARS=12000
DOM_QUERY_PAYLOAD_MAX_CHARS=14000
CONTENT_MAX_ITEMS=40
CONTENT_MAX_TEXT_CHARS=700
CONTENT_MAX_CONTROLS_PER_ITEM=8
CONTENT_MAX_TOTAL_CHARS=22000
CONTENT_QUERY_PAYLOAD_MAX_CHARS=24000
```

`AgentState` хранит:

- исходную задачу;
- компактный `execution_summary`;
- последние `recent_actions`.

Main Agent получает компактное состояние и последний tool exchange вместо бесконечного raw history.

## Security Layer

`SafetyGuard` блокирует рискованные действия до подтверждения пользователя. Риск классифицируется по tool name, selector, text и `action_description`.

Опасные категории:

- оплата;
- финальное подтверждение заказа;
- удаление писем;
- пометка как spam;
- отправка отклика;
- отправка формы;
- отправка письма или сообщения.

Если действие рискованное, tool возвращает:

```text
error_code=safety_confirmation_required
```

После этого агент должен вызвать `ask_user_confirmation`. Если пользователь отклоняет действие, агент должен остановиться через `finish_task(status="blocked")` или `finish_task(status="need_user_input")`.

Safety approvals are structured. `safety_confirmation_required` returns an
`approval_id` and an `approval_signature` derived from the actual risky tool
call, for example `type_text + selector + text + press_enter + category`.
After the user approves, the same tool call is allowed even if the model
rephrases `action_description`. This prevents repeated confirmation loops for
send-message, delete-email, mark-spam, and submit actions.

## Error Recovery

Для `click_element`, `type_text`, `navigate_to_url` ошибки возвращаются структурированно:

- `click_failed`
- `type_failed`
- `navigation_failed`
- `validation_error`
- `tool_exception`

`next_hint` рекомендует обновить состояние страницы через `get_current_page_info` или `query_dom`, а не повторять тот же selector бесконечно.

Дополнительно есть:

```env
MAX_CONSECUTIVE_FAILURES=4
```

После лимита подряд идущих ошибок agent loop завершится с рекомендацией сделать fresh observation.

## Терминальные Логи

CLI выводит:

- приветствие;
- путь persistent profile;
- viewport;
- количество tools;
- каждый `Agent Step`;
- `Assistant` text;
- tool name;
- JSON input;
- JSON result;
- финальный отчёт.

Пример:

```text
Using tool: query_dom
Input: {"query": "Найди поле поиска"}
Result: {"found": true, "matches": [...]}
```

## Демонстрационный Сценарий Для Видео

Цель видео: показать не “магический скрипт”, а агентную архитектуру: LLM выбирает tools, браузер реально меняется, ошибки возвращаются структурированно, DOM ищется динамически, рискованные действия блокируются.

1. Показать `.env.example` и объяснить, что реальный `.env` не коммитится.
2. Запустить тесты:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

3. Запустить простой безопасный сценарий:

```powershell
browser-ai-agent "Открой https://example.com, определи заголовок страницы и заверши задачу"
```

4. Запустить сценарий с DOM:

```powershell
browser-ai-agent "Открой https://google.com, найди поле поиска и введи запрос котики"
```

5. Показать, что если Google включает anti-bot page, агент не заявляет ложный успех, а завершает `partial_success` или `blocked`.
6. Показать safety:

```powershell
browser-ai-agent "Открой любой тестовый сайт и перед финальной отправкой формы запроси подтверждение пользователя"
```

В демонстрации для внешних сайтов лучше избегать реальных оплат, отправки форм, писем и откликов.

## Секреты И Git

Реальные ключи должны быть только в `.env` или переменных окружения. `.env` и `.env.*` игнорируются git, кроме `.env.example`.

Проверки перед push:

```powershell
git status --short --ignored .env
git ls-files .env .env.*
```

Ожидаемо:

```text
!! .env
.env.example
```

Также есть локальный pre-commit hook, который блокирует staged `.env` и строки, похожие на API keys.

## Ограничения

- Это CLI MVP, не веб-панель.
- DOM Sub-Agent уже выбирает selectors из candidates, но не использует визуальное распознавание screenshot.
- На сайтах с anti-bot защитой возможны блокировки.
- Safety Layer основан на эвристиках текста, а не на отдельной модели риска.
- Нет долговременной памяти между задачами, кроме browser profile.
- Нет полноценного планировщика подзадач.
- Нет отдельной системы budget control по API spend.

## Идеи Развития

- Добавить FastAPI/web dashboard.
- Добавить visual grounding по screenshots.
- Улучшить selector verification и fallback strategies.
- Добавить отдельный risk LLM classifier.
- Добавить per-task budget limits и rate limiting.
- Добавить replay traces для отладки.
- Добавить больше unit/integration тестов Playwright.
- Добавить browser tab management.
- Добавить экспорт финального отчёта в JSON/Markdown.

## Исследование И Технические Решения

- Persistent profile выбран, чтобы пользователь мог один раз войти вручную, а агент продолжал в авторизованной сессии.
- Tools сделаны высокоуровневыми для LLM: модель не вызывает Playwright напрямую.
- Полный HTML не отправляется в LLM: вместо этого используется компактный DOM candidate list.
- `query_dom` отделён от Main Agent, потому что поиск элементов является отдельной задачей со строгим JSON-ответом.
- Safety Guard встроен в `ToolRegistry`, чтобы рискованные actions блокировались до Playwright handler.
- `AgentState` ограничивает контекст, чтобы цена и размер запросов не росли с каждым шагом.
- OpenAI выбран provider по умолчанию, Anthropic оставлен переключаемым через `LLM_PROVIDER`.
## Interactive CLI Session

By default, CLI now keeps one browser session open for follow-up messages. After
`Final Report`, `blocked`, `failed`, or `need_user_input`, the terminal shows:

```text
You (new task / clarification / approval, Enter to close):
```

Type a clarification, approval, correction, or a new task there. Press Enter on
an empty line to close the browser. Use `--one-shot` for the old single-task
mode, or `--no-wait` to close immediately after the first run.

## Click Recovery

Browser actions wait for a short UI stabilization window after navigation,
clicks, typing, and scrolling. This is important for SPA pages where the DOM
can be visible before handlers, overlays, routes, or virtualized lists settle.

Relevant `.env` knobs:

```env
BROWSER_ACTION_TIMEOUT_MS=7000
BROWSER_UI_SETTLE_MS=700
BROWSER_LOAD_STATE_TIMEOUT_MS=1500
```

`click_element` also returns `click_diagnostics` on failure. Diagnostics include
the click point, bounding box, `document.elementFromPoint(...)`, and whether
another element intercepted the target. Recovery options are generic:

- retry with `position="left"`, `right`, `top`, or `bottom`;
- use `strategy="nearest_clickable_ancestor"` when a text/span belongs to a
  larger clickable row;
- refresh selectors with `query_dom` or `extract_visible_items`;
- scroll or close overlays before retrying.
