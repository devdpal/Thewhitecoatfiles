"""
The White Coat Files — MBBS Resource Telegram Bot
Python 3.10+
Library: python-telegram-bot 21.x

Features:
- /start: student-facing welcome and resource menu
- Resource type -> MBBS subject -> files
- /add: admin-only guided upload flow (choose category, subject, then send files)
- Files are stored by Telegram file_id in SQLite; files are sent directly in bot chat
- Back/home navigation, pagination, basic validation, error handling
- Admin-only /cancel and /stats
"""

import logging
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", "white_coat_library.sqlite3")
PAGE_SIZE = 8

RESOURCE_TYPES = {
    "books": "📚 Books",
    "pdfs": "📄 PDFs / Notes",
    "videos": "🎬 Videos",
    "other": "🗂 Other Resources",
}

# Standard 19-subject MBBS structure used as an editable starting point.
# You can change these labels in this list if your university follows a different naming.
SUBJECTS = [
    "Anatomy",
    "Physiology",
    "Biochemistry",
    "Pathology",
    "Pharmacology",
    "Microbiology",
    "Forensic Medicine & Toxicology",
    "Community Medicine",
    "Ophthalmology",
    "Otorhinolaryngology (ENT)",
    "General Medicine",
    "General Surgery",
    "Obstetrics & Gynaecology",
    "Paediatrics",
    "Orthopaedics",
    "Dermatology",
    "Psychiatry",
    "Anaesthesiology",
    "Radiology",
]

SUBJECT_KEYS = {str(i): subject for i, subject in enumerate(SUBJECTS)}
CATEGORY_KEYS = set(RESOURCE_TYPES.keys())

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def parse_admin_ids(raw: str) -> set[int]:
    """Parse comma-separated Telegram numeric user IDs."""
    result: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.add(int(item))
        except ValueError as exc:
            raise ValueError(f"ADMIN_IDS contains a non-numeric value: {item!r}") from exc
    return result


ADMIN_IDS = parse_admin_ids(ADMIN_IDS_RAW)


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    with closing(db_connect()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS resources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                subject TEXT NOT NULL,
                file_id TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_name TEXT NOT NULL,
                caption TEXT,
                uploaded_by INTEGER NOT NULL,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_resources_category_subject "
            "ON resources(category, subject, id)"
        )
        conn.commit()


def is_admin(user_id: Optional[int]) -> bool:
    return user_id is not None and user_id in ADMIN_IDS


def home_keyboard(user_id: Optional[int] = None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📚 Books", callback_data="cat:books"),
            InlineKeyboardButton("📄 PDFs / Notes", callback_data="cat:pdfs"),
        ],
        [
            InlineKeyboardButton("🎬 Videos", callback_data="cat:videos"),
            InlineKeyboardButton("🗂 Other Resources", callback_data="cat:other"),
        ],
    ]
    if is_admin(user_id):
        rows.append([InlineKeyboardButton("➕ Add Resource", callback_data="admin:add")])
    return InlineKeyboardMarkup(rows)


def subjects_keyboard(category: str, page: int = 0) -> InlineKeyboardMarkup:
    rows = []
    start = page * PAGE_SIZE
    page_subjects = SUBJECTS[start:start + PAGE_SIZE]
    for offset in range(0, len(page_subjects), 2):
        row = []
        for idx in range(offset, min(offset + 2, len(page_subjects))):
            subject = page_subjects[idx]
            subject_id = SUBJECTS.index(subject)
            label = subject if len(subject) <= 30 else subject[:27] + "…"
            row.append(InlineKeyboardButton(label, callback_data=f"sub:{category}:{subject_id}:0"))
        rows.append(row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"subpage:{category}:{page-1}"))
    if start + PAGE_SIZE < len(SUBJECTS):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"subpage:{category}:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="home")])
    return InlineKeyboardMarkup(rows)


def files_keyboard(category: str, subject_id: int, page: int = 0) -> tuple[InlineKeyboardMarkup, int]:
    subject = SUBJECT_KEYS[str(subject_id)]
    with closing(db_connect()) as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM resources WHERE category=? AND subject=?",
            (category, subject),
        ).fetchone()["n"]
        rows_data = conn.execute(
            "SELECT id, file_name FROM resources WHERE category=? AND subject=? "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            (category, subject, PAGE_SIZE, page * PAGE_SIZE),
        ).fetchall()

    rows = []
    for item in rows_data:
        label = item["file_name"]
        if len(label) > 48:
            label = label[:45] + "…"
        rows.append([InlineKeyboardButton(f"📎 {label}", callback_data=f"file:{item['id']}")])

    if not rows_data:
        rows.append([InlineKeyboardButton("No files uploaded yet", callback_data="noop")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"sub:{category}:{subject_id}:{page-1}"))
    if (page + 1) * PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"sub:{category}:{subject_id}:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("⬅️ Subjects", callback_data=f"cat:{category}")])
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="home")])
    return InlineKeyboardMarkup(rows), total


def upload_category_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for key, label in RESOURCE_TYPES.items():
        rows.append([InlineKeyboardButton(label, callback_data=f"uploadcat:{key}")])
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="admin:cancel")])
    return InlineKeyboardMarkup(rows)


def upload_subject_keyboard(category: str, page: int = 0) -> InlineKeyboardMarkup:
    rows = []
    start = page * PAGE_SIZE
    page_subjects = SUBJECTS[start:start + PAGE_SIZE]
    for offset in range(0, len(page_subjects), 2):
        row = []
        for idx in range(offset, min(offset + 2, len(page_subjects))):
            subject = page_subjects[idx]
            subject_id = SUBJECTS.index(subject)
            label = subject if len(subject) <= 30 else subject[:27] + "…"
            row.append(InlineKeyboardButton(label, callback_data=f"uploadsub:{category}:{subject_id}"))
        rows.append(row)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"uploadsubpage:{category}:{page-1}"))
    if start + PAGE_SIZE < len(SUBJECTS):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"uploadsubpage:{category}:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="admin:cancel")])
    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if update.effective_message:
        await update.effective_message.reply_text(
            "👋 Welcome to The White Coat Files — MBBS Library!\n\n"
            "Choose a resource type, then select a subject to browse available files.",
            reply_markup=home_keyboard(user.id if user else None),
        )


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not is_admin(user.id):
        if update.effective_message:
            await update.effective_message.reply_text("⛔ This command is only available to the bot admin.")
        return
    context.user_data["upload_state"] = "choose_category"
    context.user_data.pop("upload_category", None)
    context.user_data.pop("upload_subject", None)
    await update.effective_message.reply_text(
        "➕ Add a resource\n\nStep 1 of 3: Choose a category.",
        reply_markup=upload_category_keyboard(),
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("upload_state", None)
    context.user_data.pop("upload_category", None)
    context.user_data.pop("upload_subject", None)
    if update.effective_message:
        await update.effective_message.reply_text(
            "Upload cancelled.",
            reply_markup=home_keyboard(update.effective_user.id if update.effective_user else None),
        )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not is_admin(user.id):
        await update.effective_message.reply_text("⛔ Admin only.")
        return
    with closing(db_connect()) as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM resources").fetchone()["n"]
        by_cat = conn.execute(
            "SELECT category, COUNT(*) AS n FROM resources GROUP BY category ORDER BY category"
        ).fetchall()
    lines = [f"Total saved files: {total}"]
    lines.extend(f"{RESOURCE_TYPES.get(row['category'], row['category'])}: {row['n']}" for row in by_cat)
    await update.effective_message.reply_text("\n".join(lines))


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    user = query.from_user
    data = query.data or ""

    try:
        if data == "noop":
            return

        if data == "home":
            context.user_data.pop("upload_state", None)
            await query.edit_message_text(
                "🏠 Main Menu\n\nChoose a resource type:",
                reply_markup=home_keyboard(user.id),
            )
            return

        if data.startswith("cat:"):
            category = data.split(":", 1)[1]
            if category not in CATEGORY_KEYS:
                await query.edit_message_text("Unknown category. Please use /start.")
                return
            await query.edit_message_text(
                f"{RESOURCE_TYPES[category]}\n\nChoose a subject:",
                reply_markup=subjects_keyboard(category, 0),
            )
            return

        if data.startswith("subpage:"):
            _, category, page_raw = data.split(":")
            page = int(page_raw)
            if category not in CATEGORY_KEYS or page < 0:
                raise ValueError("Invalid subject page")
            await query.edit_message_text(
                f"{RESOURCE_TYPES[category]}\n\nChoose a subject:",
                reply_markup=subjects_keyboard(category, page),
            )
            return

        if data.startswith("sub:"):
            _, category, subject_id_raw, page_raw = data.split(":")
            subject_id, page = int(subject_id_raw), int(page_raw)
            if category not in CATEGORY_KEYS or str(subject_id) not in SUBJECT_KEYS or page < 0:
                raise ValueError("Invalid subject selection")
            keyboard, total = files_keyboard(category, subject_id, page)
            subject = SUBJECT_KEYS[str(subject_id)]
            await query.edit_message_text(
                f"{RESOURCE_TYPES[category]} → {subject}\n\n"
                + (f"Available files: {total}" if total else "No files uploaded yet."),
                reply_markup=keyboard,
            )
            return

        if data.startswith("file:"):
            file_db_id = int(data.split(":", 1)[1])
            with closing(db_connect()) as conn:
                item = conn.execute("SELECT * FROM resources WHERE id=?", (file_db_id,)).fetchone()
            if not item:
                await query.message.reply_text("Sorry, this file entry no longer exists.")
                return
            await send_stored_file(query.message, item)
            return

        if data == "admin:add":
            if not is_admin(user.id):
                await query.answer("Admin only.", show_alert=True)
                return
            context.user_data["upload_state"] = "choose_category"
            await query.edit_message_text(
                "➕ Add a resource\n\nStep 1 of 3: Choose a category.",
                reply_markup=upload_category_keyboard(),
            )
            return

        if data.startswith("uploadcat:"):
            if not is_admin(user.id):
                await query.answer("Admin only.", show_alert=True)
                return
            category = data.split(":", 1)[1]
            if category not in CATEGORY_KEYS:
                raise ValueError("Invalid upload category")
            context.user_data["upload_category"] = category
            context.user_data["upload_state"] = "choose_subject"
            await query.edit_message_text(
                f"Category: {RESOURCE_TYPES[category]}\n\nStep 2 of 3: Choose the subject.",
                reply_markup=upload_subject_keyboard(category, 0),
            )
            return

        if data.startswith("uploadsubpage:"):
            if not is_admin(user.id):
                await query.answer("Admin only.", show_alert=True)
                return
            _, category, page_raw = data.split(":")
            page = int(page_raw)
            if category not in CATEGORY_KEYS or page < 0:
                raise ValueError("Invalid upload subject page")
            await query.edit_message_text(
                f"Category: {RESOURCE_TYPES[category]}\n\nStep 2 of 3: Choose the subject.",
                reply_markup=upload_subject_keyboard(category, page),
            )
            return

        if data.startswith("uploadsub:"):
            if not is_admin(user.id):
                await query.answer("Admin only.", show_alert=True)
                return
            _, category, subject_id_raw = data.split(":")
            subject_id = int(subject_id_raw)
            if category not in CATEGORY_KEYS or str(subject_id) not in SUBJECT_KEYS:
                raise ValueError("Invalid upload subject")
            context.user_data["upload_category"] = category
            context.user_data["upload_subject"] = SUBJECT_KEYS[str(subject_id)]
            context.user_data["upload_state"] = "receiving_files"
            await query.edit_message_text(
                f"✅ Category: {RESOURCE_TYPES[category]}\n"
                f"✅ Subject: {SUBJECT_KEYS[str(subject_id)]}\n\n"
                "Step 3 of 3: Send a book, PDF/document, video, audio, or photo now.\n"
                "You can send multiple files one after another. Each file is saved to this selection.\n\n"
                "Use /cancel when finished.",
            )
            return

        if data == "admin:cancel":
            if not is_admin(user.id):
                await query.answer("Admin only.", show_alert=True)
                return
            context.user_data.pop("upload_state", None)
            context.user_data.pop("upload_category", None)
            context.user_data.pop("upload_subject", None)
            await query.edit_message_text("Upload cancelled.", reply_markup=home_keyboard(user.id))
            return

    except (ValueError, KeyError) as exc:
        logger.warning("Invalid callback data %r: %s", data, exc)
        await query.message.reply_text("That button could not be processed. Please use /start and try again.")
    except TelegramError:
        logger.exception("Telegram API error while handling callback")
        try:
            await query.message.reply_text("Telegram couldn't complete that action. Please try again.")
        except TelegramError:
            pass


async def send_stored_file(message, item: sqlite3.Row) -> None:
    """Send a saved Telegram file by file_id."""
    file_id = item["file_id"]
    caption = item["caption"] or item["file_name"]
    file_type = item["file_type"]
    try:
        if file_type == "document":
            await message.reply_document(document=file_id, caption=caption[:1024])
        elif file_type == "video":
            await message.reply_video(video=file_id, caption=caption[:1024])
        elif file_type == "animation":
            await message.reply_animation(animation=file_id, caption=caption[:1024])
        elif file_type == "audio":
            await message.reply_audio(audio=file_id, caption=caption[:1024])
        elif file_type == "voice":
            await message.reply_voice(voice=file_id, caption=caption[:1024])
        elif file_type == "photo":
            await message.reply_photo(photo=file_id, caption=caption[:1024])
        elif file_type == "video_note":
            await message.reply_video_note(video_note=file_id)
        else:
            await message.reply_text(f"Saved file type {file_type!r} isn't supported for direct delivery.")
    except TelegramError:
        logger.exception("Could not send saved file id %s", file_id)
        await message.reply_text(
            "Sorry, Telegram couldn't send this file right now. The saved file entry may be unavailable; "
            "please notify the admin."
        )


def extract_file(message) -> Optional[dict]:
    """Return normalized file details from a Telegram message, or None."""
    if message.document:
        doc = message.document
        return {
            "file_id": doc.file_id,
            "file_type": "document",
            "file_name": doc.file_name or "Document",
            "caption": message.caption or doc.file_name or "Document",
        }
    if message.video:
        video = message.video
        return {
            "file_id": video.file_id,
            "file_type": "video",
            "file_name": video.file_name or (message.caption or "Video"),
            "caption": message.caption or video.file_name or "Video",
        }
    if message.animation:
        animation = message.animation
        return {
            "file_id": animation.file_id,
            "file_type": "animation",
            "file_name": animation.file_name or (message.caption or "Animation"),
            "caption": message.caption or animation.file_name or "Animation",
        }
    if message.audio:
        audio = message.audio
        return {
            "file_id": audio.file_id,
            "file_type": "audio",
            "file_name": audio.file_name or (message.caption or "Audio"),
            "caption": message.caption or audio.file_name or "Audio",
        }
    if message.voice:
        return {
            "file_id": message.voice.file_id,
            "file_type": "voice",
            "file_name": message.caption or "Voice message",
            "caption": message.caption or "Voice message",
        }
    if message.video_note:
        return {
            "file_id": message.video_note.file_id,
            "file_type": "video_note",
            "file_name": "Video note",
            "caption": "Video note",
        }
    if message.photo:
        photo = message.photo[-1]
        return {
            "file_id": photo.file_id,
            "file_type": "photo",
            "file_name": message.caption or "Photo",
            "caption": message.caption or "Photo",
        }
    return None


async def receive_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if not user or not message:
        return

    # Uploads are only accepted in the admin's private chat with the bot.
    if message.chat.type != ChatType.PRIVATE or not is_admin(user.id):
        return

    if context.user_data.get("upload_state") != "receiving_files":
        return

    category = context.user_data.get("upload_category")
    subject = context.user_data.get("upload_subject")
    if category not in CATEGORY_KEYS or subject not in SUBJECTS:
        context.user_data.pop("upload_state", None)
        await message.reply_text("Upload session expired. Please start again with /add.")
        return

    file_info = extract_file(message)
    if not file_info:
        await message.reply_text(
            "I couldn't recognize that as a file. Send a document/PDF, video, audio, or photo. "
            "Use /cancel to stop."
        )
        return

    try:
        with closing(db_connect()) as conn:
            cursor = conn.execute(
                "INSERT INTO resources(category, subject, file_id, file_type, file_name, caption, uploaded_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    category,
                    subject,
                    file_info["file_id"],
                    file_info["file_type"],
                    file_info["file_name"],
                    file_info["caption"],
                    user.id,
                ),
            )
            conn.commit()
            resource_id = cursor.lastrowid
        await message.reply_text(
            f"✅ Saved successfully!\n\n"
            f"Category: {RESOURCE_TYPES[category]}\n"
            f"Subject: {subject}\n"
            f"Name: {file_info['file_name']}\n"
            f"Resource ID: {resource_id}\n\n"
            "Send another file for the same subject, or use /cancel to finish."
        )
    except sqlite3.Error:
        logger.exception("Database error while saving uploaded resource")
        await message.reply_text("❌ I couldn't save this file entry because of a database error. Try again.")


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text("Unknown command. Use /start to browse or /add to upload (admin only).")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception while processing update", exc_info=context.error)


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN is missing. Set it as an environment variable before running the bot. "
            "See README.txt for instructions."
        )
    if not ADMIN_IDS:
        raise SystemExit(
            "ADMIN_IDS is missing. Set it to your numeric Telegram user ID (e.g. 123456789). "
            "See README.txt for instructions."
        )

    init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add", add_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CallbackQueryHandler(callback_router))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, receive_upload))
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    application.add_error_handler(error_handler)

    logger.info("Bot is starting. Database: %s", DATABASE_PATH)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
