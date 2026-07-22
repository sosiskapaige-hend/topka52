/**
 * Quantum WebApp
 */

/* ── Telegram WebApp Init ─────────────────────────────────────────── */
const tg = window.Telegram?.WebApp;
if (tg) {
    tg.ready();
    tg.expand();
    tg.setHeaderColor('#8B5CF6');
    tg.setBackgroundColor('#EC4899');
}

const initData = tg?.initData || '';

/* ── State ────────────────────────────────────────────────────────── */
const state = {
    me: null,
    bundles: null,
    balance: 0,
};

/* ── API ──────────────────────────────────────────────────────────── */
async function api(method, path, body = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json', 'X-TG-INIT-DATA': initData },
    };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || 'Ошибка сервера');
    return data;
}
const get  = path       => api('GET',  path);
const post = (path, b)  => api('POST', path, b);

/* ── Toast ────────────────────────────────────────────────────────── */
let _toastTimer = null;
function showToast(msg, isError = false) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.toggle('toast-error', isError);
    t.classList.add('show');
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => t.classList.remove('show'), 2500);
    tg?.HapticFeedback?.notificationOccurred(isError ? 'error' : 'success');
}

function copyText(text, label = 'Скопировано') {
    navigator.clipboard.writeText(text).then(() => showToast(label));
}

/* ── Tab Navigation ───────────────────────────────────────────────── */
let currentTab = 'wallet';

function switchTab(tab) {
    if (currentTab === tab) return;
    currentTab = tab;
    document.querySelectorAll('.tab-content').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.tab-item').forEach(n => n.classList.remove('active'));
    document.getElementById(`tab-${tab}`)?.classList.add('active');
    document.getElementById(`nav-${tab}`)?.classList.add('active');
    if (tab === 'wallet')  loadWallet();
    if (tab === 'bundles') loadBundles();
    if (tab === 'more')    loadMore();
    tg?.HapticFeedback?.selectionChanged();
}

/* ── Screen Navigation ────────────────────────────────────────────── */
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
    if (andBackBtn && tg?.BackButton) tg.BackButton.hide();
}

/* ── Bottom Sheet ─────────────────────────────────────────────────── */
function openBottomSheet()  { document.getElementById('bottom-sheet').classList.add('open'); }
function closeBottomSheet(e) {
    if (e && e.target !== document.getElementById('bottom-sheet')) return;
    document.getElementById('bottom-sheet').classList.remove('open');
    state.selectedCoin = null;
}

/* ── Wallet Tab ───────────────────────────────────────────────────── */
async function loadWallet() {
    try {
        const me = await get('/api/me');
        state.me = me;
        state.balance = me.balance;
        updateWalletUI(me);
    } catch (e) {
        console.error('loadWallet:', e);
    }
}

function updateWalletUI(me) {
    const bal = me.balance.toFixed(4);
    document.getElementById('wallet-balance').textContent = bal;
    document.getElementById('header-balance-value').textContent = `БАЛАНС ${bal} USDT`;

    document.getElementById('plus-badge').style.display = me.subscription_active ? 'block' : 'none';

    const limit = me.operations_limit || (me.subscription_active ? 300 : 100);
    document.getElementById('wallet-limit').textContent = `${me.operations_done || 0}/${limit}`;

    const depPct = Math.round((me.deposit_commission || 0.07) * 100);
    const wdPct  = Math.round((me.withdraw_commission || 0.08) * 100);
    const commEl = document.getElementById('wallet-commission-info');
    if (commEl) {
        commEl.textContent = me.subscription_active
            ? `Комиссия пополнения: ${depPct}% (Quantum+) · Вывод: ${wdPct}%`
            : `Комиссия пополнения: ${depPct}% · Вывод: ${wdPct}%`;
    }

    loadHistory();
}

async function loadHistory() {
    try {
        const { history = [] } = await get('/api/transactions');
        renderHistory(history);
        let profit24h = 0, totalProfit = 0, totalAmount = 0;
        const now = Date.now() / 1000;
        history.forEach(h => {
            const p = h.profit || 0;
            totalProfit  += p;
            totalAmount  += h.amount || 0;
            if (h.start_time && (now - h.start_time) <= 86400) profit24h += p;
        });
        const avgPct = totalAmount > 0 ? (totalProfit / totalAmount * 100) : 0;
        const s24  = document.getElementById('stat-24h');
        const sAvg = document.getElementById('stat-avg');
        if (s24)  s24.textContent  = `${profit24h.toFixed(2)} USDT`;
        if (sAvg) sAvg.textContent = `${avgPct.toFixed(1)}%`;
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
        const label  = h.type === 'deposit' ? '💳 Пополнение' : (h.coin || '—');
        const amount = h.type === 'deposit' ? `+${(h.amount || 0).toFixed(4)}` : `+${profit}`;
        return `<div class="history-item">
            <div><div class="hi-coin">${label}</div><div class="hi-date">${date}</div></div>
            <div class="hi-profit">${amount} USDT</div>
        </div>`;
    }).join('');
}

/* ── Deposit ──────────────────────────────────────────────────────── */
function showDeposit() {
    openScreen('screen-deposit');
    const me = state.me;
    const comm = me?.deposit_commission || 0.07;
    const pct = Math.round(comm * 100);
    const credited = Math.round(100 * (1 - comm));
    const lbl = document.getElementById('deposit-commission-label');
    const ex  = document.getElementById('deposit-credited-example');
    if (lbl) lbl.textContent = `${pct}%${me?.subscription_active ? ' (Quantum+)' : ''}`;
    if (ex)  ex.textContent  = `${credited} USDT`;
}

async function submitDeposit() {
    const amount = parseFloat(document.getElementById('deposit-input-amount').value.trim());
    if (!amount || amount < 1) { showToast('Минимальная сумма: 1 USDT', true); return; }

    const btn = document.getElementById('deposit-submit-btn');
    btn.disabled = true;
    btn.textContent = 'Создаём счёт...';

    try {
        const data = await post('/api/deposit/create', { amount });
        document.getElementById('deposit-invoice-section').style.display = 'block';
        document.getElementById('deposit-input-section').style.display = 'none';
        document.getElementById('deposit-pay-amount').textContent = `${data.amount} USDT`;
        document.getElementById('deposit-credited').textContent = `${data.credited} USDT (после комиссии ${data.commission_pct}%)`;
        document.getElementById('deposit-pay-btn').onclick = () => window.open(data.pay_url, '_blank');
        tg?.HapticFeedback?.notificationOccurred('success');
    } catch (e) {
        showToast(e.message || 'Ошибка создания счёта', true);
        btn.disabled = false;
        btn.textContent = 'Создать счёт';
    }
}

function resetDepositScreen() {
    document.getElementById('deposit-invoice-section').style.display = 'none';
    document.getElementById('deposit-input-section').style.display = 'block';
    document.getElementById('deposit-input-amount').value = '';
    const btn = document.getElementById('deposit-submit-btn');
    if (btn) { btn.disabled = false; btn.textContent = 'Создать счёт'; }
}

/* ── Withdraw ─────────────────────────────────────────────────────── */
function showWithdraw() {
    openScreen('screen-withdraw');
    const me = state.me;
    const wdPct = Math.round((me?.withdraw_commission || 0.08) * 100);
    const bal = (state.balance || 0).toFixed(4);
    document.getElementById('withdraw-alert').innerHTML =
        `Мин. сумма: <b>30 USDT</b> · Комиссия: <b>${wdPct}%</b><br>Ваш баланс: <b>${bal} USDT</b>`;
}

async function submitWithdraw() {
    const address = document.getElementById('withdraw-address').value.trim();
    const amount  = parseFloat(document.getElementById('withdraw-amount').value);
    if (!address) { showToast('Введите адрес кошелька', true); return; }
    if (!amount || amount < 30) { showToast('Минимальная сумма — 30 USDT', true); return; }
    if (amount > state.balance) { showToast('Недостаточно средств', true); return; }

    const wdComm = state.me?.withdraw_commission || 0.08;
    const net = (amount * (1 - wdComm)).toFixed(4);
    if (!confirm(`Вывод: ${amount} USDT\nКомиссия ${Math.round(wdComm * 100)}%\nПолучите: ${net} USDT\n\nПодтвердить?`)) return;

    try {
        const data = await post('/api/withdraw', { amount, address });
        showToast(`Заявка создана! К выплате: ${data.net_amount} USDT`);
        state.balance -= amount;
        if (state.me) state.me.balance = state.balance;
        updateWalletUI(state.me);
        setTimeout(closeScreen, 1500);
    } catch (e) {
        showToast(e.message || 'Ошибка вывода', true);
    }
}

/* ── Bundles Tab ──────────────────────────────────────────────────── */
let _bundlesFetching = false;

async function loadBundles() {
    if (_bundlesFetching) return;
    _bundlesFetching = true;
    try {
        const data = await get('/api/bundles');
        state.bundles = data;
        renderBundleGrid(data.available_coins);
        renderActiveBundles(data.active_bundles);
    } catch (e) {
        document.getElementById('bundles-grid').innerHTML =
            '<div class="empty-state">Не удалось загрузить данные</div>';
    } finally {
        _bundlesFetching = false;
    }
}

function renderBundleGrid(coins) {
    const grid = document.getElementById('bundles-grid');
    if (!coins?.length) {
        grid.innerHTML = '<div class="empty-state" style="grid-column:span 2">Нет монет</div>';
        return;
    }
    grid.innerHTML = coins.map(c => {
        const cfg = c.config;
        const minAmt = Array.isArray(cfg) ? cfg[3] : 10;
        return `<div class="bundle-card" onclick="selectBundle('${c.ticker}')">
            <div class="bundle-ticker">${c.ticker}</div>
            <div class="bundle-spread">${c.spread}</div>
            <div class="bundle-min">${minAmt} USDT</div>
            <div class="bundle-arrow">›</div>
        </div>`;
    }).join('');
}

function renderActiveBundles(active) {
    const list = document.getElementById('active-bundles-list');
    if (!active?.length) {
        list.innerHTML = '<div class="empty-state">Нет активных связок</div>';
        return;
    }
    list.innerHTML = active.map(b => {
        const pct    = (b.progress || 0).toFixed(0);
        const profit = (b.current_profit || 0).toFixed(4);
        return `<div class="active-bundle-card">
            <div class="ab-header"><div class="ab-coin">${b.coin || '—'}</div><div class="ab-profit">+${profit} USDT</div></div>
            <div class="ab-bar"><div class="ab-bar-fill" style="width:${pct}%"></div></div>
        </div>`;
    }).join('');
}

function selectBundle(ticker) {
    state.selectedCoin = ticker;
    const bundleData = state.bundles?.available_coins?.find(c => c.ticker === ticker);
    if (!bundleData) return;
    const cfg = bundleData.config;
    const minAmt = Array.isArray(cfg) ? cfg[3] : 10;
    const ex1    = Array.isArray(cfg) ? cfg[0] : '';
    const ex2    = Array.isArray(cfg) ? cfg[1] : '';
    document.getElementById('bs-title').textContent    = `${ex1} → ${ex2}`;
    document.getElementById('bs-subtitle').textContent = `${ticker} · ${bundleData.spread} · минимум ${minAmt} USDT`;
    document.getElementById('launch-balance-hint').textContent = `Баланс: ${(state.balance || 0).toFixed(4)} USDT`;
    document.getElementById('launch-amount').value = '';
    openBottomSheet();
    tg?.HapticFeedback?.impactOccurred('medium');
}

function setMaxAmount() {
    document.getElementById('launch-amount').value = (state.balance || 0).toFixed(2);
}

async function submitLaunch() {
    const coin   = state.selectedCoin;
    const amount = parseFloat(document.getElementById('launch-amount').value);
    if (!coin)         { showToast('Монета не выбрана', true); return; }
    if (!amount || isNaN(amount)) { showToast('Введите сумму', true); return; }
    if (amount > (state.balance || 0)) { showToast('Недостаточно средств', true); return; }

    const btn = document.getElementById('launch-submit-btn');
    const origText = btn?.textContent;
    if (btn) { btn.disabled = true; btn.textContent = 'Запускаем...'; }

    try {
        await post('/api/bundles/launch', { coin, amount });
        showToast(`✅ Связка ${coin} запущена!`);
        closeBottomSheet();
        state.balance -= amount;
        if (state.me) state.me.balance = state.balance;
        setTimeout(() => { loadBundles(); loadWallet(); }, 600);
        tg?.HapticFeedback?.notificationOccurred('success');
    } catch (e) {
        const msg = e.message || 'Ошибка запуска';
        showToast(`❌ ${msg}`, true);
        tg?.HapticFeedback?.notificationOccurred('error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = origText; }
    }
}

/* ── More Tab ─────────────────────────────────────────────────────── */
function loadMore() {
    if (!state.me) { loadWallet().then(updateMoreProfile); return; }
    updateMoreProfile();
}

function updateMoreProfile() {
    const me = state.me;
    if (!me) return;
    const name = [me.first_name, me.last_name].filter(Boolean).join(' ');
    document.getElementById('profile-name').textContent   = name || 'Пользователь';
    document.getElementById('profile-sys-id').textContent = me.system_id || '—';
    document.getElementById('profile-tg-id').textContent  = me.telegram_id || '—';

    const subEl = document.getElementById('profile-subscription');
    if (subEl) {
        if (me.subscription_active) {
            const expiry = me.subscription_expiry
                ? new Date(me.subscription_expiry).toLocaleDateString('ru') : '—';
            subEl.textContent = `⭐ Quantum+ активен до ${expiry}`;
            subEl.style.color = '#8B5CF6';
        } else {
            subEl.textContent = 'Quantum+ не активен';
            subEl.style.color = '#999';
        }
    }
}

/* ── Referrals ────────────────────────────────────────────────────── */
async function showReferrals() {
    openScreen('screen-referrals');
    try {
        const data = await get('/api/referrals');
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

/* ── Support ──────────────────────────────────────────────────────── */
function showSupport() {
    openScreen('screen-support');
    setTimeout(() => document.getElementById('support-input')?.focus(), 300);
}

let _supportSending = false;

async function sendSupportMessage() {
    if (_supportSending) return;
    const input   = document.getElementById('support-input');
    const message = input.value.trim();
    if (!message) return;

    _supportSending = true;
    appendChatMessage(message, 'outgoing');
    input.value = '';

    try {
        const data = await post('/api/support', { message });
        appendChatMessage(`✅ Обращение #${data.ticket_id} принято! Ответим в ближайшее время.`, 'incoming');
        tg?.HapticFeedback?.notificationOccurred('success');
    } catch (e) {
        const msg = e.message || 'Не удалось отправить';
        // Показываем понятное сообщение вместо технического
        const friendly = msg.includes('5 минут')
            ? '⏳ Подождите 5 минут перед следующим обращением.'
            : `❌ ${msg}`;
        appendChatMessage(friendly, 'incoming');
    } finally {
        _supportSending = false;
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

/* ── Quantum+ ─────────────────────────────────────────────────────── */
function showQuantumPlus() {
    openScreen('screen-plus');
    const me = state.me;
    const depPct     = Math.round((me?.deposit_commission || 0.07) * 100);
    const wdPct      = Math.round((me?.withdraw_commission || 0.08) * 100);
    const currentLim = me?.subscription_active ? 300 : 100;

    const statusEl = document.getElementById('plus-status');
    const buyBtn   = document.getElementById('plus-buy-btn');
    if (me?.subscription_active) {
        const expiry = me.subscription_expiry
            ? new Date(me.subscription_expiry).toLocaleDateString('ru') : '—';
        if (statusEl) statusEl.innerHTML = `✅ <b>Quantum+ активен</b> до ${expiry}`;
        if (buyBtn) buyBtn.style.display = 'none';
    } else {
        if (statusEl) statusEl.innerHTML = 'Вы не подписчик Quantum+';
        if (buyBtn) buyBtn.style.display = 'block';
    }

    const infoEl = document.getElementById('plus-info');
    if (infoEl) infoEl.innerHTML = `
        <div class="info-text">
            <p>🔄 <b>300 операций</b> вместо ${currentLim}</p>
            <p>💸 Комиссия пополнения <b>3%</b> вместо ${depPct}%</p>
            <p>💸 Комиссия вывода: <b>${wdPct}%</b></p>
            <p>🚀 Приоритет обработки заявок</p>
            <p>⏳ Срок: 30 дней · Стоимость: <b>40 USDT</b></p>
        </div>`;
}

async function buyQuantumPlus() {
    const btn = document.getElementById('plus-buy-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Создаём счёт...'; }
    try {
        const data = await post('/api/plus/buy', {});
        showToast('Счёт создан!');
        window.open(data.pay_url, '_blank');
    } catch (e) {
        showToast(e.message || 'Ошибка', true);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Купить Quantum+ (40 USDT)'; }
    }
}

/* ── Info & FAQ ───────────────────────────────────────────────────── */
function showInfo() { openScreen('screen-info'); }
function showFAQ()  { openScreen('screen-faq'); }

function toggleAccordion(item) {
    const content = item.querySelector('.accordion-content');
    const isOpen  = item.classList.contains('open');
    document.querySelectorAll('.accordion-item.open').forEach(el => {
        el.classList.remove('open');
        el.querySelector('.accordion-content').style.display = 'none';
    });
    if (!isOpen) {
        item.classList.add('open');
        content.style.display = 'block';
        tg?.HapticFeedback?.selectionChanged();
    }
}

function showTransactions() {
    switchTab('wallet');
    setTimeout(() => document.getElementById('history-list')?.scrollIntoView({ behavior: 'smooth' }), 100);
}

/* ── Auto-refresh active bundles (с защитой от накопления) ────────── */
setInterval(() => {
    if (currentTab === 'bundles' && state.bundles && !_bundlesFetching) {
        _bundlesFetching = true;
        get('/api/bundles').then(data => {
            state.bundles = data;
            renderActiveBundles(data.active_bundles);
        }).catch(() => {}).finally(() => { _bundlesFetching = false; });
    }
}, 8000);

/* ── DOMContentLoaded ─────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('support-input')?.addEventListener('keypress', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendSupportMessage(); }
    });

    // Reset deposit screen when opened
    const depScreen = document.getElementById('screen-deposit');
    if (depScreen) {
        new MutationObserver(() => {
            if (depScreen.classList.contains('open')) resetDepositScreen();
        }).observe(depScreen, { attributes: true, attributeFilter: ['class'] });
    }

    // Wire More tab menu items
    const menuItems = {
        'menu-support': showSupport,
        'menu-faq':     showFAQ,
        'menu-plus':    showQuantumPlus,
    };
    let _lastClick = 0;
    Object.entries(menuItems).forEach(([id, fn]) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.removeAttribute('onclick');
        el.addEventListener('click', e => {
            e.preventDefault(); e.stopPropagation();
            const now = Date.now();
            if (now - _lastClick < 400) return;
            _lastClick = now;
            fn();
        });
    });
});

/* ── Init ─────────────────────────────────────────────────────────── */
async function init() {
    await loadWallet();
}

init().catch(console.error);
