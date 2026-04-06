import os
import asyncio
import tempfile
import glob
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.constants import ParseMode, ChatAction
import yt_dlp

TOKEN = os.environ.get("BOT_TOKEN", "")

# ── URL detection ──────────────────────────────
URL_RE = re.compile(r'https?://[^\s]+')

def is_url(text):
    return bool(URL_RE.match(text.strip()))

# ── yt-dlp helpers ────────────────────────────
def make_opts(fmt, quality, out_tmpl):
    if fmt == "mp3":
        return dict(
            outtmpl=out_tmpl + ".%(ext)s",
            format="bestaudio/best",
            quiet=True, no_warnings=True, noplaylist=True,
            concurrent_fragment_downloads=4,
            postprocessors=[{"key":"FFmpegExtractAudio",
                             "preferredcodec":"mp3","preferredquality":"192"}],
        )
    if quality == "best":
        fmt_str = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
    else:
        q = int(quality)
        fmt_str = (
            f"bestvideo[height<={q}][ext=mp4]+bestaudio[ext=m4a]"
            f"/bestvideo[height<={q}]+bestaudio/best[height<={q}]/best"
        )
    return dict(
        outtmpl=out_tmpl + ".%(ext)s",
        format=fmt_str,
        merge_output_format="mp4",
        quiet=True, no_warnings=True, noplaylist=True,
        concurrent_fragment_downloads=8,
        http_chunk_size=10485760,
    )

def friendly_error(e: str) -> str:
    e = e.lower()
    if "unsupported url" in e or "unable to extract" in e:
        return "❌ الرابط غير مدعوم. تأكد أنه من يوتيوب أو تيك توك أو إنستغرام أو تويتر."
    if "private" in e:
        return "🔒 الفيديو خاص ولا يمكن تحميله."
    if "removed" in e or "deleted" in e:
        return "🗑 الفيديو محذوف من المنصة."
    if "429" in e or "rate" in e:
        return "⏳ طلبات كثيرة جداً، حاول بعد دقيقتين."
    if "copyright" in e:
        return "⚠️ الفيديو محجوب بسبب حقوق الملكية."
    if "ffmpeg" in e:
        return "⚙️ خطأ في معالجة الفيديو، جرب جودة مختلفة."
    if "sign in" in e or "login" in e:
        return "🔐 هذا الفيديو يتطلب تسجيل دخول."
    return f"❌ حدث خطأ: {e[:200]}"

# ── keyboard builders ──────────────────────────
def fmt_keyboard(url):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 فيديو MP4", callback_data=f"fmt|mp4|best|{url}"),
            InlineKeyboardButton("🎵 صوت MP3",   callback_data=f"fmt|mp3|best|{url}"),
        ]
    ])

def quality_keyboard(url):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌟 أفضل جودة", callback_data=f"dl|mp4|best|{url}"),
            InlineKeyboardButton("1080p",         callback_data=f"dl|mp4|1080|{url}"),
        ],
        [
            InlineKeyboardButton("720p",          callback_data=f"dl|mp4|720|{url}"),
            InlineKeyboardButton("480p",          callback_data=f"dl|mp4|480|{url}"),
            InlineKeyboardButton("360p",          callback_data=f"dl|mp4|360|{url}"),
        ],
        [
            InlineKeyboardButton("🔙 رجوع",       callback_data=f"back|{url}"),
        ]
    ])

# ── handlers ──────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *أهلاً بك في Savely Bot!*\n\n"
        "أرسل لي أي رابط فيديو من:\n"
        "▶️ يوتيوب • 🎵 تيك توك • 📸 إنستغرام\n"
        "🐦 تويتر/X • 📘 فيسبوك • وأكثر من 1000 موقع\n\n"
        "وسأحمّله لك مباشرة بدون علامة مائية! ⚡",
        parse_mode=ParseMode.MARKDOWN
    )

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *كيفية الاستخدام:*\n\n"
        "1️⃣ أرسل رابط الفيديو\n"
        "2️⃣ اختر الصيغة (فيديو أو صوت)\n"
        "3️⃣ اختر الجودة\n"
        "4️⃣ انتظر قليلاً وسيصلك الملف ✅\n\n"
        "💡 *نصيحة:* الفيديوهات الأقصر تتحمل أسرع.",
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not is_url(text):
        await update.message.reply_text("⚠️ من فضلك أرسل رابط فيديو صحيح يبدأ بـ https://")
        return

    await update.message.reply_text(
        "🎯 اختر صيغة التحميل:",
        reply_markup=fmt_keyboard(text)
    )

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|", 3)
    action = parts[0]

    if action == "fmt":
        _, fmt, _, url = parts
        if fmt == "mp3":
            # MP3 → download directly
            await query.edit_message_text("⏳ جارٍ تحميل الصوت...")
            await do_download(query.message, url, "mp3", "best", ctx)
        else:
            # MP4 → ask quality
            await query.edit_message_text(
                "📐 اختر الجودة:",
                reply_markup=quality_keyboard(url)
            )

    elif action == "dl":
        _, fmt, quality, url = parts
        await query.edit_message_text("⏳ جارٍ التحميل، انتظر لحظة...")
        await do_download(query.message, url, fmt, quality, ctx)

    elif action == "back":
        url = parts[1]
        await query.edit_message_text(
            "🎯 اختر صيغة التحميل:",
            reply_markup=fmt_keyboard(url)
        )

async def do_download(msg, url, fmt, quality, ctx):
    loop = asyncio.get_event_loop()
    chat_id = msg.chat_id

    # Send typing action
    await ctx.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)

    with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "file")
        opts = make_opts(fmt, quality, out)

        try:
            # Run yt-dlp in thread to not block event loop
            info = await loop.run_in_executor(
                None, lambda: _dl(url, opts)
            )
        except Exception as e:
            await msg.reply_text(friendly_error(str(e)))
            return

        title = info.get("title", "video")[:60]
        ext   = "mp3" if fmt == "mp3" else "mp4"

        matches = glob.glob(out + ".*")
        if not matches:
            await msg.reply_text("❌ لم يُنشأ الملف، جرب رابطاً آخر.")
            return
        filepath = matches[0]

        size_mb = os.path.getsize(filepath) / 1048576

        # Telegram limit: 50MB for bots
        if size_mb > 49:
            await msg.reply_text(
                f"⚠️ الملف كبير جداً ({size_mb:.0f} MB).\n"
                "جرب جودة أقل مثل 720p أو 480p."
            )
            return

        caption = f"✅ *{title}*\n📁 {size_mb:.1f} MB · {ext.upper()}"
        await ctx.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)

        with open(filepath, "rb") as f:
            if ext == "mp3":
                await ctx.bot.send_audio(
                    chat_id=chat_id, audio=f,
                    title=title, caption=caption,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await ctx.bot.send_video(
                    chat_id=chat_id, video=f,
                    caption=caption, supports_streaming=True,
                    parse_mode=ParseMode.MARKDOWN
                )

def _dl(url, opts):
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=True)

# ── main ──────────────────────────────────────
def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set!")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help",  help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("🤖 Savely Bot is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
