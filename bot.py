import settings


from hashlib import sha256
from imaplib import IMAP4_SSL
import datetime
import email
import email.policy
import json
import logging
import re
import sqlite3
import sys
import time
import urllib.request
import zoneinfo


from telegram.ext import CommandHandler, Updater


def init_db():
    """Opens the sqlite file and create the tables if they don't exist"""
    db = sqlite3.connect(settings.DB_NAME).cursor()

    if db.execute("SELECT name FROM sqlite_master WHERE name='mails';").fetchone() is None:
        db.execute("CREATE TABLE mails(uid INTEGER NOT NULL PRIMARY KEY, subject TEXT, time INTEGER);")

    if db.execute("SELECT name FROM sqlite_master WHERE name='addresses';").fetchone() is None:
        db.execute("CREATE TABLE addresses(id INTEGER NOT NULL PRIMARY KEY, address TEXT NOT NULL, mail_id INTEGER NOT NULL, FOREIGN KEY(mail_id) REFERENCES mails(uid) ON DELETE CASCADE);")

    if db.execute("SELECT name FROM sqlite_master WHERE name='transactions';").fetchone() is None:
        db.execute("CREATE TABLE transactions(id INTEGER NOT NULL PRIMARY KEY, hash TEXT NOT NULL, address_id INTEGER NOT NULL, FOREIGN KEY(address_id) REFERENCES addresses(id) ON DELETE CASCADE);")

    return db

def check_mails(db, bot):
    """Connect to the IMAP mailbox and fetch all mails that where not already processed. The mails are scanned for BTC addresses and saved in the db"""
    imap = IMAP4_SSL(host=settings.IMAP_HOSTNAME)
    status, _ = imap.login(settings.IMAP_USERNAME, settings.IMAP_PASSWORD)
    if status != "OK":
        raise Exception("Can't connect to IMAP mailbox")

    status, _ = imap.select(settings.IMAP_MAILBOX)
    if status != "OK":
        raise Exception("Can't select IMAP mailbox")

    status, data = imap.search(None, "ALL")
    if status != "OK":
        raise Exception("Can't list the mails in mailbox")

    mails = data[0].decode().split(" ")

    for mail in mails:
        status, data = imap.fetch(mail, "(UID)")
        if status != "OK":
            raise Exception("Can't fetch mail")

        data = data[0].decode()
        match = re.search(r"\(UID (.*)\)", data)
        if not match:
            raise Exception("Can't parse UID")

        uid = int(match.group(1))
        if db.execute("SELECT uid FROM mails WHERE uid=?;", (uid, )).fetchone() is None:
            status, data = imap.fetch(mail, "(RFC822)")
            if status != "OK":
                raise Exception("Can't fetch mail")

            mail = data[0][1]
            mail = email.message_from_bytes(mail, policy=email.policy.default)
            subject = mail["Subject"]

            db.execute("INSERT INTO mails(uid, subject, time) VALUES(?, ?, strftime('%s', 'now'))", (uid, subject))
            print(f"Processing mail UID {uid}")
            find_btc_address(db, uid, mail, bot)
            db.connection.commit()
        else:
            print(f"Mail UID {uid} was already processed")


    status, _ = imap.close()
    if status != "OK":
        raise Exception("Can't close mailbox")

    status, _ = imap.logout()
    if status != "BYE":
        raise Exception("Can't logout from IMAP server")


def find_btc_address(db, uid, mail, bot):
    """Scan an email for BTC addresses. If some are found, save them in the db."""
    DIGITS_BASE_58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    regex = re.compile(fr"\b([{DIGITS_BASE_58}]{{25,34}})\b")

    for address in regex.findall(mail.get_body(("html", "plain")).get_content()):

        # Verify checksum
        n = 0
        for char in address:
            n *= 58
            n += DIGITS_BASE_58.index(char)
        bin_address = n.to_bytes(25, 'big')
        if bin_address[-4:] == sha256(sha256(bin_address[:-4]).digest()).digest()[:4]:
            db.execute("INSERT INTO addresses(address, mail_id) VALUES(?, ?)", (address, uid))
            print(f"Found address {address}")
            bot.send_message(chat_id=settings.TELEGRAM_INFO_CHAT_ID, text=f"Found bitcoin address {address}")


def fetch_transactions(db, bot):
    """Call blockchair.com API to get the transactions for all addresses in the db"""
    for address_id, address, uid in db.connection.execute("SELECT id, address, mail_id FROM addresses;"):
        time.sleep(2)
        print(f"Checking transactions for address {address}")
        data = json.loads(urllib.request.urlopen(f"https://api.blockchair.com/bitcoin/dashboards/address/{address}?limit=10000&transaction_details=true&state=latest").read().decode())

        for tx in data["data"][address]["transactions"]:
            if db.execute("SELECT id FROM transactions WHERE hash=?;", (tx["hash"],)).fetchone() is None:
                db.execute("INSERT INTO transactions(hash, address_id) VALUES(?, ?)", (tx["hash"], address_id))
                db.connection.commit()
                print(f"Found new transactions {tx['hash']} for address {address}: balance {tx['balance_change']} satoshis")

                if tx['balance_change'] > 0:
                    subject = db.execute("SELECT subject FROM mails WHERE uid=?;", (uid,)).fetchone()[0]
                    bot.send_message(chat_id=settings.TELEGRAM_NOTIFS_CHAT_ID, text=f"💰 Quelqu'un a payé ! 💸\nHash de la transaction : {tx['hash']}\nMontant : {tx['balance_change'] / 1e8} BTC / {tx['balance_change'] / 1e8 * data['context']['market_price_usd']} USD\nSujet du mail : {subject}")

            else:
                print(f"Transaction {tx['hash']} already known")


def cron_job(bot):
    try:
        db = init_db()
        db.execute("DELETE FROM mails WHERE time < strftime('%s', 'now') - ?;", (settings.MAIL_TIMEOUT * 86400,))
        db.connection.commit()

        check_mails(db, bot)

        if db.execute("SELECT COUNT(*) as count FROM addresses;").fetchone()[0] > 600:
            bot.send_message(chat_id=settings.TELEGRAM_INFO_CHAT_ID, text=f"Too many addresses, I won't lookup transactions too avoid hitting the rate limit.")
            return

        fetch_transactions(db, bot)

    except Exception as e:
        message = f"Error while running cron job : {type(e).__name__} {e}"
        bot.send_message(chat_id=settings.TELEGRAM_INFO_CHAT_ID, text=message)
        print(message)


def start(update, context):
    print("test")
    context.bot.send_message(chat_id=update.effective_chat.id, text="Hi! I'm not made to be used by end users directly. Checkout https://github.com/SimonTagne/BTCFollowerBot for more details.")


def get_id(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text=f"Your telegram ID is {update.effective_user.id}")


if __name__ ==  "__main__":
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

    updater = Updater(token=settings.TELEGRAM_BOT_TOKEN)
    dispatcher = updater.dispatcher
    start_handler = CommandHandler('start', start)
    dispatcher.add_handler(start_handler)
    dispatcher.add_handler(CommandHandler('get_id', get_id))

    if "--debug" not in sys.argv and "-d" not in sys.argv:
        updater.job_queue.run_daily((lambda context:cron_job(context.bot)), datetime.time(14, 0, 0, tzinfo=zoneinfo.ZoneInfo("Europe/Zurich")), name="Cron job")
    else:
        updater.job_queue.run_repeating((lambda context: cron_job(context.bot)), 60, name="Cron job")

    updater.start_polling()
    updater.idle()
