<h1 id="ai-daily-assistant-for-scrum-teams">AI Daily Assistant for Scrum Teams</h1>

<p> <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-blue" alt="Python" class="badge"></a></p>
<a href="https://n8n.io/"><img src="https://img.shields.io/badge/n8n-Automation-orange" alt="n8n" class="badge"></a> <a href="https://tracker.yandex.com/"><img src="https://img.shields.io/badge/Yandex%20Tracker-Task%20Management-green" alt="Yandex Tracker" class="badge"></a> <a href="https://opensource.org/licenses/MIT"></p>
<h2 id="описание">Описание</h2>

<p>Этот репозиторий содержит прототип ИИ-ассистента для асинхронного управления разработкой в scrum-командах. Проект разработан в рамках кейса K2 НейроТех AI Boostcamp (задача: Ассистент руководителя разработки). Ассистент заменяет ежедневные созвоны (daily stand-ups) на асинхронные опросы в Telegram, анализирует ответы с помощью ИИ, интегрируется с Yandex Tracker и генерирует дайджесты для Team Lead/PM.</p>

<p>Ключевые проблемы, которые решает ассистент:</p>
<ul>
<li>Потеря времени на синхронные митинги.</li>
<li>Задержки в выявлении блокеров.</li>
<li>Проблемы с часовыми поясами в распределённых командах.</li>
<li>Ручной анализ статусов задач.</li>
</ul>

<p>Ассистент собирает daily-обновления (вчера/сегодня/блокеры), парсит их с помощью LLM, проверяет статусы в Tracker и предоставляет структурированный отчёт с анализом рисков, прогрессом (в %) и рекомендациями.</p>

<h2 id="функции">Функции</h2>

<h3 id="основные">Основные</h3>
<ul>
<li><strong>Асинхронный daily-опрос</strong>: Ежедневно в 9:00 по локальному времени (учёт таймзон) бот опрашивает Dev/QA. Ответы сохраняются в БД и синхронизируются с задачами в Yandex Tracker.</li>
<li><strong>Генерация дайджеста</strong>: Команда /digest (для TL/PM) — ИИ-анализ: статистика спринта (% выполнения, задачи в работе), блокеры с критичностью (низкая/средняя/высокая), рекомендации по эскалации.</li>
<li><strong>Эскалация блокеров</strong>: Автоматическое уведомление TL при критичных проблемах (через n8n workflow).</li>
<li><strong>Интеграция с Yandex Tracker</strong>: Получение задач, статусов, уведомления о смене статуса (webhook: активация/деактивация daily).</li>
</ul>

<h3 id="дополнительные">Дополнительные</h3>
<ul>
<li><strong>Персональная сводка</strong>: /summary — личные задачи, блокеры, напоминания о &quot;зависших&quot; карточках.</li>
<li><strong>Просмотр задач</strong>: /task — текущая задача с ссылкой на Tracker; для TL — просмотр задач сотрудников.</li>
<li><strong>Онбординг новичков</strong>: /onboarding — мини-FAQ по процессу, подсказки в опросах.</li>
<li><strong>Аналитика спринта</strong>: Прогноз рисков, velocity, загрузка по участникам (в дайджесте).</li>
<li><strong>Интерактивные запросы</strong>: Вопросы вроде &quot;Покажи риски&quot; (расширение для будущего).</li>
</ul>

<h3 id="функции-удобства">Функции удобства</h3>
<ul>
<li><strong>Профиль пользователя</strong>: /profile — редактирование имени, email, таймзоны (30+ вариантов: Россия, СНГ, мир), роли.</li>
<li><strong>Уведомления</strong>: Авто-уведомления о новой/завершённой задаче (7–21 по локальному времени).</li>
<li><strong>Анимация загрузки</strong>: Красивые индикаторы обработки запросов.</li>
<li><strong>Меню по ролям</strong>: Inline-меню адаптировано (Dev/QA vs TL/PM).</li>
</ul>

<h2 id="технологии">Технологии</h2>

<ul>
<li><strong>Backend</strong>: Python 3.10+ (telebot, psycopg2, requests, apscheduler, pytz).</li>
<li><strong>Оркестрация</strong>: n8n (workflow для webhook, ИИ-анализа; JSON-файлы в repo).</li>
<li><strong>ИИ</strong>: LLM через OpenRouter (deepseek модель) — парсинг текстов, оценка прогресса.</li>
<li><strong>БД</strong>: PostgreSQL (хранение профилей, daily, ролей; retry-подключение).</li>
<li><strong>Интеграции</strong>: 
<ul>
<li>Telegram Bot API.</li>
<li>Yandex Tracker REST API (IAM-токены, поиск задач).</li>
</ul>
</li>
<li><strong>Планировщик</strong>: APScheduler (cron для опросов/напоминаний).</li>
<li><strong>Другое</strong>: Logging, threading для асинхронности.</li>
</ul>

<h2 id="структура-репозитория">Структура репозитория</h2>

<pre><code>├── README.md               # Это файл
├── tg_bot_ai_3_good_role_yt.py  # Основной код Telegram-бота
├── n8n_workflows/
│   ├── Tracker_Events_Webhook.json  # n8n: Обработка событий из Tracker
│   └── YandexTracker_Daily_Digest.json  # n8n: Генерация дайджеста
├── docs/
│   ├── К2_НейроТех_Ассистент_руководителя_разработки.pdf  # Описание кейса
│   └── Презентация_черновик.pptx  # Черновик презентации
├── config/                 # Примеры конфигов (DB_CONFIG, TOKENS)
│   └── env.example         # Шаблон .env для ключей
├── screenshots/            # Скриншоты бота, дайджестов (добавьте свои)
└── requirements.txt        # Зависимости Python
</code></pre>

<h2 id="установка">Установка</h2>

<ol>
<li><strong>Клонируйте репозиторий</strong>:
<pre><code>git clone https://github.com/yourusername/ai-daily-assistant.git
cd ai-daily-assistant
</code></pre>
</li>
<li><strong>Установите зависимости</strong> (Python 3.10+):
<pre><code>pip install -r requirements.txt
</code></pre>
</li>
<li><strong>Настройте окружение</strong>:
<ul>
<li>Создайте <code>.env</code> на основе <code>env.example</code>:
<pre><code>TELEGRAM_TOKEN=your_telegram_bot_token
DB_HOST=your_db_host
DB_NAME=your_db_name
DB_USER=your_db_user
DB_PASSWORD=your_db_password
TRACKER_ORG_ID=your_yandex_org_id
OAUTH_TOKEN=your_yandex_oauth_token
</code></pre>
</li>
<li>Настройте PostgreSQL: Создайте БД с таблицами (users, roles, checkins) — скрипт в <code>docs/db_schema.sql</code> (добавьте, если нужно).</li>
</ul>
</li>
<li><strong>n8n Setup</strong>:
<ul>
<li>Импортируйте JSON-файлы в n8n.</li>
<li>Настройте credentials: Telegram API, PostgreSQL, Yandex IAM.</li>
</ul>
</li>
<li><strong>Yandex Tracker</strong>:
<ul>
<li>Настройте webhook для событий (status changes) на ваш n8n endpoint.</li>
</ul>
</li>
</ol>

<h2 id="запуск">Запуск</h2>

<ul>
<li><strong>Бот</strong>: 
<pre><code>python tg_bot_ai_3_good_role_yt.py
</code></pre>
</li>
<li><strong>n8n</strong>: Активируйте workflows в интерфейсе n8n.</li>
</ul>

<p>Тестирование: Запустите бота, зарегистрируйтесь (/start), настройте профиль (/profile), протестируйте /daily и /digest.</p>

<h2 id="примеры-использования">Примеры использования</h2>

<ul>
<li><strong>Опрос</strong>: Бот шлёт вопросы в 9:00. Ответьте текстом — ИИ парсит.</li>
<li><strong>Дайджест</strong> (для TL):
<pre><code>/digest
</code></pre>
Вывод: Статистика спринта, прогресс по задачам, блокеры.
</li>
</ul>

<p>Скриншоты в <code>screenshots/</code></p>

<h2 id="контакты">Контакты</h2>

<ul>
<li>Автор: [Калинина А] (email@example.com)</li>
<li>Кейс: K2 НейроТех AI Boostcamp, 2025.</li>
</ul>

<p>Если репозиторий полезен — звезда ★!</p>

</body>
</html>
