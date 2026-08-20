import io
import os
import re
import json
import time
import threading
import contextlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import telebot
from telebot import types
from dotenv import load_dotenv

load_dotenv()

import fetch_loker


# =========================
# CONFIG
# =========================

BOT_TOKEN = (
    os.getenv("BOT_TOKEN")
    or os.getenv("TOKEN_BOT")
    or ""
).strip()

TARGET_CHAT_ID = (
    os.getenv("CHAT_ID")
    or os.getenv("TELEGRAM_CHAT_ID")
    or os.getenv("MY_CHAT_ID")
    or ""
).strip()

ADMIN_CHAT_IDS = {
    chat_id.strip()
    for chat_id in (
        os.getenv("ADMIN_CHAT_ID")
        or os.getenv("ADMIN_CHAT_IDS")
        or os.getenv("MY_CHAT_ID")
        or ""
    ).replace(",", " ").split()
    if chat_id.strip()
}

SCHEDULE_FILE = Path("schedule.json")
DEFAULT_SCHEDULE = ["08:00", "12:00", "19:40"]
WIB = ZoneInfo("Asia/Jakarta")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN not found. "
        "Add BOT_TOKEN in the Railway Variables."
    )


# =========================
# INIT BOT
# =========================

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="HTML"
)

schedule_lock = threading.RLock()
run_lock = threading.Lock()


# =========================
# COUNTRIES / JOB SITES
# =========================

COUNTRIES = {
    "usa": ("United States", [
        ("usajobs.gov", "https://www.usajobs.gov/"),
        ("simplyhired.com", "https://www.simplyhired.com/"),
        ("builtin.com", "https://builtin.com/"),
    ]),
    "switzerland": ("Switzerland", [
        ("jobs.ch", "https://jobs.ch/"),
        ("jobup.ch", "https://www.jobup.ch/en/"),
        ("experteer.ch", "https://www.experteer.ch/"),
    ]),
    "germany": ("Germany", [
        ("staufenbiel.de", "https://staufenbiel.de/"),
        ("arbeitsagentur.de", "https://www.arbeitsagentur.de/jobsuche/"),
        ("jobvector.de", "https://www.jobvector.de/"),
    ]),
    "canada": ("Canada", [
        ("jobbank.gc.ca", "https://www.jobbank.gc.ca/"),
        ("eluta.ca", "https://www.eluta.ca/"),
        ("jobillico.com", "https://www.jobillico.com/fr/"),
    ]),
    "japan": ("Japan", [
        ("rikunabi.com", "https://job.rikunabi.com/?mode=intern"),
        ("mynavi.jp", "https://www.mynavi.jp/"),
        ("daijob.com", "https://www.daijob.com/"),
    ]),
    "saudi_arabia": ("Saudi Arabia", [
        ("bayt.com", "https://www.bayt.com/"),
        ("mihnati.com", "https://www.mihnati.com/"),
        ("naukrigulf.com", "https://www.naukrigulf.com/"),
    ]),
    "australia": ("Australia", [
        ("seek.com", "https://au.seek.com/"),
        ("careerone.com.au", "https://www.careerone.com.au/"),
        ("workforceaustralia.gov.au", "https://www.workforceaustralia.gov.au/"),
    ]),
}


def build_country_menu():
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton(name, callback_data=f"country:{code}")
        for code, (name, _links) in COUNTRIES.items()
    ]
    keyboard.add(*buttons)
    return keyboard


def build_links_menu(links):
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    for label, url in links:
        keyboard.add(types.InlineKeyboardButton(label, url=url))
    keyboard.add(
        types.InlineKeyboardButton("⬅️ Back", callback_data="jobs:back")
    )
    return keyboard


# =========================
# HELPERS
# =========================

def normalize_time(raw_time):
    match = re.fullmatch(r"(\d{1,2})[:.](\d{2})", raw_time.strip())
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2))

    if hour > 23 or minute > 59:
        return None

    return f"{hour:02d}:{minute:02d}"


def load_schedule():
    if not SCHEDULE_FILE.exists():
        save_schedule(DEFAULT_SCHEDULE)
        return DEFAULT_SCHEDULE[:]

    try:
        data = json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        save_schedule(DEFAULT_SCHEDULE)
        return DEFAULT_SCHEDULE[:]

    times = data.get("times") if isinstance(data, dict) else data

    if not isinstance(times, list):
        save_schedule(DEFAULT_SCHEDULE)
        return DEFAULT_SCHEDULE[:]

    clean_times = sorted(
        {
            normalized
            for normalized in (normalize_time(str(item)) for item in times)
            if normalized
        }
    )

    if not clean_times:
        clean_times = DEFAULT_SCHEDULE[:]

    save_schedule(clean_times)
    return clean_times


def save_schedule(times):
    SCHEDULE_FILE.write_text(
        json.dumps({"times": times}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def schedule_text():
    with schedule_lock:
        times = load_schedule()

    return ", ".join(f"{item} WIB" for item in times)


def is_admin(message):
    if not ADMIN_CHAT_IDS:
        return False

    user_id = str(message.from_user.id) if message.from_user else ""
    chat_id = str(message.chat.id)

    return user_id in ADMIN_CHAT_IDS or chat_id in ADMIN_CHAT_IDS


def require_admin(message):
    if is_admin(message):
        return True

    if not ADMIN_CHAT_IDS:
        bot.reply_to(
            message,
            (
                "Admin is not configured yet. Add <b>ADMIN_CHAT_ID</b> "
                "in the Railway Variables with the admin's Telegram ID."
            ),
            reply_markup=main_menu()
        )
        return False

    bot.reply_to(
        message,
        "This command is admin only.",
        reply_markup=main_menu()
    )
    return False


def run_loker_now(force=False):
    if not TARGET_CHAT_ID:
        return False, "CHAT_ID/TELEGRAM_CHAT_ID is not configured in the Railway Variables."

    if not run_lock.acquire(blocking=False):
        return False, "A job broadcast is already running. Please wait a moment."

    old_chat_id = fetch_loker.CHAT_ID

    try:
        fetch_loker.CHAT_ID = TARGET_CHAT_ID
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            total = fetch_loker.main(force=force)

        log = output.getvalue()
        match = re.search(r"(\d+) new job\(s\) sent", log)
        total_text = match.group(1) if match else str(total)

        if force:
            return True, f"Done. {total_text} latest job(s) resent."

        return True, f"Done. {total_text} new job(s) sent."

    except SystemExit as error:
        return False, f"Failed to run the job broadcast. Exit code: {error.code}"

    except Exception as error:
        return False, f"Failed to run the job broadcast: {error}"

    finally:
        fetch_loker.CHAT_ID = old_chat_id
        run_lock.release()


def ads_list_text(ads):
    return "\n".join(
        f"<b>{key}</b> ({fetch_loker.ADS_LABELS.get(key, key)}):\n{url}"
        for key, url in ads.items()
    )


def main_menu():
    keyboard = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2
    )
    keyboard.add(
        types.KeyboardButton("/start"),
        types.KeyboardButton("/help"),
        types.KeyboardButton("/jobs"),
        types.KeyboardButton("/schedule"),
        types.KeyboardButton("/setschedule"),
        types.KeyboardButton("/runjobs"),
        types.KeyboardButton("/forcejobs"),
        types.KeyboardButton("/resetjobs"),
        types.KeyboardButton("/ads"),
        types.KeyboardButton("/setad"),
        types.KeyboardButton("/id"),
        types.KeyboardButton("/admin")
    )
    return keyboard


# =========================
# HANDLERS
# =========================

@bot.message_handler(commands=["start"])
def handle_start(message):
    bot.reply_to(
        message,
        (
            "Welcome to the <b>GlobalHire</b> Bot!\n\n"
            "Type /help to see the menu."
        ),
        reply_markup=main_menu()
    )


@bot.message_handler(commands=["help"])
def handle_help(message):
    bot.reply_to(
        message,
        (
            "<b>Help Menu:</b>\n"
            "/start - Start the bot\n"
            "/help - Help\n"
            "/jobs - Browse job listings by country\n"
            "/schedule - View the automatic schedule\n"
            "/setschedule 08:00 12:00 19:40 - Change the automatic schedule\n"
            "/runjobs - Send job listings now\n"
            "/forcejobs - Force resend the latest job listings\n"
            "/resetjobs - Reset the anti-duplicate history\n"
            "/ads - View current ads\n"
            "/setad iklan-1 https://example.com - Change an ad's link\n"
            "/id - View your Telegram ID\n"
            "/admin - Admin info"
        ),
        reply_markup=main_menu()
    )


@bot.message_handler(commands=["jobs"])
def handle_jobs(message):
    bot.reply_to(
        message,
        "Select a country to browse job listings:",
        reply_markup=build_country_menu()
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("country:"))
def handle_country_selection(call):
    code = call.data.split(":", 1)[1]
    country = COUNTRIES.get(code)

    if not country:
        bot.answer_callback_query(call.id, "Country not found.")
        return

    name, links = country

    bot.edit_message_text(
        f"Job websites for <b>{name}</b>:",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=build_links_menu(links)
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "jobs:back")
def handle_jobs_back(call):
    bot.edit_message_text(
        "Select a country to browse job listings:",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=build_country_menu()
    )
    bot.answer_callback_query(call.id)


@bot.message_handler(commands=["schedule"])
def handle_schedule(message):
    bot.reply_to(
        message,
        f"Current automatic schedule:\n<b>{schedule_text()}</b>",
        reply_markup=main_menu()
    )


@bot.message_handler(commands=["setschedule"])
def handle_setschedule(message):
    if not require_admin(message):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(
            message,
            (
                "Format:\n"
                "<code>/setschedule 08:00 12:00 19:40</code>"
            ),
            reply_markup=main_menu()
        )
        return

    raw_items = re.split(r"[\s,]+", parts[1].strip())
    times = []

    for item in raw_items:
        normalized = normalize_time(item)
        if not normalized:
            bot.reply_to(
                message,
                f"Time <b>{item}</b> is invalid. Example: 08:00",
                reply_markup=main_menu()
            )
            return
        times.append(normalized)

    with schedule_lock:
        clean_times = sorted(set(times))
        save_schedule(clean_times)

    bot.reply_to(
        message,
        f"Automatic schedule changed to:\n<b>{schedule_text()}</b>",
        reply_markup=main_menu()
    )


@bot.message_handler(commands=["runjobs"])
def handle_runjobs(message):
    if not require_admin(message):
        return

    bot.reply_to(message, "Okay, checking and sending job listings now.")
    success, info = run_loker_now()

    bot.reply_to(
        message,
        info if success else f"Failed: {info}",
        reply_markup=main_menu()
    )


@bot.message_handler(commands=["forcejobs"])
def handle_forcejobs(message):
    if not require_admin(message):
        return

    bot.reply_to(message, "Okay, resending the latest job listings.")
    success, info = run_loker_now(force=True)

    bot.reply_to(
        message,
        info if success else f"Failed: {info}",
        reply_markup=main_menu()
    )


@bot.message_handler(commands=["resetjobs"])
def handle_resetjobs(message):
    if not require_admin(message):
        return

    fetch_loker.save_sent([])

    bot.reply_to(
        message,
        (
            "Job history has been reset.\n\n"
            "After this, /runjobs will resend the latest job listings "
            "found in the RSS feed."
        ),
        reply_markup=main_menu()
    )


@bot.message_handler(commands=["ads"])
def handle_ads(message):
    ads = fetch_loker.load_ads()

    bot.reply_to(
        message,
        f"<b>Current ads:</b>\n\n{ads_list_text(ads)}",
        reply_markup=main_menu()
    )


@bot.message_handler(commands=["setad"])
def handle_setad(message):
    if not require_admin(message):
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(
            message,
            (
                "Format:\n"
                "<code>/setad iklan-1 https://example.com</code>\n\n"
                f"<b>Current ads:</b>\n\n{ads_list_text(fetch_loker.load_ads())}"
            ),
            reply_markup=main_menu()
        )
        return

    key, url = parts[1].strip(), parts[2].strip()

    if not re.fullmatch(r"iklan-\d+", key):
        bot.reply_to(
            message,
            "Ad key must look like <code>iklan-1</code>, <code>iklan-2</code>, etc.",
            reply_markup=main_menu()
        )
        return

    if not re.match(r"^https?://", url):
        bot.reply_to(
            message,
            "The URL must start with http:// or https://",
            reply_markup=main_menu()
        )
        return

    ads = fetch_loker.set_ad(key, url)

    bot.reply_to(
        message,
        (
            f"Ad <b>{key}</b> updated.\n\n"
            f"<b>Current ads:</b>\n\n{ads_list_text(ads)}"
        ),
        reply_markup=main_menu()
    )


@bot.message_handler(commands=["admin"])
def handle_admin(message):
    bot.reply_to(
        message,
        "GlobalHire admin is ready to help. Send your message here.",
        reply_markup=main_menu()
    )


@bot.message_handler(commands=["id"])
def handle_id(message):
    user_id = message.from_user.id if message.from_user else "-"
    chat_id = message.chat.id

    bot.reply_to(
        message,
        (
            "Your Telegram ID:\n"
            f"<code>{user_id}</code>\n\n"
            "This chat's ID:\n"
            f"<code>{chat_id}</code>"
        ),
        reply_markup=main_menu()
    )


@bot.message_handler(func=lambda message: True)
def handle_unknown(message):
    bot.reply_to(
        message,
        "Command not recognized. Type /help to see the menu.",
        reply_markup=main_menu()
    )


# =========================
# SCHEDULER
# =========================

def scheduler_loop():
    last_run_key = None

    while True:
        now = datetime.now(WIB)
        current_time = now.strftime("%H:%M")
        current_key = now.strftime("%Y-%m-%d %H:%M")

        with schedule_lock:
            times = load_schedule()

        if current_time in times and current_key != last_run_key:
            print(f"Running automatic job broadcast: {current_time} WIB")
            success, info = run_loker_now()
            print(info if success else f"Failed: {info}")
            last_run_key = current_key

        time.sleep(20)


def main():
    print("=" * 50)
    print("GlobalHire Bot")
    print("BOT ACTIVE")
    print(f"Automatic schedule: {schedule_text()}")
    print("=" * 50)

    threading.Thread(
        target=scheduler_loop,
        daemon=True
    ).start()

    bot.infinity_polling(
        timeout=30,
        long_polling_timeout=30,
        skip_pending=True
    )


if __name__ == "__main__":
    main()
