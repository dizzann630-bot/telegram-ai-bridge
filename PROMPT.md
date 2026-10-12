# Промпт для ИИ-агента в браузере

Скопируй текст ниже целиком и отдай агенту, который умеет управлять браузером
(Claude в Chrome, ChatGPT agent / Atlas и т. п.). Агент сделает всё сам, а ты будешь
только входить в аккаунты и вводить секреты.

```
Помоги мне подключить мой Telegram к ChatGPT через MCP-сервер
https://github.com/dizzann630-bot/telegram-ai-bridge (бесплатный хостинг Render).
Веди меня по шагам ниже, сам нажимай кнопки и заполняй обычные поля.

ПРАВИЛА БЕЗОПАСНОСТИ (строго):
- Ты НЕ вводишь и не просишь прислать в чат: номер телефона, коды входа из Telegram,
  любые пароли (Telegram, GitHub, Render, ADMIN_PASSWORD), api_hash, строку сессии.
  Их ввожу я сам: поставь курсор в нужное поле и скажи «введите сюда …», потом жди.
- Входы в аккаунты (GitHub, Render, ChatGPT, my.telegram.org) делаю я.
- На my.telegram.org никогда не нажимай ничего в разделе «Delete account».
- На странице /setup не нажимай «Показать строку» и не копируй строку сессии сам.
- Если что-то не получается — остановись и опиши, что видишь на экране.

ШАГ 1. Ключи Telegram.
Открой https://my.telegram.org. Важно: VPN должен быть выключен. Я ввожу номер и код
(код придёт в приложение Telegram). Затем «API development tools», заполни форму:
App title: AI Bridge, Short name: aibridge + 5 случайных цифр, Platform: Desktop,
остальное пусто → «Create application». Если появилось «ERROR» — скажи мне включить
обход блокировок (zapret) при выключенном VPN и повтори. Не переписывай api_hash
в чат: скажи мне, где на странице api_id и api_hash, они понадобятся в шаге 3.

ШАГ 2. GitHub.
Открой https://github.com/dizzann630-bot/telegram-ai-bridge (если нужно — я войду
или зарегистрируюсь) → «Fork» → «Create fork».

ШАГ 3. Render.
Открой https://dashboard.render.com, я вхожу через GitHub. Затем New → Blueprint →
подключи GitHub, выбери мой форк telegram-ai-bridge, Blueprint Name: telegram-ai.
В переменных:
  ADMIN_PASSWORD — я придумываю и ввожу сам (от 10 символов, его надо запомнить);
  TELEGRAM_API_ID и TELEGRAM_API_HASH — я копирую с my.telegram.org и вставляю сам;
  TELEGRAM_SESSION — впиши один знак минус: -
→ «Deploy Blueprint». Дождись статуса Live (3–5 минут) и запомни адрес сервиса
вида https://telegram-ai-xxxx.onrender.com (дальше — АДРЕС).

ШАГ 4. Проверка.
Открой АДРЕС/health. Должно быть "telegram_keys_set":true и "password_set":true.
Если false — проверь переменные в Render → Environment.

ШАГ 5. Вход в Telegram.
Открой АДРЕС/setup. Я ввожу ADMIN_PASSWORD, потом вхожу по номеру телефона или по QR
(я сам). Дальше я следую инструкции на странице: копирую строку, открываю Render,
Edit → 5-я строка TELEGRAM_SESSION → вставляю → «Save, rebuild, and deploy».
Ты только подсказываешь, строку не трогаешь. Через 2–3 минуты открой АДРЕС/health:
должно быть "telegram_configured":true.

ШАГ 6. Подключение к ChatGPT (на компьютере, в браузере).
chatgpt.com → Плагины → «Добавить» → пункт для своего MCP-сервера / по URL.
Название: Telegram. URL: АДРЕС/mcp. Аутентификация: OAuth (Client ID и Secret пустые).
Если есть галочка «доверяю» — поставь → «Создать». На странице входа я ввожу
ADMIN_PASSWORD и нажимаю «Разрешить».
(Для Claude: Настройки → Коннекторы → Добавить свой коннектор → АДРЕС/mcp.)

ШАГ 7. Тест.
Новый чат → «+» → Telegram → напиши: «Кто я в Telegram? Покажи 10 последних чатов».
Если пришёл ответ — готово, скажи мне об этом.
```

После настройки можно закрыть вкладки. Строку сессии нигде не храни, кроме Render.
