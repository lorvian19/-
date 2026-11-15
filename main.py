import asyncio
import logging
import os
import sqlite3

from dotenv import load_dotenv
load_dotenv()

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.types import ChatPermissions
from aiogram.enums import ChatMemberStatus, ChatType

# ============ НАСТРОЙКИ ============
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "/data/channels.db")

if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN в переменных окружения")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
BOT_ID = int(BOT_TOKEN.split(":")[0])  # ID бота из токена


# ============ БАЗА ДАННЫХ ============
def db():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            channel_id TEXT NOT NULL,
            channel_link TEXT,
            added_by INTEGER,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(chat_id, channel_id)
        )
    """)
    conn.commit()
    conn.close()


init_db()


def register_user(user: types.User):
    conn = db()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
        (user.id, user.username, user.full_name),
    )
    c.execute(
        "UPDATE users SET username = ?, full_name = ? WHERE user_id = ?",
        (user.username, user.full_name, user.id),
    )
    conn.commit()
    conn.close()


def register_chat(chat: types.Chat):
    conn = db()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO chats (chat_id, title) VALUES (?, ?)",
        (chat.id, chat.title),
    )
    c.execute("UPDATE chats SET title = ? WHERE chat_id = ?", (chat.title, chat.id))
    conn.commit()
    conn.close()


def add_channel(chat_id: int, channel_id: str, link: str, added_by: int) -> bool:
    conn = db()
    c = conn.cursor()
    try:
        c.execute(
            "INSERT OR REPLACE INTO channels (chat_id, channel_id, channel_link, added_by) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, channel_id, link, added_by),
        )
        conn.commit()
        return True
    except Exception as e:
        logging.error(f"add_channel error: {e}")
        return False
    finally:
        conn.close()


def remove_channel(chat_id: int, channel_id: str) -> bool:
    conn = db()
    c = conn.cursor()
    c.execute(
        "DELETE FROM channels WHERE chat_id = ? AND channel_id = ?",
        (chat_id, channel_id),
    )
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def get_channels(chat_id: int):
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT channel_id, channel_link FROM channels WHERE chat_id = ?",
        (chat_id,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def stats():
    conn = db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM chats")
    chats = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM channels")
    chans = c.fetchone()[0]
    conn.close()
    return users, chats, chans


# ============ ПРОВЕРКИ ============
async def is_subscribed(user_id: int, channel_id: str) -> bool:
    try:
        m = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        return m.status in {
            ChatMemberStatus.CREATOR,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.MEMBER,
        }
    except Exception as e:
        logging.warning(f"check_sub {channel_id}: {e}")
        return False


async def is_chat_admin(chat_id: int, user_id: int) -> bool:
    try:
        m = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return m.status in {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR}
    except Exception:
        return False


async def restrict_user(chat_id: int, user_id: int, can_send: bool):
    perms = ChatPermissions(
        can_send_messages=can_send,
        can_send_media_messages=can_send,
        can_send_other_messages=can_send,
        can_add_web_page_previews=can_send,
        can_send_polls=can_send,
    )
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id, user_id=user_id, permissions=perms
        )
    except Exception as e:
        logging.error(f"restrict {user_id}: {e}")


# ============ КОМАНДЫ ============
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.from_user:
        register_user(message.from_user)

    if message.chat.type == ChatType.PRIVATE:
        await message.answer(
            f"👋 Привет, {message.from_user.first_name}!\n\n"
            "Я бот-замок для Telegram-чатов. Проверяю подписку на каналы "
            "и не даю писать тем, кто не подписан.\n\n"
            "🚀 <b>Быстрый старт:</b>\n"
            "1. Добавьте меня в свою группу\n"
            "2. Дайте мне права: <b>удалять сообщения</b> + <b>ограничивать участников</b>\n"
            "3. Добавьте меня в канал-обязаловку (тоже администратором)\n"
            "4. В группе напишите <code>/add_channel @ваш_канал</code>\n\n"
            "⚙️ <b>Команды администратора группы:</b>\n"
            "/add_channel — добавить канал\n"
            "/remove_channel — удалить канал\n"
            "/list_channels — список каналов\n"
            "/menu — панель управления\n\n"
            "👤 <b>Команды участника:</b>\n"
            "/check — проверить подписку и разблокироваться\n\n"
            "ℹ️ ID канала: перешлите любое сообщение из него боту @userinfobot",
            parse_mode="HTML",
        )
    else:
        register_chat(message.chat)
        await message.answer("Готов к работе! /menu — панель управления.")


@dp.message(Command("menu"))
async def cmd_menu(message: types.Message):
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Меню доступно в группах. Добавьте меня в группу.")
        return

    if not await is_chat_admin(message.chat.id, message.from_user.id):
        await message.answer("⛔ Только для администраторов чата.")
        return

    channels = get_channels(message.chat.id)
    text = "⚙️ <b>Панель управления</b>\n\n"
    text += f"📡 Обязательных каналов: <b>{len(channels)}</b>\n\n"
    text += "<b>Добавить канал:</b>\n"
    text += "<code>/add_channel @username</code>\n"
    text += "<code>/add_channel -1001234567890 https://t.me/link</code>\n\n"
    text += "<b>Список:</b> /list_channels\n"
    text += "<b>Удалить:</b> /remove_channel &lt;ID&gt;"
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("add_channel"))
async def cmd_add_channel(message: types.Message, command: CommandObject):
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Эта команда работает только в группах.")
        return

    if not await is_chat_admin(message.chat.id, message.from_user.id):
        await message.answer("⛔ Только для администраторов этого чата.")
        return

    args = command.args
    if not args:
        await message.answer(
            "📝 <b>Использование:</b>\n"
            "<code>/add_channel @my_channel</code>\n"
            "или с явной ссылкой:\n"
            "<code>/add_channel -1001234567890 https://t.me/my_channel</code>\n\n"
            "💡 Бот должен быть администратором канала!",
            parse_mode="HTML",
        )
        return

    parts = args.split(maxsplit=1)
    raw = parts[0].strip()
    link = parts[1].strip() if len(parts) > 1 else None

    # Резолвим @username в ID
    resolved_id = raw
    title = raw
    if raw.startswith("@"):
        try:
            chat = await bot.get_chat(raw)
            resolved_id = str(chat.id)
            title = chat.title or raw
            if not link and chat.username:
                link = f"https://t.me/{chat.username}"
        except Exception as e:
            await message.answer(
                f"❌ Не удалось найти канал <code>{raw}</code>.\n"
                f"Убедитесь, что я добавлен в него как администратор.\n\n"
                f"<i>{e}</i>",
                parse_mode="HTML",
            )
            return

    # Проверяем, что бот админ в канале
    try:
        bm = await bot.get_chat_member(chat_id=resolved_id, user_id=BOT_ID)
        if bm.status not in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
            await message.answer(
                "❌ Я не администратор в этом канале.\n"
                "Добавьте меня в канал администратором и попробуйте снова."
            )
            return
    except Exception as e:
        await message.answer(
            f"❌ Не могу проверить канал. Убедитесь, что я админ канала.\n"
            f"<i>{e}</i>",
            parse_mode="HTML",
        )
        return

    if add_channel(message.chat.id, resolved_id, link, message.from_user.id):
        await message.answer(
            f"✅ Канал добавлен!\n\n"
            f"<b>Название:</b> {title}\n"
            f"<b>ID:</b> <code>{resolved_id}</code>\n"
            f"<b>Ссылка:</b> {link or '—'}\n\n"
            f"Теперь любой, кто не подписан, не сможет писать в этот чат.",
            parse_mode="HTML",
        )
    else:
        await message.answer("❌ Не удалось сохранить канал. Попробуйте позже.")


@dp.message(Command("remove_channel"))
async def cmd_remove_channel(message: types.Message, command: CommandObject):
    if message.chat.type == ChatType.PRIVATE:
        return
    if not await is_chat_admin(message.chat.id, message.from_user.id):
        await message.answer("⛔ Только для администраторов чата.")
        return

    if not command.args:
        await message.answer("📝 Использование: <code>/remove_channel &lt;ID&gt;</code>", parse_mode="HTML")
        return

    channel_id = command.args.strip()
    if remove_channel(message.chat.id, channel_id):
        await message.answer(f"🗑 Канал <code>{channel_id}</code> удалён.", parse_mode="HTML")
    else:
        await message.answer("⚠️ Такой канал не найден в списке.")


@dp.message(Command("list_channels"))
async def cmd_list_channels(message: types.Message):
    if message.chat.type == ChatType.PRIVATE:
        return
    if not await is_chat_admin(message.chat.id, message.from_user.id):
        await message.answer("⛔ Только для администраторов чата.")
        return

    channels = get_channels(message.chat.id)
    if not channels:
        await message.answer(
            "📭 Список каналов пуст.\n\n"
            "Добавьте первый: <code>/add_channel @your_channel</code>",
            parse_mode="HTML",
        )
        return

    text = "📋 <b>Обязательные каналы:</b>\n\n"
    for i, (ch_id, link) in enumerate(channels, 1):
        text += f"{i}. <code>{ch_id}</code>"
        if link:
            text += f" — {link}"
        text += "\n"
    text += "\n💡 Удалить: <code>/remove_channel &lt;ID&gt;</code>"
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("check"))
async def cmd_check(message: types.Message):
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Эта команда работает в группах.")
        return

    user_id = message.from_user.id
    chat_id = message.chat.id

    channels = get_channels(chat_id)
    if not channels:
        await message.answer("✅ Список каналов пуст, все могут писать.")
        return

    not_sub = []
    for ch_id, link in channels:
        if not await is_subscribed(user_id, ch_id):
            not_sub.append((ch_id, link))

    if not not_sub:
        await restrict_user(chat_id, user_id, True)
        await message.answer("✅ Отлично! Вы подписаны на всё. Можете писать.")
    else:
        links = "\n".join([f"• {link or ch_id}" for _, link in not_sub])
        await message.answer(
            f"⚠️ Вы не подписаны на:\n{links}\n\n"
            "Подпишитесь и напишите /check снова.",
            disable_web_page_preview=True,
        )


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if message.chat.type == ChatType.PRIVATE:
        users, chats, chans = stats()
        await message.answer(
            f"📊 <b>Статистика бота</b>\n\n"
            f"👥 Пользователей: <b>{users}</b>\n"
            f"💬 Чатов: <b>{chats}</b>\n"
            f"📡 Каналов: <b>{chans}</b>",
            parse_mode="HTML",
        )


# ============ АВТО-ДЕЙСТВИЯ ============
@dp.message(F.new_chat_members)
async def on_new_members(message: types.Message):
    for member in message.new_chat_members:
        if member.id == BOT_ID:
            register_chat(message.chat)
            await message.answer(
                "🎉 Спасибо за добавление!\n\n"
                "⚙️ <b>Чтобы включить защиту:</b>\n"
                "1. Дайте мне права: <b>удалять сообщения</b> + <b>ограничивать участников</b>\n"
                "2. Добавьте меня администратором в канал, на который надо проверять\n"
                "3. В этом чате напишите <code>/add_channel @ваш_канал</code>\n\n"
                "📖 Полная инструкция: /start\n"
                "⚙️ Панель: /menu",
                parse_mode="HTML",
            )
            return


@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def enforce_subscription(message: types.Message):
    if not message.from_user or message.from_user.is_bot:
        return

    user_id = message.from_user.id
    chat_id = message.chat.id

    register_user(message.from_user)
    register_chat(message.chat)

    # Админов пропускаем
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        if member.status in {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR}:
            return
    except Exception:
        pass

    channels = get_channels(chat_id)
    if not channels:
        return

    not_sub = []
    for ch_id, link in channels:
        if not await is_subscribed(user_id, ch_id):
            not_sub.append((ch_id, link))

    if not not_sub:
        await restrict_user(chat_id, user_id, True)
        return

    # Удаляем сообщение и ограничиваем
    try:
        await message.delete()
    except Exception:
        pass

    await restrict_user(chat_id, user_id, False)

    links = "\n".join([f"• {link or ch_id}" for _, link in not_sub])
    try:
        await bot.send_message(
            chat_id,
            f"⚠️ {message.from_user.full_name}, чтобы писать в этот чат, "
            f"подпишитесь на:\n{links}\n\n"
            f"После подписки напишите /check",
            disable_web_page_preview=True,
        )
    except Exception:
        pass


# ============ ЗАПУСК ============
async def main():
    logging.info(f"Бот запущен. ID: {BOT_ID}")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())