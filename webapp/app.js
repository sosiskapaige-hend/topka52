/**
 * Quantum WebApp — Main Application Script
 */

/* ── Telegram WebApp Init ────────────────────────────────────────── */
const tg = window.Telegram?.WebApp;
if (tg) {
    tg.ready();
    tg.expand();
    tg.setHeaderColor('#8B5CF6');
    tg.setBackgroundColor('#EC4899');
}

const initData = tg?.initData || '';

/* ── State ───────────────────────────────────────────────────────── */
let state = {
    me: null,
    bundles: null,
    referrals: null,
    depositInfo: null,
    selectedCoin: null,
    balance: 0,
};

/* ── API Helper ─────────────────────────────────────────────────── */
async function api(method, path, body = null) {
    const opts = {
        method,
        headers: {
            'Content-Type': 'application/json',
            'X-TG-INIT-DATA': initData,
        }
    };
    if (body) opts.body = JSON.stringify(body);
    try {
        const res = await fetch(path, opts);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Ошибка сервера');
        return data;
    } catch (e) {
        throw e;
    }
}

const get  = (path)        => api('GET',  path);
const post = (path, body)  => api('POST', path, body);

/* ── Toast ───────────────────────────────────────────────────────── */
let toastTimer = null;
function showToast(msg, isError = false) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    if (isError) t.classList.add('toast-error');
    else t.classList.remove('toast-error');
    t.classList.add('show');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), 2500);
    if (tg?.HapticFeedback) {
        tg.HapticFeedback.notificationOccurred(isError ? 'error' : 'success');
    }
}

/* ── Clipboard ────────────────────────────────────────────────────── */
function copyText(text, label = 'Скопировано') {
    navigator.clipboard.writeText(text).then(() => showToast(label));
}

/* ── Tab Navigation ─────────────────────────────────────────────── */
let currentTab = 'wallet';

function switchTab(tab) {
    if (currentTab === tab) return;
    currentTab = tab;

    document.querySelectorAll('.tab-content').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.tab-item').forEach(n => n.classList.remove('active'));

    document.getElementById(`tab-${tab}`).classList.add('active');
    document.getElementById(`nav-${tab}`).classList.add('active');

    if (tab === 'wallet')  loadWallet();
    if (tab === 'bundles') loadBundles();
    if (tab === 'more')    loadMore();

    if (tg?.HapticFeedback) tg.HapticFeedback.selectionChanged();
}

/* ── Screen Navigation ───────────────────────────────────────────── */
let currentScreen = null;

function openScreen(id) {
    closeScreen(false);
    const screen = document.getElementById(id);
    if (!screen) return;
    screen.classList.add('open');
    currentScreen = id;

    if (tg?.BackButton) {
        tg.BackButton.show();
        tg.BackButton.onClick(closeScreen);
    }
}

function closeScreen(andBackBtn = true) {
    if (currentScreen) {
        document.getElementById(currentScreen)?.classList.remove('open');
        currentScreen = null;
    }
    if (andBackBtn && tg?.BackButton) {
        tg.BackButton.hide();
    }
}

/* ── Bottom Sheet ───────────────────────────────────────────────── */
function openBottomSheet() {
    document.getElementById('bottom-sheet').classList.add('open');
}
function closeBottomSheet(e) {
    if (e && e.target !== document.getElementById('bottom-sheet')) return;
    document.getElementById('bottom-sheet').classList.remove('open');
    state.selectedCoin = null;
}

/* ── Wallet Tab ─────────────────────────────────────────────────── */
async function loadWallet() {
    try {
        const me = await get('/api/me');
        state.me = me;
        state.balance = me.balance;
        updateWalletUI(me);
    } catch (e) {
        console.error(e);
    }
}

function updateWalletUI(me) {
    const bal = me.balance.toFixed(4);
    document.getElementById('wallet-balance').textContent = bal;
    document.getElementById('header-balance-value').textContent = `БАЛАНС ${bal} USDT`;

    const plusBadge = document.getElementById('plus-badge');
    plusBadge.style.display = me.subscription_active ? 'block' : 'none';

    const limit = me.subscription_active ? 300 : 100;
    const done  = me.operations_done || 0;
    document.getElementById('wallet-limit').textContent = `${done}/${limit}`;

    // Load transactions to calculate real stats
    loadHistory();
}

async function loadHistory() {
    try {
        const data = await get('/api/transactions');
        const history = data.history || [];
        renderHistory(history);
        
        // Calculate real stats
        let profit24h = 0;
        let totalProfit = 0;
        let totalAmount = 0;
        const now = Date.now() / 1000;
        
        history.forEach(h => {
            const p = h.profit || 0;
            totalProfit += p;
            totalAmount += h.amount || 0;
            
            if (h.start_time && (now - h.start_time) <= 86400) {
                profit24h += p;
            }
        });
        
        const avgPercent = totalAmount > 0 ? (totalProfit / totalAmount * 100) : 0;
        
        // Update stats UI
        const stat24h = document.getElementById('stat-24h');
        const statAvg = document.getElementById('stat-avg');
        if (stat24h) stat24h.textContent = `${profit24h.toFixed(2)} USDT`;
        if (statAvg) statAvg.textContent  = `${avgPercent.toFixed(1)}%`;
        
    } catch { /* silent */ }
}

function renderHistory(history) {
    const list = document.getElementById('history-list');
    if (!history.length) {
        list.innerHTML = '<div class="empty-state">Нет операций</div>';
        return;
    }
    list.innerHTML = history.slice(-20).reverse().map(h => {
        const profit = (h.profit || 0).toFixed(4);
        const date   = h.start_time ? new Date(h.start_time * 1000).toLocaleDateString('ru') : '—';
        return `
            <div class="history-item">
                <div>
                    <div class="hi-coin">${h.coin}</div>
                    <div class="hi-date">${date}</div>
                </div>
                <div class="hi-profit">+${profit} USDT</div>
            </div>`;
    }).join('');
}

/* ── Deposit ─────────────────────────────────────────────────────── */
async function showDeposit() {
    openScreen('screen-deposit');
    // Generate a unique deposit amount based on user system_id
    const sysId = state.me?.system_id || '';
    const cents  = sysId.split('').reduce((a, c) => a + c.charCodeAt(0), 0) % 100;
    const amount = (100 + cents / 100).toFixed(2);
    state.depositInfo = { amount, address: '0xf26222c49108635a7a00797c98a5416e5b9cd15a' };
    document.getElementById('deposit-amount-display').textContent = `${amount} USDT`;
    document.getElementById('deposit-address-display').textContent = state.depositInfo.address;
}

function copyDepositAmount() {
    if (!state.depositInfo) return;
    copyText(state.depositInfo.amount, 'Сумма скопирована');
}

function copyDepositAddress() {
    if (!state.depositInfo) return;
    copyText(state.depositInfo.address, 'Адрес скопирован');
}

/* ── Withdraw ───────────────────────────────────────────────────── */
function showWithdraw() {
    openScreen('screen-withdraw');
    const bal = (state.balance || 0).toFixed(4);
    document.getElementById('withdraw-alert').innerHTML = `Минимальная сумма вывода: <b>30.0 USDT</b>. Ваш баланс: <b>${bal} USDT</b>`;
}

async function submitWithdraw() {
    const address = document.getElementById('withdraw-address').value.trim();
    const amount  = parseFloat(document.getElementById('withdraw-amount').value);
    if (!address) { showToast('Введите адрес кошелька', true); return; }
    if (!amount || amount < 30) { showToast('Минимальная сумма — 30 USDT', true); return; }
    if (amount > state.balance) { showToast('Недостаточно средств', true); return; }
    
    try {
        await post('/api/withdraw', { amount, address });
        showToast('Заявка на вывод отправлена!');
        state.balance -= amount; // Optimistic update
        updateWalletUI(state.me);
        setTimeout(closeScreen, 1500);
    } catch (e) {
        showToast(e.message || 'Ошибка вывода', true);
    }
}

/* ── Transactions Screen ─────────────────────────────────────────── */
function showTransactions() {
    // Just scroll wallet to history
    switchTab('wallet');
    setTimeout(() => {
        document.getElementById('history-list')?.scrollIntoView({ behavior: 'smooth' });
    }, 100);
}

/* ── Bundles Tab ─────────────────────────────────────────────────── */
async function loadBundles() {
    try {
        const data = await get('/api/bundles');
        state.bundles = data;
        renderBundleGrid(data.available_coins);
        renderActiveBundles(data.active_bundles);
    } catch (e) {
        console.error(e);
        document.getElementById('bundles-grid').innerHTML = '<div class="empty-state">Не удалось загрузить данные</div>';
    }
}

function renderBundleGrid(coins) {
    const grid = document.getElementById('bundles-grid');
    if (!coins || !coins.length) {
        grid.innerHTML = '<div class="empty-state" style="grid-column:span 2">Нет доступных монет</div>';
        return;
    }
    grid.innerHTML = coins.map(c => {
        const cfg = c.config; // tuple: (ex1, ex2, spread, min, max, ...)
        const minAmt = Array.isArray(cfg) ? cfg[3] : 10;
        return `
            <div class="bundle-card" onclick="selectBundle('${c.ticker}')">
                <div class="bundle-ticker">${c.ticker}</div>
                <div class="bundle-spread">${c.spread}</div>
                <div class="bundle-min">${minAmt} USDT</div>
                <div class="bundle-arrow">›</div>
            </div>`;
    }).join('');
}

function renderActiveBundles(active) {
    const list = document.getElementById('active-bundles-list');
    if (!active || !active.length) {
        list.innerHTML = '<div class="empty-state">Нет активных связок</div>';
        return;
    }
    list.innerHTML = active.map(b => {
        const pct    = (b.progress || 0).toFixed(0);
        const profit = (b.current_profit || 0).toFixed(4);
        return `
            <div class="active-bundle-card">
                <div class="ab-header">
                    <div class="ab-coin">${b.coin}</div>
                    <div class="ab-profit">+${profit} USDT</div>
                </div>
                <div class="ab-bar"><div class="ab-bar-fill" style="width:${pct}%"></div></div>
            </div>`;
    }).join('');
}

function selectBundle(ticker) {
    state.selectedCoin = ticker;
    const bundleData = state.bundles?.available_coins?.find(c => c.ticker === ticker);
    if (!bundleData) return;

    const cfg = bundleData.config;
    const spread = bundleData.spread;
    const minAmt = Array.isArray(cfg) ? cfg[3] : 10;
    const ex1    = Array.isArray(cfg) ? cfg[0] : '';
    const ex2    = Array.isArray(cfg) ? cfg[1] : '';

    document.getElementById('bs-title').textContent    = `${ex1} → ${ex2}`;
    document.getElementById('bs-subtitle').textContent = `${ticker} · ${spread} · минимум ${minAmt} USDT`;

    const bal = (state.balance || 0).toFixed(4);
    document.getElementById('launch-balance-hint').textContent = `Баланс: ${bal} USDT`;
    document.getElementById('launch-amount').value = '';

    openBottomSheet();
    if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
}

function setMaxAmount() {
    document.getElementById('launch-amount').value = (state.balance || 0).toFixed(2);
}

async function submitLaunch() {
    const coin   = state.selectedCoin;
    const amount = parseFloat(document.getElementById('launch-amount').value);

    if (!coin)   { showToast('Монета не выбрана', true); return; }
    if (!amount) { showToast('Введите сумму', true); return; }

    try {
        await post('/api/bundles/launch', { coin, amount });
        showToast(`Связка ${coin} запущена!`);
        closeBottomSheet();
        setTimeout(() => { loadBundles(); loadWallet(); }, 800);
        if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
    } catch (e) {
        showToast(e.message || 'Ошибка запуска', true);
    }
}

/* ── More Tab ────────────────────────────────────────────────────── */
function loadMore() {
    if (!state.me) {
        loadWallet().then(updateMoreProfile);
        return;
    }
    updateMoreProfile();
}

function updateMoreProfile() {
    const me = state.me;
    if (!me) return;
    const name = [me.first_name, me.last_name].filter(Boolean).join(' ');
    document.getElementById('profile-name').textContent    = name || 'Пользователь';
    document.getElementById('profile-sys-id').textContent  = me.system_id || '—';
    document.getElementById('profile-tg-id').textContent   = me.telegram_id || '—';
}

/* ── Referrals ───────────────────────────────────────────────────── */
async function showReferrals() {
    openScreen('screen-referrals');
    try {
        const data = await get('/api/referrals');
        state.referrals = data;
        document.getElementById('ref-count').textContent = data.referral_count || 0;
        document.getElementById('ref-bonus').textContent = (data.referral_bonus || 0).toFixed(2);
        document.getElementById('ref-link-display').textContent = data.link || '—';
    } catch {
        document.getElementById('ref-link-display').textContent = 'Ошибка загрузки';
    }
}

function copyRefLink() {
    const link = document.getElementById('ref-link-display').textContent;
    if (link && link !== '—') copyText(link, 'Ссылка скопирована');
}

/* ── Support ─────────────────────────────────────────────────────── */
function showSupport() {
    openScreen('screen-support');
    document.getElementById('support-input').focus();
}

async function sendSupportMessage() {
    const input   = document.getElementById('support-input');
    const message = input.value.trim();
    if (!message) return;

    // Append outgoing message immediately
    appendChatMessage(message, 'outgoing');
    input.value = '';

    try {
        const data = await post('/api/support', { message });
        appendChatMessage(`✅ Обращение #${data.ticket_id} принято! Ответим в ближайшее время.`, 'incoming');
        if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
    } catch (e) {
        appendChatMessage(`❌ ${e.message || 'Не удалось отправить'}`, 'incoming');
    }
}

function appendChatMessage(text, direction) {
    const container = document.getElementById('support-messages');
    const div = document.createElement('div');
    div.className = `message ${direction}`;
    div.innerHTML = `<div class="message-text">${text}</div>`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

// Allow Enter key in support input and ensure correct menu bindings
document.addEventListener('DOMContentLoaded', () => {
    const supportInput = document.getElementById('support-input');
    if (supportInput) {
        supportInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendSupportMessage();
            }
        });
    }

    // Re-bind menu items explicitly by id to avoid stale/cached incorrect handlers
    const miSupport = document.getElementById('menu-support');
    const miFAQ = document.getElementById('menu-faq');
    // Prevent accidental double-activation: debounce menu clicks for 600ms
    let _lastMenuClick = 0;
    function handleMenuClick(fn) {
        return function (e) {
            e.preventDefault();
            e.stopPropagation();
            const now = Date.now();
            if (now - _lastMenuClick < 600) return; // ignore rapid second click
            _lastMenuClick = now;
            try { fn(); } catch (err) { console.error(err); }
        };
    }

    if (miSupport) {
        miSupport.removeAttribute('onclick');
        miSupport.addEventListener('click', handleMenuClick(showSupport));
    }
    if (miFAQ) {
        miFAQ.removeAttribute('onclick');
        miFAQ.addEventListener('click', handleMenuClick(showFAQ));
    }
});

/* ── Info & FAQ ──────────────────────────────────────────────────── */
function showInfo() { openScreen('screen-info'); }
function showFAQ()  { openScreen('screen-faq'); }

function toggleAccordion(item) {
    const content = item.querySelector('.accordion-content');
    const isOpen  = item.classList.contains('open');
    // Close all
    document.querySelectorAll('.accordion-item.open').forEach(el => {
        el.classList.remove('open');
        el.querySelector('.accordion-content').style.display = 'none';
    });
    // Open clicked if it wasn't open
    if (!isOpen) {
        item.classList.add('open');
        content.style.display = 'block';
        if (tg?.HapticFeedback) tg.HapticFeedback.selectionChanged();
    }
}

/* ── Auto-refresh active bundles ─────────────────────────────────── */
setInterval(() => {
    if (currentTab === 'bundles' && state.bundles) {
        get('/api/bundles').then(data => {
            state.bundles = data;
            renderActiveBundles(data.active_bundles);
        }).catch(() => {});
    }
}, 5000);

/* ── Init ────────────────────────────────────────────────────────── */
async function init() {
    // On first load show wallet tab
    await loadWallet();
}

init().catch(console.error);
