// ============================================================
// AI-Финансист — Telegram Mini App
// Версия 2.0: учёт доходов и расходов
// ============================================================

const tg = window.Telegram?.WebApp;

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
        { id, name: id, emoji: '📦' }
    );
}

// Фильтрует по периоду
function filterByPeriod(txs, f) {
    const now = new Date();
    return txs.filter(tx => {
        const d = new Date(tx.datetime);
        if (f === 'day')   return d.toDateString() === now.toDateString();
        if (f === 'week')  return d >= new Date(now - 7*24*60*60*1000);
        if (f === 'month') return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
        return true;
    });
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
function showApp(html) {
    const loader = document.getElementById('static-loader');
    const app    = document.getElementById('app');
    if (loader) loader.style.display = 'none';
    if (app)    { app.style.display = 'block'; app.innerHTML = html; }
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
        </div>
        ${buildNav()}
        ${buildBottomSheet()}`);
    attachNavHandlers();
    if (state.screen === 'dashboard') renderCharts();
    if (state.screen === 'history')   attachHistoryHandlers();
    if (state.screen === 'add')       attachAddHandlers();
    if (state.screen === 'plan')      attachPlanHandlers();
    if (state.screen === 'upgrade')   attachUpgradeHandlers();
    if (state.selectedTx)             attachSheetHandlers();
}

// ============================================================
// НАВИГАЦИЯ
// ============================================================
function buildNav() {
    const d = state.screen === 'dashboard',
          h = state.screen === 'history',
          p = state.screen === 'plan' || state.screen === 'upgrade';
    return `
        <nav class="fixed bottom-0 left-0 right-0 bg-white/95 backdrop-blur-md border-t border-gray-100
                    flex items-center justify-around px-1 py-1 z-40 shadow-lg"
             style="padding-bottom:max(env(safe-area-inset-bottom),4px)">
            <button class="nav-btn flex flex-col items-center gap-0.5 py-2 px-3 rounded-xl
                           ${d ? 'text-indigo-600' : 'text-gray-400'}" data-screen="dashboard">
                <span class="text-2xl">📊</span><span class="text-xs font-medium">Дашборд</span>
            </button>
            <button class="nav-btn flex flex-col items-center gap-0.5 py-2 px-3 rounded-xl
                           ${h ? 'text-indigo-600' : 'text-gray-400'}" data-screen="history">
                <span class="text-2xl">📜</span><span class="text-xs font-medium">История</span>
            </button>
            <button class="nav-btn flex flex-col items-center py-1 px-3" data-screen="add">
                <span class="bg-indigo-600 text-white text-3xl rounded-full w-12 h-12
                             flex items-center justify-center shadow-md leading-none">+</span>
            </button>
            <button class="nav-btn flex flex-col items-center gap-0.5 py-2 px-3 rounded-xl
                           ${p ? 'text-indigo-600' : 'text-gray-400'}" data-screen="plan">
                <span class="text-2xl">💎</span><span class="text-xs font-medium">План</span>
            </button>
        </nav>`;
}

function attachNavHandlers() {
    document.querySelectorAll('.nav-btn').forEach(btn =>
        btn.addEventListener('click', () => {
            state.screen = btn.dataset.screen;
            if (state.screen !== 'history') { state.periodFilter = 'month'; state.typeFilter = 'all'; }
            state.selectedTx = null; state.editingTx = false;
            render();
        })
    );
}

// ============================================================
// ЭКРАН 1: ДАШБОРД
// ============================================================
function buildDashboard() {
    const now      = new Date();
    const monthTxs = filterByPeriod(state.transactions, 'month');
    const incomes  = monthTxs.filter(t => txType(t) === 'income');
    const expenses = monthTxs.filter(t => txType(t) === 'expense');
    const totalIncome  = incomes.reduce((s,t) => s+t.amount, 0);
    const totalExpense = expenses.reduce((s,t) => s+t.amount, 0);
    const balance      = totalIncome - totalExpense;
    const balancePct   = balance >= 0;

    const monthNames = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];

    // Топ-3 расходов
    const byCat = {};
    expenses.forEach(t => { byCat[t.category] = (byCat[t.category]||0) + t.amount; });
    const top3 = Object.entries(byCat).sort((a,b)=>b[1]-a[1]).slice(0,3);

    return `
        <div class="px-4 pt-5">
            <div class="flex items-start justify-between mb-4">
                <div>
                    <p class="text-gray-400 text-sm">Привет, ${state.me?.first_name||'Друг'}! 👋</p>
                    <h1 class="text-2xl font-bold text-gray-900">${monthNames[now.getMonth()]}</h1>
                </div>
                <div class="w-10 h-10 bg-indigo-100 rounded-full flex items-center justify-center text-xl">💰</div>
            </div>

            <!-- 3 карточки: доходы / расходы / остаток -->
            <div class="grid grid-cols-1 gap-3 mb-4">
                <div class="grid grid-cols-2 gap-3">
                    <div class="bg-green-500 rounded-2xl p-4 text-white shadow">
                        <p class="text-green-100 text-xs mb-1">Доходы</p>
                        <p class="text-xl font-bold leading-tight">${fmt(totalIncome)}</p>
                        <p class="text-green-200 text-xs mt-1">${incomes.length} ${pluralTx(incomes.length)}</p>
                    </div>
                    <div class="bg-red-500 rounded-2xl p-4 text-white shadow">
                        <p class="text-red-100 text-xs mb-1">Расходы</p>
                        <p class="text-xl font-bold leading-tight">${fmt(totalExpense)}</p>
                        <p class="text-red-200 text-xs mt-1">${expenses.length} ${pluralTx(expenses.length)}</p>
                    </div>
                </div>
                <div class="${balancePct ? 'bg-indigo-600' : 'bg-red-600'} rounded-2xl p-4 text-white shadow">
                    <p class="text-white/70 text-xs mb-1">Остаток за месяц</p>
                    <p class="text-2xl font-bold">${balancePct ? '+' : '−'}${fmt(balance)}</p>
                    <p class="text-white/60 text-xs mt-1">${balancePct ? 'Отличный результат 🎉' : 'Расходы превышают доходы ⚠️'}</p>
                </div>
            </div>

            ${monthTxs.length === 0 ? `
                <div class="bg-white rounded-2xl p-8 text-center shadow-sm">
                    <div class="text-4xl mb-3">🎉</div>
                    <p class="font-semibold text-gray-700">Трат пока нет</p>
                    <p class="text-sm text-gray-400 mt-1">Запиши первую операцию через бота или «+»</p>
                </div>
            ` : `
                <!-- Расходы по категориям -->
                <div class="bg-white rounded-2xl p-4 shadow-sm mb-4">
                    <h2 class="font-semibold text-gray-700 mb-3 text-sm">💸 Расходы по категориям</h2>
                    ${expenses.length === 0 ? `<p class="text-gray-400 text-sm text-center py-4">Расходов нет</p>` : `
                        <div class="relative" style="height:200px"><canvas id="donut-expense"></canvas></div>
                        <div class="mt-4 space-y-2 pt-3 border-t border-gray-100">
                            ${top3.map(([id,sum]) => {
                                const cat = getCat(id);
                                const pct = totalExpense > 0 ? Math.round(sum/totalExpense*100) : 0;
                                return `<div class="flex items-center justify-between">
                                    <div class="flex items-center gap-2">
                                        <span class="text-xl">${cat.emoji}</span>
                                        <span class="text-sm text-gray-700">${cat.name}</span>
                                        <span class="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded-full">${pct}%</span>
                                    </div>
                                    <span class="font-semibold text-sm text-red-600">${fmt(sum)}</span>
                                </div>`;
                            }).join('')}
                        </div>
                    `}
                </div>

                <!-- Доходы по категориям -->
                <div class="bg-white rounded-2xl p-4 shadow-sm mb-4">
                    <h2 class="font-semibold text-gray-700 mb-3 text-sm">💰 Доходы по категориям</h2>
                    ${incomes.length === 0 ? `
                        <p class="text-gray-400 text-sm text-center py-4">
                            Доходов нет. Запиши свой первый доход через бота.
                        </p>
                    ` : `<div class="relative" style="height:180px"><canvas id="donut-income"></canvas></div>`}
                </div>

                <!-- Линейный график по дням (две линии) -->
                <div class="bg-white rounded-2xl p-4 shadow-sm mb-4">
                    <h2 class="font-semibold text-gray-700 mb-3 text-sm">📅 Динамика по дням</h2>
                    <div class="relative" style="height:160px"><canvas id="line-chart"></canvas></div>
                </div>
            `}
        </div>`;
}

function renderCharts() {
    const now      = new Date();
    const monthTxs = filterByPeriod(state.transactions, 'month');
    const incomes  = monthTxs.filter(t => txType(t) === 'income');
    const expenses = monthTxs.filter(t => txType(t) === 'expense');

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
                    datasets: [{ data: entries.map(([,v])=>v), backgroundColor: entries.map(([id])=>EXPENSE_COLORS[id]||'#ccc'), borderWidth:2, borderColor:'#fff' }],
                },
                options: { responsive:true, maintainAspectRatio:false, cutout:'62%',
                    plugins: { legend:{position:'right',labels:{font:{size:11},boxWidth:12,padding:8}},
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
                    datasets: [{ data: entries.map(([,v])=>v), backgroundColor: entries.map(([id])=>INCOME_COLORS[id]||'#22c55e'), borderWidth:2, borderColor:'#fff' }],
                },
                options: { responsive:true, maintainAspectRatio:false, cutout:'62%',
                    plugins: { legend:{position:'right',labels:{font:{size:11},boxWidth:12,padding:8}},
                        tooltip:{callbacks:{label:ctx=>` +${fmt(ctx.raw)}`}} } },
            });
        }
    }

    // --- Двойной линейный график по дням ---
    const daysInMonth = new Date(now.getFullYear(), now.getMonth()+1, 0).getDate();
    const days = Array.from({length:daysInMonth},(_,i)=>i+1);
    const expByDay = {}, incByDay = {};
    expenses.forEach(t => { const d=new Date(t.datetime).getDate(); expByDay[d]=(expByDay[d]||0)+t.amount; });
    incomes.forEach(t  => { const d=new Date(t.datetime).getDate(); incByDay[d]=(incByDay[d]||0)+t.amount; });

    const el = document.getElementById('line-chart');
    if (el) {
        state.charts['line-chart'] = new Chart(el, {
            type: 'line',
            data: {
                labels: days.map(String),
                datasets: [
                    { label:'Расходы', data:days.map(d=>expByDay[d]||0), borderColor:'#ef4444', backgroundColor:'rgba(239,68,68,0.07)', fill:true, tension:0.4, pointRadius:2 },
                    { label:'Доходы',  data:days.map(d=>incByDay[d]||0), borderColor:'#22c55e', backgroundColor:'rgba(34,197,94,0.07)',  fill:true, tension:0.4, pointRadius:2 },
                ],
            },
            options: {
                responsive:true, maintainAspectRatio:false,
                plugins:{ legend:{ labels:{font:{size:10},boxWidth:12} } },
                scales:{
                    x:{ grid:{display:false}, ticks:{font:{size:9},maxTicksLimit:10} },
                    y:{ beginAtZero:true, grid:{color:'rgba(0,0,0,0.04)'}, ticks:{font:{size:9},callback:v=>v>=1000?`${(v/1000).toFixed(0)}к`:v} },
                },
            },
        });
    }
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
    const amtColor = isInc ? 'text-green-600' : 'text-red-500';
    const bgColor  = isInc ? '#22c55e22' : (EXPENSE_COLORS[tx.category]||'#ccc')+'22';
    const signedAmt = `${isInc?'+':'−'}${fmt(tx.amount)}`;

    return `
        <div class="tx-row bg-white rounded-2xl px-4 py-3.5 flex items-center gap-3 shadow-sm cursor-pointer active:opacity-70"
             data-id="${tx.id}">
            <div class="w-11 h-11 rounded-xl flex items-center justify-center text-2xl flex-shrink-0"
                 style="background-color:${bgColor}">${cat.emoji}</div>
            <div class="flex-1 min-w-0">
                <p class="font-medium text-gray-900 text-sm">${cat.name}</p>
                ${tx.description
                    ? `<p class="text-xs text-gray-400 truncate">${tx.description}</p>`
                    : `<p class="text-xs text-gray-400">${fmtDate(tx.datetime)}</p>`}
            </div>
            <div class="text-right flex-shrink-0">
                <p class="font-bold text-sm ${amtColor}">${signedAmt}</p>
                ${tx.description?`<p class="text-xs text-gray-300">${fmtDate(tx.datetime)}</p>`:''}
            </div>
        </div>`;
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
                            <span class="emoji">${cat.emoji}</span>
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
            state.screen = 'history';
            state.typeFilter = state.addType; // сразу показываем нужный фильтр
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
    const amtColor = isInc ? 'text-green-600' : 'text-red-500';
    const signedAmt = `${isInc?'+':'−'}${fmt(tx.amount)}`;
    const typeBadge = isInc
        ? `<span class="bg-green-100 text-green-700 text-xs font-semibold px-2 py-0.5 rounded-full">Доход</span>`
        : `<span class="bg-red-100 text-red-600 text-xs font-semibold px-2 py-0.5 rounded-full">Расход</span>`;

    return `
        <div class="text-center py-4">
            <div class="w-16 h-16 rounded-2xl mx-auto flex items-center justify-center text-4xl mb-3"
                 style="background-color:${isInc?'#22c55e22':((EXPENSE_COLORS[tx.category]||'#ccc')+'22')}">${cat.emoji}</div>
            <p class="text-3xl font-bold ${amtColor}">${signedAmt}</p>
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
                            <span class="emoji">${cat.emoji}</span><span>${cat.name}</span>
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
const PLAN_VISUAL = {
    trial:   { icon: '🎁', title: 'Trial',   subtitle: 'Полная пробная неделя' },
    free:    { icon: '🆓', title: 'Free',    subtitle: 'Бесплатно навсегда' },
    premium: { icon: '💎', title: 'Premium', subtitle: '$7 в месяц' },
    pro:     { icon: '🚀', title: 'Pro',     subtitle: '$15 в месяц' },
};

function fmtPlanTimeLeft(planData) {
    if (!planData) return '';
    const target = planData.plan === 'trial' ? planData.trial_until : planData.subscription_until;
    if (planData.plan === 'free') return 'Бесплатный режим';
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
        <div id="plan-widget" class="bg-gradient-to-br from-indigo-600 to-purple-600 rounded-2xl
                                     p-4 text-white shadow-md mb-4 cursor-pointer">
            <div class="flex items-center justify-between mb-3">
                <div class="flex items-center gap-2">
                    <span class="text-2xl">${v.icon}</span>
                    <div>
                        <p class="font-bold leading-tight">${v.title}</p>
                        <p class="text-white/70 text-xs">${fmtPlanTimeLeft(p)}</p>
                    </div>
                </div>
                <span class="text-white/80 text-xs">Подробнее →</span>
            </div>
            ${lineHTML('Транзакции', tx)}
            ${lineHTML('Фото чека', ph)}
            ${lineHTML('AI-финансист', ai)}
        </div>`;
}

function attachPlanWidgetHandlers() {
    document.getElementById('plan-widget')?.addEventListener('click', () => {
        state.screen = 'plan';
        render();
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

    const upgradeBtn =
        p.plan === 'pro' ? '' :
        `<button id="open-upgrade-btn"
                 class="w-full bg-indigo-600 text-white py-3 rounded-2xl font-semibold shadow-md mt-4 active:scale-95 transition">
            ${p.plan === 'free' ? '✨ Попробовать Premium' :
             p.plan === 'trial' ? '💎 Купить подписку' :
             '🚀 Поднять до Pro'}
        </button>`;

    return `
        <div class="px-4 pt-5 pb-6">
            <div class="bg-gradient-to-br from-indigo-600 to-purple-600 rounded-2xl p-5 text-white shadow-md mb-4">
                <div class="flex items-center gap-3 mb-1">
                    <span class="text-3xl">${v.icon}</span>
                    <div>
                        <p class="text-xl font-bold">${v.title}</p>
                        <p class="text-white/80 text-sm">${v.subtitle}</p>
                    </div>
                </div>
                <p class="text-white/70 text-xs mt-2">${fmtPlanTimeLeft(p)}</p>
            </div>

            <div class="bg-white rounded-2xl p-4 shadow-sm mb-4">
                <h2 class="font-semibold text-gray-700 mb-1 text-sm">Использование сейчас</h2>
                ${row('Транзакции', 'transaction')}
                ${row('Фото чеков', 'photo')}
                ${row('AI-финансист', 'ai_question')}
                ${row('Голосовые', 'voice')}
            </div>

            <div class="bg-white rounded-2xl p-4 shadow-sm">
                <h2 class="font-semibold text-gray-700 mb-1 text-sm">Возможности плана</h2>
                ${staticRow('История', limits.history_days ? `${limits.history_days} дн.` : 'вся')}
                ${staticRow('Категорий', limits.categories_max || '—')}
                ${staticRow('Регулярных платежей', limits.recurring_payments_max || '—')}
                ${staticRow('Импорт CSV', limits.csv_import ? '✅' : '❌')}
                ${staticRow('Экспорт', limits.exports_per_month != null ? `${limits.exports_per_month}/мес` :
                            limits.exports_total != null ? `${limits.exports_total} за триал` : '—')}
                ${staticRow('Mini App аналитика', limits.mini_app_analytics === 'full' ? 'Полная' : 'Базовая')}
            </div>

            ${upgradeBtn}
        </div>`;
}

function attachPlanHandlers() {
    document.getElementById('open-upgrade-btn')?.addEventListener('click', () => {
        state.screen = 'upgrade';
        render();
    });
}

function buildUpgrade() {
    if (!state.plan) return '<div class="px-4 pt-6 text-gray-500">Загрузка...</div>';
    const pricing = state.plan.pricing || {};
    const premium = pricing.premium || { stars: 350, usd: 7 };
    const pro     = pricing.pro     || { stars: 750, usd: 15 };

    const tierCard = (key, icon, title, price, features, recommended) => `
        <div class="bg-white rounded-2xl p-5 shadow-sm ${recommended ? 'ring-2 ring-indigo-500' : ''} mb-3 relative">
            ${recommended ? '<span class="absolute -top-2.5 left-4 bg-indigo-600 text-white text-xs px-2 py-0.5 rounded-full">Популярный</span>' : ''}
            <div class="flex items-center justify-between mb-3">
                <div class="flex items-center gap-2">
                    <span class="text-2xl">${icon}</span>
                    <div>
                        <p class="font-bold text-gray-900">${title}</p>
                        <p class="text-xs text-gray-400">${price.stars}⭐ ≈ $${price.usd}/мес</p>
                    </div>
                </div>
            </div>
            <ul class="text-sm text-gray-700 space-y-1.5 mb-4">
                ${features.map(f => `<li class="flex items-start gap-2"><span class="text-green-500">✓</span><span>${f}</span></li>`).join('')}
            </ul>
            <button class="upgrade-btn w-full bg-indigo-600 text-white py-2.5 rounded-xl font-semibold active:scale-95 transition"
                    data-tier="${key}" data-stars="${price.stars}">
                Купить за ${price.stars}⭐
            </button>
        </div>`;

    return `
        <div class="px-4 pt-5 pb-6">
            <div class="flex items-center justify-between mb-4">
                <h1 class="text-2xl font-bold text-gray-900">Поднять план</h1>
                <button id="back-to-plan" class="text-indigo-600 text-sm">← План</button>
            </div>

            ${tierCard('premium', '💎', 'Premium', premium, [
                '17 трат / день (≈500/мес)',
                '300 вопросов AI-финансисту в месяц',
                '30 фото чеков в месяц',
                'Голос: 60/мес',
                'История 12 месяцев',
                'Импорт CSV и экспорт (3/мес)',
            ], true)}

            ${tierCard('pro', '🚀', 'Pro', pro, [
                '100 трат / день (≈3000/мес)',
                '1500 вопросов AI-финансисту в месяц',
                '150 фото чеков в месяц',
                'Голос: 200/мес',
                'История 24 месяца, 100 категорий',
                'Экспорт 10/мес',
            ], false)}

            <p class="text-xs text-gray-400 text-center mt-4">
                Оплата через Telegram Stars. Подключение в работе — кнопки временно открывают подтверждение.
            </p>
        </div>`;
}

function attachUpgradeHandlers() {
    document.getElementById('back-to-plan')?.addEventListener('click', () => {
        state.screen = 'plan';
        render();
    });
    document.querySelectorAll('.upgrade-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tier  = btn.dataset.tier;
            const stars = btn.dataset.stars;
            // TODO: следующим коммитом — Telegram.WebApp.openInvoice(url) после генерации invoice на бэке.
            if (tg?.showAlert) {
                tg.showAlert(
                    `Оплата ${tier === 'pro' ? 'Pro' : 'Premium'} за ${stars}⭐ скоро будет доступна. ` +
                    `Платежи через Telegram Stars подключаются на этой неделе.`
                );
            } else {
                alert(`Оплата ${tier} за ${stars}⭐ скоро будет доступна.`);
            }
        });
    });
}

// ============================================================
// ЗАПУСК
// ============================================================
init();
