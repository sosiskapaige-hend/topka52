"""Quantum Telegram bot entry point."""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.constants import (
    CB_DEPOSIT,
    CB_DEPOSIT_CANCEL,
    CB_MAIN,
    CB_COIN_PREFIX,
    CB_BUNDLES,
    CB_SUPPORT_WRITE,
    CB_SUPPORT,
    CB_WITHDRAW,
    SUPPORT_MESSAGE,
    DEPOSIT_AMOUNT,
    BUNDLE_AMOUNT,
    ADMIN_REPLY_TEXT,
    ADMIN_WITHDRAW_REJECT_REASON,
    CB_ADMIN_PANEL,
    CB_ADMIN_REPLY_PREFIX,
    CB_ADMIN_WITHDRAW_PREFIX,
    CB_ADMIN_WITHDRAW_APPROVE,
    CB_ADMIN_WITHDRAW_REJECT,
    WITHDRAW_AMOUNT,
    WITHDRAW_ADDRESS,
)
from bot.handlers import (
    callback_router,
    deposit_amount_handler,
    deposit_cancel,
    menu_command,
    show_deposit_awaiting,
    start_command,
    show_bundle_launch,
    bundle_amount_handler,
    bundle_cancel,
    support_write_start,
    support_message_handler,
    support_cancel,
    withdraw_start,
    withdraw_amount_handler,
    withdraw_address_handler,
    withdraw_cancel,
)
from bot.admin_handlers import (
    cmd_giveadmin,
    cmd_deleteadmin,
    cmd_add,
    cmd_delete,
    cmd_ban,
    cmd_sub,
    cmd_send,
    show_admin_panel,
    admin_panel_ticket_view,
    admin_send_reply,
    admin_reply_cancel,
    show_withdraw_panel,
    admin_withdraw_view,
    admin_withdraw_approve,
    admin_withdraw_reject_start,
    admin_withdraw_reject_reason,
    admin_withdraw_reject_cancel,
)
from bot.storage import UserStorage, TicketStorage, WithdrawStorage

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def error_handler(update: Update | None, context) -> None:
    """Log errors caused by updates."""
    logger.error(f"Update {update} caused error {context.error}", exc_info=context.error)


def _start_xrocket_poller(app: "Application") -> None:
    """Start background task that polls pending Xrocket invoices.

    Runs independently of FastAPI so payments are processed even if
    the web server is unavailable. Interval: XROCKET_POLL_INTERVAL seconds.
    """
    import asyncio
    enabled = os.getenv("ENABLE_XROCKET_POLL", "true").lower() in ("1", "true", "yes")
    if not enabled:
        logger.info("Xrocket polling disabled")
        return

    interval = int(os.getenv("XROCKET_POLL_INTERVAL", "60"))

    async def _poll_loop() -> None:
        import bot.xrocket_client_prod as xrocket
        from bot.payments_service import (
            invoice_is_paid,
            try_complete_payment,
            schedule_deposit_notification,
        )
        logger.info("Xrocket invoice poller started (interval=%ds)", interval)
        while True:
            try:
                payments = app.bot_data.get("payments")
                storage = app.bot_data.get("storage")
                if not payments or not storage:
                    await asyncio.sleep(5)
                    continue
                pending = payments.get_pending_payments()
                for rec in pending:
                    invoice_id = rec.get("invoice_id")
                    if not invoice_id:
                        continue
                    try:
                        info = await xrocket.get_invoice(str(invoice_id))
                        if not invoice_is_paid(info):
                            continue
                        result = try_complete_payment(
                            payments, storage, str(invoice_id),
                            external_meta=info if isinstance(info, dict) else None,
                        )
                        if result:
                            schedule_deposit_notification(result)
                            logger.info("Poller credited invoice %s for user %s", invoice_id, result["user_id"])
                    except Exception as e:
                        logger.error("Poller error for invoice %s: %s", invoice_id, e)
            except Exception as e:
                logger.error("Xrocket poller loop error: %s", e)
            await asyncio.sleep(interval)

    asyncio.get_event_loop().create_task(_poll_loop())


def main() -> None:
    load_dotenv()

    token = os.getenv("BOT_TOKEN")
    if not token or token == "your_telegram_bot_token_here":
        logger.error("Set BOT_TOKEN in .env (see .env.example)")
        sys.exit(1)

    webapp_url = os.getenv("WEBAPP_URL")
    bot_name = os.getenv("BOT_NAME", "quantumcryptobot")

    # Warn if WEBAPP_URL isn't HTTPS — WebApp buttons inside Telegram will only work with https URLs.
    if webapp_url and not webapp_url.startswith("https://"):
        logger.warning("WEBAPP_URL is not HTTPS — Telegram in-client WebApp button will not work. Provide an https:// URL to enable in-client opening.")
        # keep webapp_url as-is to allow external fallback links (open in browser) during development


    try:
        import asyncio
        import uvicorn
        from bot.webapp_api import app as fastapi_app
        import bot.webapp_api as webapp_api
        import main
        
        async def post_init(app: Application) -> None:
            import socket
            # Start Xrocket invoice poller (runs regardless of FastAPI)
            _start_xrocket_poller(app)

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind(("0.0.0.0", 8000))
                sock.close()
                config = uvicorn.Config(fastapi_app, host="0.0.0.0", port=8000, log_level="info")
                server = uvicorn.Server(config)
                asyncio.create_task(server.serve())
            except OSError:
                logger.error("Port 8000 is already in use. WebApp API will NOT start, but the bot will continue running.")
            
        application = (
            Application.builder()
            .token(token)
            .post_init(post_init)
            .build()
        )

        storage = UserStorage(bot_name=bot_name)
        tickets = TicketStorage()
        withdrawals = WithdrawStorage()
        from bot.storage import PaymentStorage
        payments = PaymentStorage()
        application.bot_data["storage"] = storage
        application.bot_data["tickets"] = tickets
        application.bot_data["withdrawals"] = withdrawals
        application.bot_data["payments"] = payments
        application.bot_data["webapp_url"] = webapp_url

        # Ensure first admin exists
        storage.ensure_first_admin(5710686998)

        # FSM for deposit flow
        deposit_conversation = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(show_deposit_awaiting, pattern=f"^{CB_DEPOSIT}$")
            ],
            states={
                DEPOSIT_AMOUNT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        deposit_amount_handler,
                    ),
                    CallbackQueryHandler(
                        deposit_cancel,
                        pattern=f"^{CB_DEPOSIT_CANCEL}$",
                    ),
                    CallbackQueryHandler(
                        deposit_cancel,
                        pattern=f"^{CB_MAIN}$",
                    ),
                ]
            },
            fallbacks=[
                CallbackQueryHandler(
                    deposit_cancel,
                    pattern=f"^{CB_DEPOSIT_CANCEL}$",
                ),
                CallbackQueryHandler(
                    deposit_cancel,
                    pattern=f"^{CB_MAIN}$",
                ),
                CommandHandler("start", start_command),
                CommandHandler("menu", menu_command),
            ],
            per_message=False,
        )

        # FSM for bundle launch flow
        bundle_conversation = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(show_bundle_launch, pattern=f"^{CB_COIN_PREFIX}")
            ],
            states={
                BUNDLE_AMOUNT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        bundle_amount_handler,
                    ),
                    CallbackQueryHandler(
                        bundle_cancel,
                        pattern=f"^{CB_BUNDLES}$",
                    ),
                    CallbackQueryHandler(
                        bundle_cancel,
                        pattern=f"^{CB_MAIN}$",
                    ),
                ]
            },
            fallbacks=[
                CallbackQueryHandler(
                    bundle_cancel,
                    pattern=f"^{CB_BUNDLES}$",
                ),
                CallbackQueryHandler(
                    bundle_cancel,
                    pattern=f"^{CB_MAIN}$",
                ),
                CommandHandler("start", start_command),
                CommandHandler("menu", menu_command),
            ],
            per_message=False,
        )

        # FSM for support flow
        support_conversation = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(support_write_start, pattern=f"^{CB_SUPPORT_WRITE}$")
            ],
            states={
                SUPPORT_MESSAGE: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        support_message_handler,
                    ),
                    CallbackQueryHandler(
                        support_cancel,
                        pattern=f"^{CB_SUPPORT}$",
                    ),
                    CallbackQueryHandler(
                        support_cancel,
                        pattern=f"^{CB_MAIN}$",
                    ),
                ]
            },
            fallbacks=[
                CallbackQueryHandler(
                    support_cancel,
                    pattern=f"^{CB_SUPPORT}$",
                ),
                CallbackQueryHandler(
                    support_cancel,
                    pattern=f"^{CB_MAIN}$",
                ),
                CommandHandler("start", start_command),
                CommandHandler("menu", menu_command),
            ],
            per_message=False,
        )

        # FSM for admin reply to support tickets
        admin_reply_conversation = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(
                    admin_panel_ticket_view,
                    pattern=f"^{CB_ADMIN_REPLY_PREFIX}",
                )
            ],
            states={
                ADMIN_REPLY_TEXT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        admin_send_reply,
                    ),
                    CallbackQueryHandler(
                        admin_reply_cancel,
                        pattern=f"^{CB_ADMIN_PANEL}$",
                    ),
                ]
            },
            fallbacks=[
                CallbackQueryHandler(
                    admin_reply_cancel,
                    pattern=f"^{CB_ADMIN_PANEL}$",
                ),
                CommandHandler("start", start_command),
                CommandHandler("menu", menu_command),
                CommandHandler("panel", show_admin_panel),
            ],
            per_message=False,
        )

        # FSM for withdraw flow (bot)
        withdraw_conversation = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(withdraw_start, pattern=f"^{CB_WITHDRAW}$")
            ],
            states={
                WITHDRAW_AMOUNT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_amount_handler),
                    CallbackQueryHandler(withdraw_cancel, pattern=f"^{CB_MAIN}$"),
                ],
                WITHDRAW_ADDRESS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_address_handler),
                    CallbackQueryHandler(withdraw_cancel, pattern=f"^{CB_MAIN}$"),
                ],
            },
            fallbacks=[
                CallbackQueryHandler(withdraw_cancel, pattern=f"^{CB_MAIN}$"),
                CommandHandler("start", start_command),
                CommandHandler("menu", menu_command),
            ],
            per_message=False,
        )

        # FSM for admin withdraw rejection reason
        admin_withdraw_reject_conversation = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(
                    admin_withdraw_reject_start,
                    pattern=f"^{CB_ADMIN_WITHDRAW_REJECT}",
                )
            ],
            states={
                ADMIN_WITHDRAW_REJECT_REASON: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_withdraw_reject_reason),
                    CallbackQueryHandler(admin_withdraw_reject_cancel, pattern=f"^{CB_ADMIN_PANEL}$"),
                ]
            },
            fallbacks=[
                CallbackQueryHandler(admin_withdraw_reject_cancel, pattern=f"^{CB_ADMIN_PANEL}$"),
                CommandHandler("panel", show_admin_panel),
            ],
            per_message=False,
        )

        # Basic commands
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("menu", menu_command))
        application.add_handler(CommandHandler("panel", show_admin_panel))

        # Admin commands
        application.add_handler(CommandHandler("giveadmin", cmd_giveadmin))
        application.add_handler(CommandHandler("deleteadmin", cmd_deleteadmin))
        application.add_handler(CommandHandler("add", cmd_add))
        application.add_handler(CommandHandler("delete", cmd_delete))
        application.add_handler(CommandHandler("ban", cmd_ban))
        application.add_handler(CommandHandler("sub", cmd_sub))
        application.add_handler(CommandHandler("send", cmd_send))

        # Conversation handlers (must be before generic callback router)
        application.add_handler(deposit_conversation)
        application.add_handler(bundle_conversation)
        application.add_handler(support_conversation)
        application.add_handler(admin_reply_conversation)
        application.add_handler(withdraw_conversation)
        application.add_handler(admin_withdraw_reject_conversation)

        # Admin withdraw approve/reject callbacks (register specific handlers first)
        application.add_handler(CallbackQueryHandler(admin_withdraw_approve, pattern=f"^{CB_ADMIN_WITHDRAW_APPROVE}"), group=0)
        application.add_handler(CallbackQueryHandler(admin_withdraw_reject_start, pattern=f"^{CB_ADMIN_WITHDRAW_REJECT}"), group=0)
        # Then register generic withdraw view to show details (will not match approve/reject due to guard)
        application.add_handler(CallbackQueryHandler(admin_withdraw_view, pattern=f"^{CB_ADMIN_WITHDRAW_PREFIX}"), group=0)

        # Generic callback router (lowest priority)
        application.add_handler(CallbackQueryHandler(callback_router), group=1)
        application.add_error_handler(error_handler)

        logger.info("Quantum bot started. Send /start or /menu in Telegram.")
        
        # Pass context to FastAPI
        main.ptb_app = application
        webapp_api._storage = storage
        webapp_api._tickets = tickets
        webapp_api._withdrawals = withdrawals
        webapp_api._payments = payments

        application.run_polling(allowed_updates=Update.ALL_TYPES)

    except Exception as e:
        logger.error(f"Failed to start bot: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
