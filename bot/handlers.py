from __future__ import annotations

import logging
import html

from telegram import Update, User, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ContextTypes, ConversationHandler

logger = logging.getLogger(__name__)

import uuid
import random
import time
import string

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
    CB_ADMIN_PANEL,
    COINS,
    OPERATIONS_LIMIT,
    BUNDLE_CONFIG,
    DEPOSIT_AMOUNT,
    BUNDLE_AMOUNT,
    SUPPORT_MESSAGE,
    WITHDRAW_AMOUNT,
    WITHDRAW_ADDRESS,
    DEPOSIT_COMMISSION,
    DEPOSIT_COMMISSION_PLUS,
    WITHDRAW_COMMISSION,
    PLUS_SUBSCRIPTION_PRICE,
)
from bot.keyboards import (
    active_bundles_keyboard,
    active_bundles_refresh_keyboard,
    back_to_bundles_keyboard,
    back_to_main_keyboard,
    back_to_select_bundle_keyboard,
    back_to_wallet_keyboard,
    bundle_launch_keyboard,
    bundles_keyboard,
    deposit_awaiting_keyboard,
    deposit_requisites_keyboard,
    main_menu_keyboard,
    plus_about_keyboard,
    plus_buy_keyboard,
    plus_keyboard,
    referral_keyboard,
    select_bundle_keyboard,
    wallet_keyboard,
    info_keyboard,
    tutorial_1_keyboard,
    tutorial_2_keyboard,
    tutorial_3_keyboard,
    tutorial_4_keyboard,
    tos_1_keyboard,
    tos_2_keyboard,
    tos_3_keyboard,
    tos_4_keyboard,
    support_main_keyboard,
    support_write_keyboard,
    about_keyboard,
)
from bot.storage import UserStorage
from bot import texts

# Conversation state for Quantum+ purchase
PLUS_BUY_AMOUNT = 7

def _format_user_line(user: User) -> str:
    """Format user info into a readable line: Name @username (id)."""
    name = user.first_name or ""
    if user.last_name:
        name = f"{name} {user.last_name}".strip()
    name = html.escape(name)
    if user.username:
        username = html.escape(user.username)
        return f"{name} @{username} ({user.id})"
    return f"{name} ({user.id})"


def _webapp_url(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    """Get WebApp URL from bot_data."""
    return context.application.bot_data.get("webapp_url")


def _storage(context: ContextTypes.DEFAULT_TYPE) -> UserStorage:
    """Get UserStorage instance from bot_data."""
    return context.application.bot_data["storage"]


async def _safe_edit_message_text(query, text: str, reply_markup=None, parse_mode: str | None = None) -> None:
    """Safely edit message text handling 'Message is not modified' error."""
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            raise


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool) -> None:
    """Display main menu. Either edit existing message or send new."""
    text = texts.MAIN_MENU
    keyboard = main_menu_keyboard(_webapp_url(context))
    if edit and update.callback_query:
        await _safe_edit_message_text(update.callback_query, text, reply_markup=keyboard)
    elif update.message:
        await update.message.reply_text(text, reply_markup=keyboard)


async def show_bundles(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display bundles with operation counter."""
    user = update.effective_user
    if user is None:
        return
    record = await _storage(context).get_or_create(user.id)
    from bot.constants import PLUS_OPERATIONS_LIMIT
    limit = PLUS_OPERATIONS_LIMIT if record.subscription_active else (record.operations_limit or OPERATIONS_LIMIT)
    text = texts.BUNDLES.format(
        done=record.operations_done,
        limit=limit,
    )
    query = update.callback_query
    if query is None:
        return
    await _safe_edit_message_text(query, text, reply_markup=bundles_keyboard())


async def show_select_bundle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display cryptocurrency selection grid."""
    query = update.callback_query
    if query is None:
        return
    await _safe_edit_message_text(query, texts.SELECT_BUNDLE, reply_markup=select_bundle_keyboard())


async def show_bundle_launch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None:
        return BUNDLE_AMOUNT
        
    coin = query.data.removeprefix(CB_COIN_PREFIX)
    config = BUNDLE_CONFIG.get(coin)
    if not config:
        return BUNDLE_AMOUNT
        
    ex1, ex2, spread, min_u, max_u, p_min, p_max, t_min, t_max = config
    
    text = texts.BUNDLE_LAUNCH.format(
        coin=coin, ex1=ex1, ex2=ex2, spread=spread, min_usdt=min_u, max_usdt=max_u
    )
    
    context.user_data["current_bundle_coin"] = coin
    
    await _safe_edit_message_text(query, text, reply_markup=bundle_launch_keyboard())
    return BUNDLE_AMOUNT


async def _finish_bundle_task(application, duration: int, user_id: int, bundle_id: str, profit: float) -> None:
    import asyncio
    await asyncio.sleep(duration)
    
    storage = application.bot_data["storage"]
    completed = await storage.complete_bundle(user_id, bundle_id, profit)
    
    if completed:
        try:
            record = await storage.get_or_create(user_id)
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            from bot.constants import CB_MAIN
            
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Меню", callback_data=CB_MAIN)]])
            await application.bot.send_message(
                chat_id=user_id,
                text=texts.HISTORY_FINISH_NOTIFICATION.format(
                    coin=completed["coin"],
                    ex1=completed["ex1"],
                    ex2=completed["ex2"],
                    amount=completed["amount"],
                    exit_amount=completed["amount"] + profit,
                    profit=profit,
                    spread=completed["spread_str"],
                    balance=record.balance
                ),
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Failed to send bundle finish notification to {user_id}: {e}")

async def bundle_amount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return BUNDLE_AMOUNT
        
    user = update.effective_user
    if user is None:
        return BUNDLE_AMOUNT
        
    try:
        await update.message.delete()
    except Exception:
        pass

    coin = context.user_data.get("current_bundle_coin")
    if not coin:
        await show_main_menu(update, context, edit=False)
        return ConversationHandler.END
        
    config = BUNDLE_CONFIG.get(coin)
    if not config:
        return BUNDLE_AMOUNT
        
    ex1, ex2, spread_str, min_u, max_u, p_min, p_max, t_min, t_max = config

    try:
        import math
        amount = float(update.message.text.strip())
        if math.isnan(amount) or math.isinf(amount) or amount < min_u or amount > max_u:
            await update.message.reply_text(f"❌ Сумма должна быть от {min_u} до {max_u} USDT.")
            return BUNDLE_AMOUNT
            
        storage = _storage(context)
        record = await storage.get_or_create(user.id)
        
        # Check balance
        if record.balance < amount:
            await update.message.reply_text("❌ Недостаточно средств на балансе.")
            return BUNDLE_AMOUNT
            
        # Check limits
        # Максимально пользователь может получить x3 от суммы всех своих пополнений.
        limit = record.total_deposited * 3
        # calculate total profit made so far
        total_profit = sum(b.get("profit", 0) for b in record.history)
        
        if total_profit >= limit and limit > 0:
            await update.message.reply_text(texts.BUNDLE_LIMIT_REACHED)
            return BUNDLE_AMOUNT
            
        if limit == 0:
            # According to prompt: "После первого пополнения фиксируется общий объём... Для продолжения работы необходимо пополнить баланс."
            await update.message.reply_text(texts.BUNDLE_LIMIT_REACHED)
            return BUNDLE_AMOUNT

        # Calculate expected profit
        profit_percent = random.uniform(p_min, p_max) / 100.0
        profit = amount * profit_percent
        
        # Determine duration
        duration = random.randint(t_min, t_max)
        
        bundle_id = str(uuid.uuid4())
        
        bundle_data = {
            "id": bundle_id,
            "coin": coin,
            "ex1": ex1,
            "ex2": ex2,
            "amount": amount,
            "spread_str": spread_str,
            "profit": 0  # will be updated when done
        }
        
        # Deduct balance and add to active
        await storage.update_user(user.id, balance=record.balance - amount)
        await storage.add_active_bundle(user.id, bundle_data)
        
        # Schedule task
        import asyncio
        asyncio.create_task(_finish_bundle_task(
            context.application, duration, user.id, bundle_id, profit
        ))
        
        # Show success screen (active bundles)
        await show_active_bundles(update, context, edit=False)
        return ConversationHandler.END
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text(f"❌ Введите корректную сумму от {min_u} до {max_u} USDT.")
        return BUNDLE_AMOUNT

async def bundle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await show_bundles(update, context)
    return ConversationHandler.END

async def add_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /add command: /add <telegram_id> <amount>"""
    if update.effective_user is None or update.message is None:
        return
        
    args = context.args
    if not args or len(args) != 2:
        await update.message.reply_text("Использование: /add <telegram_id> <сумма>")
        return
        
    try:
        target_id = int(args[0])
        amount = float(args[1])
    except ValueError:
        await update.message.reply_text("❌ Ошибка: ID и сумма должны быть числами.")
        return
        
    storage = _storage(context)
    try:
        record, referral_credited = storage.process_deposit(target_id, amount)
        await update.message.reply_text(
            f"✅ Пользователю {target_id} начислено {amount} USDT.\n"
            f"Текущий баланс: {record.balance:.4f} USDT.\n"
            f"Всего пополнений: {record.total_deposited:.4f} USDT."
        )
        if referral_credited:
            # Notify the newly credited referrer
            referrer = next(
                (u for u in storage._users.values() if u.system_id == record.referred_by),
                None
            )
            if referrer:
                try:
                    await context.bot.send_message(
                        chat_id=referrer.telegram_id,
                        text=(
                            f"🎉 <b>Реферальный бонус начислен!</b>\n\n"
                            f"Ваш реферал пополнил баланс.\n"
                            f"Ваш бонус: <b>+{referrer.referral_bonus:.2f} USDT</b>"
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"Failed to add balance: {e}")
        await update.message.reply_text("❌ Ошибка при начислении баланса.")

async def show_active_bundles(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = True) -> None:
    """Display active bundles."""
    user = update.effective_user
    if user is None:
        return
    query = update.callback_query
    if edit and query is None:
        return
    record = await _storage(context).get_or_create(user.id)
    active = record.active_bundles

    if not active:
        text = texts.ACTIVE_BUNDLES_EMPTY
        markup = active_bundles_keyboard()
    else:
        text_parts = [texts.ACTIVE_BUNDLES_HEADER.format(count=len(active))]
        for b in active:
            card = texts.ACTIVE_BUNDLE_CARD.format(
                coin=b["coin"],
                ex1=b["ex1"],
                ex2=b["ex2"],
                amount=b["amount"],
                spread=b["spread_str"],
            )
            text_parts.append(card)
        text = "\n\n".join(text_parts)
        markup = active_bundles_refresh_keyboard()

    if edit and query:
        await _safe_edit_message_text(query, text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display history."""
    user = update.effective_user
    if user is None:
        return
    query = update.callback_query
    if query is None:
        return
    record = await _storage(context).get_or_create(user.id)
    history = record.history

    if not history:
        await _safe_edit_message_text(
            query,
            "История пуста.",
            reply_markup=back_to_main_keyboard(),
        )
        return
        
    text_parts = [texts.HISTORY_TITLE.strip()]
    # Show last 10
    for b in list(reversed(history))[:10]:
        card = texts.HISTORY_CARD.format(
            coin=b["coin"],
            ex1=b["ex1"],
            ex2=b["ex2"],
            amount=b["amount"],
            exit_amount=b["amount"] + b.get("profit", 0),
            spread=b["spread_str"],
        )
        text_parts.append(card)

    await _safe_edit_message_text(
        query,
        "\n\n".join(text_parts),
        reply_markup=back_to_main_keyboard(),
    )


async def show_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display wallet info with balance and system ID."""
    user = update.effective_user
    if user is None:
        return
    record = await _storage(context).get_or_create(user.id)
    text = texts.WALLET.format(
        user_line=_format_user_line(user),
        system_id=record.system_id,
        balance=record.balance,
    )
    query = update.callback_query
    if query is None:
        return
    await _safe_edit_message_text(query, text, reply_markup=wallet_keyboard())


async def show_deposit_awaiting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show deposit amount input screen (FSM entry point)."""
    query = update.callback_query
    if query is None:
        return DEPOSIT_AMOUNT
    user = update.effective_user
    record = await _storage(context).get_or_create(user.id) if user else None
    commission = DEPOSIT_COMMISSION_PLUS if (record and record.subscription_active) else DEPOSIT_COMMISSION
    commission_pct = int(commission * 100)
    text = (
        f"💳 Пополнение баланса\n\n"
        f"Пополнение выполняется через @xrocket (USDT).\n\n"
        f"⚠️ Комиссия: <b>{commission_pct}%</b>\n"
        f"(при вводе 100 USDT зачисляется {100 - commission_pct} USDT)\n\n"
        f"Введите сумму в USDT:"
    )
    await _safe_edit_message_text(query, text, reply_markup=deposit_awaiting_keyboard(), parse_mode="HTML")
    return DEPOSIT_AMOUNT


async def deposit_amount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle user deposit amount input. Validates integer and shows requisites."""
    if update.message is None:
        return DEPOSIT_AMOUNT

    user = update.effective_user
    if user is None:
        return DEPOSIT_AMOUNT

    try:
        raw = update.message.text.strip().replace(",", ".")
        amount = float(raw)
        if amount <= 0 or amount != amount:  # NaN check
            await update.message.reply_text("❌ Сумма должна быть положительным числом.")
            return DEPOSIT_AMOUNT
        if amount < 1:
            await update.message.reply_text("❌ Минимальная сумма пополнения: 1 USDT.")
            return DEPOSIT_AMOUNT

        try:
            await update.message.delete()
        except Exception as e:
            logger.debug(f"Failed to delete user message: {e}")

        # Generate a small unique fractional part to make invoice amount unique (0.001 - 0.199)
        import os, time, random
        rnd = int.from_bytes(os.urandom(2), "big")
        cents_part = (rnd % 199) + 1  # 1..199 -> 0.001 .. 0.199
        unique_amount = float(amount) + (cents_part / 1000.0)
        unique_amount = round(unique_amount, 3)

        # Create invoice via Xrocket
        import json as _json

        try:
            from bot import xrocket_client_prod as xrocket
            from bot.payments_service import extract_invoice_from_create_response

            payments = context.application.bot_data.get("payments")
            storage = _storage(context)
            user_rec = await storage.get_or_create(user.id)
            payload_meta = _json.dumps(
                {"user_id": user.id, "system_id": user_rec.system_id, "amount_requested": amount},
                ensure_ascii=False,
            )
            callback_url = context.application.bot_data.get("webapp_url")
            resp = await xrocket.create_invoice(
                unique_amount,
                description=f"Пополнение баланса {amount} USDT",
                payload=payload_meta,
                callback_url=callback_url,
                num_payments=1,
            )

            invoice_id, pay_url = extract_invoice_from_create_response(resp)
            if not invoice_id:
                raise RuntimeError(f"Xrocket не вернул id счёта: {resp!r}")

            metadata = {"user_id": user.id, "system_id": user_rec.system_id, "amount_requested": amount}
            if payments:
                await payments.create_payment(
                    invoice_id=invoice_id,
                    user_id=user.id,
                    amount_requested=amount,
                    unique_amount=unique_amount,
                    currency="USDT",
                    payment_url=pay_url,
                    metadata=metadata,
                )

            commission = DEPOSIT_COMMISSION_PLUS if user_rec.subscription_active else DEPOSIT_COMMISSION
            credited = round(amount * (1 - commission), 4)
            commission_pct = int(commission * 100)
            text = (
                f"💳 Счёт создан:\n\n"
                f"Сумма к оплате: <b>{unique_amount:.3f} USDT</b>\n"
                f"Комиссия: {commission_pct}%\n"
                f"Будет зачислено: <b>{credited:.4f} USDT</b>\n\n"
                f"После оплаты баланс будет зачислен автоматически."
            )

            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            if pay_url:
                kb = InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("Перейти к оплате", url=pay_url)],
                        [InlineKeyboardButton("⬅️ Главное меню", callback_data=CB_MAIN)],
                    ]
                )
                await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")
            else:
                await update.message.reply_text(
                    text + "\n\n⚠️ Ссылка на оплату не получена. Попробуйте позже или обратитесь в поддержку.",
                    reply_markup=deposit_requisites_keyboard(),
                    parse_mode="HTML",
                )

            return ConversationHandler.END

        except Exception as e:
            logger.error("Failed to create invoice via Xrocket: %s", e, exc_info=True)
            await update.message.reply_text(
                "❌ Не удалось создать счёт для оплаты. Попробуйте позже или обратитесь в поддержку.",
                reply_markup=deposit_awaiting_keyboard(),
            )
            return DEPOSIT_AMOUNT

    except ValueError:
        await update.message.reply_text(
            "❌ Пожалуйста, введите число (10, 20.5, 50...)."
        )
        return DEPOSIT_AMOUNT


async def deposit_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel deposit and return to wallet screen."""
    await show_wallet(update, context)
    return ConversationHandler.END


async def show_referrals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display referral program info with personal ref link and stats."""
    user = update.effective_user
    if user is None:
        return
    storage = _storage(context)
    record = await storage.get_or_create(user.id)
    referral_link = await storage.get_referral_link(user.id)

    text = texts.REFERRALS.format(
        referral_link=referral_link,
        referral_count=record.referral_count,
        referral_bonus=record.referral_bonus,
    )
    query = update.callback_query
    if query is None:
        return
    await _safe_edit_message_text(query, text, reply_markup=referral_keyboard())


async def show_plus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display Quantum+ subscription status."""
    user = update.effective_user
    if user is None:
        return
    record = await _storage(context).get_or_create(user.id)

    if record.subscription_active:
        # Calculate remaining days/hours if expiry is set
        import datetime
        if record.subscription_expiry:
            try:
                expiry = datetime.datetime.fromisoformat(record.subscription_expiry)
                remaining = expiry - datetime.datetime.now()
                days = max(0, remaining.days)
                hours = max(0, remaining.seconds // 3600)
            except Exception:
                days, hours = 30, 0
        else:
            days, hours = 30, 0
        text = texts.PLUS_ACTIVE.format(days=days, hours=hours)
    else:
        text = texts.PLUS_NO_SUBSCRIPTION

    query = update.callback_query
    if query is None:
        return
    await _safe_edit_message_text(query, text, reply_markup=plus_keyboard())


async def show_plus_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display Quantum+ benefits list."""
    query = update.callback_query
    if query is None:
        return
    await _safe_edit_message_text(query, texts.PLUS_ABOUT, reply_markup=plus_about_keyboard())


async def show_plus_buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start Quantum+ purchase flow via xrocket invoice."""
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()
    text = texts.PLUS_BUY_AWAITING
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Оплатить 40 USDT", callback_data="plus:confirm_buy")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=CB_QUANTUM_PLUS)],
    ])
    await _safe_edit_message_text(query, text, reply_markup=keyboard, parse_mode="HTML")
    return ConversationHandler.END


async def plus_confirm_buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Create xrocket invoice for Quantum+ subscription."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    user = update.effective_user
    if not user:
        return

    try:
        from bot import xrocket_client_prod as xrocket
        from bot.payments_service import extract_invoice_from_create_response
        import json as _json

        storage = _storage(context)
        user_rec = await storage.get_or_create(user.id)
        payments = context.application.bot_data.get("payments")

        import os
        rnd = int.from_bytes(os.urandom(2), "big")
        cents_part = (rnd % 199) + 1
        unique_amount = round(PLUS_SUBSCRIPTION_PRICE + cents_part / 1000.0, 3)

        payload_meta = _json.dumps(
            {"user_id": user.id, "system_id": user_rec.system_id, "type": "plus_subscription"},
            ensure_ascii=False,
        )
        resp = await xrocket.create_invoice(
            unique_amount,
            description="Quantum+ подписка 30 дней",
            payload=payload_meta,
            num_payments=1,
        )
        invoice_id, pay_url = extract_invoice_from_create_response(resp)
        if not invoice_id:
            raise RuntimeError("No invoice id")

        if payments:
            await payments.create_payment(
                invoice_id=invoice_id,
                user_id=user.id,
                amount_requested=PLUS_SUBSCRIPTION_PRICE,
                unique_amount=unique_amount,
                currency="USDT",
                payment_url=pay_url,
                metadata={"user_id": user.id, "type": "plus_subscription"},
            )

        text = (
            f"⭐ Счёт на Quantum+ создан:\n\n"
            f"Сумма: <b>{unique_amount:.3f} USDT</b>\n\n"
            f"После оплаты подписка активируется автоматически."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Перейти к оплате", url=pay_url)],
            [InlineKeyboardButton("⬅️ Главное меню", callback_data=CB_MAIN)],
        ])
        await _safe_edit_message_text(query, text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        logger.error("Failed to create Quantum+ invoice: %s", e, exc_info=True)
        await query.message.reply_text("❌ Не удалось создать счёт. Попробуйте позже.")

# --- Info and Tutorial Handlers ---

async def show_info_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None: return
    await _safe_edit_message_text(query, texts.INFO_MAIN, reply_markup=info_keyboard())

async def show_tut1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None: return
    await _safe_edit_message_text(query, texts.TUTORIAL_1, reply_markup=tutorial_1_keyboard())

async def show_tut2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None: return
    await _safe_edit_message_text(query, texts.TUTORIAL_2, reply_markup=tutorial_2_keyboard())

async def show_tut3(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None: return
    await _safe_edit_message_text(query, texts.TUTORIAL_3, reply_markup=tutorial_3_keyboard())

async def show_tut4(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None: return
    await _safe_edit_message_text(query, texts.TUTORIAL_4, reply_markup=tutorial_4_keyboard())

async def show_tos1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None: return
    await _safe_edit_message_text(query, texts.TOS_1, reply_markup=tos_1_keyboard())

async def show_tos2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None: return
    await _safe_edit_message_text(query, texts.TOS_2, reply_markup=tos_2_keyboard())

async def show_tos3(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None: return
    await _safe_edit_message_text(query, texts.TOS_3, reply_markup=tos_3_keyboard())

async def show_tos4(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None: return
    await _safe_edit_message_text(query, texts.TOS_4, reply_markup=tos_4_keyboard())

async def show_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None: return
    await _safe_edit_message_text(query, texts.ABOUT, reply_markup=about_keyboard())


async def support_write_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None: return ConversationHandler.END
    
    storage: UserStorage = context.application.bot_data["storage"]
    record = await storage.get_or_create(update.effective_user.id)
    
    now = time.time()
    if now - record.last_support_time < 300:
        await query.answer("⚠️ Лимит: одно сообщение раз в 5 минут.", show_alert=True)
        return ConversationHandler.END
        
    await _safe_edit_message_text(query, texts.SUPPORT_WRITE, reply_markup=support_write_keyboard())
    return SUPPORT_MESSAGE
    
async def support_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from bot.storage import TicketStorage
    storage: UserStorage = context.application.bot_data["storage"]
    ticket_store: TicketStorage = context.application.bot_data["tickets"]
    user = update.effective_user
    
    now = time.time()
    await storage.update_support_time(user.id, now)
    
    # Create ticket with unique ID
    username = _format_user_line(user)
    ticket_id = await ticket_store.create_ticket(user.id, username, update.message.text)
    
    # Notify admins
    admins = await storage.get_all_admins()
    escaped_text = html.escape(update.message.text)
    msg = (
        f"📩 <b>Новое обращение #{ticket_id}</b>\n"
        f"От: {username}\n\n"
        f"{escaped_text}\n\n"
        f"💡 Откройте /panel для ответа"
    )
    for admin_id in admins:
        try:
            await context.bot.send_message(chat_id=admin_id, text=msg, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send support ticket to admin {admin_id}: {e}")
            
    await update.message.reply_text(texts.SUPPORT_SUCCESS.format(ticket_id=ticket_id))
    
    # Return to main menu
    webapp_url = _webapp_url(context)
    await update.message.reply_text(texts.MAIN_MENU, reply_markup=main_menu_keyboard(webapp_url))
    return ConversationHandler.END

async def support_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None: return ConversationHandler.END
    await _safe_edit_message_text(query, texts.SUPPORT_MAIN, reply_markup=support_main_keyboard())
    return ConversationHandler.END

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command with optional referral payload."""
    user = update.effective_user
    if user is None:
        return

    logger.info(f"✓ start_command called for user {user.id}")
    storage = _storage(context)
    await storage.get_or_create(user.id)

    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            referrer_system_id = arg.removeprefix("ref_").strip()
            if referrer_system_id:
                await storage.register_referral(user.id, referrer_system_id)

    await show_main_menu(update, context, edit=False)


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /menu command."""
    logger.info(f"✓ menu_command called for user {update.effective_user.id if update.effective_user else 'N/A'}")
    await show_main_menu(update, context, edit=False)


async def show_open_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None: return
    url = _webapp_url(context)
    if url:
        from telegram import WebAppInfo
        buttons = []
        # WebApp button for in-client opening (only works for https URLs)
        if url.startswith("https://"):
            buttons.append([InlineKeyboardButton("🚀 Запустить Quantum App (в Telegram)", web_app=WebAppInfo(url=url))])
        # Always provide a fallback external link to open in browser
        buttons.append([InlineKeyboardButton("Открыть WebApp в браузере", url=url)])
        buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data=CB_MAIN)])
        keyboard = InlineKeyboardMarkup(buttons)
        await _safe_edit_message_text(query, "🚀 Откройте WebApp ниже:", reply_markup=keyboard)
    else:
        # If WEBAPP_URL is not configured for HTTPS, provide a helpful fallback link to open the locally-served app in a browser.
        local_index = "http://localhost:8000/app/index.html"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Открыть WebApp в браузере (локально)", url=local_index)],
            [InlineKeyboardButton("⬅️ Назад", callback_data=CB_MAIN)]
        ])
        await _safe_edit_message_text(query, texts.OPEN_APP + "\n\nWebApp не настроено на HTTPS. Для разработки можно открыть локальную версию в браузере:", reply_markup=keyboard)

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route callback queries to appropriate handlers."""
    query = update.callback_query
    if query is None:
        return

    # Ban check
    user = update.effective_user
    if user:
        storage = _storage(context)
        record = await storage.get_or_create(user.id)
        if record.is_banned:
            await query.answer("🚫 Вы заблокированы.", show_alert=True)
            return

    logger.info(f"✓ callback_router called with data: {query.data}")

    try:
        await query.answer()
    except Exception as e:
        logger.debug(f"query.answer() failed (expected for old queries): {e}")

    data = query.data or ""

    # Import admin panel handler lazily to avoid circular imports
    try:
        from bot.admin_handlers import show_admin_panel
    except Exception:
        show_admin_panel = None

    HANDLER_MAP = {
        CB_MAIN: lambda u, c: show_main_menu(u, c, edit=True),
        CB_BUNDLES: show_bundles,
        CB_SELECT_BUNDLE: show_select_bundle,
        CB_ACTIVE_BUNDLES: show_active_bundles,
        CB_WALLET: show_wallet,
        CB_OPEN_APP: show_open_app,
        CB_HISTORY: show_history,
        CB_INFO: show_info_main,
        CB_TUTORIAL_1: show_tut1,
        CB_TUTORIAL_2: show_tut2,
        CB_TUTORIAL_3: show_tut3,
        CB_TUTORIAL_4: show_tut4,
        CB_ABOUT: show_about,
        CB_TOS_1: show_tos1,
        CB_TOS_2: show_tos2,
        CB_TOS_3: show_tos3,
        CB_TOS_4: show_tos4,
        CB_SUPPORT: lambda u, c: _safe_edit_message_text(u.callback_query, texts.SUPPORT_MAIN, reply_markup=support_main_keyboard()),
        CB_REFERRALS: show_referrals,
        CB_TX_HISTORY: lambda u, c: show_placeholder(u, c, text=texts.TX_HISTORY, back_callback="wallet"),
        CB_QUANTUM_PLUS: show_plus,
        CB_PLUS_ABOUT: show_plus_about,
        CB_PLUS_BUY: show_plus_buy,
        "plus:confirm_buy": plus_confirm_buy,
    }

    # Map admin panel to its handler if available
    if show_admin_panel:
        HANDLER_MAP[CB_ADMIN_PANEL] = show_admin_panel

    handler = HANDLER_MAP.get(data)
    if handler:
        try:
            await handler(update, context)
        except Exception as e:
            logger.error(f"Handler for '{data}' raised an exception: {e}", exc_info=True)
            # Notify user minimally if callback exists
            if update.callback_query:
                try:
                    await update.callback_query.answer("Произошла ошибка при обработке. Администраторы уведомлены.")
                except Exception:
                    pass


async def show_placeholder(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    text: str,
    back_callback: str,
) -> None:
    """Display placeholder screen with appropriate back button."""
    query = update.callback_query
    if query is None:
        return

    if back_callback == "wallet":
        keyboard = back_to_wallet_keyboard()
    elif back_callback == "bundles":
        keyboard = back_to_bundles_keyboard()
    elif back_callback == "select_bundle":
        keyboard = back_to_select_bundle_keyboard()
    elif back_callback == "info":
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=CB_INFO)]])
    else:
        keyboard = back_to_main_keyboard()

    await _safe_edit_message_text(query, text, reply_markup=keyboard)


# ── Withdraw (Bot) ────────────────────────────────────────────────────────────

async def withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start withdraw flow, prompt for amount."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END

    user = update.effective_user
    if not user:
        return ConversationHandler.END

    storage = _storage(context)
    record = await storage.get_or_create(user.id)

    from bot.storage import WITHDRAW_MIN_AMOUNT

    if record.balance < WITHDRAW_MIN_AMOUNT:
        await query.answer(
            f"❌ Минимальная сумма вывода: {WITHDRAW_MIN_AMOUNT} USDT\nВаш баланс: {record.balance:.4f} USDT",
            show_alert=True
        )
        return ConversationHandler.END

    text = (
        f"💸 <b>Вывод средств</b>\n\n"
        f"Доступно: {record.balance:.4f} USDT\n"
        f"Мин. сумма: {WITHDRAW_MIN_AMOUNT} USDT\n"
        f"Комиссия: 8% (вычитается из суммы вывода)\n\n"
        f"Введите сумму для вывода:"
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=CB_MAIN)]])

    await query.answer()
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    return WITHDRAW_AMOUNT


async def withdraw_amount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle withdraw amount, prompt for address."""
    if not update.message:
        return WITHDRAW_AMOUNT

    user = update.effective_user
    if not user:
        return WITHDRAW_AMOUNT

    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Введите корректное число (например, 50 или 50.5).")
        return WITHDRAW_AMOUNT

    storage = _storage(context)
    record = await storage.get_or_create(user.id)

    from bot.storage import WITHDRAW_MIN_AMOUNT

    if amount < WITHDRAW_MIN_AMOUNT:
        await update.message.reply_text(f"❌ Минимальная сумма вывода: {WITHDRAW_MIN_AMOUNT} USDT.")
        return WITHDRAW_AMOUNT

    if amount > record.balance:
        await update.message.reply_text(f"❌ Недостаточно средств. Ваш баланс: {record.balance:.4f} USDT.")
        return WITHDRAW_AMOUNT

    context.user_data["withdraw_amount"] = amount
    net_amount = round(amount * (1 - WITHDRAW_COMMISSION), 4)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=CB_MAIN)]])
    await update.message.reply_text(
        f"✅ Сумма: {amount:.4f} USDT\n"
        f"Комиссия 8%: −{amount * WITHDRAW_COMMISSION:.4f} USDT\n"
        f"Получите на руки: <b>{net_amount:.4f} USDT</b>\n\n"
        f"Введите адрес вашего кошелька (USDT TON):",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    return WITHDRAW_ADDRESS


async def withdraw_address_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle withdraw address, create request, notify admins."""
    if not update.message:
        return WITHDRAW_ADDRESS

    user = update.effective_user
    if not user:
        return WITHDRAW_ADDRESS

    address = update.message.text.strip()
    if len(address) < 10:
        await update.message.reply_text("❌ Неверный формат адреса. Попробуйте еще раз:")
        return WITHDRAW_ADDRESS

    amount = context.user_data.pop("withdraw_amount", None)
    if not amount:
        await update.message.reply_text("⚠️ Ошибка: сумма не найдена. Начните сначала.")
        return ConversationHandler.END

    storage = _storage(context)
    record = await storage.get_or_create(user.id)

    if amount > record.balance:
        await update.message.reply_text("❌ Ошибка: недостаточно средств.")
        return ConversationHandler.END

    net_amount = round(amount * (1 - WITHDRAW_COMMISSION), 4)
    # Deduct full amount from balance immediately
    await storage.update_user(user.id, balance=record.balance - amount)

    withdrawals = context.application.bot_data["withdrawals"]
    uname = user.username or user.first_name or str(user.id)
    withdraw_id = await withdrawals.create_withdrawal(
        user_id=user.id,
        username=uname,
        amount=net_amount,
        address=address
    )

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data=CB_MAIN)]])
    await update.message.reply_text(
        f"✅ <b>Заявка на вывод #{withdraw_id} создана!</b>\n\n"
        f"Списано: {amount:.4f} USDT\n"
        f"Комиссия 8%: −{amount * WITHDRAW_COMMISSION:.4f} USDT\n"
        f"К выплате: <b>{net_amount:.4f} USDT</b>\n"
        f"Адрес: <code>{html.escape(address)}</code>\n\n"
        f"Ожидайте подтверждения администратором.",
        parse_mode="HTML",
        reply_markup=keyboard
    )

    # Notify admins
    admins = await storage.get_all_admins()
    for admin_id in admins:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    f"💸 <b>Новая заявка на вывод!</b>\n\n"
                    f"Пользователь: {html.escape(uname)}\n"
                    f"Сумма: <b>{amount:.4f} USDT</b>\n\n"
                    f"Откройте панель администратора для обработки."
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔧 Админ-панель", callback_data=CB_ADMIN_PANEL)]])
            )
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id} of withdrawal: {e}")

    return ConversationHandler.END


async def withdraw_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("withdraw_amount", None)
    await show_main_menu(update, context)
    return ConversationHandler.END

