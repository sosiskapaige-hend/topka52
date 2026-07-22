from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from bot.constants import (
    CB_ACTIVE_BUNDLES,
    CB_QUANTUM_PLUS,
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
    CB_REFERRALS,
    CB_SELECT_BUNDLE,
    CB_SUPPORT,
    CB_SUPPORT_WRITE,
    CB_TX_HISTORY,
    CB_WALLET,
    CB_WITHDRAW,
    CB_TUTORIAL_1,
    CB_TUTORIAL_2,
    CB_TUTORIAL_3,
    CB_TUTORIAL_4,
    CB_ABOUT,
    CB_TOS_1,
    CB_TOS_2,
    CB_TOS_3,
    CB_TOS_4,
    COINS,
)

BACK = "⬅️ Назад"
BACK_TO_MAIN = "⬅️ Назад"
CANCEL = "❌ Отмена"


def _row(*buttons: InlineKeyboardButton) -> list[InlineKeyboardButton]:
    return list(buttons)


def _full_width(text: str, callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([_row(InlineKeyboardButton(text, callback_data=callback_data))])


def main_menu_keyboard(webapp_url: str | None = None) -> InlineKeyboardMarkup:
    if webapp_url and webapp_url.startswith("https://"):
        app_button = InlineKeyboardButton("🚀 Открыть приложение", web_app=WebAppInfo(url=webapp_url))
    else:
        app_button = InlineKeyboardButton("🚀 Открыть приложение", callback_data=CB_OPEN_APP)

    return InlineKeyboardMarkup([
        _row(app_button),
        _row(InlineKeyboardButton("🔗 Связки", callback_data=CB_BUNDLES)),
        _row(InlineKeyboardButton("💼 Кошелек", callback_data=CB_WALLET)),
        _row(InlineKeyboardButton("📋 История операций", callback_data=CB_HISTORY)),
        _row(InlineKeyboardButton("ℹ️ Информация", callback_data=CB_INFO)),
        _row(InlineKeyboardButton("🆘 Поддержка", callback_data=CB_SUPPORT)),
        _row(InlineKeyboardButton("👥 Рефералы", callback_data=CB_REFERRALS)),
    ])

def info_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            _row(InlineKeyboardButton("📖 Обучение", callback_data=CB_TUTORIAL_1)),
            _row(InlineKeyboardButton("🏢 О проекте", callback_data=CB_ABOUT)),
            _row(InlineKeyboardButton("📜 Пользовательское соглашение", callback_data=CB_TOS_1)),
            _row(InlineKeyboardButton(BACK, callback_data=CB_MAIN)),
        ]
    )

def tutorial_1_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        _row(InlineKeyboardButton("Далее ▶️", callback_data=CB_TUTORIAL_2))
    ])

def tutorial_2_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        _row(
            InlineKeyboardButton("◀️ Назад", callback_data=CB_TUTORIAL_1),
            InlineKeyboardButton("Далее ▶️", callback_data=CB_TUTORIAL_3)
        )
    ])

def tutorial_3_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        _row(
            InlineKeyboardButton("◀️ Назад", callback_data=CB_TUTORIAL_2),
            InlineKeyboardButton("Далее ▶️", callback_data=CB_TUTORIAL_4)
        )
    ])

def tutorial_4_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        _row(InlineKeyboardButton("◀️ Назад", callback_data=CB_TUTORIAL_3)),
        _row(InlineKeyboardButton("✅ Завершить обучение", callback_data=CB_MAIN))
    ])

def tos_1_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        _row(InlineKeyboardButton("Далее ▶️", callback_data=CB_TOS_2))
    ])

def tos_2_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        _row(
            InlineKeyboardButton("◀️ Назад", callback_data=CB_TOS_1),
            InlineKeyboardButton("Далее ▶️", callback_data=CB_TOS_3)
        )
    ])

def tos_3_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        _row(
            InlineKeyboardButton("◀️ Назад", callback_data=CB_TOS_2),
            InlineKeyboardButton("Далее ▶️", callback_data=CB_TOS_4)
        )
    ])

def tos_4_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        _row(InlineKeyboardButton("◀️ Назад", callback_data=CB_TOS_3)),
        _row(InlineKeyboardButton("✅ Принять соглашение", callback_data=CB_INFO))
    ])


def bundles_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            _row(InlineKeyboardButton("📊 Выбрать связку", callback_data=CB_SELECT_BUNDLE)),
            _row(InlineKeyboardButton("⚡ Активные связки", callback_data=CB_ACTIVE_BUNDLES)),
            _row(InlineKeyboardButton(BACK, callback_data=CB_MAIN)),
        ]
    )


def select_bundle_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []

    for ticker, spread in COINS:
        label = f"{ticker} ({spread})"
        button = InlineKeyboardButton(label, callback_data=f"{CB_COIN_PREFIX}{ticker}")
        pair.append(button)
        if len(pair) == 2:
            rows.append(pair)
            pair = []

    if pair:
        rows.append(pair)

    rows.append(_row(InlineKeyboardButton(BACK, callback_data=CB_BUNDLES)))
    return InlineKeyboardMarkup(rows)


def active_bundles_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([_row(InlineKeyboardButton(BACK, callback_data=CB_BUNDLES))])


def wallet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            _row(InlineKeyboardButton("➕ Пополнить", callback_data=CB_DEPOSIT)),
            _row(InlineKeyboardButton("📤 Вывести", callback_data=CB_WITHDRAW)),
            _row(InlineKeyboardButton("📄 История транзакций", callback_data=CB_TX_HISTORY)),
            _row(InlineKeyboardButton("⭐ Quantum+", callback_data=CB_QUANTUM_PLUS)),
            _row(InlineKeyboardButton(BACK, callback_data=CB_MAIN)),
        ]
    )


def deposit_awaiting_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            _row(InlineKeyboardButton(CANCEL, callback_data=CB_DEPOSIT_CANCEL)),
            _row(InlineKeyboardButton(BACK_TO_MAIN, callback_data=CB_MAIN)),
        ]
    )


def deposit_requisites_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([_row(InlineKeyboardButton(BACK_TO_MAIN, callback_data=CB_MAIN))])


def referral_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([_row(InlineKeyboardButton(BACK, callback_data=CB_MAIN))])


def plus_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            _row(InlineKeyboardButton("📋 О подписке", callback_data=CB_PLUS_ABOUT)),
            _row(InlineKeyboardButton("💳 Купить Quantum+", callback_data=CB_PLUS_BUY)),
            _row(InlineKeyboardButton(BACK, callback_data=CB_WALLET)),
        ]
    )


def plus_about_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            _row(InlineKeyboardButton("💳 Купить Quantum+", callback_data=CB_PLUS_BUY)),
            _row(InlineKeyboardButton(BACK, callback_data=CB_QUANTUM_PLUS)),
        ]
    )


def plus_buy_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([_row(InlineKeyboardButton(BACK, callback_data=CB_QUANTUM_PLUS))])


def back_to_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([_row(InlineKeyboardButton(BACK_TO_MAIN, callback_data=CB_MAIN))])


def back_to_wallet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([_row(InlineKeyboardButton(BACK, callback_data=CB_WALLET))])


def back_to_bundles_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([_row(InlineKeyboardButton(BACK, callback_data=CB_BUNDLES))])


def back_to_select_bundle_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([_row(InlineKeyboardButton(BACK, callback_data=CB_SELECT_BUNDLE))])


def bundle_launch_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            _row(InlineKeyboardButton(CANCEL, callback_data=CB_BUNDLES)),
            _row(InlineKeyboardButton("⬅️ К связкам", callback_data=CB_SELECT_BUNDLE)),
        ]
    )


def active_bundles_refresh_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            _row(InlineKeyboardButton("🔄 Обновить", callback_data=CB_ACTIVE_BUNDLES)),
            _row(InlineKeyboardButton(BACK, callback_data=CB_BUNDLES)),
        ]
    )

def support_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        _row(InlineKeyboardButton("✉️ Написать в поддержку", callback_data=CB_SUPPORT_WRITE)),
        _row(InlineKeyboardButton("⬅️ Назад", callback_data=CB_MAIN))
    ])

def support_write_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        _row(InlineKeyboardButton("❌ Отмена", callback_data=CB_SUPPORT)),
        _row(InlineKeyboardButton("⬅️ Главное меню", callback_data=CB_MAIN))
    ])

def about_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        _row(InlineKeyboardButton("⬅️ Назад", callback_data=CB_INFO))
    ])
