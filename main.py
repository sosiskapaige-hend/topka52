"""Quantum Telegram bot — Render-compatible entry point.

On Render a single process must:
  1. Bind the HTTP port assigned via $PORT (FastAPI / uvicorn).
  2. Run the Telegram bot (PTB polling).
Both run concurrently inside one asyncio event loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import uvicorn
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
from bot.storage import UserStorage, TicketStorage, WithdrawStorage, PaymentStorage

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Global PTB application reference (used by webapp_api and payments_service)
ptb_app: Application | None = None


async def error_handler(update: Update | None, context) -> None:
    logger.error("Update %s caused error %s", update, context.error, exc_info=context.error)


def _start_self_ping(port: int) -> None:
    """Ping own HTTP endpoint every 50s to prevent Render free-tier sleep."""
    url = os.getenv("RENDER_EXTERNAL_URL", f"http://localhost:{port}") + "/health"

    async def _ping_loop() -> None:
        await asyncio.sleep(10)  # wait for uvicorn to start
        logger.info("Self-ping started → %s", url)
        while True:
            try:
                import urllib.request
                urllib.request.urlopen(url, timeout=10)  # noqa: S310
            except Exception:
                pass  # ignore errors — server may still be starting
            await asyncio.sleep(50)

    asyncio.get_event_loop().create_task(_ping_loop())


def _start_xrocket_poller(app: Application) -> None:
    """Poll pending Xrocket invoices in background (fallback when webhook unavailable)."""
    enabled = os.getenv("ENABLE_XROCKET_POLL", "true").lower() in ("1", "true", "yes")
    if not enabled:
        return

    interval = int(os.getenv("XROCKET_POLL_INTERVAL", "60"))

    async def _poll_loop() -> None:
        import bot.xrocket_client_prod as xrocket
        from bot.payments_service import invoice_is_paid, try_complete_payment, schedule_deposit_notification

        logger.info("Xrocket invoice poller started (interval=%ds)", interval)
        while True:
            try:
                payments: PaymentStorage | None = app.bot_data.get("payments")
                storage: UserStorage | None = app.bot_data.get("storage")
                if payments and storage:
                    for rec in payments.get_pending_payments():
                        invoice_id = rec.get("invoice_id")
                        if not invoice_id:
                            continue
                        try:
                            info = await xrocket.get_invoice(str(invoice_id))
                            if not invoice_is_paid(info):
                                continue
                            result = await try_complete_payment(
                                payments, storage, str(invoice_id),
                                external_meta=info if isinstance(info, dict) else None,
                            )
                            if result:
                                schedule_deposit_notification(result)
                                logger.info("Poller credited invoice %s → user %s", invoice_id, result["user_id"])
                        except Exception as e:
                            logger.error("Poller error for invoice %s: %s", invoice_id, e)
            except Exception as e:
                logger.error("Xrocket poller loop error: %s", e)
            await asyncio.sleep(interval)

    asyncio.get_event_loop().create_task(_poll_loop())


def _build_application(webapp_url: str | None, bot_name: str) -> Application:
    """Build and configure the PTB Application."""
    application = Application.builder().token(os.environ["BOT_TOKEN"]).build()

    storage = UserStorage(bot_name=bot_name)
    tickets = TicketStorage()
    withdrawals = WithdrawStorage()
    payments = PaymentStorage()

    application.bot_data["storage"] = storage
    application.bot_data["tickets"] = tickets
    application.bot_data["withdrawals"] = withdrawals
    application.bot_data["payments"] = payments
    application.bot_data["webapp_url"] = webapp_url

    # ── Conversation: deposit ────────────────────────────────────────────────
    deposit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(show_deposit_awaiting, pattern=f"^{CB_DEPOSIT}$")],
        states={
            DEPOSIT_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_amount_handler),
                CallbackQueryHandler(deposit_cancel, pattern=f"^{CB_DEPOSIT_CANCEL}$"),
                CallbackQueryHandler(deposit_cancel, pattern=f"^{CB_MAIN}$"),
            ]
        },
        fallbacks=[
            CallbackQueryHandler(deposit_cancel, pattern=f"^{CB_DEPOSIT_CANCEL}$"),
            CallbackQueryHandler(deposit_cancel, pattern=f"^{CB_MAIN}$"),
            CommandHandler("start", start_command),
            CommandHandler("menu", menu_command),
        ],
        per_message=False,
    )

    # ── Conversation: bundle ─────────────────────────────────────────────────
    bundle_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(show_bundle_launch, pattern=f"^{CB_COIN_PREFIX}")],
        states={
            BUNDLE_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bundle_amount_handler),
                CallbackQueryHandler(bundle_cancel, pattern=f"^{CB_BUNDLES}$"),
                CallbackQueryHandler(bundle_cancel, pattern=f"^{CB_MAIN}$"),
            ]
        },
        fallbacks=[
            CallbackQueryHandler(bundle_cancel, pattern=f"^{CB_BUNDLES}$"),
            CallbackQueryHandler(bundle_cancel, pattern=f"^{CB_MAIN}$"),
            CommandHandler("start", start_command),
            CommandHandler("menu", menu_command),
        ],
        per_message=False,
    )

    # ── Conversation: support ────────────────────────────────────────────────
    support_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(support_write_start, pattern=f"^{CB_SUPPORT_WRITE}$")],
        states={
            SUPPORT_MESSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, support_message_handler),
                CallbackQueryHandler(support_cancel, pattern=f"^{CB_SUPPORT}$"),
                CallbackQueryHandler(support_cancel, pattern=f"^{CB_MAIN}$"),
            ]
        },
        fallbacks=[
            CallbackQueryHandler(support_cancel, pattern=f"^{CB_SUPPORT}$"),
            CallbackQueryHandler(support_cancel, pattern=f"^{CB_MAIN}$"),
            CommandHandler("start", start_command),
            CommandHandler("menu", menu_command),
        ],
        per_message=False,
    )

    # ── Conversation: admin reply ────────────────────────────────────────────
    admin_reply_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_panel_ticket_view, pattern=f"^{CB_ADMIN_REPLY_PREFIX}")],
        states={
            ADMIN_REPLY_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_send_reply),
                CallbackQueryHandler(admin_reply_cancel, pattern=f"^{CB_ADMIN_PANEL}$"),
            ]
        },
        fallbacks=[
            CallbackQueryHandler(admin_reply_cancel, pattern=f"^{CB_ADMIN_PANEL}$"),
            CommandHandler("start", start_command),
            CommandHandler("menu", menu_command),
            CommandHandler("panel", show_admin_panel),
        ],
        per_message=False,
    )

    # ── Conversation: withdraw ───────────────────────────────────────────────
    withdraw_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(withdraw_start, pattern=f"^{CB_WITHDRAW}$")],
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

    # ── Conversation: admin withdraw reject ──────────────────────────────────
    admin_wd_reject_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_withdraw_reject_start, pattern=f"^{CB_ADMIN_WITHDRAW_REJECT}")],
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

    # ── Register handlers ────────────────────────────────────────────────────
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("panel", show_admin_panel))
    application.add_handler(CommandHandler("giveadmin", cmd_giveadmin))
    application.add_handler(CommandHandler("deleteadmin", cmd_deleteadmin))
    application.add_handler(CommandHandler("add", cmd_add))
    application.add_handler(CommandHandler("delete", cmd_delete))
    application.add_handler(CommandHandler("ban", cmd_ban))
    application.add_handler(CommandHandler("sub", cmd_sub))
    application.add_handler(CommandHandler("send", cmd_send))

    application.add_handler(deposit_conv)
    application.add_handler(bundle_conv)
    application.add_handler(support_conv)
    application.add_handler(admin_reply_conv)
    application.add_handler(withdraw_conv)
    application.add_handler(admin_wd_reject_conv)

    application.add_handler(CallbackQueryHandler(admin_withdraw_approve, pattern=f"^{CB_ADMIN_WITHDRAW_APPROVE}"), group=0)
    application.add_handler(CallbackQueryHandler(admin_withdraw_reject_start, pattern=f"^{CB_ADMIN_WITHDRAW_REJECT}"), group=0)
    application.add_handler(CallbackQueryHandler(admin_withdraw_view, pattern=f"^{CB_ADMIN_WITHDRAW_PREFIX}"), group=0)
    application.add_handler(CallbackQueryHandler(callback_router), group=1)
    application.add_error_handler(error_handler)

    return application


async def _run_bot(app: Application) -> None:
    """Run PTB polling inside an already-running event loop."""
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Telegram bot polling started")
    # Keep running until cancelled
    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


async def _run_web(port: int) -> None:
    """Run uvicorn inside an already-running event loop."""
    from bot.webapp_api import app as fastapi_app
    config = uvicorn.Config(fastapi_app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def _main_async() -> None:
    global ptb_app

    token = os.getenv("BOT_TOKEN")
    if not token or token == "your_telegram_bot_token_here":
        logger.error("BOT_TOKEN is not set")
        sys.exit(1)

    webapp_url = os.getenv("WEBAPP_URL", "https://topka52.onrender.com/app/index.html")
    bot_name = os.getenv("BOT_NAME", "quantumcryptobot")
    port = int(os.getenv("PORT", "8000"))

    if webapp_url and not webapp_url.startswith("https://"):
        logger.warning("WEBAPP_URL is not HTTPS — Telegram WebApp button will not work")

    # Initialize PostgreSQL pool (Neon)
    from bot.db import init_pool, close_pool
    await init_pool()
    logger.info("PostgreSQL pool initialized")

    # Build PTB app
    application = _build_application(webapp_url, bot_name)
    ptb_app = application

    # Ensure first admin exists in DB
    await application.bot_data["storage"].ensure_first_admin(5710686998)

    # Wire FastAPI to shared storage
    import bot.webapp_api as webapp_api
    webapp_api._storage = application.bot_data["storage"]
    webapp_api._tickets = application.bot_data["tickets"]
    webapp_api._withdrawals = application.bot_data["withdrawals"]
    webapp_api._payments = application.bot_data["payments"]

    # Start Xrocket poller
    _start_xrocket_poller(application)

    # Keep Render free tier awake
    _start_self_ping(port)

    logger.info("Starting on port %d | webapp_url=%s", port, webapp_url)

    # Run bot + web server concurrently
    await asyncio.gather(
        _run_bot(application),
        _run_web(port),
    )


def main() -> None:
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
