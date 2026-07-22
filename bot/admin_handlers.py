"""Admin commands, support ticket panel, and withdraw approval for Quantum bot."""
from __future__ import annotations

import logging
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from bot.storage import UserStorage, TicketStorage, WithdrawStorage
from bot.constants import (
    ADMIN_REPLY_TEXT,
    ADMIN_WITHDRAW_REJECT_REASON,
    CB_ADMIN_PANEL,
    CB_ADMIN_REPLY_PREFIX,
    CB_ADMIN_WITHDRAW_PREFIX,
    CB_ADMIN_WITHDRAW_APPROVE,
    CB_ADMIN_WITHDRAW_REJECT,
    CB_MAIN,
)

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _storage(context: ContextTypes.DEFAULT_TYPE) -> UserStorage:
    return context.application.bot_data["storage"]

def _tickets(context: ContextTypes.DEFAULT_TYPE) -> TicketStorage:
    return context.application.bot_data["tickets"]

def _withdrawals(context: ContextTypes.DEFAULT_TYPE) -> WithdrawStorage:
    return context.application.bot_data["withdrawals"]

async def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False
    record = await _storage(context).get_or_create(user.id)
    return record.is_admin


# ── Admin panel ───────────────────────────────────────────────────────────────

async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all open support tickets to admin."""
    if not await _is_admin(update, context):
        if update.message:
            await update.message.reply_text("⛔ Нет доступа.")
        return

    try:
        tickets = await _tickets(context).get_open_tickets()
        # Withdrawals storage method is get_pending_withdrawals()
        withdraws = await _withdrawals(context).get_pending_withdrawals()

        if not tickets and not withdraws:
            text = "📋 <b>Панель администратора</b>\n\nОбращений нет 🎉\nЗаявок на вывод нет 🎉"
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=CB_MAIN)]])
        else:
            text = f"📋 <b>Панель администратора</b>\n\n<b>Открытых обращений: {len(tickets)}</b>\n<b>Заявок на вывод: {len(withdraws)}</b>\n\n"
            buttons = []
            for w in withdraws:
                uname = w.get("username") or f"id:{w['user_id']}"
                buttons.append([InlineKeyboardButton(
                    f"📤 Вывод #{w['id']} • {w['amount']:.2f} USDT",
                    callback_data=f"{CB_ADMIN_WITHDRAW_PREFIX}{w['id']}"
                )])
            for t in tickets:
                uname = t.get("username") or f"id:{t['user_id']}"
                preview = t["message"][:30] + ("…" if len(t["message"]) > 30 else "")
                buttons.append([InlineKeyboardButton(
                    f"#{t['id']} • {uname}: {preview}",
                    callback_data=f"{CB_ADMIN_REPLY_PREFIX}{t['id']}"
                )])
            keyboard = InlineKeyboardMarkup(buttons)

        if update.callback_query:
            await update.callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        elif update.message:
            await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error showing admin panel: {e}", exc_info=True)
        if update.message:
            await update.message.reply_text("❌ Ошибка при открытии панели администратора.")
        elif update.callback_query:
            await update.callback_query.answer("❌ Ошибка при открытии панели администратора.", show_alert=True)


async def admin_panel_ticket_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin clicked on a specific ticket — show full message and ask for reply."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END

    if not await _is_admin(update, context):
        await query.answer("⛔ Нет доступа.", show_alert=True)
        return ConversationHandler.END

    ticket_id = query.data.removeprefix(CB_ADMIN_REPLY_PREFIX)
    ticket = await _tickets(context).get_ticket(ticket_id)

    if not ticket or ticket.get("status") != "open":
        await query.answer("Заявка уже закрыта или не найдена.", show_alert=True)
        return ConversationHandler.END

    context.user_data["reply_ticket_id"] = ticket_id
    context.user_data["reply_user_id"] = ticket["user_id"]

    uname = ticket.get("username") or f"id:{ticket['user_id']}"
    escaped_msg = html.escape(ticket['message'])
    text = (
        f"📩 <b>Обращение #{ticket_id}</b>\n"
        f"От: {uname}\n\n"
        f"{escaped_msg}\n\n"
        f"─────────────────\n"
        f"✍️ <i>Напишите ответ пользователю:</i>"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Отмена", callback_data=CB_ADMIN_PANEL)
    ]])
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    return ADMIN_REPLY_TEXT


async def admin_send_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin sent reply text — deliver to user and close ticket."""
    ticket_id = context.user_data.get("reply_ticket_id")
    reply_user_id = context.user_data.get("reply_user_id")

    if not ticket_id or not reply_user_id:
        await update.message.reply_text("⚠️ Ошибка: тикет не найден.")
        return ConversationHandler.END

    reply_text = update.message.text

    # Close the ticket
    await _tickets(context).close_ticket(ticket_id)

    # Send beautiful notification to user
    escaped_reply = html.escape(reply_text)
    user_notification = (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📬 <b>Ответ на ваше обращение #{ticket_id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{escaped_reply}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Служба поддержки Quantum</i>"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 Главное меню", callback_data=CB_MAIN)
    ]])
    try:
        await context.bot.send_message(
            chat_id=reply_user_id,
            text=user_notification,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.error(f"Failed to send reply to user {reply_user_id}: {e}")

    # Confirm to admin and re-show panel
    await update.message.reply_text(
        f"✅ Ответ по заявке <b>#{ticket_id}</b> отправлен пользователю.",
        parse_mode="HTML",
    )

    # Refresh the panel
    open_tickets = await _tickets(context).get_open_tickets()
    if not open_tickets:
        panel_text = "📋 <b>Панель администратора</b>\n\nОбращений нет 🎉"
        await update.message.reply_text(panel_text, parse_mode="HTML")
    else:
        panel_text = f"📋 <b>Панель администратора</b>\n\n<b>Открытых обращений: {len(open_tickets)}</b>"
        buttons = []
        for t in open_tickets:
            uname = t.get("username") or f"id:{t['user_id']}"
            preview = t["message"][:30] + ("…" if len(t["message"]) > 30 else "")
            buttons.append([InlineKeyboardButton(
                f"#{t['id']} • {uname}: {preview}",
                callback_data=f"{CB_ADMIN_REPLY_PREFIX}{t['id']}"
            )])
        await update.message.reply_text(panel_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

    context.user_data.pop("reply_ticket_id", None)
    context.user_data.pop("reply_user_id", None)
    return ConversationHandler.END


async def admin_reply_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel reply and return to admin panel."""
    context.user_data.pop("reply_ticket_id", None)
    context.user_data.pop("reply_user_id", None)
    await show_admin_panel(update, context)
    return ConversationHandler.END


# ── Admin commands ────────────────────────────────────────────────────────────

async def cmd_giveadmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_admin(update, context):
        return
    if not context.args:
        await update.message.reply_text("Использование: /giveadmin ID")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Неверный ID")
        return
    if await _storage(context).set_admin(target_id, True):
        await update.message.reply_text(f"✅ Пользователь {target_id} назначен администратором.")
    else:
        await update.message.reply_text("❌ Пользователь не найден.")


async def cmd_deleteadmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_admin(update, context):
        return
    if not context.args:
        await update.message.reply_text("Использование: /deleteadmin ID")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Неверный ID")
        return
    if target_id == 5710686998:
        await update.message.reply_text("⛔ Нельзя забрать права у главного администратора.")
        return
    if await _storage(context).set_admin(target_id, False):
        await update.message.reply_text(f"✅ Пользователь {target_id} лишён прав администратора.")
    else:
        await update.message.reply_text("❌ Пользователь не найден.")


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_admin(update, context):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /add ID СУММА")
        return
    try:
        target_id = int(context.args[0])
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Неверные параметры.")
        return
    storage = _storage(context)
    record = await storage.get_or_create(target_id)
    await storage.update_user(target_id, balance=record.balance + amount)
    await update.message.reply_text(f"✅ Баланс пользователя {target_id} пополнен на {amount:.2f}$.")


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_admin(update, context):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /delete ID СУММА")
        return
    try:
        target_id = int(context.args[0])
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Неверные параметры.")
        return
    storage = _storage(context)
    record = await storage.get_or_create(target_id)
    await storage.update_user(target_id, balance=max(0.0, record.balance - amount))
    await update.message.reply_text(f"✅ У пользователя {target_id} списано {amount:.2f}$.")


async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_admin(update, context):
        return
    if not context.args:
        await update.message.reply_text("Использование: /ban ID")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Неверный ID")
        return
    storage = _storage(context)
    record = await storage.get_or_create(target_id)
    new_banned = not record.is_banned
    await storage.set_banned(target_id, new_banned)
    status = "🔒 заблокирован" if new_banned else "🔓 разблокирован"
    await update.message.reply_text(f"Пользователь {target_id} {status}.")


async def cmd_sub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_admin(update, context):
        return
    if not context.args:
        await update.message.reply_text("Использование: /sub ID")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Неверный ID")
        return
    import datetime
    storage = _storage(context)
    record = await storage.get_or_create(target_id)
    new_sub = not record.subscription_active
    expiry = (datetime.datetime.now() + datetime.timedelta(days=30)).isoformat() if new_sub else None
    await storage.update_user(target_id, subscription_active=new_sub, subscription_expiry=expiry)
    status = "⭐ получил подписку Quantum+ (30 дней)" if new_sub else "лишился подписки Quantum+"
    await update.message.reply_text(f"✅ Пользователь {target_id} {status}.")


async def cmd_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_admin(update, context):
        return
    if not context.args:
        await update.message.reply_text("Использование: /send ТЕКСТ")
        return
    message = " ".join(context.args)
    users = await _storage(context).get_all_users()
    count = 0
    await update.message.reply_text(f"📡 Начинаю рассылку для {len(users)} пользователей...")
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=message)
            count += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ Рассылка завершена. Доставлено: {count}/{len(users)}")


# ── Withdraw admin handlers ───────────────────────────────────────────────────

async def show_withdraw_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all pending withdrawal requests to admin."""
    if not await _is_admin(update, context):
        if update.message:
            await update.message.reply_text("⛔ Нет доступа.")
        return

    pending = await _withdrawals(context).get_pending_withdrawals()

    if not pending:
        text = "💸 <b>Заявки на вывод</b>\n\nПендинг-заявок нет 🎉"
        keyboard = InlineKeyboardMarkup([[]])
    else:
        text = f"💸 <b>Заявки на вывод</b>\n\n<b>Ожидают обработки: {len(pending)}</b>\n"
        buttons = []
        for w in pending:
            uname = w.get("username") or f"id:{w['user_id']}"
            buttons.append([InlineKeyboardButton(
                f"#{w['id']} · {uname} · {w['amount']:.2f} USDT",
                callback_data=f"{CB_ADMIN_WITHDRAW_PREFIX}{w['id']}"
            )])
        keyboard = InlineKeyboardMarkup(buttons)

    if update.message:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    elif update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


async def admin_withdraw_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin clicked on a withdraw request — show details with approve/reject buttons."""
    query = update.callback_query
    if not query:
        return
    if not await _is_admin(update, context):
        await query.answer("⛔ Нет доступа.", show_alert=True)
        return

    withdraw_id = query.data.removeprefix(CB_ADMIN_WITHDRAW_PREFIX)
    # Guard: don't process approve/reject prefixes here
    if query.data.startswith(CB_ADMIN_WITHDRAW_APPROVE) or query.data.startswith(CB_ADMIN_WITHDRAW_REJECT):
        # Answer callback so the UI doesn't stall and allow more specific handlers to run
        try:
            await query.answer()
        except Exception:
            pass
        return

    w = await _withdrawals(context).get_withdrawal(withdraw_id)

    if not w or w["status"] != "pending":
        await query.answer("Заявка уже обработана или не найдена.", show_alert=True)
        return

    uname = w.get("username") or f"id:{w['user_id']}"
    text = (
        f"💸 <b>Заявка на вывод #{w['id']}</b>\n"
        f"От: {html.escape(uname)}\n"
        f"Сумма: <b>{w['amount']:.4f} USDT</b>\n"
        f"Адрес: <code>{html.escape(w['address'])}</code>\n\n"
        f"Выберите действие:"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Одобрить", callback_data=f"{CB_ADMIN_WITHDRAW_APPROVE}{w['id']}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"{CB_ADMIN_WITHDRAW_REJECT}{w['id']}"),
        ],
        [InlineKeyboardButton("« Назад", callback_data=CB_ADMIN_PANEL)],
    ])
    await query.answer()
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


async def admin_withdraw_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin approved the withdrawal — deduct balance, notify user."""
    query = update.callback_query
    if not query:
        return
    if not await _is_admin(update, context):
        await query.answer("⛔ Нет доступа.", show_alert=True)
        return

    withdraw_id = query.data.removeprefix(CB_ADMIN_WITHDRAW_APPROVE)
    w = await _withdrawals(context).approve_withdrawal(withdraw_id)

    if not w:
        await query.answer("Заявка уже обработана.", show_alert=True)
        return

    # Deduct balance from user
    storage = _storage(context)
    record = await storage.get_or_create(w["user_id"])
    new_balance = max(0.0, record.balance - w["amount"])
    await storage.update_user(w["user_id"], balance=new_balance)

    # Notify user
    try:
        await context.bot.send_message(
            chat_id=w["user_id"],
            text=(
                f"✅ <b>Заявка на вывод #{w['id']} одобрена!</b>\n\n"
                f"Сумма: <b>{w['amount']:.4f} USDT</b>\n"
                f"Адрес: <code>{html.escape(w['address'])}</code>\n\n"
                f"Средства будут переведены в течение нескольких минут."
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Failed to notify user {w['user_id']} on withdrawal approval: {e}")

    await query.answer("✅ Одобрено!")
    await query.message.edit_text(
        f"✅ Заявка <b>#{w['id']}</b> одобрена. Баланс пользователя списан.",
        parse_mode="HTML",
    )


async def admin_withdraw_reject_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin clicked Reject — ask for reason text."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    if not await _is_admin(update, context):
        await query.answer("⛔ Нет доступа.", show_alert=True)
        return ConversationHandler.END

    withdraw_id = query.data.removeprefix(CB_ADMIN_WITHDRAW_REJECT)
    context.user_data["reject_withdraw_id"] = withdraw_id
    await query.answer()
    await query.message.edit_text(
        f"❌ Введите причину отказа по заявке <b>#{withdraw_id}</b>:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data=CB_ADMIN_PANEL)]]),
    )
    return ADMIN_WITHDRAW_REJECT_REASON


async def admin_withdraw_reject_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin sent rejection reason — reject withdrawal and notify user."""
    withdraw_id = context.user_data.pop("reject_withdraw_id", None)
    if not withdraw_id or not update.message:
        return ConversationHandler.END

    reason = update.message.text.strip()
    w = await _withdrawals(context).reject_withdrawal(withdraw_id, reason)

    if not w:
        await update.message.reply_text("⚠️ Заявка не найдена или уже обработана.")
        return ConversationHandler.END

    # Notify user
    try:
        await context.bot.send_message(
            chat_id=w["user_id"],
            text=(
                f"❌ <b>Заявка на вывод #{w['id']} отклонена</b>\n\n"
                f"Причина: {html.escape(reason)}\n\n"
                f"Средства остались на вашем балансе. Обратитесь в поддержку при необходимости."
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Failed to notify user {w['user_id']} on withdrawal rejection: {e}")

    await update.message.reply_text(
        f"✅ Заявка <b>#{withdraw_id}</b> отклонена. Пользователь уведомлён.",
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def admin_withdraw_reject_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("reject_withdraw_id", None)
    await show_admin_panel(update, context)
    return ConversationHandler.END

