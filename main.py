import asyncio
import logging
import os
import shutil

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Fix for Python 3.12+ loop issues
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

from pyrogram import Client, filters, idle, enums
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    CallbackQuery, BotCommand, InlineQueryResultArticle, 
    InputTextMessageContent
)
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import UserNotParticipant
from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_USERNAMES, ADMIN_IDS, CHANNEL_USERNAME, CHANNEL_LINK, REQUEST_GROUP
from gdrive_handler import drive_handler
from database import db

# Global state
broadcast_queues = {} # {user_id: [messages]}
admin_mode = {} # {user_id: bool}
request_mode = {} # {user_id: bool}
delete_mode = {} # {user_id: bool}
duplicate_store = {} # {user_id: [file_ids]}
ban_mode = {} # {user_id: bool}
unban_mode = {} # {user_id: bool}

app = Client(
    "file_search_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

async def check_join(client: Client, user_id: int):
    # Bypass check for Admins
    if user_id in ADMIN_IDS:
        return True
    
    chat_id = CHANNEL_USERNAME
    # Clean up full URLs if provided
    if "t.me/" in str(chat_id):
        chat_id = chat_id.split("t.me/")[-1].split("/")[0]

    if isinstance(chat_id, str) and not chat_id.startswith("@") and not str(chat_id).startswith("-100"):
        chat_id = f"@{chat_id}"

    if not chat_id or chat_id == "@":
        return True
    
    try:
        member = await client.get_chat_member(chat_id, user_id)
        if member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            return True
    except UserNotParticipant:
        return False
    except Exception as e:
        logger.error(f"🔴 Force Join Error: {e} | Channel: {chat_id} | User: {user_id}")
        logger.error("🛑 TIP: Make sure your Bot is an ADMINISTRATOR in your channel with 'Invite Users' permission.")
        return False # Strict mode: if we can't check, we block
    return False

def is_admin(user):
    if not user:
        return False
    # Check by ID first (more reliable)
    if user.id in ADMIN_IDS:
        return True
    # Check by Username
    return user.username and user.username.lower() in [u.lower() for u in ADMIN_USERNAMES]

def get_size_str(size_bytes):
    if not size_bytes:
        return "Unknown Size"
    try:
        size_bytes = int(size_bytes)
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024**2:
            return f"{size_bytes/1024:.2f} KB"
        elif size_bytes < 1024**3:
            return f"{size_bytes/1024**2:.2f} MB"
        else:
            return f"{size_bytes/1024**3:.2f} GB"
    except Exception:
        return "Error"

async def safe_edit(message: Message, text, **kwargs):
    """Edit a message but ignore MESSAGE_NOT_MODIFIED errors."""
    try:
        return await message.edit(text, **kwargs)
    except Exception as e:
        if "MESSAGE_NOT_MODIFIED" in str(e):
            return message
        logger.error(f"Safe edit error: {e}")
        # If it's another error, try to send a new message instead of crashing
        try:
            return await message.reply_text(text, **kwargs)
        except Exception:
            return message

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    user_id = message.from_user.id
    
    # Force Join Check
    if not await check_join(client, user_id):
        return await send_join_message(client, message)

    if db.is_user_banned(user_id):
        await message.reply_text("❌ **You are banned from using this bot.**")
        return

    logger.info(f"Start command from {user_id}")
    
    # Register user in database
    db.add_user(
        message.from_user.id, 
        message.from_user.first_name, 
        message.from_user.username
    )

    # Handle Deep Links (for Inline Downloads)
    if len(message.command) > 1:
        param = message.command[1]
        if param.startswith("dl_"):
            file_id = param.split("_", 1)[1]
            return await handle_download(client, message, file_id)

    if not drive_handler.is_authenticated():
        if is_admin(message.from_user):
            auth_url = drive_handler.get_auth_url()
            if not auth_url:
                await message.reply_text(
                    "❌ **Error:** `credentials.json` file not found.\n"
                    "Please setup Google Cloud Console and add the file to the bot directory."
                )
                return
            
            await message.reply_text(
                "👋 **Welcome Admin!**\n\n"
                "To search for files, I need access to Google Drive. Please visit the link below and send me the authorization code:\n\n"
                f"[Authorize Here]({auth_url})",
                disable_web_page_preview=True
            )
        else:
            await message.reply_text(
                "👋 **Welcome!**\n\n"
                "⚠️ **Notice:** The bot is currently not connected to Google Drive.\n"
                "Please wait for an administrator to authorize the bot."
            )
    else:
        await message.reply_text(
            "Type the name of any TV series to obtain Sinhala subtitles."
        )

@app.on_message(filters.command("status"))
async def status_command(client, message):
    user_id = message.from_user.id
    admin_stat = "Yes" if is_admin(message.from_user) else "No"
    
    status_text = (
        "🤖 **Bot Status Check**\n\n"
        f"🆔 **Your ID:** `{user_id}`\n"
        f"👑 **Is Admin:** `{admin_stat}`\n"
        f"📅 **Admin List (IDs):** `{ADMIN_IDS}`\n\n"
        "If 'Is Admin' is 'No', please check your Heroku `ADMIN_IDS` config var."
    )
    await message.reply_text(status_text)

@app.on_message(filters.command("stats"))
async def stats_command(client, message):
    if not is_admin(message.from_user):
        await message.reply_text("❌ **Denied:** Only admins can view stats.")
        return

    msg = await message.reply_text("📊 **Generating Statistics...**")
    
    total_users = db.get_user_count()
    monthly_users = db.get_monthly_user_count()
    total_chats, groups, channels = db.get_chat_stats()
    
    # Deep Scan for accurate file count
    from config import FOLDER_ID
    file_count = drive_handler.get_recursive_file_count(FOLDER_ID)
    
    stats_text = (
        "📊 **Bot Statistics**\n\n"
        f"👥 **Total Users:** `{total_users}`\n"
        f"📅 **Monthly Active Users:** `{monthly_users}`\n\n"
        f"📢 **Channels Added:** `{channels}`\n"
        f"👥 **Groups Added:** `{groups}`\n"
        f"🏢 **Total Chats:** `{total_chats}`\n\n"
        f"📂 **Indexed Files:** `{file_count}`\n"
    )
    
    await msg.edit(stats_text)

@app.on_message(filters.command("groups"))
async def groups_command(client, message):
    if not is_admin(message.from_user):
        await message.reply_text("❌ **Denied:** Only admins can use this command.")
        return

    msg = await message.reply_text("📋 **Fetching Group Details...**")
    
    try:
        chats = db.get_all_chats_detailed()
        if not chats:
            await msg.edit("❌ **No groups found in database.**")
            return

        report = "📋 **Detailed Group List**\n\n"
        
        for chat_id, title, username, chat_type, adder_id, adder_name in chats:
            # Format group info
            username_str = f"| @{username}" if username else "| No Username"
            adder_str = f"| **Added by:** {adder_name} (`{adder_id}`)" if adder_id else "| **Added by:** Unknown"
            
            report += f"🔹 **{title}**\n"
            report += f"ID: `{chat_id}` {username_str}\n"
            report += f"Type: `{chat_type}` {adder_str}\n\n"

        if len(report) > 4096:
            # Handle long reports by sending multiple messages if needed
            # For simplicity here, we'll just truncate and add a note
            report = report[:4000] + "\n\n... (Report truncated due to length)"

        await msg.edit(report)
    except Exception as e:
        logger.error(f"Groups command error: {e}")
        await msg.edit(f"❌ **Error:** `{str(e)}`")

@app.on_chat_member_updated()
async def on_added_to_chat(client, chat_member_updated):
    # Only track when the bot itself is added
    if chat_member_updated.new_chat_member and chat_member_updated.new_chat_member.user.is_self:
        chat = chat_member_updated.chat
        chat_type = chat.type.name.lower()
        
        # Who added the bot?
        adder_id = None
        adder_name = None
        if chat_member_updated.from_user:
            adder_id = chat_member_updated.from_user.id
            adder_name = chat_member_updated.from_user.first_name
            if chat_member_updated.from_user.username:
                adder_name += f" (@{chat_member_updated.from_user.username})"

        db.add_chat(chat.id, chat.title, chat.username, chat_type, adder_id, adder_name)
        logger.info(f"Bot added to {chat_type}: {chat.title} ({chat.id}) by {adder_name or 'unknown'}")

@app.on_message(filters.command("menu") & filters.private)
async def menu_command(client, message):
    if not await check_join(client, message.from_user.id):
        await message.reply_text(
            f"⚠️ **Access Denied!**\n\n"
            f"You must join our update channel to use this bot.\n\n"
            f"Please join here: {CHANNEL_LINK}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Channel 📢", url=CHANNEL_LINK)]
            ])
        )
        return

    menu_text = (
        "🛠️ **Bot Menu**\n\n"
        "Welcome! I am the Sinhala Subtitle Search Bot.\n\n"
        "📜 **Commands:**\n"
        "• `/start` - Start the bot / Refresh authentication\n"
        "• `/menu` - Show this menu\n\n"
        "🔍 **How to Search:**\n"
        "Just type the name of any TV series and I will find the Sinhala subtitles for you!\n\n"
        "📝 **Requests:**\n"
        "Can't find what you're looking for? Use `/request` to let us know!\n\n"
        f"📢 **Updates:** [Join our channel]({CHANNEL_LINK})"
    )
    
    if is_admin(message.from_user):
        menu_text += (
            "\n\n⚡ **Admin Commands:**\n"
            "• `/broadcast` - Start a broadcast\n"
            "• `/del` - Search & Delete a file\n"
            "• `/scan` - Find duplicates\n"
            "• `/removeall` - Cleanup duplicates\n"
            "• `/ban` - Ban a user\n"
            "• `/unban` - Unban a user\n"
            "• `/groups` - View group details"
        )
        
    buttons = []
    if is_admin(message.from_user):
        buttons.append([
            InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
            InlineKeyboardButton("🗑️ Scan Duplicates", callback_data="admin_scan")
        ])
        buttons.append([
            InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban"),
            InlineKeyboardButton("✅ Unban User", callback_data="admin_unban")
        ])

    await message.reply_text(
        menu_text, 
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
    )

@app.on_message(filters.command("broadcast") & filters.private)
async def broadcast_command(client, message, from_user=None):
    user = from_user or message.from_user
    if not is_admin(user):
        await message.reply_text("❌ **Denied:** Only admins can use this command.")
        return

    admin_mode[user.id] = True
    await message.reply_text(
        "📣 **Broadcast Mode Activated!**\n\n"
        "Now send me any messages (text, media, documents) you want to broadcast.\n"
        "I will collect them in a queue.\n\n"
        "Commands:\n"
        "🚀 `/broadcastnow` - Start broadcasting the queue\n"
        "🧹 `/clear` - Clear the current queue\n"
        "❌ `/broadcast` - Toggle mode off"
    )

@app.on_message(filters.command("clear") & filters.private)
async def clear_broadcast(client, message):
    if not is_admin(message.from_user): return
    
    user_id = message.from_user.id
    broadcast_queues[user_id] = []
    admin_mode[user_id] = False
    await message.reply_text("🧹 **Broadcast queue cleared and mode deactivated!**")

@app.on_message(filters.command("broadcastnow") & filters.private)
async def broadcast_now(client, message):
    if not is_admin(message.from_user): return
    
    user_id = message.from_user.id
    if not broadcast_queues.get(user_id):
        await message.reply_text("❌ **Queue is empty!** Send some messages first.")
        return

    users = db.get_all_users()
    count = len(users)
    queue = broadcast_queues[user_id]
    
    status_msg = await message.reply_text(f"🚀 **Broadcasting {len(queue)} messages to {count} users...**")
    
    success = 0
    failed = 0
    
    for u_id in users:
        try:
            for msg in queue:
                await msg.copy(u_id)
                await asyncio.sleep(0.05) # Prevent flood
            success += 1
        except Exception:
            failed += 1
            
    # Exit broadcast mode and clear queue
    admin_mode[user_id] = False
    broadcast_queues[user_id] = []
    
    await status_msg.edit(
        f"✅ **Broadcast Completed!**\n\n"
        f"✨ **Successful Users:** `{success}`\n"
        f"❌ **Failed Users:** `{failed}`\n\n"
        "Broadcast mode deactivated and queue cleared."
    )

@app.on_message(filters.command("request") & filters.private)
async def request_command(client, message):
    if not await check_join(client, message.from_user.id):
        await message.reply_text(f"⚠️ Join our channel first: {CHANNEL_LINK}")
        return
        
    request_mode[message.from_user.id] = True
    await message.reply_text(
        "📝 **Send your request now!**\n\n"
        "You can send text, photos, or documents. Your request will be sent directly to our team."
    )

@app.on_message(filters.command("contact"))
async def contact_command(client, message):
    contact_text = (
        "Bot ගේ මොකක් හරි අවුලක් තිබ්බොතින් හරි , දැනගන්න ඕන දෙයක් තිබ්බොත් හරි, අනිවාරෙන් Message එකක් දාන්න.... 😇\n\n"
        "🍀🍀🍀🍀🍀🍀🍀🍀🍀\n\n"
        "ඔබගේ ව්යාපාරයේ Business මදි නිසා පසුතැවෙනවද ? 😐\n\n"
        "Website එකක් ගහලා Business එක Up කරලා ගමුද ? 😏\n\n"
        "ඔබගේ එදිනෙදා වැඩ කටයුතු පහසු කර ගැනීමට Telegram Bot කෙනෙක් හදාගන්න කැමතිද ?\n\n"
        "ඉතාම සාධාරණ අඩු මුදලකට ඔබගේ ව්යාපාරයට අවශ්ය Websites , Telegram bots, Telegram Userbots සාදා ගැනීමට අවශ්ය නම් පහත Contacts වලින් සම්බන්ධ වන්න...😇"
    )
    
    buttons = [
        [
            InlineKeyboardButton("✈️ Telegram", url="https://t.me/sljohnwick"),
            InlineKeyboardButton("💬 WhatsApp", url="https://wa.me/94769168815")
        ],
        [
            InlineKeyboardButton("📂 My Projects", url="https://telegra.ph/Sadisa-Harshana-02-05")
        ]
    ]
    
    await message.reply_text(
        contact_text,
        reply_markup=InlineKeyboardMarkup(buttons),
        disable_web_page_preview=True
    )

@app.on_message(filters.command("del") & filters.private)
async def delete_command(client, message):
    if not is_admin(message.from_user):
        await message.reply_text("❌ **Denied:** Only admins can use this command.")
        return

    delete_mode[message.from_user.id] = True
    await message.reply_text(
        "🗑️ **Deletion Mode Activated!**\n\n"
        "Send me the name of the file you want to **PERMANENTLY DELETE**."
    )

@app.on_message(filters.command("scan") & filters.private)
async def scan_duplicates(client, message, from_user=None):
    user = from_user or message.from_user
    if not is_admin(user):
        await message.reply_text("❌ **Denied:** Only admins can use this command.")
        return

    status_msg = await message.reply_text("🔎 **Scanning Google Drive for duplicates...**\nPlease wait, this may take a moment.")
    
    try:
        files = drive_handler.get_all_files()
        if not files:
            await safe_edit(status_msg, "❌ **No files found to scan.**")
            return

        # Group files by name
        grouped = {}
        for f in files:
            name = f.get('name')
            if name not in grouped:
                grouped[name] = []
            grouped[name].append(f)

        duplicates = []
        to_delete_ids = []
        
        for name, file_list in grouped.items():
            if len(file_list) > 1:
                # Sort by createdTime (oldest first)
                file_list.sort(key=lambda x: x.get('createdTime', ''))
                
                # Keep the first one, delete the rest
                keep = file_list[0]
                rems = file_list[1:]
                
                duplicates.append({
                    'name': name,
                    'count': len(file_list),
                    'keep_id': keep['id']
                })
                to_delete_ids.extend([f['id'] for f in rems])

        if not duplicates:
            await safe_edit(status_msg, "✅ **Scan Complete:** No duplicate files found!")
            return

        # Store IDs for removal
        duplicate_store[user.id] = to_delete_ids
        
        report = f"📂 **Duplicate Scan Results**\n\n"
        report += f"✨ **Total Duplicates Found:** `{len(duplicates)} names`\n"
        report += f"🗑️ **Files to be removed:** `{len(to_delete_ids)}` items\n\n"
        
        # Show a few examples
        report += "**Example Duplicates:**\n"
        for d in duplicates[:10]:
            report += f"• `{d['name']}` ({d['count']} copies)\n"
        
        if len(duplicates) > 10:
            report += f"\n... and `{len(duplicates)-10}` more."

        report += "\n\n🚀 Use `/removeall` to permanently delete these duplicates (keeping one original of each)."
        
        await safe_edit(status_msg, report)

    except Exception as e:
        logger.error(f"Scan error: {e}")
        try:
            await safe_edit(status_msg, f"❌ **Scan Error:** `{str(e)}`")
        except Exception:
            await message.reply_text(f"❌ **Scan Error:** `{str(e)}`")

@app.on_message(filters.command("removeall") & filters.private)
async def remove_duplicates(client, message):
    if not is_admin(message.from_user):
        await message.reply_text("❌ **Denied:** Only admins can use this command.")
        return

    user_id = message.from_user.id
    if not duplicate_store.get(user_id):
        await message.reply_text("❌ **No pending deletions.** Please run `/scan` first.")
        return

    ids = duplicate_store[user_id]
    count = len(ids)
    
    status_msg = await message.reply_text(f"🗑️ **Removing {count} duplicate files...**")
    
    success = 0
    failed = 0
    first_error = None
    
    for i, file_id in enumerate(ids):
        try:
            drive_handler.delete_file(file_id)
            success += 1
            if (i + 1) % 10 == 0:
                await safe_edit(status_msg, f"🗑️ **Progress:** Deleting... (`{i+1}/{count}`)")
        except Exception as e:
            failed += 1
            if not first_error:
                # Capture a more descriptive error if possible
                first_error = str(e)
                if "403" in first_error:
                    first_error = "403 Forbidden (Wait for owner/manager permission)"
                elif "404" in first_error:
                    first_error = "404 Not Found"
        
        await asyncio.sleep(0.1) # Small delay to avoid API rate limits

    # Clear store
    duplicate_store[user_id] = []
    
    final_text = (
        f"✅ **Removal Completed!**\n\n"
        f"✨ **Successfully Deleted:** `{success}`\n"
        f"❌ **Failed:** `{failed}`\n\n"
        "All duplicate files (except one original of each) have been removed."
    )
    
    if first_error:
        final_text += f"\n\n⚠️ **First Error:** `{first_error}`"
        if "403" in first_error:
            final_text += "\n\n💡 **Tip:** Ensure the bot's account has 'Manager' or 'Organizer' permissions if this is a Shared Drive."
        
    await safe_edit(status_msg, final_text)

@app.on_message(filters.command("ban") & filters.private)
async def ban_command(client, message, from_user=None):
    user = from_user or message.from_user
    if not is_admin(user):
        await message.reply_text("❌ **Denied:** Only admins can use this command.")
        return

    ban_mode[user.id] = True
    await message.reply_text(
        "🚫 **Ban Mode Activated!**\n\n"
        "Please send me the **username** or **user ID** of the person you want to ban."
    )

@app.on_message(filters.command("unban") & filters.private)
async def unban_command(client, message, from_user=None):
    user = from_user or message.from_user
    if not is_admin(user):
        await message.reply_text("❌ **Denied:** Only admins can use this command.")
        return

    unban_mode[user.id] = True
    await message.reply_text(
        "✅ **Unban Mode Activated!**\n\n"
        "Please send me the **username** or **user ID** of the person you want to unban."
    )

async def send_join_message(client, message):
    """Helper to send the join channel message."""
    await message.reply_text(
        f"⚠️ **Access Denied!**\n\n"
        f"You must join our update channel to use this bot.\n\n"
        f"Please join here: {CHANNEL_LINK}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Join Channel 📢", url=CHANNEL_LINK)]
        ])
    )

@app.on_message(filters.private & filters.incoming)
async def handle_message(client, message):
    if message.from_user and message.from_user.is_self:
        return
    user_id = message.from_user.id

    # Force Join Check (Bypass for Admins in check_join)
    if not await check_join(client, user_id):
        return await send_join_message(client, message)

    if db.is_user_banned(user_id):
        return # Silently ignore banned users in private

    text = message.text or ""

    # Register user in database (if not already done via /start)
    db.add_user(user_id, message.from_user.first_name, message.from_user.username)

    # Check if admin is in broadcast mode
    if admin_mode.get(user_id):
        if text.startswith("/"):
            # Allow commands even in broadcast mode
            pass
        else:
            if user_id not in broadcast_queues:
                broadcast_queues[user_id] = []
            
            # Clone the message for queue
            broadcast_queues[user_id].append(message)
            await message.reply_text(f"✅ **Message added to broadcast queue.**\nTotal: `{len(broadcast_queues[user_id])}`\n\nSend more or use `/broadcastnow` to start.")
            return

    if text.startswith("/"):
        return

    # Handle request mode
    if request_mode.get(user_id):
        try:
            # Send to request group
            await message.copy(REQUEST_GROUP)
            
            # Send info message to group
            info_msg = (
                "📬 **New Request!**\n"
                f"👤 **From:** {message.from_user.first_name} (@{message.from_user.username or 'No Username'})\n"
                f"🆔 **ID:** `{user_id}`"
            )
            await client.send_message(REQUEST_GROUP, info_msg)
            
            # Confirm to user
            request_mode[user_id] = False
            await message.reply_text("✅ **Your request has been sent!** Our team will look into it soon.")
            return
        except Exception as e:
            logger.error(f"Error sending request: {e}")
            await message.reply_text("❌ **Error:** Failed to send request. Group might not be accessible.")
            request_mode[user_id] = False
            return

    # Handle deletion mode
    if delete_mode.get(user_id):
        if text.startswith("/"):
            delete_mode[user_id] = False
        else:
            query = text.strip()
            delete_mode[user_id] = False # Exit mode after search
            await perform_search(client, message, query, in_group=False, for_deletion=True)
            return

    # Handle Ban Mode
    if ban_mode.get(user_id):
        target = text.strip()
        ban_mode[user_id] = False
        if db.set_ban_status(target, 1):
            await message.reply_text(f"🚫 **Successfully banned:** `{target}`")
        else:
            await message.reply_text(f"❌ **Error:** User `{target}` not found in database.")
        return

    # Handle Unban Mode
    if unban_mode.get(user_id):
        target = text.strip()
        unban_mode[user_id] = False
        if db.set_ban_status(target, 0):
            await message.reply_text(f"✅ **Successfully unbanned:** `{target}`")
        else:
            await message.reply_text(f"❌ **Error:** User `{target}` not found in database.")
        return

    logger.info(f"Message from {user_id}: {text}")

    # Check if user is sending an auth code
    if not drive_handler.is_authenticated():
        if is_admin(message.from_user):
            if len(text) > 20: # Rough check for auth code
                try:
                    if drive_handler.authenticate(text):
                        await message.reply_text("✅ **Success!** You are now authenticated. Send me a file name to search.")
                    else:
                        await message.reply_text("❌ **Failed!** Invalid code. Please try again.")
                except Exception as e:
                    logger.error(f"Auth error: {e}")
                    await message.reply_text(f"❌ **Error during auth:** `{str(e)}`")
            else:
                await message.reply_text("⚠️ Please authenticate first by clicking the link in /start.")
        else:
            await message.reply_text("⚠️ **Notice:** The bot is not authorized. Please contact an admin.")
        return

    # Search for files
    query = text.strip()
    
    if not await check_join(client, user_id):
        await send_join_message(client, message)
        return

    await perform_search(client, message, query, in_group=False)

async def perform_search(client, message, query, in_group=False, for_deletion=False, auto_search=False):
    """Reusable search logic for private chats and groups."""
    try:
        files = drive_handler.search_files(query)
        if not files:
            if not auto_search:
                await message.reply_text(f"❌ **No files found for:** `{query}`")
            return

        buttons = []
        for file in files:
            name = file.get('name')
            file_id = file.get('id')
            
            if in_group:
                # In groups, deep-link to PM for download
                buttons.append([InlineKeyboardButton(name, url=f"https://t.me/{client.me.username}?start=dl_{file_id}")])
            elif for_deletion:
                # For deletion, use rm_ callback
                buttons.append([InlineKeyboardButton(f"🗑️ Delete: {name}", callback_data=f"rm_{file_id}")])
            else:
                # In private, use callback
                buttons.append([InlineKeyboardButton(name, callback_data=f"dl_{file_id}")])
        
        title = "Delete Results" if for_deletion else "Search Results"
        await message.reply_text(
            f"🔍 **{title} for:** `{query}`",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        logger.error(f"Search error: {e}")
        await message.reply_text(f"❌ **Search Error:** `{str(e)}`")

@app.on_message(filters.command(["tv", "search", "filter"]))
async def group_search_command(client, message):
    user_id = message.from_user.id
    if db.is_user_banned(user_id):
        return

    db.add_user(user_id, message.from_user.first_name, message.from_user.username)
    
    if len(message.command) < 2:
        await message.reply_text("❌ **Please provide a search query!**\nExample: `/tv Breaking Bad`")
        return
        
    query = " ".join(message.command[1:])

    if not await check_join(client, user_id):
        await send_join_message(client, message)
        return

    in_group = message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL]
    await perform_search(client, message, query, in_group=in_group)

@app.on_message(filters.group & filters.text & ~filters.command(["start", "help", "menu", "tv", "search", "filter", "stats", "status", "del", "scan", "removeall", "ban", "unban", "broadcast", "broadcastnow", "clear", "request", "contact"]))
async def group_auto_search(client, message):
    user_id = message.from_user.id
    if db.is_user_banned(user_id):
        return

    # Basic cleaning of query
    query = message.text.strip()
    if len(query) < 3: # Ignore very short messages to avoid false positives
        return

    # Skip if it looks like a command from another bot
    if query.startswith("/"):
        return

    db.add_user(user_id, message.from_user.first_name, message.from_user.username)
    
    # We do a silent force join check for auto-search in groups
    # If they are not joined, we just don't respond to keep group clean
    if not await check_join(client, user_id):
        return

    await perform_search(client, message, query, in_group=True, auto_search=True)

async def handle_download(client, message, file_id):
    """Core logic to download a file and send it to user."""
    user_id = message.from_user.id

    if not await check_join(client, user_id):
        await send_join_message(client, message)
        return

    full_name = "file"
    
    # Show initial status
    msg = await message.reply_text("📥 **Fetching file info...**")
    
    try:
        service = drive_handler.get_service()
        if not service:
            await msg.edit("❌ **Error:** Google Drive service not initialized.")
            return

        file_info = service.files().get(fileId=file_id, fields="name", supportsAllDrives=True).execute()
        full_name = file_info.get('name', 'file')
        
        await msg.edit(f"📥 **Downloading:** `{full_name}`\nPlease wait...")
        
        path = drive_handler.download_file(file_id, full_name)
        await msg.edit(f"📤 **Uploading:** `{full_name}` to Telegram...")
        
        await client.send_document(
            chat_id=message.chat.id,
            document=path,
            caption=f"✅ **File:** `{full_name}`"
        )
        await msg.delete()
        
        # Cleanup
        if os.path.exists(path):
            os.remove(path)
            
    except Exception as e:
        logger.error(f"Download error: {e}")
        await msg.edit(f"❌ **Error:** Failed to download or send file.\n`{str(e)}`")

@app.on_inline_query()
async def inline_search(client, inline_query):
    user_id = inline_query.from_user.id
    query = inline_query.query

    # Register user in DB
    db.add_user(user_id, inline_query.from_user.first_name, inline_query.from_user.username)

    # Check join status
    if not await check_join(client, user_id):
        await inline_query.answer(
            results=[],
            cache_time=1,
            switch_pm_text="⚠️ Please join our channel to search!",
            switch_pm_parameter="join_required"
        )
        return

    if not query:
        return

    try:
        files = drive_handler.search_files(query)
        results = []
        
        for file in files:
            name = file.get('name')
            file_id = file.get('id')
            size = get_size_str(file.get('size'))
            
            results.append(
                InlineQueryResultArticle(
                    id=file_id,
                    title=name,
                    description=f"Size: {size}",
                    input_message_content=InputTextMessageContent(
                        f"🎬 **Subtitle Found:** `{name}`\n\n"
                        f"Click the button below to download the file directly from the bot!",
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📥 Get File", url=f"https://t.me/{client.me.username}?start=dl_{file_id}")]
                    ])
                )
            )
        
        await inline_query.answer(results, cache_time=1)
    except Exception as e:
        logger.error(f"Inline search error: {e}")

@app.on_callback_query(filters.regex(r"^admin_"))
async def admin_callback(client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user):
        await callback_query.answer("❌ Denied: Admin only.", show_alert=True)
        return

    cmd = callback_query.data.split("_")[1]
    user = callback_query.from_user
    if cmd == "broadcast":
        await broadcast_command(client, callback_query.message, from_user=user)
    elif cmd == "scan":
        await scan_duplicates(client, callback_query.message, from_user=user)
    elif cmd == "ban":
        await ban_command(client, callback_query.message, from_user=user)
    elif cmd == "unban":
        await unban_command(client, callback_query.message, from_user=user)
    
    await callback_query.answer()

@app.on_callback_query(filters.regex(r"^dl_"))
async def download_callback(client, callback_query: CallbackQuery):
    # Correctly extract file_id, preserving underscores
    file_id = callback_query.data.split("_", 1)[1]
    await handle_download(client, callback_query.message, file_id)
    await callback_query.answer()

@app.on_callback_query(filters.regex(r"^rm_"))
async def delete_callback(client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user):
        await callback_query.answer("❌ Denied: Only admins can delete.", show_alert=True)
        return

    file_id = callback_query.data.split("_", 1)[1]
    
    # Optional: Get filename first for better feedback
    try:
        service = drive_handler.get_service()
        file_info = service.files().get(fileId=file_id, fields="name", supportsAllDrives=True).execute()
        filename = file_info.get('name', 'Unknown')
        
        await callback_query.message.edit(f"🗑️ **Deleting:** `{filename}`...")
        
        if drive_handler.delete_file(file_id):
            await callback_query.message.edit(f"✅ **Permanently Deleted:** `{filename}`")
        else:
            await callback_query.message.edit(f"❌ **Failed to delete:** `{filename}`")
            
    except Exception as e:
        logger.error(f"Callback delete error: {e}")
        await callback_query.message.edit(f"❌ **Error during deletion:** `{str(e)}`")
    
    await callback_query.answer()

if __name__ == "__main__":
    if "Replace with your actual bot token" in BOT_TOKEN:
        print("⚠️  WARNING: You are using a placeholder BOT_TOKEN in config.py!")
        print("Please replace it with your actual token from @BotFather.")
    
    async def start_bot():
        await app.start()
        logger.info("Bot started!")
        
        # Set command menu
        commands = [
            BotCommand("start", "Start the bot / Refresh"),
            BotCommand("status", "Check your ID and status"),
            BotCommand("menu", "Show main menu"),
            BotCommand("stats", "Show bot statistics (Admin Only)"),
            BotCommand("request", "Request a file/series"),
            BotCommand("tv", "Search subtitles (e.g. /tv query)"),
            BotCommand("contact", "Contact the developer"),
            BotCommand("del", "Delete a file from GDrive (Admin)"),
            BotCommand("scan", "Scan for duplicates (Admin)"),
            BotCommand("removeall", "Remove all duplicates (Admin)"),
            BotCommand("ban", "Ban a user (Admin)"),
            BotCommand("unban", "Unban a user (Admin)"),
        ]
        await app.set_bot_commands(commands)
        logger.info("Command menu registered!")
        
        await idle()
        await app.stop()

    try:
        loop.run_until_complete(start_bot())
    except Exception as e:
        logger.error(f"Bot failed to start: {e}")
        import sys
        sys.exit(1)
