from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from bot.constants import (
    CB_ABOUT,
    CB_ACTIVE_BUNDLES,
    CB_BUNDLES,
    CB_COIN_PREFIX,
    CB_DEPOSIT,
    CB_DEPOSIT_CANCEL,
    CB_HISTORY,
    CB_INFO,
    CB_MAIN,
    CB_OPEN_APP,
    CB_PLUS_ABOUT,
    CB_PLUS_BUY,
    CB_QUANTUM_PLUS,
    CB_REFERRALS,
    CB_SELECT_BUNDLE,
    CB_SUPPORT,
    CB_SUPPORT_WRITE,
    CB_TOS_1,
    CB_TOS_2,
    CB_TOS_3,
    CB_TOS_4,
    CB_TUTORIAL_1,
    CB_TUTORIAL_2,
    CB_TUTORIAL_3,
    CB_TUTORIAL_4,
    CB_TX_HISTORY,
    CB_WALLET,
    CB_WITHDRAW,
    COINS,
)

BACK = "⬅️ Назад"
CANCEL = "❌ Отмена"


def main_menu_keyboard(webapp_url: str | None = None) -> InlineKeyboardMarkup:
    if webapp_url and webapp_url.startswith("https://"):
        app_button = InlineKeyboardButton("🚀 Открыть приложение", web_app=WebAppInfo(url=webapp_url))
    else:
        app_button = InlineKeyboardButton("🚀 Открыть приложение", callback_data=CB_OPEN_APP)
    return InlineKeyboardMarkup([
        [app_button],
        [InlineKeyboardButton("🔗 Связки", callback_data=CB_BUNDLES)],
        [InlineKeyboardButton("💼 Кошелек", callback_data=CB_WALLET)],
        [InlineKeyboardButton("📋 История операций", callback_data=CB_HISTORY)],
        [InlineKeyboardButton("ℹ️ Информация", callback_data=CB_INFO)],
        [InlineKeyboardButton("🆘 Поддержка", callback_data=CB_SUPPORT)],
        [InlineKeyboardButton("👥 Рефералы", callback_data=CB_REFERRALS)],
    ])


def info_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Обучение", callback_data=CB_TUTORIAL_1)],
        [InlineKeyboardButton("🏢 О проекте", callback_data=CB_ABOUT)],
        [InlineKeyboardButton("📜 Пользовательское соглашение", callback_data=CB_TOS_1)],
        [InlineKeyboardButton(BACK, callback_data=CB_MAIN)],
    ])


def tutorial_1_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Далее ▶️", callback_data=CB_TUTORIAL_2)]])


def tutorial_2_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Назад", callback_data=CB_TUTORIAL_1),
        InlineKeyboardButton("Далее ▶️", callback_data=CB_TUTORIAL_3),
    ]])


def tutorial_3_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Назад", callback_data=CB_TUTORIAL_2),
        InlineKeyboardButton("Далее ▶️", callback_data=CB_TUTORIAL_4),
    ]])


def tutorial_4_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Назад", callback_data=CB_TUTORIAL_3)],
        [InlineKeyboardButton("✅ Завершить обучение", callback_data=CB_MAIN)],
    ])


def tos_1_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Далее ▶️", callback_data=CB_TOS_2)]])


def tos_2_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Назад", callback_data=CB_TOS_1),
        InlineKeyboardButton("Далее ▶️", callback_data=CB_TOS_3),
    ]])


def tos_3_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Назад", callback_data=CB_TOS_2),
        InlineKeyboardButton("Далее ▶️", callback_data=CB_TOS_4),
    ]])


def tos_4_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Назад", callback_data=CB_TOS_3)],
        [InlineKeyboardButton("✅ Принять соглашение", callback_data=CB_INFO)],
    ])


def bundles_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Выбрать связку", callback_data=CB_SELECT_BUNDLE)],
        [InlineKeyboardButton("⚡ Активные связки", callback_data=CB_ACTIVE_BUNDLES)],
        [InlineKeyboardButton(BACK, callback_data=CB_MAIN)],
    ])


def select_bundle_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for ticker, spread in COINS:
        pair.append(InlineKeyboardButton(f"{ticker} ({spread})", callback_data=f"{CB_COIN_PREFIX}{ticker}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([InlineKeyboardButton(BACK, callback_data=CB_BUNDLES)])
    return InlineKeyboardMarkup(rows)


def active_bundles_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(BACK, callback_data=CB_BUNDLES)]])


def active_bundles_refresh_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить", callback_data=CB_ACTIVE_BUNDLES)],
        [InlineKeyboardButton(BACK, callback_data=CB_BUNDLES)],
    ])


def bundle_launch_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(CANCEL, callback_data=CB_BUNDLES)],
        [InlineKeyboardButton("⬅️ К связкам", callback_data=CB_SELECT_BUNDLE)],
    ])


def wallet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Пополнить", callback_data=CB_DEPOSIT)],
        [InlineKeyboardButton("📤 Вывести", callback_data=CB_WITHDRAW)],
        [InlineKeyboardButton("📄 История транзакций", callback_data=CB_TX_HISTORY)],
        [InlineKeyboardButton("⭐ Quantum+", callback_data=CB_QUANTUM_PLUS)],
        [InlineKeyboardButton(BACK, callback_data=CB_MAIN)],
    ])


def deposit_awaiting_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(CANCEL, callback_data=CB_DEPOSIT_CANCEL)],
        [InlineKeyboardButton(BACK, callback_data=CB_MAIN)],
    ])


def deposit_requisites_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(BACK, callback_data=CB_MAIN)]])


def referral_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(BACK, callback_data=CB_MAIN)]])


def plus_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 О подписке", callback_data=CB_PLUS_ABOUT)],
        [InlineKeyboardButton("💳 Купить Quantum+", callback_data=CB_PLUS_BUY)],
        [InlineKeyboardButton(BACK, callback_data=CB_WALLET)],
    ])


def plus_about_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Купить Quantum+", callback_data=CB_PLUS_BUY)],
        [InlineKeyboardButton(BACK, callback_data=CB_QUANTUM_PLUS)],
    ])


def plus_buy_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(BACK, callback_data=CB_QUANTUM_PLUS)]])


def back_to_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(BACK, callback_data=CB_MAIN)]])


def back_to_wallet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(BACK, callback_data=CB_WALLET)]])


def back_to_bundles_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(BACK, callback_data=CB_BUNDLES)]])


def back_to_select_bundle_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(BACK, callback_data=CB_SELECT_BUNDLE)]])


def support_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✉️ Написать в поддержку", callback_data=CB_SUPPORT_WRITE)],
        [InlineKeyboardButton(BACK, callback_data=CB_MAIN)],
    ])


def support_write_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(CANCEL, callback_data=CB_SUPPORT)],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data=CB_MAIN)],
    ])


def about_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(BACK, callback_data=CB_INFO)]])
