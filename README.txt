THE WHITE COAT FILES — MBBS RESOURCE BOT
========================================

What it does
------------
- /start: students see Books, PDFs/Notes, Videos, Other Resources.
- Students choose a resource type, then one of 19 MBBS subjects, then a file.
- Admin runs /add, selects category and subject, then sends one or more files.
- /cancel ends the current upload session.
- /stats shows counts (admin only).
- SQLite stores Telegram file_id and the category/subject mapping.
- Files are delivered directly in the bot chat; students do not need access to any private channel.

IMPORTANT LIMITATION
--------------------
This is a tested starter implementation, not a guarantee of zero errors in every Telegram environment.
You must set your bot token and numeric Telegram user ID. Keep the database file backed up.
Telegram file_id values are associated with this bot. If a file_id becomes invalid, that file may need to be re-uploaded.

SETUP ON A COMPUTER OR HOSTING SERVICE
--------------------------------------
1. Install Python 3.10 or newer.
2. Put bot.py and requirements.txt in the same folder.
3. Install dependencies:
       python -m pip install -r requirements.txt

4. Create a bot through Telegram's official @BotFather and copy its token.
   Never share the token publicly or commit it to a public repository.

5. Find your numeric Telegram user ID using a trusted ID bot or a method you trust.
   Do not use your username as ADMIN_IDS; it must be a numeric user ID.

6. Set environment variables.

   Linux/macOS:
       export BOT_TOKEN="PASTE_BOT_TOKEN_HERE"
       export ADMIN_IDS="123456789"
       python bot.py

   Windows PowerShell:
       $env:BOT_TOKEN="PASTE_BOT_TOKEN_HERE"
       $env:ADMIN_IDS="123456789"
       python bot.py

   On hosting, add BOT_TOKEN and ADMIN_IDS in the service's environment variables panel.
   Keep the process running continuously for the bot to stay online.

7. Open your bot in Telegram and send /start.
   As the admin, send /add, choose a category, choose a subject, and send a PDF/book/video.
   Send /cancel when you finish uploading.

RESOURCE TYPES
--------------
Books | PDFs / Notes | Videos | Other Resources

The 19 subject labels are in SUBJECTS in bot.py and can be edited.

HOW FILES ARE HANDLED
---------------------
- PDFs and book files: send as Telegram documents.
- Videos: send as Telegram videos or as documents if you want to preserve the original file.
- Other resources: documents, audio, voice messages, video notes, photos are accepted.
- Students receive the saved Telegram file directly in their private chat with the bot.

BACKUP
------
Stop the bot and copy white_coat_library.sqlite3 somewhere safe. Do this regularly.
If you change DATABASE_PATH, ensure the parent folder exists and is writable.

SECURITY
--------
- Only numeric user IDs in ADMIN_IDS can upload.
- Students can browse and receive resources, but cannot upload through /add.
- Do not add untrusted user IDs to ADMIN_IDS.
- Do not post your bot token in chats, screenshots, or source code.
