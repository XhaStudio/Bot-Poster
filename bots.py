import logging
import sqlite3
import re
import random
import string
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# Logging Setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

BOT_TOKEN = "8687589066:AAGalfDMlR6AENC5HP9J2qc7kkuYN1M6LlE"  # Replace with your BotFather Token
CHANNEL_ID = "@AdvertiseYourBotChat"

# Conversation States
TITLE, LINK, DESCRIPTION, HASHTAGS, CHAT_ID, CREATOR, MEDIA = range(7)


# --- DATABASE SETUP ---

def init_db():
    conn = sqlite3.connect("bots.db")
    cursor = conn.cursor()

    # Track a single vote per user per post (message)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_votes (
            user_id INTEGER,
            message_id INTEGER,
            vote_type TEXT,
            PRIMARY KEY (user_id, message_id)
        )
    """)

    # Main table with all fields the rest of the code relies on
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id TEXT UNIQUE,
            user_id INTEGER,
            title TEXT,
            link TEXT,
            description TEXT,
            hashtags TEXT,
            chat_id TEXT,
            creator_str TEXT,
            channel_message_id INTEGER,
            has_media INTEGER DEFAULT 0,
            media_type TEXT,
            likes INTEGER DEFAULT 0,
            dislikes INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def generate_unique_post_id() -> str:
    conn = sqlite3.connect("bots.db")
    cursor = conn.cursor()

    while True:
        random_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        cursor.execute("SELECT 1 FROM user_bots WHERE post_id = ?", (random_id,))
        if not cursor.fetchone():
            conn.close()
            return random_id


def add_bot_to_db(post_id: str, user_id: int, title: str, link: str, description: str,
                   hashtags: str, chat_id: str, creator_str: str, channel_message_id: int,
                   has_media: int, media_type: str) -> int:
    conn = sqlite3.connect("bots.db")
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO user_bots
           (post_id, user_id, title, link, description, hashtags, chat_id,
            creator_str, channel_message_id, has_media, media_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (post_id, user_id, title, link, description, hashtags, chat_id,
         creator_str, channel_message_id, has_media, media_type),
    )
    bot_db_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return bot_db_id


def update_channel_message_id(bot_db_id: int, message_id: int):
    conn = sqlite3.connect("bots.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE user_bots SET channel_message_id = ? WHERE id = ?", (message_id, bot_db_id))
    conn.commit()
    conn.close()


def get_bot_by_id(bot_db_id: int):
    conn = sqlite3.connect("bots.db")
    cursor = conn.cursor()
    cursor.execute("SELECT link FROM user_bots WHERE id = ?", (bot_db_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def get_post_by_post_id(post_id: str):
    conn = sqlite3.connect("bots.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, title, link, hashtags, chat_id, user_id, channel_message_id FROM user_bots WHERE post_id = ?",
        (post_id.upper(),),
    )
    row = cursor.fetchone()
    conn.close()
    return row


def get_user_bots_from_db(user_id: int):
    conn = sqlite3.connect("bots.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, post_id, title, link, hashtags FROM user_bots WHERE user_id = ?",
        (user_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def delete_bot_from_db(bot_db_id: int, user_id: int):
    conn = sqlite3.connect("bots.db")
    cursor = conn.cursor()

    # Get channel message ID before deleting record
    cursor.execute("SELECT channel_message_id FROM user_bots WHERE id = ? AND user_id = ?", (bot_db_id, user_id))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return False, None

    msg_id = row[0]
    cursor.execute("DELETE FROM user_bots WHERE id = ? AND user_id = ?", (bot_db_id, user_id))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0, msg_id


# --- VOTE HELPERS ---

def get_user_vote(user_id: int, message_id: int):
    conn = sqlite3.connect("bots.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT vote_type FROM user_votes WHERE user_id = ? AND message_id = ?",
        (user_id, message_id),
    )
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def set_user_vote(user_id: int, message_id: int, vote_type: str):
    conn = sqlite3.connect("bots.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO user_votes (user_id, message_id, vote_type) VALUES (?, ?, ?)",
        (user_id, message_id, vote_type),
    )
    conn.commit()
    conn.close()


# --- POST FORMATTING / KEYBOARD HELPERS ---

def build_post_keyboard(bot_db_id: int, link: str, chat_id: str, like_count: int = 0, dislike_count: int = 0):
    keyboard = [
        [
            InlineKeyboardButton(f"👍 {like_count}", callback_data="vote_up"),
            InlineKeyboardButton(f"👎 {dislike_count}", callback_data="vote_down"),
        ],
        [
            # Direct url= button: single tap opens the user's link immediately.
            InlineKeyboardButton(
                "Visit/သွားရောက်လည်ပတ်မည်။",
                url=link,
            )
        ]
    ]

    if chat_id and chat_id != "None":
        clean_chat_id = chat_id.strip()
        if not clean_chat_id.lstrip('-').isdigit() and not clean_chat_id.startswith("http"):
            review_url = f"https://t.me/{clean_chat_id.replace('@', '')}"
            keyboard.append([InlineKeyboardButton("💬 Write a Review", url=review_url)])
        elif clean_chat_id.startswith("-100"):
            review_url = f"https://t.me/c/{clean_chat_id.replace('-100', '')}/1"
            keyboard.append([InlineKeyboardButton("💬 Write a Review", url=review_url)])
        elif clean_chat_id.startswith("http://") or clean_chat_id.startswith("https://"):
            keyboard.append([InlineKeyboardButton("💬 Write a Review", url=clean_chat_id)])

    return InlineKeyboardMarkup(keyboard)


def build_channel_caption(title: str, description: str, post_id: str, hashtags: str,
                           creator_str: str) -> str:
    hashtag_str = f"🏷️ {hashtags}\n" if hashtags and hashtags != "None" else ""
    desc_str = f"📝 <b>Description:</b>\n{description}\n\n" if description else ""
    return (
        f"🤖 <b>{title}</b>\n\n"
        f"{desc_str}"
        f"🆔 <b>ID:</b> <code>{post_id}</code>\n"
        f"{hashtag_str}"
        f"👤 Created by {creator_str}"
    )


# --- SEARCH POST BY ID ---
async def search_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ ကျေးဇူးပြု၍ Post ID ထည့်သွင်းပါ!\n\nဥပမာ: <code>/search B8K3X9</code>", parse_mode="HTML")
        return

    search_id = context.args[0].strip().upper()
    bot_data = get_post_by_post_id(search_id)

    if not bot_data:
        await update.message.reply_text(f"❌ ID <b>{search_id}</b> ဖြင့် Post ရှာမတွေ့ပါ။", parse_mode="HTML")
        return

    bot_db_id, title, link, hashtags, user_chat_id, _, _ = bot_data
    hashtag_str = f"🏷️ {hashtags}\n" if hashtags and hashtags != "None" else ""

    formatted_post = (
        f"🤖 <b>{title}</b>\n\n"
        f"🆔 <b>ID:</b> <code>{search_id}</code>\n"
        f"{hashtag_str}"
    )

    keyboard = [
        [InlineKeyboardButton("Visit/သွားရောက်လည်ပတ်မည်။", url=link)]
    ]

    if user_chat_id and user_chat_id != "None":
        clean_chat_id = user_chat_id.strip()
        if not clean_chat_id.lstrip('-').isdigit() and not clean_chat_id.startswith("http"):
            review_url = f"https://t.me/{clean_chat_id.replace('@', '')}"
            keyboard.append([InlineKeyboardButton("💬 Write a Review", url=review_url)])
        elif clean_chat_id.startswith("-100"):
            review_url = f"https://t.me/c/{clean_chat_id.replace('-100', '')}/1"
            keyboard.append([InlineKeyboardButton("💬 Write a Review", url=review_url)])
        elif clean_chat_id.startswith("http://") or clean_chat_id.startswith("https://"):
            keyboard.append([InlineKeyboardButton("💬 Write a Review", url=clean_chat_id)])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(formatted_post, parse_mode="HTML", reply_markup=reply_markup)


# --- DELETE COMMAND WITH ID SEARCH OR LIST SELECT ---
async def delete_bot_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Deleting via ID directly: e.g. /del B8K3X9
    if context.args:
        search_id = context.args[0].strip().upper()
        bot_data = get_post_by_post_id(search_id)

        if not bot_data:
            await update.message.reply_text(f"❌ ID <b>{search_id}</b> ဖြင့် Post ရှာမတွေ့ပါ။", parse_mode="HTML")
            return

        bot_db_id, title, _, _, _, owner_id, channel_msg_id = bot_data

        if owner_id != user_id:
            await update.message.reply_text("❌ ဤ Post သည် သင်၏ Post မဟုတ်ပါသဖြင့် ဖျက်ပိုင်ခွင့် မရှိပါ။", parse_mode="HTML")
            return

        success, msg_id = delete_bot_from_db(bot_db_id, user_id)
        if success:
            # Delete message from Channel
            if msg_id:
                try:
                    await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=msg_id)
                except Exception as e:
                    logging.error(f"Failed to delete post from channel: {e}")

            await update.message.reply_text(f"✅ Post <b>{title}</b> (ID: <code>{search_id}</code>) ကို Database နှင့် Channel ထဲမှ အောင်မြင်စွာ ဖျက်လိုက်ပါပြီ!", parse_mode="HTML")
        else:
            await update.message.reply_text("⚠️ Post ကို ဖျက်၍ မရပါ။")
        return

    # Default: Show inline list menu to choose which post to delete
    bots = get_user_bots_from_db(user_id)

    if not bots:
        await update.message.reply_text("❌ သင့်မှာ ဖျက်စရာ Bot စာရင်း မရှိပါ!")
        return

    delete_keyboard = []
    for bot_db_id, post_id, title, _, _ in bots:
        btn_text = f"❌ Delete {title} ({post_id})"
        callback_data = f"delbot_{bot_db_id}"
        delete_keyboard.append([InlineKeyboardButton(btn_text, callback_data=callback_data)])

    reply_markup = InlineKeyboardMarkup(delete_keyboard)
    await update.message.reply_text(
        "🗑️ <b>ဘယ် Bot ကို ဖျက်ချင်ပါသလဲ?</b>\n\n"
        "💡 <i>သို့မဟုတ် <code>/del &lt;ID&gt;</code> ရိုက်ပြီး ID ဖြင့် ဖျက်နိုင်ပါသည်။</i>",
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


async def handle_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    bot_db_id = int(query.data.split("delbot_")[1])

    success, channel_msg_id = delete_bot_from_db(bot_db_id, user_id)

    if success:
        if channel_msg_id:
            try:
                await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=channel_msg_id)
                logging.info(f"Successfully deleted message {channel_msg_id} from channel.")
            except Exception as e:
                logging.error(f"Failed to delete channel post (Message ID: {channel_msg_id}): {e}")
                await update.effective_message.reply_text(f"⚠️ ချန်နယ်ပို့စ် ဖျက်ခြင်းသတိပေးချက်- {e}")

        try:
            await query.edit_message_text("✅ Post ကို ဖျက်လိုက်ပါပြီ!")
        except Exception:
            pass
    else:
        try:
            await query.edit_message_text("⚠️ Bot ကို ဖျက်၍ မရပါ။")
        except Exception as e:
            # Telegram throws "Message is not modified" if the text is identical
            # to what's already shown - safe to ignore.
            logging.info(f"Edit skipped (likely unchanged message): {e}")


# --- BUTTON CLICK HANDLER (VOTES) ---
async def handle_button_clicks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action = query.data
    user_id = query.from_user.id
    message_id = query.message.message_id

    # --- VOTES ---
    reply_markup = query.message.reply_markup
    if not reply_markup or not reply_markup.inline_keyboard:
        await query.answer("Cannot process action.", show_alert=True)
        return

    # inline_keyboard is a tuple of tuples - convert to lists so it's mutable
    keyboard = [list(row) for row in reply_markup.inline_keyboard]
    first_row = keyboard[0]

    like_match = re.search(r'\d+', first_row[0].text)
    dislike_match = re.search(r'\d+', first_row[1].text)
    like_count = int(like_match.group()) if like_match else 0
    dislike_count = int(dislike_match.group()) if dislike_match else 0

    existing_vote = get_user_vote(user_id, message_id)

    if action == "vote_up":
        if existing_vote == "up":
            await query.answer("✅ You already liked this post.", show_alert=True)
            return
        if existing_vote == "down":
            dislike_count = max(0, dislike_count - 1)
        like_count += 1
        set_user_vote(user_id, message_id, "up")
        await query.answer("You liked this post! 👍")

    elif action == "vote_down":
        if existing_vote == "down":
            await query.answer("✅ You already disliked this post.", show_alert=True)
            return
        if existing_vote == "up":
            like_count = max(0, like_count - 1)
        dislike_count += 1
        set_user_vote(user_id, message_id, "down")
        await query.answer("You disliked this post! 👎")
    else:
        await query.answer()
        return

    first_row[0] = InlineKeyboardButton(f"👍 {like_count}", callback_data="vote_up")
    first_row[1] = InlineKeyboardButton(f"👎 {dislike_count}", callback_data="vote_down")

    try:
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logging.error(f"Error updating vote count: {e}")


# --- BACK HANDLER ---
async def handle_back_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    current_state = context.user_data.get("current_state", TITLE)

    if current_state == TITLE:
        await update.message.reply_text("⚠️ သင့်တွင် နောက်သို့ ဆုတ်ရန် အဆင့် မရှိတော့ပါ။ /start ဖြင့် ပြန်စနိုင်ပါသည်။")
        return TITLE

    prev_state = current_state - 1
    context.user_data["current_state"] = prev_state

    if prev_state == TITLE:
        await update.message.reply_text("🔙 <b>သင့် Bot ရဲ့ နာမည် (Title) ကို ပြန်လည် ပို့ပေးပါ -</b>", parse_mode="HTML")
        return TITLE
    elif prev_state == LINK:
        await update.message.reply_text("🔙 <b>သင့် Bot ရဲ့ Username သို့မဟုတ် Link ကို ပြန်လည် ပို့ပေးပါ -</b>", parse_mode="HTML")
        return LINK
    elif prev_state == DESCRIPTION:
        await update.message.reply_text("🔙 <b>Bot အကြောင်း အသေးစိတ် (Description) ကို ပြန်လည် ရေးပေးပါ -</b>", parse_mode="HTML")
        return DESCRIPTION
    elif prev_state == HASHTAGS:
        await update.message.reply_text("🔙 <b>သင့် Bot အတွက် Hashtag များကို ပြန်လည် ရေးပေးပါ -</b>\n\n/skip ဟု ပို့နိုင်ပါသည်။", parse_mode="HTML")
        return HASHTAGS
    elif prev_state == CHAT_ID:
        await update.message.reply_text("🔙 <b>What is your Chat Id?</b>\n\nIf you don't have one, send /skip", parse_mode="HTML")
        return CHAT_ID
    elif prev_state == CREATOR:
        context.user_data["creators"] = []
        await update.message.reply_text("🔙 <b>Please send Creator/Owner Username (e.g., @username)</b>\n\nIf you don't want to add, send /skip", parse_mode="HTML")
        return CREATOR

    return current_state


# --- CONVERSATION FLOW ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["current_state"] = TITLE
    await update.message.reply_text(
        "Welcome to the Bot Submission Assistant! 🤖\n\n"
        "channel join ရန် https://t.me/AdvertiseYourBotChat\n\n"
        "Commands:\n"
        "• /start - Bot အသစ် တင်ရန်\n"
        "• /mybot - တင်ထားသော Bot များကို ပြန်ကြည့်ရန်\n"
        "• /search &lt;ID&gt; - ID ဖြင့် Post ပြန်ရှာရန်\n"
        "• /del - List သို့မဟုတ် /del &lt;ID&gt; ဖြင့် Bot ကို Channel မှပါ ဖျက်ရန်\n"
        "• /back - ရှေ့တစ်ဆင့်သို့ ပြန်သွားရန်\n"
        "• /cancel - လုပ်ဆောင်ချက် ပယ်ဖျက်ရန်\n\n"
        "ပထမဦးစွာ <b>သင့် Bot ရဲ့ နာမည် (Title) ကို ပို့ပေးပါ -</b>",
        parse_mode="HTML",
    )
    return TITLE


async def my_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bots = get_user_bots_from_db(user_id)

    if not bots:
        await update.message.reply_text("❌ သင် ကြော်ငြာထားသော Bot မရှိသေးပါ!\nBot အသစ်တင်ရန် /start ကို နှိပ်ပါ။")
        return

    message = "📋 <b>သင် တင်ထားသော Bot များ -</b>\n\n"
    for idx, (_, post_id, title, link, hashtags) in enumerate(bots, start=1):
        message += f"<b>{idx}. {title}</b>\n🆔 ID: <code>{post_id}</code>\n🏷️ Hashtags: {hashtags}\n🔗 Link: {link}\n\n"

    await update.message.reply_text(message, parse_mode="HTML")


async def get_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["title"] = update.message.text
    context.user_data["current_state"] = LINK
    await update.message.reply_text("ရပါပြီ! အခု <b>သင့် Bot ရဲ့ Username သို့မဟုတ် Link ကို ပို့ပေးပါ -</b>", parse_mode="HTML")
    return LINK


async def get_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw_link = update.message.text.strip()

    if not raw_link.startswith("http://") and not raw_link.startswith("https://") and not raw_link.startswith("tg://"):
        if raw_link.startswith("@"):
            raw_link = f"https://t.me/{raw_link.replace('@', '')}"
        else:
            raw_link = f"https://t.me/{raw_link}"

    context.user_data["link"] = raw_link
    context.user_data["current_state"] = DESCRIPTION
    await update.message.reply_text("ကောင်းပါပြီ! ဆက်လက်ပြီး <b>Bot အကြောင်း အသေးစိတ် (Description) ရေးပေးပါ -</b>", parse_mode="HTML")
    return DESCRIPTION


async def get_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["description"] = update.message.text
    context.user_data["current_state"] = HASHTAGS
    await update.message.reply_text(
        "🏷️ <b>သင့် Bot အတွက် Hashtag များ ရေးပေးပါ -</b>\n\nဥပမာ - <code>#AI #Utility #Game</code>\n/skip ဟု ပို့နိုင်ပါသည်။",
        parse_mode="HTML",
    )
    return HASHTAGS


async def get_hashtags(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text and not update.message.text.startswith("/skip"):
        raw_text = update.message.text.strip()
        tags = [tag if tag.startswith("#") else f"#{tag}" for tag in raw_text.split()]
        context.user_data["hashtags"] = " ".join(tags)
    else:
        context.user_data["hashtags"] = "None"

    context.user_data["current_state"] = CHAT_ID
    await update.message.reply_text(
        "💬 <b>What is your Chat Id?</b>\n\nIf you don't have one, send /skip or get ID from @userinfobot",
        parse_mode="HTML",
    )
    return CHAT_ID


async def get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip() if update.message.text else ""
    context.user_data["chat_id"] = text if text and not text.startswith("/skip") else None
    context.user_data["creators"] = []
    context.user_data["current_state"] = CREATOR

    await update.message.reply_text(
        "👤 <b>Please send Creator/Owner Username (e.g., @username)</b>\n\nIf you don't want to add, send /skip",
        parse_mode="HTML",
    )
    return CREATOR


async def collect_creators(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip() if update.message.text else ""

    if text.startswith("/done") or text.startswith("/skip"):
        context.user_data["media"] = []
        context.user_data["current_state"] = MEDIA
        await update.message.reply_text("📸🎥 <b>သင့် Bot အတွက် Photos သို့မဟုတ် Videos ပို့ပေးပါ -</b>\n\n/skip ဟု ပို့နိုင်ပါသည်။", parse_mode="HTML")
        return MEDIA

    creator = text if text.startswith("@") else f"@{text}"
    context.user_data["creators"].append(creator)

    await update.message.reply_text(
        f"✅ Added {creator}!\n\n<b>Add more creator or /skip</b>\n(Or send /done if finished)",
        parse_mode="HTML",
    )
    return CREATOR


async def send_media_confirmation(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await context.bot.send_message(
        chat_id=job.chat_id,
        text="📸🎥 Media saved!\n\n<b>Add more Photos or Videos?</b>\nSend another photo/video, or type /done to finish.",
        parse_mode="HTML",
    )


async def collect_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.photo or update.message.video:
        if update.message.photo:
            media_type = "photo"
            file_id = update.message.photo[-1].file_id
        else:
            media_type = "video"
            file_id = update.message.video.file_id

        context.user_data["media"].append({"type": media_type, "file_id": file_id})

        current_jobs = context.job_queue.get_jobs_by_name(f"confirm_{update.effective_chat.id}")
        for job in current_jobs:
            job.schedule_removal()

        context.job_queue.run_once(send_media_confirmation, when=0.8, chat_id=update.effective_chat.id, name=f"confirm_{update.effective_chat.id}")
        return MEDIA

    elif update.message.text and update.message.text.startswith("/skip"):
        return await publish_post(update, context)

    return MEDIA


async def publish_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    title = context.user_data["title"]
    link = context.user_data["link"]
    description = context.user_data["description"]
    hashtags = context.user_data.get("hashtags", "None")
    user_chat_id = context.user_data.get("chat_id")
    creators = context.user_data.get("creators", [])
    media_list = context.user_data.get("media", [])

    user = update.effective_user
    user_id = user.id

    creator_str = ", ".join(creators) if creators else (f"@{user.username}" if user.username else f"<a href='tg://user?id={user_id}'>{user.first_name}</a>")

    post_id = generate_unique_post_id()

    has_media = 1 if media_list else 0
    media_type = "group" if len(media_list) > 1 else (media_list[0]["type"] if media_list else None)

    # Insert into DB first to get a bot_db_id (used for delete/vote callbacks)
    bot_db_id = add_bot_to_db(
        post_id, user_id, title, link, description, hashtags,
        user_chat_id or "None", creator_str, 0, has_media, media_type,
    )

    formatted_post = build_channel_caption(title, description, post_id, hashtags, creator_str)
    reply_markup = build_post_keyboard(bot_db_id, link, user_chat_id or "None")

    sent_message = None

    try:
        if len(media_list) == 1:
            item = media_list[0]
            if item["type"] == "photo":
                sent_message = await context.bot.send_photo(chat_id=CHANNEL_ID, photo=item["file_id"], caption=formatted_post, parse_mode="HTML", reply_markup=reply_markup)
            else:
                sent_message = await context.bot.send_video(chat_id=CHANNEL_ID, video=item["file_id"], caption=formatted_post, parse_mode="HTML", reply_markup=reply_markup)
        elif len(media_list) > 1:
            from telegram import InputMediaPhoto, InputMediaVideo

            media_group = []
            for idx, item in enumerate(media_list):
                caption = formatted_post if idx == 0 else None
                parse_mode = "HTML" if idx == 0 else None

                if item["type"] == "photo":
                    media_group.append(InputMediaPhoto(media=item["file_id"], caption=caption, parse_mode=parse_mode))
                else:
                    media_group.append(InputMediaVideo(media=item["file_id"], caption=caption, parse_mode=parse_mode))

            msgs = await context.bot.send_media_group(chat_id=CHANNEL_ID, media=media_group)
            sent_message = msgs[0]
            await context.bot.send_message(chat_id=CHANNEL_ID, text=f"💬 Interactive options for <b>{title}</b>:", parse_mode="HTML", reply_markup=reply_markup)
        else:
            sent_message = await context.bot.send_message(chat_id=CHANNEL_ID, text=formatted_post, parse_mode="HTML", reply_markup=reply_markup)

        # Update post with actual channel message ID
        if sent_message:
            update_channel_message_id(bot_db_id, sent_message.message_id)

        await update.message.reply_text(f"✅ သင့် Bot ကို Channel ထဲသို့ အောင်မြင်စွာ တင်ပေးလိုက်ပါပြီ!\n🆔 Post ID: <code>{post_id}</code>", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text("⚠️ Post တင်ရာတွင် Error ဖြစ်ပေါ်နေပါသည်။ Admin Permission စစ်ဆေးပါ။")
        logging.error(f"Failed to post to channel: {e}")

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("လုပ်ဆောင်ချက်ကို ပယ်ဖျက်လိုက်ပါပြီ။")
    context.user_data.clear()
    return ConversationHandler.END


def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    back_handler = CommandHandler("back", handle_back_command)

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_title), back_handler],
            LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_link), back_handler],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_description), back_handler],
            HASHTAGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_hashtags), CommandHandler("skip", get_hashtags), back_handler],
            CHAT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_chat_id), CommandHandler("skip", get_chat_id), back_handler],
            CREATOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_creators), CommandHandler("skip", collect_creators), CommandHandler("done", collect_creators), back_handler],
            MEDIA: [MessageHandler(filters.PHOTO | filters.VIDEO, collect_media), CommandHandler("done", publish_post), CommandHandler("skip", collect_media), back_handler],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("mybot", my_bots))
    app.add_handler(CommandHandler("search", search_post))
    app.add_handler(CommandHandler("del", delete_bot_menu))
    app.add_handler(CallbackQueryHandler(handle_delete_callback, pattern="^delbot_"))

    app.add_handler(CallbackQueryHandler(handle_button_clicks, pattern="^(vote_up|vote_down)$"))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
