"""
crm_writer.py — вставить в проект основного бота.

Сохраняет пользователей и сообщения в PostgreSQL CRM.
Не запускает никаких Telegram handlers, polling или webhook.

Использование:
    from crm_writer import crm

    # В обработчике любого update:
    await crm.save_update(update, context)

    # Или точечно:
    await crm.save_user(update.effective_user)
    await crm.save_message(update.message, user_db_id)
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Text, \
    func, select, update, or_
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
import enum

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models (mirrors CRM schema exactly — do not change column names/types)
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


class UserStatus(str, enum.Enum):
    active = "active"
    blocked = "blocked"
    deleted = "deleted"


class MessageDirection(str, enum.Enum):
    incoming = "incoming"
    outgoing = "outgoing"


class MessageType(str, enum.Enum):
    text = "text"
    photo = "photo"
    document = "document"
    gif = "gif"
    sticker = "sticker"
    voice = "voice"
    audio = "audio"
    video_note = "video_note"
    video = "video"
    location = "location"
    contact = "contact"
    poll = "poll"
    service = "service"


class DeliveryStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    delivered = "delivered"
    read = "read"
    failed = "failed"


class AttachmentType(str, enum.Enum):
    photo = "photo"
    document = "document"
    gif = "gif"
    sticker = "sticker"
    voice = "voice"
    audio = "audio"
    video_note = "video_note"


class TelegramUser(Base):
    __tablename__ = "telegram_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    language_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    avatar_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[UserStatus] = mapped_column(Enum(UserStatus), default=UserStatus.active, index=True)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    unread_count: Mapped[int] = mapped_column(Integer, default=0)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_active: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)

    messages: Mapped[list["Message"]] = relationship("Message", back_populates="user", lazy="noload")

    __table_args__ = (
        Index("ix_users_last_active", "last_active"),
        Index("ix_users_status_last_active", "status", "last_active"),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("telegram_users.id", ondelete="CASCADE"), index=True)
    telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    direction: Mapped[MessageDirection] = mapped_column(Enum(MessageDirection), index=True)
    message_type: Mapped[MessageType] = mapped_column(Enum(MessageType), default=MessageType.text)
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parse_mode: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    reply_to_message_id: Mapped[Optional[int]] = mapped_column(ForeignKey("messages.id"), nullable=True)
    forward_from_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    forward_from_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    inline_keyboard: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    reply_keyboard: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_status: Mapped[DeliveryStatus] = mapped_column(Enum(DeliveryStatus), default=DeliveryStatus.delivered)
    sent_by_admin_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    edited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["TelegramUser"] = relationship("TelegramUser", back_populates="messages", lazy="noload")
    attachments: Mapped[list["Attachment"]] = relationship(
        "Attachment", back_populates="message", lazy="noload", cascade="all, delete-orphan"
    )
    reply_to: Mapped[Optional["Message"]] = relationship(
        "Message", remote_side="Message.id", foreign_keys=[reply_to_message_id], lazy="noload"
    )

    __table_args__ = (
        Index("ix_messages_user_created", "user_id", "created_at"),
        Index("ix_messages_chat_created", "chat_id", "created_at"),
    )


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    attachment_type: Mapped[AttachmentType] = mapped_column(Enum(AttachmentType))
    file_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    file_unique_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    message: Mapped["Message"] = relationship("Message", back_populates="attachments", lazy="noload")


# ---------------------------------------------------------------------------
# CRM Writer
# ---------------------------------------------------------------------------

class CRMWriter:
    def __init__(self, database_url: str):
        database_url = database_url.replace("&amp;", "&")
        from urllib.parse import urlparse, urlunparse, parse_qs
        parsed = urlparse(database_url)
        params = parse_qs(parsed.query)
        ssl_required = "sslmode" in params or "ssl" in params
        clean_parsed = parsed._replace(query="")
        clean_url = urlunparse(clean_parsed)
        if clean_url.startswith("postgresql://"):
            clean_url = clean_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        connect_args = {"ssl": "require"} if ssl_required else {}
        logger.info("crm_writer: connecting to %s (ssl=%s)", clean_url.split("@")[-1], ssl_required)
        self._engine = create_async_engine(
            clean_url, pool_size=3, max_overflow=5, connect_args=connect_args
        )
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def close(self):
        await self._engine.dispose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def save_update(self, update, context=None) -> None:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    if update.message:
                        await self._handle_message(session, update.message, is_edit=False)
                    elif update.edited_message:
                        await self._handle_message(session, update.edited_message, is_edit=True)
                    elif update.channel_post:
                        await self._handle_message(session, update.channel_post, is_edit=False)
                    elif update.callback_query and update.callback_query.message:
                        await self._handle_callback(session, update.callback_query)
            logger.debug("crm_writer: saved update %s", getattr(update, "update_id", "?"))
        except Exception as e:
            logger.error("crm_writer: failed to save update %s: %s", getattr(update, "update_id", "?"), e, exc_info=True)

    async def save_outgoing(
        self,
        telegram_user_id: int,
        text: str,
        telegram_message_id: Optional[int] = None,
        parse_mode: Optional[str] = None,
    ) -> None:
        """Call after bot.send_message() to record outgoing message in CRM."""
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    user = await self._get_or_none(session, telegram_user_id)
                    if not user:
                        return
                    msg = Message(
                        user_id=user.id,
                        telegram_message_id=telegram_message_id,
                        chat_id=telegram_user_id,
                        direction=MessageDirection.outgoing,
                        message_type=MessageType.text,
                        text=text,
                        parse_mode=parse_mode,
                        delivery_status=DeliveryStatus.sent,
                        created_at=datetime.now(timezone.utc),
                    )
                    session.add(msg)
                    await session.flush()
                    await self._inc_message_count(session, user.id)
        except Exception:
            logger.exception("crm_writer: failed to save outgoing message")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _handle_message(self, session: AsyncSession, msg, is_edit: bool) -> None:
        tg_user = msg.from_user
        if not tg_user:
            logger.warning("crm_writer: message has no from_user (chat_id=%s, msg_id=%s)", getattr(msg, 'chat_id', '?'), getattr(msg, 'message_id', '?'))
            return

        logger.info("crm_writer: saving message from user %s (edit=%s)", tg_user.id, is_edit)

        user = await self._upsert_user(session, tg_user)

        if is_edit:
            existing = await self._get_message_by_tg_id(session, msg.message_id, msg.chat_id)
            if existing:
                existing.text = msg.text or msg.caption
                existing.is_edited = True
                existing.edited_at = datetime.now(timezone.utc)
            return

        msg_type, text, caption = self._extract_content(msg)

        reply_to_id = None
        if msg.reply_to_message:
            ref = await self._get_message_by_tg_id(session, msg.reply_to_message.message_id, msg.chat_id)
            if ref:
                reply_to_id = ref.id

        forward_from_id = None
        forward_from_name = None
        if getattr(msg, 'forward_origin', None):
            origin = msg.forward_origin
            user = getattr(origin, 'sender_user', None)
            if user:
                forward_from_id = user.id
                name_parts = filter(None, [user.first_name, user.last_name])
                forward_from_name = " ".join(name_parts) or None

        db_msg = Message(
            user_id=user.id,
            telegram_message_id=msg.message_id,
            chat_id=msg.chat_id if isinstance(msg.chat_id, int) else msg.chat.id,
            direction=MessageDirection.incoming,
            message_type=msg_type,
            text=text,
            caption=caption,
            reply_to_message_id=reply_to_id,
            forward_from_id=forward_from_id,
            forward_from_name=forward_from_name,
            delivery_status=DeliveryStatus.delivered,
            created_at=datetime.fromtimestamp(msg.date.timestamp(), tz=timezone.utc),
        )
        session.add(db_msg)
        await session.flush()

        self._add_attachment(session, db_msg.id, msg)

        await self._inc_message_count(session, user.id)
        await self._inc_unread(session, user.id)

    async def _handle_callback(self, session: AsyncSession, cq) -> None:
        if cq.from_user:
            await self._upsert_user(session, cq.from_user)

    async def _upsert_user(self, session: AsyncSession, tg_user) -> TelegramUser:
        result = await session.execute(
            select(TelegramUser).where(TelegramUser.telegram_id == tg_user.id)
        )
        user = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)

        if user:
            user.username = tg_user.username
            user.first_name = tg_user.first_name
            user.last_name = tg_user.last_name
            user.language_code = tg_user.language_code
            user.last_active = now
        else:
            user = TelegramUser(
                telegram_id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name,
                last_name=tg_user.last_name,
                language_code=tg_user.language_code,
                is_bot=tg_user.is_bot,
                last_active=now,
            )
            session.add(user)

        await session.flush()
        return user

    async def _get_or_none(self, session: AsyncSession, telegram_id: int) -> Optional[TelegramUser]:
        result = await session.execute(
            select(TelegramUser).where(TelegramUser.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def _get_message_by_tg_id(
        self, session: AsyncSession, telegram_message_id: int, chat_id: int
    ) -> Optional[Message]:
        result = await session.execute(
            select(Message).where(
                Message.telegram_message_id == telegram_message_id,
                Message.chat_id == chat_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _extract_content(msg) -> tuple[MessageType, Optional[str], Optional[str]]:
        if msg.text:
            return MessageType.text, msg.text, None
        if msg.photo:
            return MessageType.photo, None, msg.caption
        if msg.document:
            mime = msg.document.mime_type or ""
            name = msg.document.file_name or ""
            if "gif" in mime or name.endswith(".gif"):
                return MessageType.gif, None, msg.caption
            return MessageType.document, None, msg.caption
        if msg.sticker:
            return MessageType.sticker, None, None
        if msg.voice:
            return MessageType.voice, None, None
        if msg.audio:
            return MessageType.audio, None, None
        if msg.video_note:
            return MessageType.video_note, None, None
        if msg.video:
            return MessageType.video, None, msg.caption
        if msg.location:
            return MessageType.location, None, None
        if msg.contact:
            return MessageType.contact, None, None
        if msg.poll:
            return MessageType.poll, None, None
        return MessageType.text, msg.text, None

    @staticmethod
    def _add_attachment(session: AsyncSession, message_id: int, msg) -> None:
        att = None

        if msg.photo:
            largest = max(msg.photo, key=lambda p: p.file_size or 0)
            att = Attachment(
                message_id=message_id,
                attachment_type=AttachmentType.photo,
                file_id=largest.file_id,
                file_unique_id=largest.file_unique_id,
                file_size=largest.file_size,
                width=largest.width,
                height=largest.height,
            )
        elif msg.document:
            mime = msg.document.mime_type or ""
            att = Attachment(
                message_id=message_id,
                attachment_type=AttachmentType.gif if "gif" in mime else AttachmentType.document,
                file_id=msg.document.file_id,
                file_unique_id=msg.document.file_unique_id,
                file_name=msg.document.file_name,
                mime_type=mime,
                file_size=msg.document.file_size,
            )
        elif msg.sticker:
            att = Attachment(
                message_id=message_id,
                attachment_type=AttachmentType.sticker,
                file_id=msg.sticker.file_id,
                file_unique_id=msg.sticker.file_unique_id,
                width=msg.sticker.width,
                height=msg.sticker.height,
            )
        elif msg.voice:
            att = Attachment(
                message_id=message_id,
                attachment_type=AttachmentType.voice,
                file_id=msg.voice.file_id,
                file_unique_id=msg.voice.file_unique_id,
                mime_type=msg.voice.mime_type,
                file_size=msg.voice.file_size,
                duration=msg.voice.duration,
            )
        elif msg.audio:
            att = Attachment(
                message_id=message_id,
                attachment_type=AttachmentType.audio,
                file_id=msg.audio.file_id,
                file_unique_id=msg.audio.file_unique_id,
                file_name=msg.audio.file_name,
                mime_type=msg.audio.mime_type,
                file_size=msg.audio.file_size,
                duration=msg.audio.duration,
            )
        elif msg.video_note:
            att = Attachment(
                message_id=message_id,
                attachment_type=AttachmentType.video_note,
                file_id=msg.video_note.file_id,
                file_unique_id=msg.video_note.file_unique_id,
                file_size=msg.video_note.file_size,
                duration=msg.video_note.duration,
            )

        if att:
            session.add(att)

    @staticmethod
    async def _inc_message_count(session: AsyncSession, user_id: int) -> None:
        await session.execute(
            update(TelegramUser)
            .where(TelegramUser.id == user_id)
            .values(message_count=TelegramUser.message_count + 1)
        )

    @staticmethod
    async def _inc_unread(session: AsyncSession, user_id: int) -> None:
        await session.execute(
            update(TelegramUser)
            .where(TelegramUser.id == user_id)
            .values(unread_count=TelegramUser.unread_count + 1)
        )


# ---------------------------------------------------------------------------
# Singleton — инициализируй один раз при старте бота
# ---------------------------------------------------------------------------

crm: Optional[CRMWriter] = None


def init_crm(database_url: str) -> CRMWriter:
    """Call once on bot startup. Returns the global CRMWriter instance."""
    global crm
    crm = CRMWriter(database_url)
    return crm
