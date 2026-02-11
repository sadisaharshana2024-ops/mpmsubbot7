import os

# config.py
DB_NAME = os.environ.get("DB_NAME", "bot_data.db")

API_ID = int(os.environ.get("API_ID", 36039536))
API_HASH = os.environ.get("API_HASH", "f9c74f8a38a3b2ea0f2e88fe373b554f")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8564530553:AAGNoHoK5374qB_WfDhy12mo5jHazLk63xo")

# Google Drive folder ID to search within
FOLDER_ID = os.environ.get("FOLDER_ID", "1ZNwWkXJWmCi3iVVH02Y_y78yJl9qtTp5")

# Bot administrators (Usernames without @, comma-separated in env)
ADMIN_USERNAMES_STR = os.environ.get("ADMIN_USERNAMES", "slhomelander,sljohnwick")
ADMIN_USERNAMES = [u.strip() for u in ADMIN_USERNAMES_STR.split(",")]

# Mandatory join channel
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "MpMStudioOfficial")
CHANNEL_LINK = os.environ.get("CHANNEL_LINK", "https://t.me/MpMStudioOfficial")

# Group for user requests
REQUEST_GROUP = os.environ.get("REQUEST_GROUP", "requestmpm")

# Bot administrators (User IDs, comma-separated in env)
ADMIN_IDS_STR = os.environ.get("ADMIN_IDS", "6115934442")
ADMIN_IDS = [int(i.strip()) for i in ADMIN_IDS_STR.split(",") if i.strip()]
