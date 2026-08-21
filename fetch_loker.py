import os
import re
import sys
import json
import time
import html
import requests
import xml.etree.ElementTree as ET


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

CHAT_ID = (
    os.getenv("CHAT_ID")
    or os.getenv("TELEGRAM_CHAT_ID")
    or ""
).strip()


# =========================================================
# ADS (editable via bot commands)
# =========================================================

ADS_FILE = "ads.json"

DEFAULT_ADS = {
    "iklan-1": "https://cv-kerjadimana.gemilangsakti31.workers.dev",
    "iklan-2": "https://omg10.com/4/11592711/",
}

ADS_LABELS = {
    "iklan-1": "📄 Build a Professional CV",
    "iklan-2": "✍️ Write a Cover Letter",
}


def save_ads(ads):
    with open(
        ADS_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            ads,
            file,
            ensure_ascii=False,
            indent=2
        )


def load_ads():

    if not os.path.exists(ADS_FILE):
        save_ads(DEFAULT_ADS)
        return DEFAULT_ADS.copy()

    try:

        with open(
            ADS_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if isinstance(data, dict) and data:
            merged = DEFAULT_ADS.copy()
            merged.update(data)
            return merged

        save_ads(DEFAULT_ADS)
        return DEFAULT_ADS.copy()

    except (json.JSONDecodeError, OSError):
        save_ads(DEFAULT_ADS)
        return DEFAULT_ADS.copy()


def set_ad(key, url):
    ads = load_ads()
    ads[key] = url
    save_ads(ads)
    return ads


SENT_FILE = "sent.json"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


# =========================================================
# RSS
# =========================================================

DEFAULT_RSS_FEEDS = [
    "https://rss.app/feeds/MZMZkLtTiHKbr2ck.xml",
    "https://rss.app/feeds/7oEScJlZFeoYE3oo.xml",
]

DEFAULT_FALLBACK_RSS_FEEDS = [
    (
        "https://news.google.com/rss/search?"
        "q=loker%20Cirebon%20OR%20Kuningan%20"
        "site%3Aglints.com%20OR%20site%3Ajobstreet.co.id%20"
        "OR%20site%3Akarir.com"
        "&hl=id&gl=ID&ceid=ID:id"
    ),
    (
        "https://news.google.com/rss/search?"
        "q=lowongan%20kerja%20Cirebon%20OR%20Kuningan%20"
        "site%3Aglints.com%20OR%20site%3Ajobstreet.co.id"
        "&hl=id&gl=ID&ceid=ID:id"
    ),
]


def env_list(name, default):
    raw_value = os.getenv(name, "").strip()

    if not raw_value:
        return default[:]

    items = [
        item.strip()
        for item in re.split(r"[\n,]+", raw_value)
        if item.strip()
    ]

    return items or default[:]


RSS_FEEDS = env_list(
    "RSS_FEEDS",
    DEFAULT_RSS_FEEDS
)

FALLBACK_RSS_FEEDS = env_list(
    "FALLBACK_RSS_FEEDS",
    DEFAULT_FALLBACK_RSS_FEEDS
)


# =========================================================
# VALIDATION
# =========================================================

def validate_config():

    if not BOT_TOKEN:
        print("❌ BOT_TOKEN not found.")
        print("Add BOT_TOKEN in the GitHub Secrets.")
        sys.exit(1)

    if not CHAT_ID:
        print("❌ CHAT_ID not found.")
        print("Add CHAT_ID in the GitHub Secrets.")
        sys.exit(1)

    print("✅ BOT_TOKEN available.")
    print(f"✅ CHAT_ID: {CHAT_ID}")

    ads = load_ads()

    print()
    print("🌐 CV LINK (iklan-1):")
    print(ads["iklan-1"])

    print()
    print("✍️ COVER LETTER LINK (iklan-2):")
    print(ads["iklan-2"])


# =========================================================
# ANTI-DUPLICATE DATABASE
# =========================================================

def save_sent(sent):

    with open(
        SENT_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            sent,
            file,
            ensure_ascii=False,
            indent=2
        )


def load_sent():

    if not os.path.exists(SENT_FILE):

        print(
            "ℹ️ sent.json does not exist yet. "
            "Creating a new file..."
        )

        save_sent([])

        return []

    try:

        with open(
            SENT_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if isinstance(data, list):
            return data

        print(
            "⚠️ sent.json content is invalid. "
            "Database reset."
        )

        save_sent([])

        return []

    except (
        json.JSONDecodeError,
        OSError
    ) as error:

        print(
            f"⚠️ Failed to read sent.json: {error}"
        )

        print(
            "⚠️ Anti-duplicate database reset."
        )

        save_sent([])

        return []


# =========================================================
# CLEAN TEXT
# =========================================================

def strip_html(raw_text):

    if not raw_text:
        return ""

    text = re.sub(
        r"<[^>]+>",
        " ",
        raw_text
    )

    text = html.unescape(text)

    return " ".join(text.split())


def clean_job_title(raw_title):

    title = strip_html(raw_title)

    for suffix in (
        " - Glints",
        " | Glints TapLoker",
        " - Karir.com",
        " - Jobstreet",
        " - JobStreet",
    ):

        title = title.replace(
            suffix,
            ""
        )

    return title.strip(" ,-") 


def fallback_description(
    title,
    source
):

    source_text = (
        f" from {source}"
        if source
        else ""
    )

    return (
        f"This job listing was found"
        f"{source_text} for the "
        "Cirebon/Kuningan area and surroundings. "
        f"Position available: {title}. "
        "Open the View Job button to "
        "read the job details, "
        "qualifications, requirements, salary, "
        "and how to apply directly "
        "on the official job page."
    )


# =========================================================
# TELEGRAM KEYBOARD
# =========================================================

def build_keyboard(link):

    ads = load_ads()

    return {
        "inline_keyboard": [

            [
                {
                    "text": ADS_LABELS["iklan-1"],
                    "url": ads["iklan-1"]
                }
            ],

            [
                {
                    "text": ADS_LABELS["iklan-2"],
                    "url": ads["iklan-2"]
                }
            ],

            [
                {
                    "text": "🔎 View Job Listing",
                    "url": link
                }
            ]

        ]
    }


# =========================================================
# SEND TO TELEGRAM
# =========================================================

def send_telegram(
    title,
    description,
    link
):

    if len(description) > 3000:

        description = (
            description[:3000]
            + "..."
        )

    pesan = (
        "📢 <b>GlobalHire INFO</b>\n\n"

        f"🏢 <b>{title}</b>\n\n"

        "📝 <b>Job Description</b>\n"

        f"{description}\n\n"

        "━━━━━━━━━━━━━━\n\n"

        "📄 <b>BUILD YOUR CV</b>\n"

        "🎯 Build a professional CV to "
        "boost your chances of getting hired.\n\n"

        "🤖 <b>GlobalHire</b>"
    )

    keyboard = build_keyboard(link)

    payload = {

        "chat_id": CHAT_ID,

        "text": pesan,

        "parse_mode": "HTML",

        "reply_markup": keyboard,

        "disable_web_page_preview": True

    }

    ads = load_ads()

    print()
    print("📤 SENDING POST")

    print(
        "🌐 CV:"
    )

    print(ads["iklan-1"])

    print(
        "✍️ COVER LETTER:"
    )

    print(ads["iklan-2"])

    print(
        "🔎 JOB LISTING:"
    )

    print(link)

    try:

        response = requests.post(

            f"{TELEGRAM_API}/sendMessage",

            json=payload,

            timeout=30

        )

    except requests.RequestException as error:

        print(
            f"❌ Failed to connect to Telegram: "
            f"{error}"
        )

        return False

    try:

        data = response.json()

    except ValueError:

        print(
            "❌ Telegram response is not JSON."
        )

        print(response.text)

        return False

    if (
        response.status_code == 200
        and data.get("ok")
    ):

        print(
            "✅ SUCCESS:"
            f" {html.unescape(title)[:70]}"
        )

        return True

    print(
        "❌ TELEGRAM FAILED"
    )

    print(
        f"HTTP Status: "
        f"{response.status_code}"
    )

    print(
        f"Response: "
        f"{response.text}"
    )

    return False


# =========================================================
# PROCESS RSS
# =========================================================

def process_feed(
    rss_url,
    sent,
    force=False
):

    print()
    print("=" * 60)

    print(
        "📡 Fetching RSS:"
    )

    print(rss_url)

    try:

        response = requests.get(

            rss_url,

            timeout=30,

            headers={
                "User-Agent":
                "Mozilla/5.0 "
                "GlobalHireBot/1.0"
            }

        )

    except requests.RequestException as error:

        print(
            f"❌ Failed to fetch RSS: "
            f"{error}"
        )

        return 0

    if response.status_code != 200:

        print(
            f"⚠️ RSS HTTP "
            f"{response.status_code}. "
            "Feed skipped."
        )

        return 0

    try:

        root = ET.fromstring(
            response.content
        )

    except ET.ParseError as error:

        print(
            f"❌ Invalid RSS XML: "
            f"{error}"
        )

        return 0

    items = root.findall(
        ".//item"
    )

    print(
        f"📦 Found "
        f"{len(items)} item(s)."
    )

    jumlah_berhasil = 0

    for item in items[:5]:

        title_raw = item.findtext(
            "title",
            ""
        )

        link_raw = item.findtext(
            "link",
            ""
        )

        desc_raw = item.findtext(
            "description",
            ""
        )

        source_raw = item.findtext(
            "source",
            ""
        )

        link = (
            link_raw or ""
        ).strip()

        if not link:

            print(
                "⏭️ Item has no link."
            )

            continue

        if (
            link in sent
            and not force
        ):

            print(
                "⏭️ Already sent: "
                f"{title_raw[:60]}"
            )

            continue

        title_plain = clean_job_title(
            title_raw
        )

        description_plain = strip_html(
            desc_raw
        )

        if not title_plain:

            title_plain = (
                "Latest Job Opening"
            )

        if (
            len(description_plain) < 80
            or
            description_plain.lower()
            in title_plain.lower()
        ):

            description_plain = (
                fallback_description(
                    title_plain,
                    strip_html(
                        source_raw
                    )
                )
            )

        title = html.escape(
            title_plain
        )

        description = html.escape(
            description_plain
        )

        print()

        print(
            "📨 Processing: "
            f"{html.unescape(title)[:70]}"
        )

        berhasil = send_telegram(

            title,

            description,

            link

        )

        if berhasil:

            if link not in sent:

                sent.append(link)

                save_sent(sent)

            jumlah_berhasil += 1

            print(
                "⏳ Waiting 2 seconds..."
            )

            time.sleep(2)

    return jumlah_berhasil


# =========================================================
# MAIN
# =========================================================

def main(force=False):

    validate_config()

    sent = load_sent()

    print()
    print("=" * 60)

    print(
        "🤖 GlobalHire Auto Job Broadcast"
    )

    print("=" * 60)

    ads = load_ads()

    print(
        f"📢 CHAT_ID: {CHAT_ID}"
    )

    print(
        f"🌐 CV (iklan-1): {ads['iklan-1']}"
    )

    print(
        f"✍️ Cover letter (iklan-2): {ads['iklan-2']}"
    )

    print(
        f"📚 Anti-duplicate database: "
        f"{len(sent)} link(s)"
    )

    print(
        "🔁 Force resend: "
        f"{'YES' if force else 'NO'}"
    )

    print("=" * 60)

    total = 0

    # =====================================================
    # MAIN FEEDS
    # =====================================================

    for rss_url in RSS_FEEDS:

        total += process_feed(

            rss_url,

            sent,

            force=force

        )

    # =====================================================
    # FALLBACK
    # =====================================================

    if (
        total == 0
        and FALLBACK_RSS_FEEDS
    ):

        print()
        print("=" * 60)

        print(
            "⚠️ Main feeds sent no job listings."
        )

        print(
            "🔎 Trying fallback "
            "Google News RSS..."
        )

        print("=" * 60)

        for rss_url in FALLBACK_RSS_FEEDS:

            total += process_feed(

                rss_url,

                sent,

                force=force

            )

    save_sent(sent)

    print()
    print("=" * 60)

    print(
        "✅ DONE — "
        f"{total} new job(s) sent."
    )

    print("=" * 60)

    return total


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    print("========================================", flush=True)
    print("Starting GlobalHire Bot...", flush=True)
    print("BOT_TOKEN detected:", bool(BOT_TOKEN), flush=True)
    print("CHAT_ID configured:", bool(TARGET_CHAT_ID), flush=True)
    print("Loading Telegram polling...", flush=True)
    print("========================================", flush=True)

    try:
        main()
    except Exception as error:
        print("========================================", flush=True)
        print("BOT CRASHED!", flush=True)
        print(f"Error: {error}", flush=True)
        print("========================================", flush=True)
        raise
