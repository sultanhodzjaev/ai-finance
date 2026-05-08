// ============================================================
// AI-Финансист — Telegram Mini App (SPA)
// ============================================================

const tg = window.Telegram?.WebApp;

// Инициализируем Telegram WebApp и применяем его цветовую тему
if (tg) {
    tg.ready();
    tg.expand();
    const bg   = tg.themeParams?.bg_color   || '#f9fafb';
    const text = tg.themeParams?.text_color || '#1f2937';
    document.documentElement.style.setProperty('--bg-color', bg);
    document.documentElement.style.setProperty('--text-color', text);
}

// ============================================================
// КОНСТАНТЫ — цвета категорий для графиков
// ============================================================
const CAT_COLORS = {
    food:          '#FF6B6B',
    groceries:     '#4ECDC4',
    transport:     '#45B7D1',
    entertainment: '#F7DC6F',
    health:        '#82E0AA',
    clothes:       '#BB8FCE',
    home:          '#F0B27A',
    communication: '#85C1E9',
    gifts:         '#F1948A',
    other:         '#BDC3C7',
};

// ============================================================
// ГЛОБАЛЬНОЕ СОСТОЯНИЕ ПРИЛОЖЕНИЯ
// ============================================================
const state = {
    screen:       'dashboard',  // текущий экран
    me:           null,         // данные пользователя из /api/me
    categories:   [],           // [{id, name, emoji}] из /api/categories
    transactions: [],           // все транзакции (от новых к старым)
    filter:       'month',      // фильтр истории: 'day'|'week'|'month'|'all'
    selectedTx:   null,         // транзакция для Bottom Sheet
    editingTx:    false,        // открыт ли режим редактирования
    charts:       {},           // Chart.js-инстансы (храним, чтобы уничтожать при пересоздании)
};

// ============================================================
// API — универсальная функция запросов
// ============================================================
async function api(method, path, body = null) {
    const initData = tg?.initData || '';
    const opts = {
        method,
        headers: {
            'Content-Type': 'application/json',
            'X-Init-Data': initData,
        },
    };
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch(`/miniapp/api${path}`, opts);
    if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || `Ошибка ${r.status}`);
    }
    return r.json();
}

// ============================================================
// ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
// ============================================================

// Форматирует сумму: 12500 → "12 500 KGS"
function fmt(amount) {
    const cur = state.me?.currency || 'KGS';
    return `${Math.round(amount).toLocaleString('ru-RU')} ${cur}`;
}

// Форматирует дату: "2024-05-08T14:30:00" → "8 май, 14:30"
function fmtDate(iso) {
    const d = new Date(iso);
    const months = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
    const hh = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return `${d.getDate()} ${months[d.getMonth()]}, ${hh}:${mm}`;
}

// Получает объект категории по id
function getCat(id) {
    return state.categories.find(c => c.id === id) || { id, name: id, emoji: '📦' };
}

// Цвет категории для Chart.js
function catColor(id) {
    return CAT_COLORS[id] || '#BDC3C7';
}

// Фильтрует транзакции по временному периоду
function filterTxs(f) {
    const now = new Date();
    return state.transactions.filter(tx => {
        const d = new Date(tx.datetime);
        if (f === 'day')   return d.toDateString() === now.toDateString();
        if (f === 'week')  return d >= new Date(now - 7 * 24 * 60 * 60 * 1000);
        if (f === 'month') return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
        return true; // 'all'
    });
}

// Русское склонение слова "транзакция"
function pluralTx(n) {
    if (n % 10 === 1 && n % 100 !== 11)                              return 'транзакция';
    if ([2,3,4].includes(n%10) && ![12,13,14].includes(n%100))       return 'транзакции';
    return 'транзакций';
}

// Уничтожает Chart.js-инстанс, чтобы не было конфликта при пересоздании canvas
function destroyChart(key) {
    if (state.charts[key]) {
        state.charts[key].destroy();
        delete state.charts[key];
    }
}

// ============================================================
// ИНИЦИАЛИЗАЦИЯ — загружаем данные и запускаем SPA
// ============================================================
async function init() {
    document.getElementById('app').innerHTML = `
        <div class="flex flex-col items-center justify-center min-h-screen">
            <div class="text-6xl mb-3 animate-pulse">💰</div>
            <p class="text-gray-400 text-sm">Загружаю данные...</p>
        </div>`;
    try {
        // Параллельно запрашиваем данные пользователя, категории и транзакции
        const [me, catsR, txsR] = await Promise.all([
            api('GET', '/me'),
            api('GET', '/categories'),
            api('GET', '/transactions'),
        ]);
        state.me           = me;
        state.categories   = catsR.categories;
        state.transactions = txsR.transactions;
        render();
    } catch (e) {
        // Показываем ошибку если инициализация не удалась (вне Telegram или невалидный initData)
        document.getElementById('app').innerHTML = `
            <div class="flex flex-col items-center justify-center min-h-screen p-8 text-center gap-4">
                <div class="text-6xl">🤖</div>
                <p class="font-semibold text-gray-800 text-lg">Нет доступа</p>
                <p class="text-sm text-gray-500 max-w-xs">
                    Открой приложение через кнопку <strong>«📲 Открыть приложение»</strong>
                    в боте Telegram
                </p>
            </div>`;
    }
}

// ============================================================
// РЕНДЕР — перестраивает весь DOM при смене экрана или данных
// ============================================================
function render() {
    // Уничтожаем графики перед пересборкой DOM
    destroyChart('donut');
    destroyChart('line');

    document.getElementById('app').innerHTML = `
        <div class="pb-24 min-h-screen screen-enter">
            ${state.screen === 'dashboard' ? buildDashboard() : ''}
            ${state.screen === 'history'   ? buildHistory()   : ''}
            ${state.screen === 'add'       ? buildAdd()       : ''}
        </div>
        ${buildNav()}
        ${buildBottomSheet()}
    `;

    // Прикрепляем обработчики после вставки HTML
    attachNavHandlers();
    if (state.screen === 'dashboard') renderCharts();
    if (state.screen === 'history')   attachHistoryHandlers();
    if (state.screen === 'add')       attachAddHandlers();
    if (state.selectedTx)             attachSheetHandlers();
}

// ============================================================
// НАВИГАЦИОННАЯ ПАНЕЛЬ
// ============================================================
function buildNav() {
    const d = state.screen === 'dashboard';
    const h = state.screen === 'history';
    return `
        <nav class="fixed bottom-0 left-0 right-0 bg-white/95 backdrop-blur-md border-t border-gray-100
                    flex items-center justify-around px-2 py-1 z-40 shadow-lg"
             style="padding-bottom: max(env(safe-area-inset-bottom), 4px)">
            <button class="nav-btn flex flex-col items-center gap-0.5 py-2 px-5 rounded-xl transition-colors
                           ${d ? 'text-indigo-600' : 'text-gray-400 hover:text-gray-600'}"
                    data-screen="dashboard">
                <span class="text-2xl">📊</span>
                <span class="text-xs font-medium">Дашборд</span>
            </button>

            <button class="nav-btn flex flex-col items-center py-1 px-5" data-screen="add">
                <span class="bg-indigo-600 text-white text-3xl rounded-full w-12 h-12
                             flex items-center justify-center shadow-md leading-none">+</span>
            </button>

            <button class="nav-btn flex flex-col items-center gap-0.5 py-2 px-5 rounded-xl transition-colors
                           ${h ? 'text-indigo-600' : 'text-gray-400 hover:text-gray-600'}"
                    data-screen="history">
                <span class="text-2xl">📜</span>
                <span class="text-xs font-medium">История</span>
            </button>
        </nav>`;
}

function attachNavHandlers() {
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            state.screen = btn.dataset.screen;
            if (state.screen !== 'history') state.filter = 'month';
            state.selectedTx = null;
            state.editingTx  = false;
            render();
        });
    });
}

// ============================================================
// ЭКРАН 1: ДАШБОРД
// ============================================================
function buildDashboard() {
    const now      = new Date();
    const monthTxs = filterTxs('month');
    const total    = monthTxs.reduce((s, t) => s + t.amount, 0);

    // Сгруппированные данные по категориям для топ-3
    const byCat = {};
    monthTxs.forEach(t => { byCat[t.category] = (byCat[t.category] || 0) + t.amount; });
    const top3 = Object.entries(byCat).sort((a, b) => b[1] - a[1]).slice(0, 3);

    const monthNames = [
        'Январь','Февраль','Март','Апрель','Май','Июнь',
        'Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь',
    ];

    return `
        <div class="px-4 pt-5">
            <!-- Шапка -->
            <div class="flex items-start justify-between mb-4">
                <div>
                    <p class="text-gray-400 text-sm">Привет, ${state.me?.first_name || 'Друг'}! 👋</p>
                    <h1 class="text-2xl font-bold text-gray-900">${monthNames[now.getMonth()]} ${now.getFullYear()}</h1>
                </div>
                <div class="w-10 h-10 bg-indigo-100 rounded-full flex items-center justify-center text-xl">💰</div>
            </div>

            <!-- Карточка суммы -->
            <div class="bg-gradient-to-br from-indigo-500 to-indigo-700 rounded-2xl p-5 mb-4 text-white shadow-xl">
                <p class="text-indigo-200 text-sm mb-1">Потрачено в этом месяце</p>
                <p class="text-3xl font-bold tracking-tight">${fmt(total)}</p>
                <p class="text-indigo-300 text-sm mt-1">${monthTxs.length} ${pluralTx(monthTxs.length)}</p>
            </div>

            ${monthTxs.length === 0 ? `
                <div class="bg-white rounded-2xl p-8 text-center shadow-sm">
                    <div class="text-4xl mb-3">🎉</div>
                    <p class="font-semibold text-gray-700">Трат пока нет</p>
                    <p class="text-sm text-gray-400 mt-1">Запиши первую трату через бота или нажми «+»</p>
                </div>
            ` : `
                <!-- Диаграмма по категориям -->
                <div class="bg-white rounded-2xl p-4 shadow-sm mb-4">
                    <h2 class="font-semibold text-gray-700 mb-3 text-sm">По категориям</h2>
                    <div class="relative" style="height: 200px">
                        <canvas id="donut-chart"></canvas>
                    </div>
                    <!-- Топ-3 строки -->
                    <div class="mt-4 space-y-2.5 pt-3 border-t border-gray-100">
                        ${top3.map(([id, sum]) => {
                            const cat = getCat(id);
                            const pct = total > 0 ? Math.round(sum / total * 100) : 0;
                            return `
                                <div class="flex items-center justify-between">
                                    <div class="flex items-center gap-2">
                                        <span class="text-xl">${cat.emoji}</span>
                                        <span class="text-sm text-gray-700">${cat.name}</span>
                                        <span class="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded-full">${pct}%</span>
                                    </div>
                                    <span class="font-semibold text-sm text-gray-900">${fmt(sum)}</span>
                                </div>`;
                        }).join('')}
                    </div>
                </div>

                <!-- График расходов по дням -->
                <div class="bg-white rounded-2xl p-4 shadow-sm mb-4">
                    <h2 class="font-semibold text-gray-700 mb-3 text-sm">По дням месяца</h2>
                    <div class="relative" style="height: 160px">
                        <canvas id="line-chart"></canvas>
                    </div>
                </div>
            `}
        </div>`;
}

// Создаёт Chart.js-графики после вставки canvas в DOM
function renderCharts() {
    const monthTxs = filterTxs('month');
    if (monthTxs.length === 0) return;

    // --- Донат-диаграмма по категориям ---
    const byCat = {};
    monthTxs.forEach(t => { byCat[t.category] = (byCat[t.category] || 0) + t.amount; });
    const catEntries = Object.entries(byCat).sort((a, b) => b[1] - a[1]);

    const donutEl = document.getElementById('donut-chart');
    if (donutEl) {
        state.charts.donut = new Chart(donutEl, {
            type: 'doughnut',
            data: {
                labels:   catEntries.map(([id]) => getCat(id).name),
                datasets: [{
                    data:            catEntries.map(([, v]) => v),
                    backgroundColor: catEntries.map(([id]) => catColor(id)),
                    borderWidth: 2,
                    borderColor: '#fff',
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '62%',
                plugins: {
                    legend: {
                        position: 'right',
                        labels: { font: { size: 11 }, boxWidth: 12, padding: 8 },
                    },
                    tooltip: {
                        callbacks: { label: ctx => ` ${fmt(ctx.raw)}` },
                    },
                },
            },
        });
    }

    // --- Линейный график трат по дням текущего месяца ---
    const now = new Date();
    const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
    const byDay = {};
    monthTxs.forEach(t => {
        const day = new Date(t.datetime).getDate();
        byDay[day] = (byDay[day] || 0) + t.amount;
    });
    const days     = Array.from({ length: daysInMonth }, (_, i) => i + 1);
    const lineData = days.map(d => byDay[d] || 0);

    const lineEl = document.getElementById('line-chart');
    if (lineEl) {
        state.charts.line = new Chart(lineEl, {
            type: 'line',
            data: {
                labels:   days.map(String),
                datasets: [{
                    data:            lineData,
                    borderColor:     '#4f46e5',
                    backgroundColor: 'rgba(79,70,229,0.08)',
                    fill:            true,
                    tension:         0.4,
                    pointRadius:     2,
                    pointBackgroundColor: '#4f46e5',
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { font: { size: 9 }, maxTicksLimit: 10 },
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(0,0,0,0.04)' },
                        ticks: {
                            font: { size: 9 },
                            callback: v => v >= 1000 ? `${(v/1000).toFixed(0)}к` : v,
                        },
                    },
                },
            },
        });
    }
}

// ============================================================
// ЭКРАН 2: ИСТОРИЯ
// ============================================================
function buildHistory() {
    const filtered = filterTxs(state.filter);
    const filterOptions = [
        { key: 'day',   label: 'День' },
        { key: 'week',  label: 'Неделя' },
        { key: 'month', label: 'Месяц' },
        { key: 'all',   label: 'Всё' },
    ];

    return `
        <div class="px-4 pt-5">
            <h1 class="text-2xl font-bold text-gray-900 mb-4">История трат</h1>

            <!-- Фильтры периода -->
            <div class="flex gap-2 mb-4 overflow-x-auto pb-1 -mx-1 px-1">
                ${filterOptions.map(f => `
                    <button class="filter-btn flex-shrink-0 px-4 py-1.5 rounded-full text-sm font-medium
                                   border transition-all duration-150
                                   ${state.filter === f.key
                                       ? 'bg-indigo-600 text-white border-indigo-600 shadow-sm'
                                       : 'bg-white text-gray-600 border-gray-200 hover:border-indigo-300'}"
                            data-filter="${f.key}">${f.label}</button>
                `).join('')}
            </div>

            <!-- Список транзакций -->
            ${filtered.length === 0 ? `
                <div class="text-center py-16">
                    <div class="text-5xl mb-3">📭</div>
                    <p class="text-gray-500 font-medium">Трат нет за этот период</p>
                    <p class="text-gray-400 text-sm mt-1">Запиши трату через бота или «+»</p>
                </div>
            ` : `
                <div class="space-y-2.5">
                    ${filtered.map(tx => buildTxRow(tx)).join('')}
                </div>
            `}
        </div>`;
}

// Строит одну строку транзакции в списке
function buildTxRow(tx) {
    const cat = getCat(tx.category);
    return `
        <div class="tx-row bg-white rounded-2xl px-4 py-3.5 flex items-center gap-3 shadow-sm
                    cursor-pointer active:opacity-70 transition-opacity"
             data-id="${tx.id}">
            <div class="w-11 h-11 rounded-xl flex items-center justify-center text-2xl flex-shrink-0"
                 style="background-color: ${catColor(tx.category)}22">
                ${cat.emoji}
            </div>
            <div class="flex-1 min-w-0">
                <p class="font-medium text-gray-900 text-sm">${cat.name}</p>
                ${tx.description
                    ? `<p class="text-xs text-gray-400 truncate">${tx.description}</p>`
                    : `<p class="text-xs text-gray-400">${fmtDate(tx.datetime)}</p>`}
            </div>
            <div class="text-right flex-shrink-0">
                <p class="font-bold text-gray-900 text-sm">${fmt(tx.amount)}</p>
                ${tx.description ? `<p class="text-xs text-gray-300">${fmtDate(tx.datetime)}</p>` : ''}
            </div>
        </div>`;
}

function attachHistoryHandlers() {
    // Переключение фильтров
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            state.filter = btn.dataset.filter;
            render();
        });
    });
    // Тап по транзакции → Bottom Sheet
    document.querySelectorAll('.tx-row').forEach(row => {
        row.addEventListener('click', () => {
            const tx = state.transactions.find(t => t.id === row.dataset.id);
            if (tx) openSheet(tx);
        });
    });
}

// ============================================================
// ЭКРАН 3: ДОБАВИТЬ ТРАТУ
// ============================================================
let addSelectedCat = 'food';

function buildAdd() {
    addSelectedCat = state.categories[0]?.id || 'food';
    return `
        <div class="px-4 pt-5">
            <h1 class="text-2xl font-bold text-gray-900 mb-5">Новая трата</h1>

            <!-- Поле суммы -->
            <div class="bg-white rounded-2xl p-5 text-center shadow-sm mb-4">
                <p class="text-xs text-gray-400 mb-1 font-medium uppercase tracking-wide">Сумма</p>
                <input id="add-amount" type="number" inputmode="decimal" placeholder="0"
                    class="amount-input w-full text-center text-4xl font-bold text-gray-900
                           placeholder-gray-200 border-none outline-none bg-transparent">
                <p class="text-sm text-gray-400 mt-2 font-medium">${state.me?.currency || 'KGS'}</p>
            </div>

            <!-- Выбор категории -->
            <div class="bg-white rounded-2xl p-4 shadow-sm mb-4">
                <p class="text-sm font-semibold text-gray-600 mb-3">Категория</p>
                <div class="grid grid-cols-5 gap-2" id="add-cat-grid">
                    ${state.categories.map((cat, i) => `
                        <button class="cat-btn ${i === 0 ? 'selected' : ''}" data-cat="${cat.id}">
                            <span class="emoji">${cat.emoji}</span>
                            <span>${cat.name}</span>
                        </button>
                    `).join('')}
                </div>
            </div>

            <!-- Описание -->
            <div class="bg-white rounded-2xl p-4 shadow-sm mb-6">
                <p class="text-sm font-semibold text-gray-600 mb-2">
                    Описание
                    <span class="text-gray-400 font-normal text-xs ml-1">необязательно</span>
                </p>
                <input id="add-desc" type="text" placeholder="Кофе, такси, продукты..."
                    class="w-full outline-none text-gray-800 placeholder-gray-300 text-sm bg-transparent">
            </div>

            <!-- Кнопка сохранить -->
            <button id="add-save-btn"
                class="w-full bg-indigo-600 text-white font-bold py-4 rounded-2xl text-base
                       shadow-lg active:opacity-80 transition-opacity">
                💾 Сохранить
            </button>
        </div>`;
}

function attachAddHandlers() {
    // Выбор категории
    document.querySelectorAll('#add-cat-grid .cat-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('#add-cat-grid .cat-btn').forEach(b => b.classList.remove('selected'));
            btn.classList.add('selected');
            addSelectedCat = btn.dataset.cat;
        });
    });

    // Сохранение транзакции
    document.getElementById('add-save-btn')?.addEventListener('click', async () => {
        const rawAmount = document.getElementById('add-amount')?.value || '';
        const amount    = parseFloat(rawAmount);
        const desc      = document.getElementById('add-desc')?.value?.trim() || '';

        if (!amount || amount <= 0) {
            if (tg?.showAlert) tg.showAlert('Введи сумму больше нуля');
            else alert('Введи сумму больше нуля');
            return;
        }

        const btn = document.getElementById('add-save-btn');
        if (btn) { btn.disabled = true; btn.textContent = 'Сохраняю...'; }

        try {
            const tx = await api('POST', '/transactions', {
                amount,
                category:    addSelectedCat,
                description: desc,
            });
            state.transactions.unshift(tx); // добавляем в начало списка
            state.screen = 'history';
            render();
        } catch (e) {
            if (tg?.showAlert) tg.showAlert(`Ошибка: ${e.message}`);
            else alert(`Ошибка: ${e.message}`);
            if (btn) { btn.disabled = false; btn.textContent = '💾 Сохранить'; }
        }
    });
}

// ============================================================
// BOTTOM SHEET — детали транзакции
// ============================================================
function buildBottomSheet() {
    if (!state.selectedTx) return '<div id="bottom-sheet-placeholder"></div>';
    const tx  = state.selectedTx;
    const cat = getCat(tx.category);
    const sourceLabel = { text: '✍️ Текст', photo: '📷 Фото', miniapp: '📲 Mini App' };

    return `
        <div id="bottom-sheet" class="fixed inset-0 z-50 flex flex-col justify-end">
            <!-- Затемнённый оверлей -->
            <div id="sheet-overlay"
                 class="absolute inset-0 bg-black/40 backdrop-blur-sm"></div>

            <!-- Сама панель -->
            <div class="relative bg-white rounded-t-3xl shadow-2xl max-h-[88vh] overflow-y-auto sheet-slide-up">
                <!-- Дёргалка -->
                <div class="flex justify-center pt-3 pb-1">
                    <div class="w-10 h-1 bg-gray-200 rounded-full"></div>
                </div>
                <div class="px-6 pb-8">
                    ${state.editingTx ? buildEditForm(tx) : buildSheetView(tx, cat, sourceLabel)}
                </div>
            </div>
        </div>`;
}

// Вид детали транзакции (не режим редактирования)
function buildSheetView(tx, cat, sourceLabel) {
    return `
        <div class="text-center py-4">
            <div class="w-16 h-16 rounded-2xl mx-auto flex items-center justify-center text-4xl mb-3"
                 style="background-color: ${catColor(tx.category)}22">
                ${cat.emoji}
            </div>
            <p class="text-3xl font-bold text-gray-900">${fmt(tx.amount)}</p>
            <p class="text-gray-500 mt-1">${cat.name}</p>
        </div>

        <div class="space-y-3 py-4 border-t border-b border-gray-100 mb-5">
            ${tx.description ? `
                <div class="flex justify-between items-start gap-4">
                    <span class="text-gray-400 text-sm flex-shrink-0">Описание</span>
                    <span class="text-gray-800 text-sm font-medium text-right">${tx.description}</span>
                </div>` : ''}
            <div class="flex justify-between">
                <span class="text-gray-400 text-sm">Дата и время</span>
                <span class="text-gray-800 text-sm font-medium">${fmtDate(tx.datetime)}</span>
            </div>
            <div class="flex justify-between">
                <span class="text-gray-400 text-sm">Источник</span>
                <span class="text-gray-800 text-sm font-medium">${sourceLabel[tx.source] || tx.source}</span>
            </div>
            ${tx.merchant ? `
                <div class="flex justify-between">
                    <span class="text-gray-400 text-sm">Магазин</span>
                    <span class="text-gray-800 text-sm font-medium">${tx.merchant}</span>
                </div>` : ''}
        </div>

        <div class="grid grid-cols-2 gap-3">
            <button id="sheet-edit-btn"
                class="py-3.5 rounded-2xl border border-gray-200 text-gray-700 font-semibold text-sm
                       active:opacity-70 transition-opacity">
                ✏️ Редактировать
            </button>
            <button id="sheet-delete-btn"
                class="py-3.5 rounded-2xl bg-red-50 text-red-500 font-semibold text-sm
                       active:opacity-70 transition-opacity border border-red-100">
                🗑 Удалить
            </button>
        </div>`;
}

// Форма редактирования внутри Bottom Sheet
function buildEditForm(tx) {
    return `
        <div class="pt-2">
            <h3 class="text-lg font-bold text-gray-900 mb-5">Редактировать трату</h3>

            <div class="mb-4">
                <p class="text-sm text-gray-500 mb-1.5 font-medium">Сумма</p>
                <input id="edit-amount" type="number" inputmode="decimal"
                    value="${tx.amount}"
                    class="w-full border border-gray-200 rounded-xl px-4 py-3 text-xl font-bold
                           outline-none focus:border-indigo-400 transition-colors">
            </div>

            <div class="mb-4">
                <p class="text-sm text-gray-500 mb-2 font-medium">Категория</p>
                <div class="grid grid-cols-5 gap-2" id="edit-cat-grid">
                    ${state.categories.map(cat => `
                        <button class="edit-cat-btn cat-btn ${cat.id === tx.category ? 'selected' : ''}"
                                data-cat="${cat.id}">
                            <span class="emoji">${cat.emoji}</span>
                            <span>${cat.name}</span>
                        </button>
                    `).join('')}
                </div>
            </div>

            <div class="mb-5">
                <p class="text-sm text-gray-500 mb-1.5 font-medium">Описание</p>
                <input id="edit-desc" type="text"
                    value="${tx.description || ''}"
                    class="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm
                           outline-none focus:border-indigo-400 transition-colors">
            </div>

            <div class="grid grid-cols-2 gap-3">
                <button id="edit-cancel-btn"
                    class="py-3.5 rounded-2xl border border-gray-200 text-gray-600 font-semibold text-sm">
                    Отмена
                </button>
                <button id="edit-save-btn"
                    class="py-3.5 rounded-2xl bg-indigo-600 text-white font-bold text-sm
                           active:opacity-80 transition-opacity">
                    Сохранить
                </button>
            </div>
        </div>`;
}

function openSheet(tx) {
    state.selectedTx = tx;
    state.editingTx  = false;
    render();
}

function closeSheet() {
    state.selectedTx = null;
    state.editingTx  = false;
    render();
}

function attachSheetHandlers() {
    document.getElementById('sheet-overlay')?.addEventListener('click', closeSheet);

    // Кнопка «Редактировать»
    document.getElementById('sheet-edit-btn')?.addEventListener('click', () => {
        state.editingTx = true;
        render();
    });

    // Кнопка «Удалить» — с подтверждением через Telegram API или браузерный confirm
    document.getElementById('sheet-delete-btn')?.addEventListener('click', async () => {
        const tx = state.selectedTx;
        if (!tx) return;

        const confirmed = await new Promise(resolve => {
            if (tg?.showConfirm) {
                tg.showConfirm(`Удалить трату ${fmt(tx.amount)}?`, resolve);
            } else {
                resolve(window.confirm(`Удалить трату ${fmt(tx.amount)}?`));
            }
        });

        if (!confirmed) return;

        try {
            await api('DELETE', `/transactions/${tx.id}`);
            state.transactions = state.transactions.filter(t => t.id !== tx.id);
            closeSheet();
        } catch (e) {
            if (tg?.showAlert) tg.showAlert(`Ошибка: ${e.message}`);
            else alert(`Ошибка: ${e.message}`);
        }
    });

    // Если открыто редактирование — прикрепляем его обработчики
    if (state.editingTx) attachEditHandlers();
}

function attachEditHandlers() {
    let editCat = state.selectedTx?.category || 'other';

    // Выбор категории в форме редактирования
    document.querySelectorAll('.edit-cat-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.edit-cat-btn').forEach(b => b.classList.remove('selected'));
            btn.classList.add('selected');
            editCat = btn.dataset.cat;
        });
    });

    // Отмена редактирования
    document.getElementById('edit-cancel-btn')?.addEventListener('click', () => {
        state.editingTx = false;
        render();
    });

    // Сохранение изменений
    document.getElementById('edit-save-btn')?.addEventListener('click', async () => {
        const amount = parseFloat(document.getElementById('edit-amount')?.value || '0');
        const desc   = document.getElementById('edit-desc')?.value?.trim() || '';

        if (!amount || amount <= 0) {
            if (tg?.showAlert) tg.showAlert('Введи сумму больше нуля');
            else alert('Введи сумму больше нуля');
            return;
        }

        const btn = document.getElementById('edit-save-btn');
        if (btn) { btn.disabled = true; btn.textContent = 'Сохраняю...'; }

        try {
            const updated = await api('PATCH', `/transactions/${state.selectedTx.id}`, {
                amount,
                category:    editCat,
                description: desc,
            });
            // Обновляем транзакцию в локальном state
            const idx = state.transactions.findIndex(t => t.id === updated.id);
            if (idx >= 0) state.transactions[idx] = { ...state.transactions[idx], ...updated };
            state.selectedTx = null;
            state.editingTx  = false;
            render();
        } catch (e) {
            if (tg?.showAlert) tg.showAlert(`Ошибка: ${e.message}`);
            else alert(`Ошибка: ${e.message}`);
            if (btn) { btn.disabled = false; btn.textContent = 'Сохранить'; }
        }
    });
}

// ============================================================
// ЗАПУСК ПРИЛОЖЕНИЯ
// ============================================================
init();
