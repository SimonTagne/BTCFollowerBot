# BTCFollowerBot
A Telegram bot to track payment to BTC addresses extracted from scam emails

We receive lots of mails basically saying: "I've hacked <X>, send me some bitcoins or I'll do something nasty with data I got from <X>." Out of misplaced curiosity, I wanted to know how many people actually pay. This telegram bot connects to my mailbox, fetches the Junk folder and scan mails for BTC addresses. Transaction data are queried to blockchair.com's API and notifications sent to telegram.

## Installation and configuration
- Dependencies: Python 3 (tested with 3.10, probably works with other versions as well), [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
- Clone/download the repo
- Copy `settings.dist.py` to `settings.py` (which is gitignored) and edit configuration in the new file
  - `IMAP_*` are the connection details for IMAP (Normal password, TLS over port 993)
  - `TELEGRAM_BOT_TOKEN` is the token you get from [@BotFather](https://t.me/BotFather)
  - `TELEGRAM_*_CHAT_ID` are the chat IDs. You can get those by running the bot with the default value and entering the `/get_id` command. `NOTIFS` is for payment notifications and `INFO` is for information about found BTC addresses and error reporting
- Run with `python bot.py`. You can add `-d` / `--debug` to run the cron job every minute instead of every day. Note that this will quickly exhaust the API limits if you leave it running
