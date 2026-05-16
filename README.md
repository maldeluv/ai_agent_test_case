# browser_ai_agent

CLI-прототип автономного браузерного AI-агента. Агент запускает видимый Chromium через Playwright, принимает задачу на естественном языке, вызывает браузерные tools через LLM tool-use loop, ищет элементы через компактный DOM-анализ и останавливается перед рискованными действиями.

Главная идея: это не сценарный автокликер под конкретный сайт. Агент не знает DOM заранее, не использует site-specific selectors и принимает решения по текущему состоянию страницы.

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
        -> Content/list tools
           -> ContentExtractor
           -> ContentSubAgent
  -> BrowserSession
     -> Playwright persistent Chromium context
```

Цикл работы:

1. Пользователь вводит задачу.
2. Main Agent получает compact state и список tools.
3. Модель выбирает следующий tool.
4. ToolRegistry валидирует аргументы и запускает SafetyGuard.
5. Browser/tool слой выполняет действие или возвращает structured failure.
6. Результат возвращается в LLM.
7. Цикл продолжается до `finish_task`, лимита шагов, блокировки или запроса пользовательского ввода.

После успешного `finish_task` agent loop сразу прекращает обработку batch tool calls, чтобы модель не могла выполнить действия после финального завершения.

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

Минимальный `.env` для OpenAI:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.4-mini
```

Запуск:

```powershell
browser-ai-agent "Открой https://example.com и кратко опиши страницу"
```

Без ожидания Enter перед закрытием браузера:

```powershell
browser-ai-agent "Открой https://example.com и заверши задачу" --no-wait
```

Запуск модулем:

```powershell
python -m app.main "Открой https://example.com и заверши задачу"
```

## Конфигурация

Основные настройки в `.env.example`:

```env
MAX_STEPS=30
MAX_CONSECUTIVE_FAILURES=4
AGENT_RECENT_ACTIONS_LIMIT=8
AGENT_EXECUTION_SUMMARY_MAX_CHARS=3000
TOOL_RESULT_MAX_CHARS=6000
SHORT_VISIBLE_TEXT_CHARS=2000

BROWSER_ACTION_TIMEOUT_MS=7000
BROWSER_NEW_TAB_TIMEOUT_MS=4000
BROWSER_UI_SETTLE_MS=700
BROWSER_LOAD_STATE_TIMEOUT_MS=1500

OPENAI_USE_PREVIOUS_RESPONSE_ID=false

DOM_MAX_ELEMENTS=80
DOM_MAX_TEXT_CHARS=160
DOM_QUERY_PAYLOAD_MAX_CHARS=14000

CONTENT_MAX_ITEMS=40
CONTENT_MAX_TEXT_CHARS=700
CONTENT_MAX_CONTROLS_PER_ITEM=8
CONTENT_QUERY_PAYLOAD_MAX_CHARS=24000
```

`OPENAI_USE_PREVIOUS_RESPONSE_ID=false` по умолчанию: main loop не полагается на OpenAI response chain, а передаёт compact state как главный долгий контекст.

## Persistent Session

Браузер запускается в headful mode через `launch_persistent_context`. Профиль хранится в:

```text
browser_profile/
```

Папка игнорируется git. Cookies и логины сохраняются между запусками. Для ручного входа в аккаунт запусти агента, войди в открытом Chromium вручную, затем закрой CLI через Enter. Следующие запуски будут использовать тот же профиль.

## Tools

Зарегистрированные tools:

- `navigate_to_url` - переход на `http(s)` URL.
- `go_back` - возврат на предыдущую страницу по browser history.
- `get_current_page_info` - URL, title, tab summary, активный modal/top-layer и короткий видимый текст.
- `list_tabs` - список вкладок с index, title, URL и active flag.
- `switch_tab` - переключение активной вкладки.
- `query_dom` - поиск релевантных интерактивных элементов через DOM Extractor и DOM Sub-Agent.
- `get_element_info` - точечное чтение состояния известного selector: text/value, visibility, checked/disabled, rect, occlusion.
- `extract_visible_items` - чтение и анализ видимых списков, строк, карточек, писем и таблиц.
- `collect_visible_items` - накопление уникальных visible items через viewport и scroll steps.
- `classify_items_with_evidence` - классификация видимых items только по evidence/source_text.
- `prepare_batch_action_confirmation` - подготовка точных `ask_user_confirmation` и `click_element` аргументов для batch delete/mark-spam.
- `click_element` - клик по CSS selector с diagnostics и fallback strategies.
- `type_text` - ввод текста с проверкой, что текст появился в editable target.
- `scroll_page` - прокрутка страницы.
- `scroll_element` - прокрутка внутреннего scroll-container, например inbox, table, feed или chat pane.
- `wait` - короткое ожидание.
- `wait_for_page_state` - ожидание конкретного selector/text/URL вместо слепого sleep.
- `take_screenshot` - сохранение screenshot в `screenshots/`.
- `observe_screenshot` - fallback visual-анализ текущего screenshot через LLM vision, когда DOM/text tools недостаточны.
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

Ошибки не роняют приложение. Они возвращаются в LLM как structured `tool_result` с `error_code` и `next_hint`.

## DOM И Active Layer

`query_dom` не отправляет полный HTML. Он через `page.evaluate` собирает только компактный набор видимых интерактивных кандидатов:

- `button`, `a`, `input`, `textarea`, `select`;
- элементы с `role=button/link/textbox/checkbox/radio`;
- `[contenteditable]`;
- элементы с useful labels: `aria-label`, `placeholder`, `title`, `name`, `data-testid`, `data-test`, `data-qa`.

Для каждого кандидата собираются selector, text, labels, role, disabled, viewport/occlusion diagnostics, selector stability и nearby text.

`query_dom` также возвращает компактный `candidate_preview`: несколько верхних кандидатов с selector, text/labels, role, rect, stability, active-layer/work-area diagnostics. Это помогает агенту восстановиться, если DOM Sub-Agent дал низкую уверенность или не выбрал match, не отправляя в модель полный DOM.

Extractor умеет фокусироваться на активном верхнем слое:

- `dialog[open]`;
- `role="dialog"` / `role="alertdialog"`;
- `aria-modal="true"`;
- fixed/sticky overlay с высоким z-index;
- modal/popup/overlay/drawer классы.

Если открыта модалка, кандидаты под ней не конкурируют с кнопками внутри модалки. Это важно для сценариев вроде “нажал Откликнуться, поверх страницы открылась модалка со второй кнопкой Откликнуться и Добавить сопроводительное”.

## Active Work Area Для Чатов

Для обычных двухпанельных интерфейсов, где слева список чатов, а справа активный диалог, отдельной модалки может не быть. Поэтому DOM Extractor включает generic active work area heuristic.

Если запрос похож на ввод/отправку сообщения, например содержит intent `message`, `send`, `reply`, `write`, `type`, `сообщ`, `отправ`, `ответ`, `напиши`, extractor ищет видимый editable composer и фокусируется на рабочей области вокруг него. В этом режиме элементы из левого списка чатов отсекаются, а поле сообщения и кнопка отправки остаются.

Если запрос похож на переключение чата, например “открой чат Maria”, левый список остаётся доступен.

Диагностические поля:

- `inside_active_layer`;
- `active_layer_selector`;
- `inside_active_work_area`;
- `active_work_area_selector`;
- `center_occluded`;
- `selector_stability`.

## Content И List Workflows

`extract_visible_items` и `collect_visible_items` закрывают задачи чтения и обработки списков: почта, таблицы, маркетплейсы, CRM, выдачи поиска, уведомления, карточки.

Для каждого item собираются:

- `index`;
- `selector`;
- `tag`, `role`, `source_kind`;
- `source_text`;
- coordinates/rect;
- controls внутри строки: checkbox, buttons, links, menu controls;
- scroll container selector;
- active layer/work area diagnostics.

Типовой mail/list workflow:

1. Открыть нужный список.
2. Вызвать `collect_visible_items`, если нужно собрать N элементов через scroll.
3. Вызвать `classify_items_with_evidence`.
4. Использовать только visible evidence: sender, subject, snippet, source_text, controls.
5. Для batch delete/mark-spam вызвать `prepare_batch_action_confirmation`.
6. Вызвать `ask_user_confirmation`.
7. Повторить только тот `click_element`, который подготовил `prepare_batch_action_confirmation`.
8. После действия сделать observation и только потом завершать задачу.

SafetyGuard не даст выполнить batch delete/mark-spam, если batch не связан с ранее классифицированным visible evidence.

## Text Input И Send Verification

`type_text` после ввода проверяет editable target:

- `text_observed_before_enter`;
- `text_remaining_after_enter`;
- `enter_pressed`;
- `verification`.

Если `press_enter=false`, tool требует, чтобы текст реально появился в target. Если текст не наблюдается, возвращается `type_failed`.

Если `press_enter=true`, tool возвращает только “submission/send attempted”. Агент обязан сделать последующее observation перед тем, как заявлять успешную отправку.

## Verification Tools

Скриншоты из ТЗ показывают типовой паттерн демо: клик, ввод, ожидание, затем проверка результата по странице. Для этого есть два generic-инструмента без привязки к сайтам:

- `wait_for_page_state` ждёт конкретное состояние: selector visible/hidden/attached/detached, появление текста или изменение URL. Это предпочтительнее, чем повторять `wait(2)`, когда агент ожидает модалку, результаты поиска, счётчик корзины или переход.
- `get_element_info` читает состояние уже найденного selector: `text`, `value`, `checked`, `disabled`, `visible`, `rect`, `center_occluded`. Это удобно для проверки количества товара, заполненного поля, выбранного чекбокса или кнопок внутри модалки.

## Vision Fallback

Основной режим остаётся DOM-first. `observe_screenshot` нужен только когда DOM/text tools не дают ответа или противоречат реальной картинке: canvas/custom UI, непонятный overlay, визуальная раскладка, повторные selector failures, модалка/панель визуально есть, но extractor её не выделил.

Tool делает viewport screenshot в JPEG, отправляет его в Vision Sub-Agent и возвращает:

- `answer`;
- `visible_regions`;
- `suggested_next_step`;
- `confidence`;
- optional saved `path`.

Vision Sub-Agent не имеет права придумывать CSS selector. После visual observation агент должен вернуться к `query_dom` или `get_element_info`, чтобы получить точный selector перед кликом/вводом. Настройки стоимости/размера:

- `VISION_OBSERVATION_ENABLED`;
- `VISION_SCREENSHOT_QUALITY`;
- `VISION_MAX_SCREENSHOT_BYTES`;
- `VISION_QUESTION_MAX_CHARS`.

## Tab Management

Некоторые сайты открывают важные экраны в новой вкладке: auth flows, документы, внешние ссылки, почтовые или CRM-экраны. BrowserSession отслеживает новые Playwright pages и считает новую вкладку активной.

Tab-aware behavior:

- `get_current_page_info` включает `active_tab_index`, `tabs`, `tabs_error`.
- `list_tabs` возвращает все открытые вкладки.
- `switch_tab` переключает active tab.
- `click_element` ждёт новую вкладку до `BROWSER_NEW_TAB_TIMEOUT_MS` и возвращает `opened_or_switched_tab`, `active_url`.

Если видимый текст не соответствует ожидаемой странице, агент должен вызвать `list_tabs` / `switch_tab`, а не сразу говорить “не вижу”.

## Security Layer

`SafetyGuard` блокирует рискованные действия до подтверждения пользователя. Риск классифицируется по tool name, selector, text, URL, `action_description`, `target_context` и `batch_items`.

Наблюдения и content tools дополнительно возвращают `untrusted_content_warnings`, если видимый текст страницы похож на prompt-injection: просьбы игнорировать инструкции, раскрыть системный prompt, отправить секреты или управлять агентом. Это не блокировка, а явный сигнал для LLM: такие фрагменты считаются только содержимым страницы, а не инструкциями.

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

После этого агент должен вызвать `ask_user_confirmation` с `approval_id`. Если пользователь отклоняет действие, агент должен остановиться через `finish_task(status="blocked")` или `finish_task(status="need_user_input")`.

Approvals:

- structured;
- single-use;
- bound to active URL/tab;
- bound to selector/text/Enter state;
- bound to exact batch item set;
- cannot be reused after successful risky action;
- require explicit `approval_id` when several pending approvals exist.

Для batch delete/mark-spam одного текстового “да” недостаточно, если нет конкретного pending approval. Агент должен связать confirmation с тем самым `approval_id`.

## CLI Follow-Up Session

По умолчанию CLI держит один browser session открытым для follow-up сообщений. После финального отчёта терминал показывает:

```text
You (new task / clarification / approval, Enter to close):
```

Можно ввести уточнение, новую задачу или подтверждение. Pending approvals живут в session-level `SafetyGuard`, поэтому follow-up “да” связывается с конкретным pending action, а не запускает независимый run без safety state.

Используй `--one-shot` для старого single-task режима или `--no-wait`, чтобы закрыть браузер сразу после первого запуска.

## Error Recovery

Ошибки возвращаются структурированно:

- `click_failed`;
- `type_failed`;
- `navigation_failed`;
- `validation_error`;
- `tool_exception`;
- `batch_evidence_required`;
- `safety_confirmation_required`;
- `ambiguous_approval_id`.

`click_element` возвращает `click_diagnostics` на failure: click point, bounding box, `document.elementFromPoint(...)`, intercepted flag.

Generic recovery:

- сделать `get_current_page_info`;
- вызвать `query_dom` заново;
- проверить `list_tabs`;
- закрыть overlay или работать внутри active modal;
- использовать `position="left/right/top/bottom"`;
- использовать `strategy="nearest_clickable_ancestor"`;
- использовать `scroll_element` для inner list/chat/feed.

После `MAX_CONSECUTIVE_FAILURES` agent loop завершится с рекомендацией сделать fresh observation.

## Context Management

Полный HTML и бесконечная история tool results в LLM не отправляются.

`AgentState` хранит:

- исходную задачу;
- compact `execution_summary`;
- последние `recent_actions`;
- сокращённые tool inputs/results.

Sub-agents stateless: каждый DOM/content запрос получает только compact payload текущего extraction.

## Демонстрационные Сценарии

Безопасный smoke:

```powershell
browser-ai-agent "Открой https://example.com, определи заголовок страницы и заверши задачу"
```

DOM и ввод:

```powershell
browser-ai-agent "Открой сайт с поиском, найди поле поиска и введи запрос"
```

Отклик на вакансию:

```powershell
browser-ai-agent "Открой сайт с вакансиями, найди подходящую вакансию, начни отклик, добавь сопроводительное письмо и остановись перед финальной отправкой"
```

Важно: финальная отправка отклика является рискованным внешним действием. Агент должен запросить `ask_user_confirmation` перед отправкой.

Почта/list batch:

```powershell
browser-ai-agent "Прочитай последние 10 писем, найди явный спам и подготовь удаление только после моего подтверждения"
```

## Тесты

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Покрыты unit и Playwright integration-like тесты для:

- agent loop и `finish_task`;
- OpenAI/Claude tool definitions;
- safety approvals;
- batch delete evidence enforcement;
- tabs/new tab handling;
- DOM extraction;
- active modal/top-layer;
- active chat work area;
- contenteditable input;
- content/list extraction;
- fake mail batch confirmation/delete workflow.

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

Также игнорируются:

- `browser_profile/`;
- `screenshots/`;
- `.pytest_cache/`;
- `.venv/`.

## Ограничения

- Это CLI MVP, не web dashboard.
- Нет visual grounding по screenshots; DOM/content extraction остаётся главным каналом восприятия.
- На сайтах с anti-bot, captcha, 2FA или нестандартным canvas UI возможны блокировки.
- Safety Layer основан на эвристиках и structured state, а не на отдельной модели риска.
- Нет долговременной памяти между задачами, кроме browser profile.
- Нет отдельного budget control по API spend.

## Идеи Развития

- FastAPI/web dashboard.
- Replay traces для дебага.
- Visual grounding по screenshots.
- Отдельный LLM risk classifier.
- Более сильная работа с Shadow DOM/canvas.
- Экспорт финального отчёта в JSON/Markdown.
