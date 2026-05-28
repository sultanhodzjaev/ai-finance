// ============================================================
// AI-Финансист — Telegram Mini App
// Версия 2.0: учёт доходов и расходов
// ============================================================

const tg = window.Telegram?.WebApp;


// ----- Навигация: history stack + Telegram BackButton -----
// goTo(screen) — push текущий в стек, переход на новый экран.
// goTo(screen, {push:false}) — переход без push (для клика по navbar — стек чистится).
// goBack() — pop из стека (или dashboard, если стек пустой).
function goTo(screen, opts) {
    if (!state.screenStack) state.screenStack = [];
    const push = opts?.push !== false;
    if (push && state.screen && state.screen !== screen) {
        state.screenStack.push(state.screen);
    } else if (!push) {
        state.screenStack = [];
    }
    state.screen = screen;
    render();
}

function goBack() {
    if (!state.screenStack) state.screenStack = [];
    const prev = state.screenStack.pop();
    state.screen = prev || 'dashboard';
    render();
}

let _backHandlerBound = false;
function syncBackButton() {
    const bb = tg?.BackButton;
    if (!bb) return;
    if (!_backHandlerBound) {
        bb.onClick(() => goBack());
        _backHandlerBound = true;
    }
    if ((state.screenStack || []).length > 0) bb.show();
    else bb.hide();
}

if (tg) {
    tg.ready();
    tg.expand();
    document.documentElement.style.setProperty('--bg-color',   tg.themeParams?.bg_color   || '#f9fafb');
    document.documentElement.style.setProperty('--text-color', tg.themeParams?.text_color || '#1f2937');
}

// ============================================================
// КОНСТАНТЫ
// ============================================================
const EXPENSE_COLORS = {
    food: '#FF6B6B', groceries: '#4ECDC4', transport: '#45B7D1',
    entertainment: '#F7DC6F', health: '#82E0AA', clothes: '#BB8FCE',
    home: '#F0B27A', communication: '#85C1E9', gifts: '#F1948A', other: '#BDC3C7',
};
const INCOME_COLORS = {
    salary: '#22c55e', freelance: '#16a34a', business: '#15803d',
    investment: '#4ade80', gift_income: '#86efac', other_income: '#bbf7d0',
};

function catColor(id) {
    return EXPENSE_COLORS[id] || INCOME_COLORS[id] || '#BDC3C7';
}

// ============================================================
// СОСТОЯНИЕ
// ============================================================
const state = {
    screen:           'dashboard',         // 'dashboard'|'history'|'add'|'plan'|'upgrade'
    me:               null,
    expenseCategories: [],
    incomeCategories:  [],
    transactions:      [],
    plan:              null,                // данные от /miniapp/api/plan
    periodFilter:     'month',   // 'day'|'week'|'month'|'all'
    typeFilter:       'all',     // 'all'|'income'|'expense'
    selectedTx:       null,
    editingTx:        false,
    addType:          'expense', // тип в форме добавления
    charts:           {},
    // --- дашборд ---
    dashboardPeriod:  'month',   // 'day'|'week'|'month'|'year'|'custom'
    dashboardRange:   null,      // { from: 'YYYY-MM-DD', to: 'YYYY-MM-DD' } для custom
    rangePickerOpen:  false,
    // Стек экранов для кнопки «Назад» (Telegram BackButton).
    screenStack:      [],
};

// ============================================================
// API
// ============================================================
async function api(method, path, body = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json', 'X-Init-Data': tg?.initData || '' },
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
function fmt(amount) {
    return `${Math.round(Math.abs(amount)).toLocaleString('ru-RU')} ${state.me?.currency || 'KGS'}`;
}
function fmtSigned(amount, type) {
    const sign = type === 'income' ? '+' : '−';
    return `${sign}${fmt(amount)}`;
}
function fmtDate(iso) {
    const d = new Date(iso);
    const months = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
    return `${d.getDate()} ${months[d.getMonth()]}, ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
}

// Ищет категорию в обоих списках
function getCat(id) {
    return (
        state.expenseCategories.find(c => c.id === id) ||
        state.incomeCategories.find(c => c.id === id) ||
        { id, name: id, emoji: '📦', icon: 'package' }
    );
}

// Фильтрует по периоду (используется и в истории, и в дашборде)
function filterByPeriod(txs, f, range = null) {
    if (f === 'custom' && range?.from && range?.to) {
        const from = new Date(range.from + 'T00:00:00');
        const to   = new Date(range.to   + 'T23:59:59');
        return txs.filter(tx => {
            const d = new Date(tx.datetime);
            return d >= from && d <= to;
        });
    }
    const now = new Date();
    return txs.filter(tx => {
        const d = new Date(tx.datetime);
        if (f === 'day')   return d.toDateString() === now.toDateString();
        if (f === 'week')  return d >= new Date(now - 7*24*60*60*1000);
        if (f === 'month') return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
        if (f === 'year')  return d.getFullYear() === now.getFullYear();
        return true;
    });
}

// Транзакции для дашборда — по выбранному там периоду
function filterDashboard(txs) {
    return filterByPeriod(txs, state.dashboardPeriod, state.dashboardRange);
}

const MONTH_NAMES = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
const MONTH_SHORT = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];

function dashboardTitle() {
    const now = new Date();
    const p   = state.dashboardPeriod;
    if (p === 'day')   return 'Сегодня';
    if (p === 'week')  return 'Неделя';
    if (p === 'month') return MONTH_NAMES[now.getMonth()];
    if (p === 'year')  return String(now.getFullYear());
    if (p === 'custom' && state.dashboardRange) {
        const f = new Date(state.dashboardRange.from + 'T00:00:00');
        const t = new Date(state.dashboardRange.to   + 'T00:00:00');
        return `${f.getDate()} ${MONTH_SHORT[f.getMonth()]} — ${t.getDate()} ${MONTH_SHORT[t.getMonth()]}`;
    }
    return 'Период';
}

// Streak — сколько дней подряд (от сегодня или вчера) есть записи.
// Логика согласована с utils/streak.py: если сегодня запись была — стартуем от
// сегодня; иначе пытаемся стартовать от вчера, чтобы юзер не терял прогресс до
// конца дня. Дни без транзакций любого источника обрывают streak.
function computeStreakDays(transactions) {
    if (!transactions || !transactions.length) return 0;
    const oneDay = 86400000;
    const today = new Date(); today.setHours(0,0,0,0);
    const txDays = new Set();
    for (const t of transactions) {
        const d = new Date(t.datetime);
        if (isNaN(d.getTime())) continue;
        d.setHours(0,0,0,0);
        txDays.add(d.getTime());
    }
    const todayMs = today.getTime();
    let cur;
    if (txDays.has(todayMs)) cur = todayMs;
    else if (txDays.has(todayMs - oneDay)) cur = todayMs - oneDay;
    else return 0;
    let streak = 0;
    while (txDays.has(cur)) { streak++; cur -= oneDay; }
    return streak;
}

function streakWord(n) {
    if (n === 1) return 'день';
    if (n >= 2 && n <= 4) return 'дня';
    return 'дней';
}


// Подпись под Остатком в hero-карточке. Прячемся от banal-копирайта:
// если есть доход — показываем savings rate, иначе нейтральное сообщение.
function heroSubline(totalIncome, balance, balancePct) {
    if (!balancePct) return 'Расходы превышают доходы';
    if (totalIncome > 0 && balance > 0) {
        const savings = Math.round(balance / totalIncome * 100);
        if (savings >= 5) return `Сохранил ${savings}% от дохода`;
    }
    if (balance > 0) return 'В плюсе';
    return 'Баланс на нуле';
}

function dashboardBalanceLabel() {
    const p = state.dashboardPeriod;
    if (p === 'day')    return 'Остаток за день';
    if (p === 'week')   return 'Остаток за неделю';
    if (p === 'month')  return 'Остаток за месяц';
    if (p === 'year')   return 'Остаток за год';
    return 'Остаток за период';
}

function toIsoDate(d) {
    const y = d.getFullYear(), m = String(d.getMonth()+1).padStart(2,'0'), day = String(d.getDate()).padStart(2,'0');
    return `${y}-${m}-${day}`;
}

// Backward-compat: транзакции без type — расходы
function txType(tx) { return tx.type || 'expense'; }

function pluralTx(n) {
    if (n % 10 === 1 && n % 100 !== 11) return 'транзакция';
    if ([2,3,4].includes(n%10) && ![12,13,14].includes(n%100)) return 'транзакции';
    return 'транзакций';
}

function destroyChart(key) {
    if (state.charts[key]) { state.charts[key].destroy(); delete state.charts[key]; }
}

// ============================================================
// ИНИЦИАЛИЗАЦИЯ
// ============================================================
// Тема: dark если у <html> класс .dark (выставляется в index.html до рендера).
function isDark() { return document.documentElement.classList.contains('dark'); }
function chartTextColor()    { return isDark() ? '#a1a1aa' : '#71717a'; }
function chartGridColor()    { return isDark() ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)'; }
function chartSurfaceColor() { return isDark() ? '#18181b' : '#ffffff'; }

// Lucide-иконки рендерятся через <i data-lucide="имя">. Helper-удобство.
function icon(name, cls = 'w-5 h-5') {
    return `<i data-lucide="${name}" class="${cls}"></i>`;
}

// Жетон категории: круглый «пилл» с цветным фоном (≈14% opacity) и Lucide-иконкой
// цвета категории. Для кастомных категорий (без icon) — fallback на emoji.
// size — диаметр в px (default 36), iconPx — размер иконки (default 18).
function catBadge(cat, size = 36, iconPx = 18) {
    const color = catColor(cat.id);
    const style = `width:${size}px;height:${size}px;background:${color}22;color:${color};flex-shrink:0`;
    const inner = cat.icon
        ? `<i data-lucide="${cat.icon}" style="width:${iconPx}px;height:${iconPx}px;stroke-width:2"></i>`
        : `<span style="font-size:${Math.round(iconPx * 1.1)}px;line-height:1">${cat.emoji || '📦'}</span>`;
    return `<span class="inline-flex items-center justify-center rounded-full" style="${style}">${inner}</span>`;
}

function showApp(html) {
    const loader = document.getElementById('static-loader');
    const app    = document.getElementById('app');
    if (loader) loader.style.display = 'none';
    if (app)    { app.style.display = 'block'; app.innerHTML = html; }
    // Сканируем DOM и подменяем <i data-lucide=...> на SVG.
    // stroke-width 1.5 — тоньше дефолтных 2, ощущение премиум-iconography.
    if (window.lucide?.createIcons) {
        window.lucide.createIcons({ attrs: { 'stroke-width': 1.5 } });
    }
}

async function init() {
    try {
        const [me, catsR, txsR, planR] = await Promise.all([
            api('GET', '/me'),
            api('GET', '/categories'),
            api('GET', '/transactions'),
            api('GET', '/plan').catch(() => null),  // тариф необязателен — старые версии бэка не имеют
        ]);
        state.me = me;
        state.expenseCategories = catsR.expense_categories;
        state.incomeCategories  = catsR.income_categories;
        state.transactions = txsR.transactions;
        state.plan = planR;
        render();
    } catch {
        showApp(`
            <div class="flex flex-col items-center justify-center min-h-screen p-8 text-center gap-4">
                <div class="text-6xl">🤖</div>
                <p class="font-semibold text-gray-800 text-lg">Нет доступа</p>
                <p class="text-sm text-gray-500 max-w-xs">Открой приложение через кнопку <strong>«📲 Открыть приложение»</strong> в боте Telegram</p>
            </div>`);
    }
}

// ============================================================
// РЕНДЕР
// ============================================================
function render() {
    ['donut-expense','donut-income','line-chart'].forEach(k => destroyChart(k));
    showApp(`
        <div class="pb-24 min-h-screen screen-enter">
            ${state.screen === 'dashboard' ? buildDashboard() : ''}
            ${state.screen === 'history'   ? buildHistory()   : ''}
            ${state.screen === 'add'       ? buildAdd()       : ''}
            ${state.screen === 'plan'      ? buildPlan()      : ''}
            ${state.screen === 'upgrade'   ? buildUpgrade()   : ''}
            ${state.screen === 'settings'  ? buildSettings()  : ''}
            ${state.screen === 'invite'    ? buildInvite()    : ''}
            ${state.screen === 'help'      ? buildHelp()      : ''}
            ${state.screen === 'categories'? buildCategories(): ''}
            ${state.screen === 'recurring' ? buildRecurring() : ''}
        </div>
        ${buildNav()}
        ${buildBottomSheet()}
        ${state.rangePickerOpen ? buildRangePicker() : ''}
        ${buildCurrencyPicker()}`);
    attachNavHandlers();
    if (state.screen === 'dashboard') {
        renderCharts();
        document.getElementById('open-upgrade-from-dash')?.addEventListener('click', () => {
            goTo('plan');
        });
        attachDashboardPeriodHandlers();
        if (state.rangePickerOpen) attachRangePickerHandlers();
    }
    if (state.screen === 'history')   attachHistoryHandlers();
    if (state.screen === 'add')       attachAddHandlers();
    if (state.screen === 'plan')      attachPlanHandlers();
    if (state.screen === 'upgrade')   attachUpgradeHandlers();
    if (state.screen === 'settings')  attachSettingsHandlers();
    if (state.screen === 'invite')    attachInviteHandlers();
    if (state.screen === 'help')      attachHelpHandlers();
    if (state.screen === 'categories'){ attachCategoriesHandlers(); if (state.catFormOpen) attachCategoryFormHandlers(); }
    if (state.screen === 'recurring') { attachRecurringHandlers();  if (state.recFormOpen) attachRecurringFormHandlers(); }
    if (state.currencyPickerOpen)     attachCurrencyPickerHandlers();
    if (state.selectedTx)             attachSheetHandlers();
    syncBackButton();
}

// ============================================================
// НАВИГАЦИЯ
// ============================================================
function buildNav() {
    const d = state.screen === 'dashboard',
          h = state.screen === 'history',
          p = state.screen === 'plan' || state.screen === 'upgrade';
    const s = ['settings','invite','help','categories','recurring'].includes(state.screen);
    // 5-колоночная raскладка: 2 кнопки слева, FAB в центре (3-й колонке), 2 справа.
    // grid grid-cols-5 даёт идеальное симметричное распределение — каждая колонка
    // ровно 20% ширины, центр nav совпадает с центром col 3 (где FAB).
    return `
        <nav class="fixed bottom-0 left-0 right-0 bg-white/95 backdrop-blur-md border-t border-gray-100
                    grid grid-cols-5 items-center px-1 py-1 z-40 shadow-lg"
             style="padding-bottom:max(env(safe-area-inset-bottom),4px)">
            <button class="nav-btn flex flex-col items-center gap-0.5 py-2 rounded-xl
                           ${d ? 'text-indigo-600' : 'text-gray-400'}" data-screen="dashboard">
                ${icon('layout-dashboard', 'w-6 h-6')}<span class="text-xs font-medium mt-0.5">Дашборд</span>
            </button>
            <button class="nav-btn flex flex-col items-center gap-0.5 py-2 rounded-xl
                           ${h ? 'text-indigo-600' : 'text-gray-400'}" data-screen="history">
                ${icon('clock', 'w-6 h-6')}<span class="text-xs font-medium mt-0.5">История</span>
            </button>
            <div aria-hidden="true"></div>
            <button class="nav-btn flex flex-col items-center gap-0.5 py-2 rounded-xl
                           ${p ? 'text-indigo-600' : 'text-gray-400'}" data-screen="plan">
                ${icon('crown', 'w-6 h-6')}<span class="text-xs font-medium mt-0.5">План</span>
            </button>
            <button class="nav-btn flex flex-col items-center gap-0.5 py-2 rounded-xl
                           ${s ? 'text-indigo-600' : 'text-gray-400'}" data-screen="settings">
                ${icon('settings', 'w-6 h-6')}<span class="text-xs font-medium mt-0.5">Настройки</span>
            </button>
            <button class="nav-btn fab-plus"
                    data-screen="add" aria-label="Добавить трату или доход">
                <span class="fab-plus-circle">
                    ${icon('plus', 'w-6 h-6')}
                </span>
            </button>
        </nav>`;
}

function attachNavHandlers() {
    document.querySelectorAll('.nav-btn').forEach(btn =>
        btn.addEventListener('click', () => {
            const target = btn.dataset.screen;
            if (target !== 'history') { state.periodFilter = 'month'; state.typeFilter = 'all'; }
            state.selectedTx = null; state.editingTx = false;
            // Клик по navbar — это корневая навигация, стек чистим.
            goTo(target, { push: false });
            return;
        })
    );
}

// ============================================================
// ЭКРАН 1: ДАШБОРД
// ============================================================
function buildDashboard() {
    const periodTxs = filterDashboard(state.transactions);
    const incomes  = periodTxs.filter(t => txType(t) === 'income');
    const expenses = periodTxs.filter(t => txType(t) === 'expense');
    const totalIncome  = incomes.reduce((s,t) => s+t.amount, 0);
    const totalExpense = expenses.reduce((s,t) => s+t.amount, 0);
    const balance      = totalIncome - totalExpense;
    const balancePct   = balance >= 0;

    // Streak считаем по ВСЕМ транзакциям (не зависит от выбранного периода).
    const streak = computeStreakDays(state.transactions);
    const todayLogged = (() => {
        const today = new Date(); today.setHours(0,0,0,0);
        return state.transactions.some(t => {
            const d = new Date(t.datetime); if (isNaN(d.getTime())) return false;
            d.setHours(0,0,0,0);
            return d.getTime() === today.getTime();
        });
    })();

    // Топ-3 расходов
    const byCat = {};
    expenses.forEach(t => { byCat[t.category] = (byCat[t.category]||0) + t.amount; });
    const top3 = Object.entries(byCat).sort((a,b)=>b[1]-a[1]).slice(0,3);

    const periodOpts = [
        {key:'day',    label:'День'},
        {key:'week',   label:'Неделя'},
        {key:'month',  label:'Месяц'},
        {key:'year',   label:'Год'},
        {key:'custom', label:'Период'},
    ];

    return `
        <div class="px-4 pt-5">
            <div class="flex items-start justify-between mb-5">
                <div>
                    <p class="eyebrow mb-1">Привет, ${state.me?.first_name||'Друг'}</p>
                    <h1 class="h-display">${dashboardTitle()}</h1>
                    ${streak > 0 ? `
                        <div class="inline-flex items-center gap-1.5 mt-2 px-2.5 py-1 rounded-full text-[12px] font-semibold"
                             style="background:rgba(249,115,22,0.12);color:#ea580c"
                             title="${todayLogged ? 'Так держать!' : 'Запиши сегодня, чтобы не потерять стрик'}">
                            🔥 ${streak} ${streakWord(streak)} подряд
                            ${!todayLogged ? '<span style="opacity:.7">· сегодня ещё нет</span>' : ''}
                        </div>` : ''}
                </div>
                <div class="w-10 h-10 rounded-full flex items-center justify-center"
                     style="background:var(--accent-soft);color:var(--accent)">
                    ${icon('wallet', 'w-5 h-5')}
                </div>
            </div>

            <!-- Переключатель периода -->
            <div class="flex gap-2 mb-5 overflow-x-auto pb-1 -mx-1 px-1">
                ${periodOpts.map(f=>`
                    <button class="dash-period-btn flex-shrink-0 px-4 py-1.5 rounded-full text-xs font-semibold border tracking-wide
                        ${state.dashboardPeriod===f.key
                            ? 'text-white'
                            : 'bg-white text-gray-600 border-gray-200'}"
                        ${state.dashboardPeriod===f.key
                            ? 'style="background:var(--accent);border-color:var(--accent)"'
                            : ''}
                        data-period="${f.key}">${f.label}</button>
                `).join('')}
            </div>

            <!-- HERO: Остаток — главная карточка -->
            <div class="rounded-3xl p-6 text-white relative overflow-hidden mb-3"
                 style="background:${balancePct
                    ? 'radial-gradient(120% 100% at 0% 0%, #8b5cf6 0%, #6d28d9 45%, #4c1d95 100%)'
                    : 'radial-gradient(120% 100% at 0% 0%, #fb7185 0%, #be123c 60%, #881337 100%)'}">
                <div class="absolute -top-16 -right-10 w-52 h-52 rounded-full" style="background:rgba(255,255,255,0.06);filter:blur(2px)"></div>
                <div class="absolute -bottom-20 -left-8 w-48 h-48 rounded-full" style="background:rgba(255,255,255,0.04);filter:blur(2px)"></div>
                <div class="relative">
                    <p class="eyebrow mb-2" style="color:rgba(255,255,255,0.55)">${dashboardBalanceLabel()}</p>
                    <p class="hero-amount">${balancePct ? '+' : '−'}${fmt(balance)}</p>
                    <p class="text-white/65 text-[13px] mt-3">${heroSubline(totalIncome, balance, balancePct)}</p>
                </div>
            </div>

            <!-- Secondary stats: Доход / Расход — пилюлями -->
            <div class="grid grid-cols-2 gap-3 mb-5">
                <div class="rounded-2xl p-4 relative overflow-hidden"
                     style="background:var(--surface);border:1px solid var(--border)">
                    <div class="flex items-center gap-1.5 mb-2">
                        <span class="w-1.5 h-1.5 rounded-full" style="background:var(--positive)"></span>
                        <p class="eyebrow" style="letter-spacing:0.1em">Доход</p>
                    </div>
                    <p class="stat-amount" style="color:var(--text)">${fmt(totalIncome)}</p>
                    <p class="text-[11px] mt-1.5" style="color:var(--text-faint)">${incomes.length} ${pluralTx(incomes.length)}</p>
                </div>
                <div class="rounded-2xl p-4 relative overflow-hidden"
                     style="background:var(--surface);border:1px solid var(--border)">
                    <div class="flex items-center gap-1.5 mb-2">
                        <span class="w-1.5 h-1.5 rounded-full" style="background:var(--negative)"></span>
                        <p class="eyebrow" style="letter-spacing:0.1em">Расход</p>
                    </div>
                    <p class="stat-amount" style="color:var(--text)">${fmt(totalExpense)}</p>
                    <p class="text-[11px] mt-1.5" style="color:var(--text-faint)">${expenses.length} ${pluralTx(expenses.length)}</p>
                </div>
            </div>

            ${state.plan?.limits?.mini_app_analytics === 'basic' ? `
                <div class="bg-white rounded-2xl p-4 shadow-sm mb-4 border border-gray-100">
                    <p class="text-sm text-gray-500">
                        ${icon('lock', 'inline w-4 h-4 mr-1 text-gray-400')}
                        Полная аналитика — графики по категориям и дням, экспорт CSV —
                        доступны на Premium. <span class="text-indigo-600 cursor-pointer" id="open-upgrade-from-dash">Открыть план →</span>
                    </p>
                </div>
            ` : ''}

            ${periodTxs.length === 0 ? `
                <div class="bg-white rounded-2xl p-8 text-center shadow-sm">
                    <div class="text-4xl mb-3">🎉</div>
                    <p class="font-semibold text-gray-700">За этот период операций нет</p>
                    <p class="text-sm text-gray-400 mt-1">Запиши операцию через бота или «+», либо смени период выше</p>
                </div>
            ` : `
                ${state.plan?.limits?.mini_app_analytics === 'basic' ? '' : `
                <!-- Расходы по категориям -->
                <div class="bg-white rounded-2xl p-4 shadow-sm mb-4">
                    <h2 class="font-semibold text-gray-700 mb-3 text-sm flex items-center gap-2">
                        ${icon('trending-down', 'w-4 h-4 text-red-500')} Расходы по категориям
                    </h2>
                    ${expenses.length === 0 ? `<p class="text-gray-400 text-sm text-center py-4">Расходов нет</p>` : `
                        <div class="relative" style="height:200px"><canvas id="donut-expense"></canvas></div>
                        <div class="mt-4 space-y-2 pt-3 border-t border-gray-100">
                            ${top3.map(([id,sum]) => {
                                const cat = getCat(id);
                                const pct = totalExpense > 0 ? Math.round(sum/totalExpense*100) : 0;
                                return `<div class="flex items-center justify-between">
                                    <div class="flex items-center gap-2.5">
                                        ${catBadge(cat, 28, 15)}
                                        <span class="text-sm text-gray-800">${cat.name}</span>
                                        <span class="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded-full">${pct}%</span>
                                    </div>
                                    <span class="font-semibold text-sm text-gray-900 tabular-nums">${fmt(sum)}</span>
                                </div>`;
                            }).join('')}
                        </div>
                    `}
                </div>

                <!-- Доходы по категориям -->
                <div class="bg-white rounded-2xl p-4 shadow-sm mb-4">
                    <h2 class="font-semibold text-gray-700 mb-3 text-sm flex items-center gap-2">
                        ${icon('trending-up', 'w-4 h-4 text-green-500')} Доходы по категориям
                    </h2>
                    ${incomes.length === 0 ? `
                        <p class="text-gray-400 text-sm text-center py-4">
                            Доходов нет. Запиши свой первый доход через бота.
                        </p>
                    ` : `<div class="relative" style="height:180px"><canvas id="donut-income"></canvas></div>`}
                </div>

                <!-- Линейный график по дням (две линии) -->
                <div class="bg-white rounded-2xl p-4 shadow-sm mb-4">
                    <h2 class="font-semibold text-gray-700 mb-3 text-sm flex items-center gap-2">
                        ${icon('calendar-range', 'w-4 h-4 text-indigo-500')} Динамика по дням
                    </h2>
                    <div class="relative" style="height:160px"><canvas id="line-chart"></canvas></div>
                </div>
                `}
            `}
        </div>`;
}

function renderCharts() {
    const periodTxs = filterDashboard(state.transactions);
    const incomes  = periodTxs.filter(t => txType(t) === 'income');
    const expenses = periodTxs.filter(t => txType(t) === 'expense');

    const surface = chartSurfaceColor();
    const txt     = chartTextColor();

    // --- Донат расходов ---
    if (expenses.length > 0) {
        const byCat = {};
        expenses.forEach(t => { byCat[t.category] = (byCat[t.category]||0) + t.amount; });
        const entries = Object.entries(byCat).sort((a,b)=>b[1]-a[1]);
        const el = document.getElementById('donut-expense');
        if (el) {
            state.charts['donut-expense'] = new Chart(el, {
                type: 'doughnut',
                data: {
                    labels:   entries.map(([id]) => getCat(id).name),
                    datasets: [{ data: entries.map(([,v])=>v), backgroundColor: entries.map(([id])=>EXPENSE_COLORS[id]||'#ccc'), borderWidth:2, borderColor:surface }],
                },
                options: { responsive:true, maintainAspectRatio:false, cutout:'68%',
                    plugins: { legend:{position:'right',labels:{font:{size:11},boxWidth:12,padding:8,color:txt}},
                        tooltip:{callbacks:{label:ctx=>` ${fmt(ctx.raw)}`}} } },
            });
        }
    }

    // --- Донат доходов ---
    if (incomes.length > 0) {
        const byCat = {};
        incomes.forEach(t => { byCat[t.category] = (byCat[t.category]||0) + t.amount; });
        const entries = Object.entries(byCat).sort((a,b)=>b[1]-a[1]);
        const el = document.getElementById('donut-income');
        if (el) {
            state.charts['donut-income'] = new Chart(el, {
                type: 'doughnut',
                data: {
                    labels:   entries.map(([id]) => getCat(id).name),
                    datasets: [{ data: entries.map(([,v])=>v), backgroundColor: entries.map(([id])=>INCOME_COLORS[id]||'#22c55e'), borderWidth:2, borderColor:surface }],
                },
                options: { responsive:true, maintainAspectRatio:false, cutout:'68%',
                    plugins: { legend:{position:'right',labels:{font:{size:11},boxWidth:12,padding:8,color:txt}},
                        tooltip:{callbacks:{label:ctx=>` +${fmt(ctx.raw)}`}} } },
            });
        }
    }

    // --- Двойной линейный график (по дням или по месяцам — в зависимости от периода) ---
    const buckets = buildTimeBuckets();
    const expByBucket = {}, incByBucket = {};
    expenses.forEach(t => { const k = bucketKey(t.datetime); expByBucket[k] = (expByBucket[k]||0) + t.amount; });
    incomes.forEach(t  => { const k = bucketKey(t.datetime); incByBucket[k] = (incByBucket[k]||0) + t.amount; });

    const el = document.getElementById('line-chart');
    if (el) {
        state.charts['line-chart'] = new Chart(el, {
            type: 'line',
            data: {
                labels: buckets.map(b => b.label),
                datasets: [
                    { label:'Расходы', data: buckets.map(b => expByBucket[b.key]||0), borderColor:'#ef4444', backgroundColor:'rgba(239,68,68,0.07)', fill:true, tension:0.4, pointRadius:2 },
                    { label:'Доходы',  data: buckets.map(b => incByBucket[b.key]||0), borderColor:'#22c55e', backgroundColor:'rgba(34,197,94,0.07)',  fill:true, tension:0.4, pointRadius:2 },
                ],
            },
            options: {
                responsive:true, maintainAspectRatio:false,
                plugins:{ legend:{ labels:{font:{size:10},boxWidth:12,color:txt} } },
                scales:{
                    x:{ grid:{display:false}, ticks:{font:{size:9},maxTicksLimit:12,color:txt} },
                    y:{ beginAtZero:true, grid:{color:chartGridColor()}, ticks:{font:{size:9},color:txt,callback:v=>v>=1000?`${(v/1000).toFixed(0)}к`:v} },
                },
            },
        });
    }
}

// Группировка для линейного графика дашборда: day=по часам, week/month=по дням, year=по месяцам,
// custom=по дням если ≤ 31 день, иначе по месяцам.
function bucketGranularity() {
    const p = state.dashboardPeriod;
    if (p === 'year')   return 'month';
    if (p === 'day')    return 'hour';
    if (p === 'custom' && state.dashboardRange) {
        const from = new Date(state.dashboardRange.from + 'T00:00:00');
        const to   = new Date(state.dashboardRange.to   + 'T00:00:00');
        const days = Math.round((to - from) / 86400000) + 1;
        return days > 31 ? 'month' : 'day';
    }
    return 'day';
}

function bucketKey(iso) {
    const d = new Date(iso);
    const g = bucketGranularity();
    if (g === 'hour')  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}-${d.getHours()}`;
    if (g === 'month') return `${d.getFullYear()}-${d.getMonth()}`;
    return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function buildTimeBuckets() {
    const g    = bucketGranularity();
    const now  = new Date();
    const p    = state.dashboardPeriod;
    const out  = [];

    if (g === 'hour') {
        for (let h = 0; h < 24; h++) {
            out.push({ key: `${now.getFullYear()}-${now.getMonth()}-${now.getDate()}-${h}`, label: String(h).padStart(2,'0') });
        }
        return out;
    }

    if (g === 'month') {
        if (p === 'year') {
            for (let m = 0; m < 12; m++) {
                out.push({ key: `${now.getFullYear()}-${m}`, label: MONTH_SHORT[m] });
            }
            return out;
        }
        // custom long-range
        const from = new Date(state.dashboardRange.from + 'T00:00:00');
        const to   = new Date(state.dashboardRange.to   + 'T00:00:00');
        const cur  = new Date(from.getFullYear(), from.getMonth(), 1);
        while (cur <= to) {
            out.push({ key: `${cur.getFullYear()}-${cur.getMonth()}`, label: `${MONTH_SHORT[cur.getMonth()]} ${String(cur.getFullYear()).slice(2)}` });
            cur.setMonth(cur.getMonth() + 1);
        }
        return out;
    }

    // дни
    let from, to;
    if (p === 'day') {
        from = new Date(now); from.setHours(0,0,0,0);
        to   = new Date(from);
    } else if (p === 'week') {
        to   = new Date(now); to.setHours(0,0,0,0);
        from = new Date(to);  from.setDate(from.getDate() - 6);
    } else if (p === 'month') {
        from = new Date(now.getFullYear(), now.getMonth(), 1);
        to   = new Date(now.getFullYear(), now.getMonth()+1, 0);
    } else if (p === 'custom' && state.dashboardRange) {
        from = new Date(state.dashboardRange.from + 'T00:00:00');
        to   = new Date(state.dashboardRange.to   + 'T00:00:00');
    } else {
        from = new Date(now); from.setDate(1);
        to   = new Date(now);
    }
    const cur = new Date(from);
    while (cur <= to) {
        out.push({ key: `${cur.getFullYear()}-${cur.getMonth()}-${cur.getDate()}`, label: String(cur.getDate()) });
        cur.setDate(cur.getDate() + 1);
    }
    return out;
}

// ============================================================
// ЭКРАН 2: ИСТОРИЯ
// ============================================================
function buildHistory() {
    let filtered = filterByPeriod(state.transactions, state.periodFilter);
    if (state.typeFilter !== 'all') {
        filtered = filtered.filter(t => txType(t) === state.typeFilter);
    }

    const periodOpts = [{key:'day',label:'День'},{key:'week',label:'Неделя'},{key:'month',label:'Месяц'},{key:'all',label:'Всё'}];
    const typeOpts   = [{key:'all',label:'Всё'},{key:'income',label:'💰 Доходы'},{key:'expense',label:'💸 Расходы'}];

    return `
        <div class="px-4 pt-5">
            <h1 class="text-2xl font-bold text-gray-900 mb-4">История</h1>

            <!-- Фильтр периода -->
            <div class="flex gap-2 mb-2 overflow-x-auto pb-1 -mx-1 px-1">
                ${periodOpts.map(f=>`
                    <button class="period-btn flex-shrink-0 px-4 py-1.5 rounded-full text-sm font-medium border
                        ${state.periodFilter===f.key ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white text-gray-600 border-gray-200'}"
                        data-period="${f.key}">${f.label}</button>
                `).join('')}
            </div>

            <!-- Фильтр типа -->
            <div class="flex gap-2 mb-4 overflow-x-auto pb-1 -mx-1 px-1">
                ${typeOpts.map(f=>`
                    <button class="type-btn flex-shrink-0 px-4 py-1.5 rounded-full text-sm font-medium border
                        ${state.typeFilter===f.key ? 'bg-gray-800 text-white border-gray-800' : 'bg-white text-gray-600 border-gray-200'}"
                        data-type="${f.key}">${f.label}</button>
                `).join('')}
            </div>

            <!-- Список -->
            ${filtered.length === 0 ? `
                <div class="text-center py-14">
                    <div class="text-5xl mb-3">📭</div>
                    <p class="text-gray-500 font-medium">Нет операций за этот период</p>
                </div>
            ` : `
                <div class="space-y-2">
                    ${filtered.map(tx => buildTxRow(tx)).join('')}
                </div>
            `}
        </div>`;
}

function buildTxRow(tx) {
    const cat     = getCat(tx.category);
    const isInc   = txType(tx) === 'income';
    const amtColor = isInc ? 'text-emerald-600' : 'text-gray-900';
    const signedAmt = `${isInc?'+':'−'}${fmt(tx.amount)}`;

    return `
        <div class="tx-row bg-white rounded-2xl px-4 py-3.5 flex items-center gap-3 shadow-sm cursor-pointer active:opacity-70"
             data-id="${tx.id}">
            ${catBadge(cat, 40, 19)}
            <div class="flex-1 min-w-0">
                <p class="font-medium text-gray-900 text-sm">${cat.name}</p>
                ${tx.description
                    ? `<p class="text-xs text-gray-400 truncate">${tx.description}</p>`
                    : `<p class="text-xs text-gray-400">${fmtDate(tx.datetime)}</p>`}
            </div>
            <div class="text-right flex-shrink-0">
                <p class="font-semibold text-sm ${amtColor} tabular-nums">${signedAmt}</p>
                ${tx.description?`<p class="text-xs text-gray-300">${fmtDate(tx.datetime)}</p>`:''}
            </div>
        </div>`;
}

function attachDashboardPeriodHandlers() {
    document.querySelectorAll('.dash-period-btn').forEach(btn =>
        btn.addEventListener('click', () => {
            const p = btn.dataset.period;
            if (p === 'custom') {
                // Открываем пикер: дефолт — текущий месяц, либо последний выбранный диапазон
                if (!state.dashboardRange) {
                    const now = new Date();
                    state.dashboardRange = {
                        from: toIsoDate(new Date(now.getFullYear(), now.getMonth(), 1)),
                        to:   toIsoDate(now),
                    };
                }
                state.rangePickerOpen = true;
            } else {
                state.dashboardPeriod = p;
            }
            render();
        })
    );
}

function buildRangePicker() {
    const r = state.dashboardRange || {};
    return `
        <div id="range-picker-backdrop"
             class="fixed inset-0 bg-black/40 z-50 flex items-end justify-center"
             style="padding-bottom:max(env(safe-area-inset-bottom),16px)">
            <div class="bg-white rounded-t-3xl w-full max-w-md p-5 shadow-2xl">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="font-semibold text-gray-900 text-lg">Произвольный период</h3>
                    <button id="range-cancel" class="text-gray-400 text-2xl leading-none">×</button>
                </div>
                <div class="grid grid-cols-2 gap-3 mb-4">
                    <label class="block">
                        <span class="text-xs text-gray-500 mb-1 block">С</span>
                        <input type="date" id="range-from" value="${r.from||''}"
                               class="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm">
                    </label>
                    <label class="block">
                        <span class="text-xs text-gray-500 mb-1 block">По</span>
                        <input type="date" id="range-to" value="${r.to||''}"
                               class="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm">
                    </label>
                </div>
                <button id="range-apply"
                    class="w-full bg-indigo-600 text-white font-semibold py-3 rounded-xl active:opacity-80">
                    Применить
                </button>
            </div>
        </div>`;
}

function attachRangePickerHandlers() {
    const close = () => { state.rangePickerOpen = false; render(); };
    document.getElementById('range-cancel')?.addEventListener('click', close);
    document.getElementById('range-picker-backdrop')?.addEventListener('click', e => {
        if (e.target.id === 'range-picker-backdrop') close();
    });
    document.getElementById('range-apply')?.addEventListener('click', () => {
        const from = document.getElementById('range-from')?.value;
        const to   = document.getElementById('range-to')?.value;
        if (!from || !to) { tg?.showAlert?.('Укажи обе даты'); return; }
        if (from > to)   { tg?.showAlert?.('«С» должно быть раньше «По»'); return; }
        state.dashboardRange  = { from, to };
        state.dashboardPeriod = 'custom';
        state.rangePickerOpen = false;
        render();
    });
}

function attachHistoryHandlers() {
    document.querySelectorAll('.period-btn').forEach(btn =>
        btn.addEventListener('click', () => { state.periodFilter = btn.dataset.period; render(); })
    );
    document.querySelectorAll('.type-btn').forEach(btn =>
        btn.addEventListener('click', () => { state.typeFilter = btn.dataset.type; render(); })
    );
    document.querySelectorAll('.tx-row').forEach(row =>
        row.addEventListener('click', () => {
            const tx = state.transactions.find(t => t.id === row.dataset.id);
            if (tx) openSheet(tx);
        })
    );
}

// ============================================================
// ЭКРАН 3: ДОБАВИТЬ ТРАТУ / ДОХОД
// ============================================================
let addSelectedCat = 'food';

function buildAdd() {
    const isIncome = state.addType === 'income';
    const cats     = isIncome ? state.incomeCategories : state.expenseCategories;
    const defCat   = cats[0]?.id || (isIncome ? 'salary' : 'food');
    addSelectedCat = defCat;

    const btnColor = isIncome
        ? 'bg-green-600 hover:bg-green-700'
        : 'bg-red-500 hover:bg-red-600';
    const title = isIncome ? 'Новый доход' : 'Новый расход';

    return `
        <div class="px-4 pt-5">
            <h1 class="text-2xl font-bold text-gray-900 mb-4">${title}</h1>

            <!-- Переключатель Расход / Доход -->
            <div class="flex bg-gray-100 rounded-2xl p-1 mb-5 gap-1">
                <button id="toggle-expense"
                    class="flex-1 py-2.5 rounded-xl text-sm font-semibold transition-all
                           ${!isIncome ? 'bg-white text-red-600 shadow' : 'text-gray-500'}">
                    💸 Расход
                </button>
                <button id="toggle-income"
                    class="flex-1 py-2.5 rounded-xl text-sm font-semibold transition-all
                           ${isIncome ? 'bg-white text-green-600 shadow' : 'text-gray-500'}">
                    💰 Доход
                </button>
            </div>

            <!-- Поле суммы -->
            <div class="bg-white rounded-2xl p-5 text-center shadow-sm mb-4">
                <p class="text-xs text-gray-400 mb-1 font-medium uppercase tracking-wide">Сумма</p>
                <input id="add-amount" type="number" inputmode="decimal" placeholder="0"
                    class="amount-input w-full text-center text-4xl font-bold text-gray-900
                           placeholder-gray-200 border-none outline-none bg-transparent">
                <p class="text-sm font-medium mt-2 ${isIncome ? 'text-green-500' : 'text-red-400'}">${state.me?.currency||'KGS'}</p>
            </div>

            <!-- Категории -->
            <div class="bg-white rounded-2xl p-4 shadow-sm mb-4">
                <p class="text-sm font-semibold text-gray-600 mb-3">Категория</p>
                <div class="grid grid-cols-5 gap-2" id="add-cat-grid">
                    ${cats.map((cat,i) => `
                        <button class="cat-btn ${i===0?'selected':''}" data-cat="${cat.id}">
                            <span class="cat-btn-icon">${catBadge(cat, 32, 16)}</span>
                            <span>${cat.name}</span>
                        </button>
                    `).join('')}
                </div>
            </div>

            <!-- Описание -->
            <div class="bg-white rounded-2xl p-4 shadow-sm mb-6">
                <p class="text-sm font-semibold text-gray-600 mb-2">Описание <span class="text-gray-400 font-normal text-xs ml-1">необязательно</span></p>
                <input id="add-desc" type="text" placeholder="${isIncome ? 'Аванс, проект, дивиденды...' : 'Кофе, такси, продукты...'}"
                    class="w-full outline-none text-gray-800 placeholder-gray-300 text-sm bg-transparent">
            </div>

            <!-- Кнопка -->
            <button id="add-save-btn"
                class="w-full ${btnColor} text-white font-bold py-4 rounded-2xl text-base shadow-lg active:opacity-80 transition-opacity">
                💾 Сохранить ${isIncome ? 'доход' : 'расход'}
            </button>
        </div>`;
}

function attachAddHandlers() {
    // Переключатель типа
    document.getElementById('toggle-expense')?.addEventListener('click', () => {
        state.addType = 'expense'; render();
    });
    document.getElementById('toggle-income')?.addEventListener('click', () => {
        state.addType = 'income'; render();
    });

    // Выбор категории
    document.querySelectorAll('#add-cat-grid .cat-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('#add-cat-grid .cat-btn').forEach(b => b.classList.remove('selected'));
            btn.classList.add('selected');
            addSelectedCat = btn.dataset.cat;
        });
    });

    // Сохранение
    document.getElementById('add-save-btn')?.addEventListener('click', async () => {
        const amount = parseFloat(document.getElementById('add-amount')?.value || '0');
        const desc   = document.getElementById('add-desc')?.value?.trim() || '';
        if (!amount || amount <= 0) {
            if (tg?.showAlert) tg.showAlert('Введи сумму больше нуля');
            else alert('Введи сумму больше нуля');
            return;
        }
        const btn = document.getElementById('add-save-btn');
        if (btn) { btn.disabled = true; btn.textContent = 'Сохраняю...'; }
        try {
            const tx = await api('POST', '/transactions', {
                type: state.addType, amount, category: addSelectedCat, description: desc,
            });
            state.transactions.unshift(tx);
            state.typeFilter = state.addType; // сразу показываем нужный фильтр
            goTo('history', { push: false });
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
    if (!state.selectedTx) return '<div></div>';
    const tx  = state.selectedTx;
    const cat = getCat(tx.category);
    const isInc = txType(tx) === 'income';
    const sourceLabel = {text:'✍️ Текст',photo:'📷 Фото',miniapp:'📲 Mini App'};

    return `
        <div id="bottom-sheet" class="fixed inset-0 z-50 flex flex-col justify-end">
            <div id="sheet-overlay" class="absolute inset-0 bg-black/40 backdrop-blur-sm"></div>
            <div class="relative bg-white rounded-t-3xl shadow-2xl max-h-[88vh] overflow-y-auto sheet-slide-up">
                <div class="flex justify-center pt-3 pb-1">
                    <div class="w-10 h-1 bg-gray-200 rounded-full"></div>
                </div>
                <div class="px-6 pb-8">
                    ${state.editingTx ? buildEditForm(tx) : buildSheetView(tx, cat, isInc, sourceLabel)}
                </div>
            </div>
        </div>`;
}

function buildSheetView(tx, cat, isInc, sourceLabel) {
    const amtColor = isInc ? 'text-emerald-600' : 'text-gray-900';
    const signedAmt = `${isInc?'+':'−'}${fmt(tx.amount)}`;
    const typeBadge = isInc
        ? `<span class="bg-emerald-50 text-emerald-700 text-xs font-semibold px-2 py-0.5 rounded-full">Доход</span>`
        : `<span class="bg-rose-50 text-rose-600 text-xs font-semibold px-2 py-0.5 rounded-full">Расход</span>`;

    return `
        <div class="text-center py-4">
            <div class="mx-auto mb-3 flex items-center justify-center">${catBadge(cat, 64, 30)}</div>
            <p class="text-3xl font-bold ${amtColor} tabular-nums">${signedAmt}</p>
            <div class="flex items-center justify-center gap-2 mt-2">
                <p class="text-gray-500">${cat.name}</p>
                ${typeBadge}
            </div>
        </div>
        <div class="space-y-3 py-4 border-t border-b border-gray-100 mb-5">
            ${tx.description?`<div class="flex justify-between items-start gap-4">
                <span class="text-gray-400 text-sm flex-shrink-0">Описание</span>
                <span class="text-gray-800 text-sm font-medium text-right">${tx.description}</span></div>`:''}
            <div class="flex justify-between">
                <span class="text-gray-400 text-sm">Дата и время</span>
                <span class="text-gray-800 text-sm font-medium">${fmtDate(tx.datetime)}</span>
            </div>
            <div class="flex justify-between">
                <span class="text-gray-400 text-sm">Источник</span>
                <span class="text-gray-800 text-sm font-medium">${sourceLabel[tx.source]||tx.source}</span>
            </div>
            ${tx.merchant?`<div class="flex justify-between">
                <span class="text-gray-400 text-sm">Магазин</span>
                <span class="text-gray-800 text-sm font-medium">${tx.merchant}</span></div>`:''}
        </div>
        <div class="grid grid-cols-2 gap-3">
            <button id="sheet-edit-btn" class="py-3.5 rounded-2xl border border-gray-200 text-gray-700 font-semibold text-sm active:opacity-70">✏️ Редактировать</button>
            <button id="sheet-delete-btn" class="py-3.5 rounded-2xl bg-red-50 text-red-500 font-semibold text-sm active:opacity-70 border border-red-100">🗑 Удалить</button>
        </div>`;
}

function buildEditForm(tx) {
    const isInc = txType(tx) === 'income';
    const cats  = isInc ? state.incomeCategories : state.expenseCategories;

    return `
        <div class="pt-2">
            <h3 class="text-lg font-bold text-gray-900 mb-5">Редактировать</h3>
            <div class="mb-4">
                <p class="text-sm text-gray-500 mb-1.5 font-medium">Сумма</p>
                <input id="edit-amount" type="number" inputmode="decimal" value="${tx.amount}"
                    class="w-full border border-gray-200 rounded-xl px-4 py-3 text-xl font-bold outline-none focus:border-indigo-400">
            </div>
            <div class="mb-4">
                <p class="text-sm text-gray-500 mb-2 font-medium">Категория</p>
                <div class="grid grid-cols-5 gap-2" id="edit-cat-grid">
                    ${cats.map(cat=>`
                        <button class="edit-cat-btn cat-btn ${cat.id===tx.category?'selected':''}" data-cat="${cat.id}">
                            <span class="cat-btn-icon">${catBadge(cat, 32, 16)}</span><span>${cat.name}</span>
                        </button>`).join('')}
                </div>
            </div>
            <div class="mb-5">
                <p class="text-sm text-gray-500 mb-1.5 font-medium">Описание</p>
                <input id="edit-desc" type="text" value="${tx.description||''}"
                    class="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm outline-none focus:border-indigo-400">
            </div>
            <div class="grid grid-cols-2 gap-3">
                <button id="edit-cancel-btn" class="py-3.5 rounded-2xl border border-gray-200 text-gray-600 font-semibold text-sm">Отмена</button>
                <button id="edit-save-btn" class="py-3.5 rounded-2xl bg-indigo-600 text-white font-bold text-sm active:opacity-80">Сохранить</button>
            </div>
        </div>`;
}

function openSheet(tx) { state.selectedTx = tx; state.editingTx = false; render(); }
function closeSheet()  { state.selectedTx = null; state.editingTx = false; render(); }

function attachSheetHandlers() {
    document.getElementById('sheet-overlay')?.addEventListener('click', closeSheet);
    document.getElementById('sheet-edit-btn')?.addEventListener('click', () => { state.editingTx = true; render(); });
    document.getElementById('sheet-delete-btn')?.addEventListener('click', async () => {
        const tx = state.selectedTx;
        if (!tx) return;
        const ok = await new Promise(resolve => {
            if (tg?.showConfirm) tg.showConfirm(`Удалить ${txType(tx)==='income'?'доход':'расход'} ${fmt(tx.amount)}?`, resolve);
            else resolve(confirm(`Удалить ${fmt(tx.amount)}?`));
        });
        if (!ok) return;
        try {
            await api('DELETE', `/transactions/${tx.id}`);
            state.transactions = state.transactions.filter(t => t.id !== tx.id);
            closeSheet();
        } catch (e) {
            if (tg?.showAlert) tg.showAlert(`Ошибка: ${e.message}`);
        }
    });
    if (state.editingTx) attachEditHandlers();
}

function attachEditHandlers() {
    let editCat = state.selectedTx?.category || 'other';
    document.querySelectorAll('.edit-cat-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.edit-cat-btn').forEach(b => b.classList.remove('selected'));
            btn.classList.add('selected'); editCat = btn.dataset.cat;
        });
    });
    document.getElementById('edit-cancel-btn')?.addEventListener('click', () => { state.editingTx = false; render(); });
    document.getElementById('edit-save-btn')?.addEventListener('click', async () => {
        const amount = parseFloat(document.getElementById('edit-amount')?.value || '0');
        const desc   = document.getElementById('edit-desc')?.value?.trim() || '';
        if (!amount || amount <= 0) { if(tg?.showAlert) tg.showAlert('Введи сумму больше нуля'); return; }
        const btn = document.getElementById('edit-save-btn');
        if (btn) { btn.disabled=true; btn.textContent='Сохраняю...'; }
        try {
            const updated = await api('PATCH', `/transactions/${state.selectedTx.id}`, {amount, category:editCat, description:desc});
            const idx = state.transactions.findIndex(t => t.id === updated.id);
            if (idx >= 0) state.transactions[idx] = { ...state.transactions[idx], ...updated };
            state.selectedTx = null; state.editingTx = false; render();
        } catch (e) {
            if(tg?.showAlert) tg.showAlert(`Ошибка: ${e.message}`);
            if (btn) { btn.disabled=false; btn.textContent='Сохранить'; }
        }
    });
}

// ============================================================
// ТАРИФЫ И ПЛАН
// ============================================================
// TODO: subtitle для premium/pro лучше брать из state.plan.pricing (API уже отдаёт
// `pricing.premium.usd` и `pricing.pro.usd`), а не дублировать число здесь —
// иначе при смене цены в plans.py нужно помнить про два места и легко разойтись.
const PLAN_VISUAL = {
    trial:   { iconName: 'sparkles', title: 'Trial',   subtitle: 'Полная пробная неделя' },
    free:    { iconName: 'circle',   title: 'Free',    subtitle: 'Бесплатно навсегда' },
    premium: { iconName: 'gem',      title: 'Premium', subtitle: '$5 в месяц' },
    pro:     { iconName: 'crown',    title: 'Pro',     subtitle: '$10 в месяц' },
    owner:   { iconName: 'crown',    title: 'Owner',   subtitle: 'Безлимитный доступ' },
};

function fmtPlanTimeLeft(planData) {
    if (!planData) return '';
    const target = planData.plan === 'trial' ? planData.trial_until : planData.subscription_until;
    if (planData.plan === 'free')  return 'Бесплатный режим';
    if (planData.plan === 'owner') return 'Безлимит (allowlist)';
    if (!target) return 'Бессрочно';
    const t = new Date(target);
    const secs = (t - new Date()) / 1000;
    if (secs <= 0) return 'истёк';
    if (secs >= 86400) return `${Math.floor(secs/86400)} дн.`;
    if (secs >= 3600)  return `${Math.floor(secs/3600)} ч.`;
    return `${Math.max(1, Math.floor(secs/60))} мин.`;
}

function buildPlanWidget() {
    if (!state.plan) return '';
    const p   = state.plan;
    const v   = PLAN_VISUAL[p.plan] || PLAN_VISUAL.free;
    const tx  = p.usage?.transaction;
    const ph  = p.usage?.photo;
    const ai  = p.usage?.ai_question;
    const periodWord = (u) => u?.period === 'day' ? 'сегодня' : 'за месяц';
    const lineHTML = (label, u) => {
        if (!u || u.limit === 0) return `<span class="text-white/50">${label}: —</span>`;
        const pct = Math.min(100, Math.round((u.used / u.limit) * 100));
        const colour = pct >= 90 ? 'bg-red-300' : pct >= 60 ? 'bg-yellow-200' : 'bg-white/70';
        return `
            <div class="flex items-center justify-between text-xs">
                <span class="text-white/80">${label} ${periodWord(u)}</span>
                <span class="text-white font-semibold">${u.used}/${u.limit}</span>
            </div>
            <div class="h-1 bg-white/20 rounded-full overflow-hidden mb-2">
                <div class="${colour} h-full" style="width:${pct}%"></div>
            </div>`;
    };
    return `
        <div id="plan-widget" class="bg-gradient-to-br from-indigo-700 to-indigo-900 rounded-2xl
                                     p-4 text-white shadow-md mb-4 cursor-pointer">
            <div class="flex items-center justify-between mb-3">
                <div class="flex items-center gap-3">
                    <div class="w-9 h-9 bg-white/15 rounded-lg flex items-center justify-center">
                        ${icon(v.iconName, 'w-5 h-5')}
                    </div>
                    <div>
                        <p class="font-bold leading-tight">${v.title}</p>
                        <p class="text-white/70 text-xs">${fmtPlanTimeLeft(p)}</p>
                    </div>
                </div>
                <span class="text-white/80 text-xs flex items-center gap-1">Подробнее ${icon('chevron-right', 'w-3 h-3')}</span>
            </div>
            ${lineHTML('Транзакции', tx)}
            ${lineHTML('Фото чека', ph)}
            ${lineHTML('AI-финансист', ai)}
        </div>`;
}

function attachPlanWidgetHandlers() {
    document.getElementById('plan-widget')?.addEventListener('click', () => {
        goTo('plan');
    });
}

function buildPlan() {
    if (!state.plan) {
        return `
            <div class="px-4 pt-6">
                <p class="text-gray-500">Не удалось загрузить данные плана. Попробуй открыть приложение заново.</p>
            </div>`;
    }
    const p = state.plan;
    const v = PLAN_VISUAL[p.plan] || PLAN_VISUAL.free;

    const row = (label, action) => {
        const u = p.usage?.[action];
        const period = u?.period === 'day' ? 'сегодня' : 'в этом месяце';
        if (!u || u.limit === 0) {
            return `
                <div class="flex justify-between items-center py-3 border-b border-gray-100">
                    <span class="text-gray-700">${label}</span>
                    <span class="text-gray-400 text-sm">недоступно</span>
                </div>`;
        }
        const pct = Math.min(100, Math.round((u.used / u.limit) * 100));
        const colour = pct >= 90 ? 'bg-red-500' : pct >= 60 ? 'bg-yellow-500' : 'bg-indigo-500';
        return `
            <div class="py-3 border-b border-gray-100">
                <div class="flex justify-between items-center mb-1.5">
                    <span class="text-gray-700">${label}</span>
                    <span class="text-sm font-semibold text-gray-900">${u.used}/${u.limit} ${period}</span>
                </div>
                <div class="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                    <div class="${colour} h-full" style="width:${pct}%"></div>
                </div>
            </div>`;
    };

    const limits = p.limits || {};
    const staticRow = (label, value) => `
        <div class="flex justify-between items-center py-2.5 border-b border-gray-100">
            <span class="text-gray-700">${label}</span>
            <span class="text-sm font-semibold text-gray-900">${value}</span>
        </div>`;

    const upgradeBtn = p.plan === 'pro' ? '' : (() => {
        const label = p.plan === 'free'  ? 'Попробовать Premium'
                    : p.plan === 'trial' ? 'Купить подписку'
                    : 'Поднять до Pro';
        const ic    = p.plan === 'free'  ? 'sparkles'
                    : p.plan === 'trial' ? 'gem'
                    : 'crown';
        return `
            <button id="open-upgrade-btn"
                    class="w-full bg-indigo-600 text-white py-3 rounded-2xl font-semibold shadow-md mt-4
                           flex items-center justify-center gap-2 active:scale-95 transition">
                ${icon(ic, 'w-5 h-5')} ${label}
            </button>`;
    })();

    // Кнопка экспорта в CSV (показываем если экспорт вообще доступен на плане)
    const exportLimit = (p.limits || {}).exports_per_month ?? (p.limits || {}).exports_total ?? 0;
    const exportBtn = exportLimit > 0 ? `
        <button id="export-csv-btn"
                class="w-full bg-white border border-gray-200 text-gray-700 py-2.5 rounded-2xl font-medium mt-3
                       flex items-center justify-center gap-2 active:scale-95 transition">
            ${icon('download', 'w-4 h-4')} Скачать CSV
        </button>
    ` : '';

    const ref = p.referral || {};
    const referralBlock = ref.invite_link ? `
        <div class="bg-white rounded-2xl p-4 shadow-sm mt-4 border border-emerald-100">
            <h2 class="font-semibold text-gray-700 mb-2 text-sm flex items-center gap-2">
                ${icon('gift', 'w-4 h-4 text-emerald-500')} Пригласи друга — обоим +${ref.bonus_days || 14} дней Premium
            </h2>
            <p class="text-xs text-gray-500 mb-3">
                Когда друг откроет бота по твоей ссылке и сделает /start — вам обоим автоматически
                начислится Premium-подписка на ${ref.bonus_days || 14} дней.
            </p>
            <button id="share-referral-btn"
                    class="w-full bg-emerald-500 text-white py-2.5 rounded-xl font-semibold
                           flex items-center justify-center gap-2 active:scale-95 transition">
                ${icon('share-2', 'w-4 h-4')} Поделиться ссылкой
            </button>
            <button id="copy-referral-btn"
                    class="w-full bg-gray-100 text-gray-700 py-2.5 rounded-xl font-medium mt-2 text-sm
                           flex items-center justify-center gap-2 active:scale-95 transition">
                ${icon('copy', 'w-4 h-4')} Скопировать ссылку
            </button>
        </div>
    ` : '';

    return `
        <div class="px-4 pt-5 pb-6">
            <div class="bg-gradient-to-br from-indigo-700 to-indigo-900 rounded-2xl p-5 text-white shadow-md mb-4">
                <div class="flex items-center gap-3 mb-1">
                    <div class="w-12 h-12 bg-white/15 rounded-xl flex items-center justify-center">
                        ${icon(v.iconName, 'w-7 h-7')}
                    </div>
                    <div>
                        <p class="text-xl font-bold">${v.title}</p>
                        <p class="text-white/80 text-sm">${v.subtitle}</p>
                    </div>
                </div>
                <p class="text-white/70 text-xs mt-3">${fmtPlanTimeLeft(p)}</p>
            </div>

            <div class="bg-white rounded-2xl p-4 shadow-sm mb-4">
                <h2 class="font-semibold text-gray-700 mb-1 text-sm flex items-center gap-2">
                    ${icon('activity', 'w-4 h-4 text-indigo-500')} Использование сейчас
                </h2>
                ${row('Транзакции', 'transaction')}
                ${row('Фото чеков', 'photo')}
                ${row('AI-финансист', 'ai_question')}
                ${row('Голосовые', 'voice')}
            </div>

            <div class="bg-white rounded-2xl p-4 shadow-sm">
                <h2 class="font-semibold text-gray-700 mb-1 text-sm flex items-center gap-2">
                    ${icon('settings-2', 'w-4 h-4 text-indigo-500')} Возможности плана
                </h2>
                ${staticRow('История', limits.history_days ? `${limits.history_days} дн.` : 'вся')}
                ${staticRow('Категорий', limits.categories_max || '—')}
                ${staticRow('Регулярных платежей', limits.recurring_payments_max || '—')}
                ${staticRow('Импорт CSV', limits.csv_import ? '✅' : '❌')}
                ${staticRow('Экспорт', limits.exports_per_month != null ? `${limits.exports_per_month}/мес` :
                            limits.exports_total != null ? `${limits.exports_total} за триал` : '—')}
                ${staticRow('Mini App аналитика', limits.mini_app_analytics === 'full' ? 'Полная' : 'Базовая')}
            </div>

            ${upgradeBtn}
            ${exportBtn}
            ${referralBlock}
        </div>`;
}

function attachPlanHandlers() {
    document.getElementById('open-upgrade-btn')?.addEventListener('click', () => {
        goTo('upgrade');
    });

    document.getElementById('export-csv-btn')?.addEventListener('click', async () => {
        const btn = document.getElementById('export-csv-btn');
        const originalHTML = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = 'Готовлю файл...';
        try {
            const r = await api('POST', '/export.csv');
            const rows = r?.rows ?? 0;
            if (tg?.showAlert) tg.showAlert(`✅ Файл отправлен тебе в чат с ботом (${rows} транзакций).`);
        } catch (e) {
            if (tg?.showAlert) tg.showAlert(`Не удалось экспортировать: ${e.message}`);
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHTML;
            try { state.plan = await api('GET', '/plan'); } catch {}
        }
    });

    const link = state.plan?.referral?.invite_link;
    if (link) {
        document.getElementById('share-referral-btn')?.addEventListener('click', () => {
            const text = encodeURIComponent(
                `Веду учёт трат через AI-Финансиста. Кидаешь ему «250 на обед» — он сам разбирает. ` +
                `Открой по ссылке — нам обоим дадут 14 дней Premium бесплатно.`,
            );
            const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(link)}&text=${text}`;
            if (tg?.openTelegramLink) tg.openTelegramLink(shareUrl);
            else window.open(shareUrl, '_blank');
        });
        document.getElementById('copy-referral-btn')?.addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(link);
                if (tg?.showAlert) tg.showAlert('Ссылка скопирована');
            } catch {
                if (tg?.showAlert) tg.showAlert('Не удалось скопировать. Скопируй вручную из /invite в боте.');
            }
        });
    }
}

function buildUpgrade() {
    if (!state.plan) return '<div class="px-4 pt-6 text-gray-500">Загрузка...</div>';
    const pricing = state.plan.pricing || {};
    const premium = pricing.premium || { stars: 350, usd: 7 };
    const pro     = pricing.pro     || { stars: 750, usd: 15 };

    const currentPlan = state.plan?.plan;
    const tierCard = (key, iconName, title, price, features, recommended) => {
        const isCurrent = currentPlan === key;
        const ringClass = isCurrent ? 'ring-2 ring-emerald-500'
                        : recommended ? 'ring-2 ring-indigo-500'
                        : '';
        const badge = isCurrent
            ? '<span class="absolute -top-2.5 left-4 bg-emerald-500 text-white text-xs px-2 py-0.5 rounded-full font-medium">Твой план</span>'
            : recommended
                ? '<span class="absolute -top-2.5 left-4 bg-indigo-600 text-white text-xs px-2 py-0.5 rounded-full font-medium">Популярный</span>'
                : '';
        const iconBg = isCurrent ? 'bg-emerald-100 text-emerald-600'
                    : recommended ? 'bg-indigo-100 text-indigo-600'
                    : 'bg-gray-100 text-gray-700';
        const cta = isCurrent
            ? `<button class="w-full bg-gray-100 text-gray-500 py-2.5 rounded-xl font-semibold cursor-default" disabled>
                   Это твой текущий тариф
               </button>`
            : `<button class="upgrade-btn w-full bg-indigo-600 text-white py-2.5 rounded-xl font-semibold active:scale-95 transition"
                       data-tier="${key}">
                   Оформить — $${price.usd}/мес
               </button>`;
        return `
            <div class="bg-white rounded-2xl p-5 shadow-sm ${ringClass} mb-3 relative">
                ${badge}
                <div class="flex items-center justify-between mb-3">
                    <div class="flex items-center gap-3">
                        <div class="w-10 h-10 ${iconBg} rounded-xl flex items-center justify-center">
                            ${icon(iconName, 'w-5 h-5')}
                        </div>
                        <div>
                            <p class="font-bold text-gray-900">${title}</p>
                            <p class="text-xs text-gray-400">$${price.usd}/мес</p>
                        </div>
                    </div>
                </div>
                <ul class="text-sm text-gray-700 space-y-1.5 mb-4">
                    ${features.map(f => `<li class="flex items-start gap-2">${icon('check', 'w-4 h-4 text-green-500 mt-0.5 flex-shrink-0')}<span>${f}</span></li>`).join('')}
                </ul>
                ${cta}
            </div>`;
    };

    return `
        <div class="px-4 pt-5 pb-6">
            <div class="flex items-center justify-between mb-4">
                <h1 class="text-2xl font-bold text-gray-900">Поднять план</h1>
                <button id="back-to-plan" class="text-indigo-600 text-sm flex items-center gap-1">
                    ${icon('chevron-left', 'w-4 h-4')} План
                </button>
            </div>

            ${tierCard('premium', 'gem', 'Premium', premium, [
                '17 трат / день (≈500/мес)',
                '300 вопросов AI-финансисту в месяц',
                '30 фото чеков в месяц',
                'Голос: 60/мес',
                'История 12 месяцев',
                'Импорт CSV и экспорт (3/мес)',
            ], true)}

            ${tierCard('pro', 'crown', 'Pro', pro, [
                '100 трат / день (≈3000/мес)',
                '1500 вопросов AI-финансисту в месяц',
                '150 фото чеков в месяц',
                'Голос: 200/мес',
                'История 24 месяца, 100 категорий',
                'Экспорт 10/мес',
            ], false)}

            <p class="text-xs text-gray-400 text-center mt-4">
                Оплата картой через Lava.top. Подписка продлевается автоматически каждый месяц, можно отменить в любой момент.
            </p>
        </div>`;
}

function attachUpgradeHandlers() {
    document.getElementById('back-to-plan')?.addEventListener('click', () => {
        goBack();
    });
    document.querySelectorAll('.upgrade-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const tier = btn.dataset.tier;

            btn.disabled = true;
            const originalText = btn.textContent;
            btn.textContent = 'Подготавливаю оплату...';

            try {
                const { payment_url } = await api('POST', '/upgrade/invoice', { tier });
                if (!payment_url) throw new Error('Пустая ссылка на оплату');
                // Навигация в той же WebView — Лава грузится внутри Mini App,
                // юзер не покидает Telegram. После оплаты webhook активирует
                // подписку и бот пушнёт сообщение в чат.
                window.location.href = payment_url;
            } catch (e) {
                if (tg?.showAlert) tg.showAlert(`Не удалось создать счёт: ${e.message}`);
                else alert(`Ошибка: ${e.message}`);
            } finally {
                btn.disabled = false;
                btn.textContent = originalText;
            }
        });
    });
}

// ============================================================
// ЭКРАН: НАСТРОЙКИ
// ============================================================
function buildSettings() {
    const currency = state.me?.currency || '—';
    const planTitle = (() => {
        const map = { trial: 'Trial', free: 'Free', premium: 'Premium', pro: 'Pro', owner: 'Owner' };
        return map[state.plan?.plan] || state.plan?.plan || '—';
    })();
    const row = (iconName, title, value, dataAction, soonText) => `
        <button class="settings-row w-full flex items-center gap-3 px-4 py-3.5 text-left
                       hover:bg-gray-50 dark:hover:bg-white/5 transition-colors"
                ${dataAction ? `data-action="${dataAction}"` : 'disabled'}>
            <div class="w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0"
                 style="background:var(--accent-soft);color:var(--accent)">
                ${icon(iconName, 'w-4 h-4')}
            </div>
            <div class="flex-1 min-w-0">
                <p class="text-[14px] font-medium truncate" style="color:var(--text)">${title}</p>
                ${value ? `<p class="text-[12px] truncate" style="color:var(--text-faint)">${value}</p>` : ''}
            </div>
            ${soonText
                ? `<span class="text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full font-semibold"
                          style="background:var(--accent-soft);color:var(--accent)">${soonText}</span>`
                : icon('chevron-right', 'w-4 h-4 text-gray-300')}
        </button>`;

    return `
        <div class="px-4 pt-5">
            <h1 class="h-display mb-5">Настройки</h1>

            <p class="eyebrow mb-2 mt-1">Аккаунт</p>
            <div class="rounded-2xl overflow-hidden divide-y divide-gray-100 dark:divide-white/5"
                 style="background:var(--surface);border:1px solid var(--border)">
                ${row('coins',  'Валюта',       currency, 'settings_currency')}
                ${row('crown',  'Подписка',     planTitle, 'settings_plan')}
                ${row('gift',   'Пригласить друга +14 дней Premium', '', 'settings_invite')}
            </div>

            <p class="eyebrow mb-2 mt-5">Управление</p>
            <div class="rounded-2xl overflow-hidden divide-y divide-gray-100 dark:divide-white/5"
                 style="background:var(--surface);border:1px solid var(--border)">
                ${row('target', 'Бюджеты по категориям',  '', null, 'скоро')}
                ${row('tags',   'Кастомные категории',     '', 'settings_categories')}
                ${row('repeat', 'Регулярные платежи',      '', 'settings_recurring')}
            </div>

            <p class="eyebrow mb-2 mt-5">Прочее</p>
            <div class="rounded-2xl overflow-hidden divide-y divide-gray-100 dark:divide-white/5"
                 style="background:var(--surface);border:1px solid var(--border)">
                ${row('life-buoy', 'Помощь', '', 'settings_help')}
            </div>

            <p class="text-[11px] text-center mt-6" style="color:var(--text-faint)">
                AI-Финансист · botfinance.xyz
            </p>
        </div>`;
}

function attachSettingsHandlers() {
    document.querySelectorAll('[data-action]').forEach(el => {
        el.addEventListener('click', () => {
            const action = el.dataset.action;
            if (action === 'settings_plan')           { goTo('plan'); }
            else if (action === 'settings_currency')  { openCurrencyPicker(); }
            else if (action === 'settings_invite')    { goTo('invite'); }
            else if (action === 'settings_help')      { goTo('help'); }
            else if (action === 'settings_categories'){ state.customCategories = null; goTo('categories'); }
            else if (action === 'settings_recurring') { state.recurringList = null; goTo('recurring'); }
        });
    });
}


// ----- Currency picker (bottom sheet) -----

function openCurrencyPicker() {
    state.currencyPickerOpen = true;
    render();
}

function buildCurrencyPicker() {
    if (!state.currencyPickerOpen) return '';
    const currencies = [
        ['KGS', '🇰🇬 Сом (KGS)'],
        ['KZT', '🇰🇿 Тенге (KZT)'],
        ['RUB', '🇷🇺 Рубль (RUB)'],
        ['UZS', '🇺🇿 Сум (UZS)'],
        ['USD', '💵 Доллар (USD)'],
    ];
    const current = state.me?.currency;
    return `
        <div class="fixed inset-0 z-50 flex items-end justify-center"
             style="background:rgba(0,0,0,0.45)" id="currency-picker-overlay">
            <div class="w-full max-w-md rounded-t-3xl pb-6 pt-3 px-4 sheet-enter"
                 style="background:var(--surface)" onclick="event.stopPropagation()">
                <div class="w-12 h-1 rounded-full mx-auto mb-3" style="background:var(--border)"></div>
                <h3 class="text-base font-semibold mb-3" style="color:var(--text)">Выбери валюту</h3>
                <div class="space-y-1">
                    ${currencies.map(([code, label]) => `
                        <button data-currency="${code}"
                                class="currency-pick-btn w-full flex items-center justify-between
                                       px-4 py-3 rounded-xl text-left text-[15px]
                                       ${current === code ? 'font-semibold' : ''}"
                                style="background:${current === code ? 'var(--accent-soft)' : 'transparent'};
                                       color:${current === code ? 'var(--accent)' : 'var(--text)'}">
                            <span>${label}</span>
                            ${current === code ? icon('check', 'w-5 h-5') : ''}
                        </button>
                    `).join('')}
                </div>
            </div>
        </div>`;
}

function attachCurrencyPickerHandlers() {
    document.getElementById('currency-picker-overlay')?.addEventListener('click', () => {
        state.currencyPickerOpen = false; render();
    });
    document.querySelectorAll('.currency-pick-btn').forEach(btn => {
        btn.addEventListener('click', async (ev) => {
            ev.stopPropagation();
            const code = btn.dataset.currency;
            if (!code || code === state.me?.currency) {
                state.currencyPickerOpen = false; render(); return;
            }
            try {
                const res = await api('PATCH', '/me/currency', { currency: code });
                if (res?.ok) {
                    if (state.me) state.me.currency = res.currency;
                    state.currencyPickerOpen = false;
                    render();
                    const tg = window.Telegram?.WebApp;
                    tg?.HapticFeedback?.notificationOccurred?.('success');
                }
            } catch (e) {
                const tg = window.Telegram?.WebApp;
                if (tg?.showAlert) tg.showAlert(`Не удалось сменить валюту: ${e.message}`);
            }
        });
    });
}


// ----- Invite screen -----

function buildInvite() {
    const inv = state.invite;
    if (!inv) {
        // Грузим лениво
        (async () => {
            try { state.invite = await api('GET', '/me/invite'); render(); } catch (e) {}
        })();
        return `<div class="px-4 pt-6 text-gray-500">Загружаю...</div>`;
    }
    return `
        <div class="px-4 pt-5">
            <button class="text-[14px] mb-3 inline-flex items-center gap-1" style="color:var(--accent)"
                    data-action="back_to_settings">${icon('chevron-left', 'w-4 h-4')} Настройки</button>
            <h1 class="h-display mb-2">Пригласить друга</h1>
            <p class="text-[14px] mb-5" style="color:var(--text-muted)">
                Поделись ссылкой — когда друг откроет бота и нажмёт /start, обоим начислится
                <b>${inv.bonus_days}</b> дней Premium.
            </p>

            <div class="rounded-2xl p-4 mb-4" style="background:var(--surface);border:1px solid var(--border)">
                <p class="eyebrow mb-2">Твоя ссылка</p>
                <p class="text-[13px] break-all font-mono mb-3" style="color:var(--text)">${inv.link}</p>
                <div class="flex gap-2">
                    <button data-action="invite_share"
                            class="flex-1 py-2.5 rounded-xl text-white text-[14px] font-semibold"
                            style="background:linear-gradient(135deg,#8b5cf6 0%,#6366f1 55%,#4f46e5 100%)">
                        Поделиться
                    </button>
                    <button data-action="invite_copy"
                            class="flex-1 py-2.5 rounded-xl text-[14px] font-semibold"
                            style="background:var(--accent-soft);color:var(--accent)">
                        Скопировать
                    </button>
                </div>
            </div>

            <div class="grid grid-cols-2 gap-3">
                <div class="rounded-2xl p-4" style="background:var(--surface);border:1px solid var(--border)">
                    <p class="eyebrow mb-1">Приглашено</p>
                    <p class="text-2xl font-bold" style="color:var(--text)">${inv.invited_count}</p>
                </div>
                <div class="rounded-2xl p-4" style="background:var(--surface);border:1px solid var(--border)">
                    <p class="eyebrow mb-1">Бонусных дней</p>
                    <p class="text-2xl font-bold" style="color:var(--accent)">${inv.invited_count * inv.bonus_days}</p>
                </div>
            </div>
        </div>`;
}

function attachInviteHandlers() {
    document.querySelectorAll('[data-action="back_to_settings"]').forEach(el =>
        el.addEventListener('click', () => goBack()));
    document.querySelectorAll('[data-action="invite_copy"]').forEach(el =>
        el.addEventListener('click', async () => {
            const link = state.invite?.link;
            if (!link) return;
            try {
                await navigator.clipboard.writeText(link);
                const tg = window.Telegram?.WebApp;
                tg?.HapticFeedback?.notificationOccurred?.('success');
                el.textContent = 'Скопировано ✓';
                setTimeout(() => { el.textContent = 'Скопировать'; }, 1500);
            } catch (e) {}
        }));
    document.querySelectorAll('[data-action="invite_share"]').forEach(el =>
        el.addEventListener('click', () => {
            const link = state.invite?.link;
            if (!link) return;
            const tg = window.Telegram?.WebApp;
            // Telegram WebApp.openTelegramLink с share-URL открывает диалог выбора чата.
            if (tg?.openTelegramLink) {
                const shareText = `Учёт трат без таблиц — бот распознаёт и сохраняет. +14 дней Premium по моей ссылке.`;
                tg.openTelegramLink(`https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent(shareText)}`);
            } else if (navigator.share) {
                navigator.share({ url: link, text: 'AI-Финансист' }).catch(() => {});
            } else {
                navigator.clipboard?.writeText(link);
            }
        }));
}


// ----- Help screen -----

function buildHelp() {
    return `
        <div class="px-4 pt-5">
            <button class="text-[14px] mb-3 inline-flex items-center gap-1" style="color:var(--accent)"
                    data-action="back_to_settings">${icon('chevron-left', 'w-4 h-4')} Настройки</button>
            <h1 class="h-display mb-4">Как пользоваться</h1>

            <div class="rounded-2xl p-5 mb-4 space-y-3 text-[14px]" style="background:var(--surface);border:1px solid var(--border);color:var(--text)">
                <p><b>Запись траты</b> — напиши в чате с ботом обычным сообщением:</p>
                <ul class="space-y-1 ml-1" style="color:var(--text-muted)">
                    <li>• «250 кофе»</li>
                    <li>• «потратил 1500 на такси»</li>
                    <li>• «зарплата 50000»</li>
                </ul>
                <p>Я разберу сумму, категорию и сохраню. В Mini App запись доступна через FAB «+».</p>
            </div>

            <div class="rounded-2xl p-5 mb-4 space-y-2 text-[14px]" style="background:var(--surface);border:1px solid var(--border);color:var(--text)">
                <p><b>Распознавание</b></p>
                <p style="color:var(--text-muted)">📷 Фото чека — пришли в чате, бот распознает.</p>
                <p style="color:var(--text-muted)">🎙 Голосовое — то же самое.</p>
                <p style="color:var(--text-muted)">📥 CSV — импорт транзакций (Premium и Pro).</p>
            </div>

            <div class="rounded-2xl p-5 text-[14px]" style="background:var(--surface);border:1px solid var(--border);color:var(--text)">
                <p><b>AI-финансист</b></p>
                <p style="color:var(--text-muted)">
                    Спрашивай в чате: «где я слил больше всего за неделю?», «сколько на еду в мае?».
                    Бот посчитает и ответит.
                </p>
            </div>

            <div class="rounded-2xl p-5 mt-4" style="background:var(--accent-soft);border:1px solid var(--border)">
                <p class="text-[14px] mb-1" style="color:var(--text)"><b>Идеи, баги, фичи?</b></p>
                <p class="text-[13px] mb-3" style="color:var(--text-muted)">
                    Напиши мне напрямую — отвечаю на все сообщения. Если что-то не работает
                    или хочется новую функцию, пиши в любой момент.
                </p>
                <button id="help-contact-btn"
                        class="w-full py-3 rounded-xl text-white font-semibold text-[14px]
                               flex items-center justify-center gap-2 active:scale-95 transition"
                        style="background:linear-gradient(135deg,#8b5cf6 0%,#6366f1 55%,#4f46e5 100%)">
                    ${icon('message-circle', 'w-4 h-4')} Написать @sultanhodzjaevv
                </button>
            </div>
        </div>`;
}

function attachHelpHandlers() {
    document.querySelectorAll('[data-action="back_to_settings"]').forEach(el =>
        el.addEventListener('click', () => goBack()));
    document.getElementById('help-contact-btn')?.addEventListener('click', () => {
        const tg = window.Telegram?.WebApp;
        // openTelegramLink не закрывает Mini App, открывает чат в том же TG-клиенте.
        if (tg?.openTelegramLink) tg.openTelegramLink('https://t.me/sultanhodzjaevv');
        else window.open('https://t.me/sultanhodzjaevv', '_blank');
    });
}


// ============================================================
// ЭКРАН: КАСТОМНЫЕ КАТЕГОРИИ
// ============================================================
const EMOJI_CHOICES = ['🛒','🍔','🚗','🏠','💊','🎬','🎓','🐶','💰','✈️','📱','📌','💡','🎁','📦','💼','💻','📈','📊'];

function buildCategories() {
    if (state.customCategories === null || state.customCategories === undefined) {
        (async () => {
            try {
                const res = await api('GET', '/me/categories');
                state.customCategories = res.categories || [];
                render();
            } catch (e) { state.customCategories = []; render(); }
        })();
        return `<div class="px-4 pt-6 text-gray-500">Загружаю...</div>`;
    }

    const cats = state.customCategories;
    const empty = !cats.length;
    return `
        <div class="px-4 pt-5 pb-6">
            <h1 class="h-display mb-2">Кастомные категории</h1>
            <p class="text-[13px] mb-5" style="color:var(--text-muted)">
                Свои категории показываются в Mini App-дашборде и графиках. В чат-боте при
                записи трат используется основной набор — для совместимости с AI.
            </p>

            ${empty ? `
                <div class="rounded-2xl p-6 text-center" style="background:var(--surface);border:1px solid var(--border)">
                    <p class="text-[15px] mb-1" style="color:var(--text)">Пока нет своих категорий</p>
                    <p class="text-[13px]" style="color:var(--text-muted)">Создай первую — она появится в графиках Mini App.</p>
                </div>
            ` : `
                <div class="rounded-2xl overflow-hidden divide-y divide-gray-100 dark:divide-white/5"
                     style="background:var(--surface);border:1px solid var(--border)">
                    ${cats.map(c => `
                        <div class="flex items-center gap-3 px-4 py-3">
                            <span class="text-xl">${c.emoji || '📦'}</span>
                            <div class="flex-1 min-w-0">
                                <p class="text-[14px] font-medium truncate" style="color:var(--text)">${c.name}</p>
                                <p class="text-[11px]" style="color:var(--text-faint)">${c.type === 'income' ? 'Доход' : 'Расход'}</p>
                            </div>
                            <button class="cat-delete-btn p-2 rounded-lg" data-cat-id="${c.id}"
                                    style="color:var(--negative);background:rgba(244,63,94,0.08)">
                                ${icon('trash-2', 'w-4 h-4')}
                            </button>
                        </div>
                    `).join('')}
                </div>
            `}

            <button id="cat-add-btn"
                    class="fixed right-4 bottom-24 px-5 py-3 rounded-full text-white font-semibold text-[14px]
                           flex items-center gap-2 active:scale-95 transition"
                    style="background:linear-gradient(135deg,#8b5cf6 0%,#6366f1 55%,#4f46e5 100%);
                           filter:drop-shadow(0 6px 16px rgba(99,102,241,0.40))">
                ${icon('plus', 'w-4 h-4')} Добавить категорию
            </button>
        </div>
        ${state.catFormOpen ? buildCategoryForm() : ''}`;
}

function buildCategoryForm() {
    const f = state.catForm || { name: '', emoji: '📦', type: 'expense' };
    return `
        <div class="fixed inset-0 z-50 flex items-end justify-center" style="background:rgba(0,0,0,0.5)" id="cat-form-overlay">
            <div class="w-full max-w-md rounded-t-3xl pb-6 pt-3 px-4 sheet-enter"
                 style="background:var(--surface)" onclick="event.stopPropagation()">
                <div class="w-12 h-1 rounded-full mx-auto mb-4" style="background:var(--border)"></div>
                <h3 class="text-base font-semibold mb-4" style="color:var(--text)">Новая категория</h3>

                <label class="block">
                    <span class="eyebrow">Название</span>
                    <input id="cat-form-name" type="text" value="${f.name}" maxlength="50"
                           placeholder="Корм для собаки"
                           class="w-full mt-1.5 px-3 py-2.5 rounded-xl text-[15px]"
                           style="background:var(--bg);color:var(--text);border:1px solid var(--border)">
                </label>

                <div class="mt-4">
                    <span class="eyebrow">Эмодзи</span>
                    <div class="grid grid-cols-8 gap-1.5 mt-1.5">
                        ${EMOJI_CHOICES.map(e => `
                            <button class="cat-emoji-btn aspect-square rounded-lg text-xl flex items-center justify-center
                                            ${f.emoji === e ? 'ring-2' : ''}"
                                    data-emoji="${e}"
                                    style="background:${f.emoji === e ? 'var(--accent-soft)' : 'var(--bg)'};
                                           ${f.emoji === e ? 'border:1px solid var(--accent)' : ''}">${e}</button>
                        `).join('')}
                    </div>
                </div>

                <div class="mt-4">
                    <span class="eyebrow">Тип</span>
                    <div class="grid grid-cols-2 gap-2 mt-1.5">
                        <button class="cat-type-btn py-2.5 rounded-xl text-[14px] font-medium"
                                data-type="expense"
                                style="background:${f.type === 'expense' ? 'var(--accent-soft)' : 'var(--bg)'};
                                       color:${f.type === 'expense' ? 'var(--accent)' : 'var(--text-muted)'};
                                       border:1px solid ${f.type === 'expense' ? 'var(--accent)' : 'var(--border)'}">
                            💸 Расход
                        </button>
                        <button class="cat-type-btn py-2.5 rounded-xl text-[14px] font-medium"
                                data-type="income"
                                style="background:${f.type === 'income' ? 'var(--accent-soft)' : 'var(--bg)'};
                                       color:${f.type === 'income' ? 'var(--accent)' : 'var(--text-muted)'};
                                       border:1px solid ${f.type === 'income' ? 'var(--accent)' : 'var(--border)'}">
                            💰 Доход
                        </button>
                    </div>
                </div>

                <button id="cat-form-submit"
                        class="w-full mt-5 py-3 rounded-xl text-white font-semibold"
                        style="background:linear-gradient(135deg,#8b5cf6 0%,#6366f1 55%,#4f46e5 100%)">
                    Создать
                </button>
            </div>
        </div>`;
}

function attachCategoriesHandlers() {
    document.getElementById('cat-add-btn')?.addEventListener('click', () => {
        state.catForm = { name: '', emoji: '📦', type: 'expense' };
        state.catFormOpen = true;
        render();
    });
    document.querySelectorAll('.cat-delete-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.catId;
            const tg = window.Telegram?.WebApp;
            const confirm = (msg) => new Promise(res => {
                if (tg?.showConfirm) tg.showConfirm(msg, ok => res(ok));
                else res(window.confirm(msg));
            });
            if (!await confirm('Удалить категорию?')) return;
            try {
                await api('DELETE', `/me/categories/${id}`);
                state.customCategories = state.customCategories.filter(c => c.id !== id);
                render();
                tg?.HapticFeedback?.notificationOccurred?.('success');
            } catch (e) {
                if (tg?.showAlert) tg.showAlert(`Ошибка: ${e.message}`);
            }
        });
    });
}

function attachCategoryFormHandlers() {
    document.getElementById('cat-form-overlay')?.addEventListener('click', () => {
        state.catFormOpen = false; render();
    });
    document.getElementById('cat-form-name')?.addEventListener('input', (e) => {
        state.catForm.name = e.target.value;
    });
    document.querySelectorAll('.cat-emoji-btn').forEach(b =>
        b.addEventListener('click', (ev) => {
            ev.stopPropagation();
            state.catForm.emoji = b.dataset.emoji; render();
        }));
    document.querySelectorAll('.cat-type-btn').forEach(b =>
        b.addEventListener('click', (ev) => {
            ev.stopPropagation();
            state.catForm.type = b.dataset.type; render();
        }));
    document.getElementById('cat-form-submit')?.addEventListener('click', async () => {
        const f = state.catForm;
        if (!f.name || !f.name.trim()) {
            const tg = window.Telegram?.WebApp;
            if (tg?.showAlert) tg.showAlert('Заполни название');
            return;
        }
        try {
            const res = await api('POST', '/me/categories', {
                name: f.name.trim(), emoji: f.emoji, type: f.type,
            });
            state.customCategories = [...(state.customCategories || []), res.category];
            state.catFormOpen = false;
            render();
            const tg = window.Telegram?.WebApp;
            tg?.HapticFeedback?.notificationOccurred?.('success');
        } catch (e) {
            const tg = window.Telegram?.WebApp;
            if (tg?.showAlert) tg.showAlert(`Не удалось создать: ${e.message}`);
        }
    });
}


// ============================================================
// ЭКРАН: РЕГУЛЯРНЫЕ ПЛАТЕЖИ
// ============================================================
function buildRecurring() {
    if (state.recurringList === null || state.recurringList === undefined) {
        (async () => {
            try {
                const res = await api('GET', '/recurring');
                state.recurringList = res.recurring || [];
                render();
            } catch (e) { state.recurringList = []; render(); }
        })();
        return `<div class="px-4 pt-6 text-gray-500">Загружаю...</div>`;
    }

    const rps = state.recurringList;
    const empty = !rps.length;
    const currency = state.me?.currency || 'KGS';

    return `
        <div class="px-4 pt-5 pb-6">
            <h1 class="h-display mb-2">Регулярные платежи</h1>
            <p class="text-[13px] mb-5" style="color:var(--text-muted)">
                Подписки, аренда, зарплата — то, что повторяется. Я сам создам транзакцию
                когда подойдёт дата.
            </p>

            ${empty ? `
                <div class="rounded-2xl p-6 text-center" style="background:var(--surface);border:1px solid var(--border)">
                    <p class="text-[15px] mb-1" style="color:var(--text)">Пока нет регулярных</p>
                    <p class="text-[13px]" style="color:var(--text-muted)">Добавь — и я буду записывать автоматически.</p>
                </div>
            ` : `
                <div class="space-y-2">
                    ${rps.map(r => {
                        const cat = findCategoryById(r.category);
                        const sign = r.type === 'income' ? '+' : '−';
                        const colour = r.type === 'income' ? 'var(--positive)' : 'var(--text)';
                        return `
                        <div class="rounded-2xl p-4 flex items-center gap-3"
                             style="background:var(--surface);border:1px solid var(--border)">
                            <span class="text-xl flex-shrink-0">${cat.emoji}</span>
                            <div class="flex-1 min-w-0">
                                <p class="text-[14px] font-semibold truncate" style="color:var(--text)">
                                    ${r.description || cat.name}
                                </p>
                                <p class="text-[11px]" style="color:var(--text-faint)">
                                    Каждые ${r.period_days} дн · следующая ${(r.next_run_at || '').slice(0,10)}
                                </p>
                            </div>
                            <div class="text-right">
                                <p class="text-[14px] font-bold" style="color:${colour}">
                                    ${sign}${fmt(r.amount)}
                                </p>
                                <button class="rec-delete-btn text-[11px] mt-1"
                                        data-rec-id="${r.id}" style="color:var(--negative)">
                                    Удалить
                                </button>
                            </div>
                        </div>`;
                    }).join('')}
                </div>
            `}

            <button id="rec-add-btn"
                    class="fixed right-4 bottom-24 px-5 py-3 rounded-full text-white font-semibold text-[14px]
                           flex items-center gap-2 active:scale-95 transition"
                    style="background:linear-gradient(135deg,#8b5cf6 0%,#6366f1 55%,#4f46e5 100%);
                           filter:drop-shadow(0 6px 16px rgba(99,102,241,0.40))">
                ${icon('plus', 'w-4 h-4')} Добавить регулярный
            </button>
        </div>
        ${state.recFormOpen ? buildRecurringForm() : ''}`;
}

function findCategoryById(id) {
    const all = [
        ...(state.expenseCategories || []),
        ...(state.incomeCategories || []),
        ...((state.customCategories || []).map(c => ({ id: c.id, name: c.name, emoji: c.emoji }))),
    ];
    return all.find(c => c.id === id) || { id, name: id, emoji: '📦' };
}

function buildRecurringForm() {
    const f = state.recForm || { amount: '', type: 'expense', category: '', period_days: 30, description: '' };
    const cats = f.type === 'expense' ? (state.expenseCategories || []) : (state.incomeCategories || []);
    const periods = [
        { d: 7,  label: '7 дн' },
        { d: 14, label: '14 дн' },
        { d: 30, label: 'Месяц' },
        { d: 90, label: 'Квартал' },
    ];
    return `
        <div class="fixed inset-0 z-50 flex items-end justify-center" style="background:rgba(0,0,0,0.5)" id="rec-form-overlay">
            <div class="w-full max-w-md rounded-t-3xl pb-6 pt-3 px-4 sheet-enter max-h-[85vh] overflow-y-auto"
                 style="background:var(--surface)" onclick="event.stopPropagation()">
                <div class="w-12 h-1 rounded-full mx-auto mb-4" style="background:var(--border)"></div>
                <h3 class="text-base font-semibold mb-4" style="color:var(--text)">Новый регулярный платёж</h3>

                <label class="block">
                    <span class="eyebrow">Сумма</span>
                    <input id="rec-form-amount" type="number" inputmode="decimal" value="${f.amount}"
                           placeholder="8750"
                           class="w-full mt-1.5 px-3 py-2.5 rounded-xl text-[15px]"
                           style="background:var(--bg);color:var(--text);border:1px solid var(--border)">
                </label>

                <div class="mt-4">
                    <span class="eyebrow">Тип</span>
                    <div class="grid grid-cols-2 gap-2 mt-1.5">
                        <button class="rec-type-btn py-2.5 rounded-xl text-[14px] font-medium"
                                data-type="expense"
                                style="background:${f.type === 'expense' ? 'var(--accent-soft)' : 'var(--bg)'};
                                       color:${f.type === 'expense' ? 'var(--accent)' : 'var(--text-muted)'};
                                       border:1px solid ${f.type === 'expense' ? 'var(--accent)' : 'var(--border)'}">
                            💸 Расход
                        </button>
                        <button class="rec-type-btn py-2.5 rounded-xl text-[14px] font-medium"
                                data-type="income"
                                style="background:${f.type === 'income' ? 'var(--accent-soft)' : 'var(--bg)'};
                                       color:${f.type === 'income' ? 'var(--accent)' : 'var(--text-muted)'};
                                       border:1px solid ${f.type === 'income' ? 'var(--accent)' : 'var(--border)'}">
                            💰 Доход
                        </button>
                    </div>
                </div>

                <div class="mt-4">
                    <span class="eyebrow">Категория</span>
                    <div class="grid grid-cols-2 gap-1.5 mt-1.5">
                        ${cats.map(c => `
                            <button class="rec-cat-btn flex items-center gap-2 px-3 py-2 rounded-xl text-[13px] text-left"
                                    data-cat-id="${c.id}"
                                    style="background:${f.category === c.id ? 'var(--accent-soft)' : 'var(--bg)'};
                                           color:${f.category === c.id ? 'var(--accent)' : 'var(--text)'};
                                           border:1px solid ${f.category === c.id ? 'var(--accent)' : 'var(--border)'}">
                                <span>${c.emoji}</span><span class="truncate">${c.name}</span>
                            </button>
                        `).join('')}
                    </div>
                </div>

                <div class="mt-4">
                    <span class="eyebrow">Период</span>
                    <div class="grid grid-cols-4 gap-2 mt-1.5">
                        ${periods.map(p => `
                            <button class="rec-period-btn py-2 rounded-xl text-[13px] font-medium"
                                    data-days="${p.d}"
                                    style="background:${f.period_days === p.d ? 'var(--accent-soft)' : 'var(--bg)'};
                                           color:${f.period_days === p.d ? 'var(--accent)' : 'var(--text-muted)'};
                                           border:1px solid ${f.period_days === p.d ? 'var(--accent)' : 'var(--border)'}">
                                ${p.label}
                            </button>
                        `).join('')}
                    </div>
                </div>

                <label class="block mt-4">
                    <span class="eyebrow">Описание (опционально)</span>
                    <input id="rec-form-desc" type="text" value="${f.description}" maxlength="200"
                           placeholder="Spotify"
                           class="w-full mt-1.5 px-3 py-2.5 rounded-xl text-[15px]"
                           style="background:var(--bg);color:var(--text);border:1px solid var(--border)">
                </label>

                <button id="rec-form-submit"
                        class="w-full mt-5 py-3 rounded-xl text-white font-semibold"
                        style="background:linear-gradient(135deg,#8b5cf6 0%,#6366f1 55%,#4f46e5 100%)">
                    Создать
                </button>
            </div>
        </div>`;
}

function attachRecurringHandlers() {
    document.getElementById('rec-add-btn')?.addEventListener('click', () => {
        state.recForm = { amount: '', type: 'expense', category: '', period_days: 30, description: '' };
        state.recFormOpen = true;
        render();
    });
    document.querySelectorAll('.rec-delete-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.recId;
            const tg = window.Telegram?.WebApp;
            const confirm = (msg) => new Promise(res => {
                if (tg?.showConfirm) tg.showConfirm(msg, ok => res(ok));
                else res(window.confirm(msg));
            });
            if (!await confirm('Удалить регулярный платёж?')) return;
            try {
                await api('DELETE', `/recurring/${id}`);
                state.recurringList = state.recurringList.filter(r => r.id !== id);
                render();
                tg?.HapticFeedback?.notificationOccurred?.('success');
            } catch (e) {
                if (tg?.showAlert) tg.showAlert(`Ошибка: ${e.message}`);
            }
        });
    });
}

function attachRecurringFormHandlers() {
    document.getElementById('rec-form-overlay')?.addEventListener('click', () => {
        state.recFormOpen = false; render();
    });
    document.getElementById('rec-form-amount')?.addEventListener('input', (e) => {
        state.recForm.amount = e.target.value;
    });
    document.getElementById('rec-form-desc')?.addEventListener('input', (e) => {
        state.recForm.description = e.target.value;
    });
    document.querySelectorAll('.rec-type-btn').forEach(b =>
        b.addEventListener('click', (ev) => {
            ev.stopPropagation();
            // при смене типа сбрасываем выбранную категорию (другой список)
            state.recForm.type = b.dataset.type;
            state.recForm.category = '';
            render();
        }));
    document.querySelectorAll('.rec-cat-btn').forEach(b =>
        b.addEventListener('click', (ev) => {
            ev.stopPropagation();
            state.recForm.category = b.dataset.catId; render();
        }));
    document.querySelectorAll('.rec-period-btn').forEach(b =>
        b.addEventListener('click', (ev) => {
            ev.stopPropagation();
            state.recForm.period_days = parseInt(b.dataset.days, 10); render();
        }));
    document.getElementById('rec-form-submit')?.addEventListener('click', async () => {
        const f = state.recForm;
        const tg = window.Telegram?.WebApp;
        const amount = parseFloat(f.amount);
        if (!amount || amount <= 0) { tg?.showAlert?.('Введи сумму'); return; }
        if (!f.category) { tg?.showAlert?.('Выбери категорию'); return; }
        try {
            const res = await api('POST', '/recurring', {
                amount, type: f.type, category: f.category,
                period_days: f.period_days, description: f.description,
            });
            state.recurringList = [...(state.recurringList || []), res.recurring];
            state.recFormOpen = false;
            render();
            tg?.HapticFeedback?.notificationOccurred?.('success');
        } catch (e) {
            tg?.showAlert?.(`Не удалось создать: ${e.message}`);
        }
    });
}


// ============================================================
// ЗАПУСК
// ============================================================
init();
