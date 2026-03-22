import os
import time
import logging
import schedule
import requests
import feedparser
from groq import Groq
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


def get_groq_client():
    return Groq(api_key=os.getenv("GROQ_API_KEY"))


def send_telegram_message(text):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    channel = os.getenv("TELEGRAM_CHANNEL")
    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"

    if dry_run:
        log.info("[DRY RUN] Would post to Telegram: " + text)
        return True

    url = "https://api.telegram.org/bot" + token + "/sendMessage"
    payload = {
        "chat_id": channel,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        log.info("Posted to Telegram successfully")
        return True
    except Exception as e:
        log.error("Telegram post failed: " + str(e))
        return False


RSS_FEEDS = {
    "World News": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "Sports": "https://feeds.bbci.co.uk/sport/rss.xml",
    "Tech and AI": "https://feeds.feedburner.com/TechCrunch",
    "Politics": "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml",
    "Business": "https://feeds.bloomberg.com/markets/news.rss",
}

NEWSAPI_CATEGORIES = {
    "World News": "general",
    "Sports": "sports",
    "Tech and AI": "technology",
    "Politics": "general",
    "Business": "business",
}

POLITICS_KEYWORDS = [
    "election", "president", "congress", "senate", "parliament",
    "minister", "policy", "government", "vote", "political"
]

CATEGORY_EMOJI = {
    "World News": "🌍",
    "Sports": "⚽",
    "Tech and AI": "🤖",
    "Politics": "🏛",
    "Business": "💼",
}


def fetch_rss_headlines(max_per_feed=3):
    headlines = []
    for category, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                headlines.append({
                    "category": category,
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:300],
                    "source": "RSS",
                    "url": entry.get("link", ""),
                })
            log.info("RSS " + category + ": fetched items")
        except Exception as e:
            log.warning("RSS feed failed " + category + ": " + str(e))
    return headlines


def fetch_newsapi_headlines(max_per_category=2):
    api_key = os.getenv("NEWS_API_KEY")
    if not api_key:
        log.warning("NEWS_API_KEY not set — skipping NewsAPI.")
        return []

    headlines = []
    seen_titles = set()

    for category, newsapi_cat in NEWSAPI_CATEGORIES.items():
        try:
            params = {
                "apiKey": api_key,
                "category": newsapi_cat,
                "language": "en",
                "pageSize": max_per_category * 3,
            }
            resp = requests.get(
                "https://newsapi.org/v2/top-headlines",
                params=params,
                timeout=10
            )
            resp.raise_for_status()
            articles = resp.json().get("articles", [])

            count = 0
            for art in articles:
                title = art.get("title", "")
                if not title or title in seen_titles:
                    continue
                if category == "Politics":
                    combined = (title + art.get("description", "")).lower()
                    if not any(kw in combined for kw in POLITICS_KEYWORDS):
                        continue
                seen_titles.add(title)
                headlines.append({
                    "category": category,
                    "title": title,
                    "summary": art.get("description", "")[:300],
                    "source": "NewsAPI",
                    "url": art.get("url", ""),
                })
                count += 1
                if count >= max_per_category:
                    break
            log.info("NewsAPI " + category + ": fetched " + str(count) + " items")
        except Exception as e:
            log.warning("NewsAPI failed " + category + ": " + str(e))

    return headlines


posted_titles = set()


def deduplicate(headlines):
    seen = set()
    unique = []
    for h in headlines:
        key = h["title"].lower().strip()[:80]
        if key not in seen and key not in posted_titles:
            seen.add(key)
            unique.append(h)
    return unique


def summarize_to_post(client, headline):
    category = headline["category"]
    emoji = CATEGORY_EMOJI.get(category, "📰")
    prompt = (
        "Write a short news update about this story. "
        "Max 200 characters for the main text. "
        "Factual and punchy tone. "
        "Do not add hashtags or emojis. "
        "Output ONLY the summary text. Nothing else.\n\n"
        "Headline: " + headline["title"] + "\n"
        "Context: " + headline["summary"]
    )

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
        )
        summary = response.choices[0].message.content.strip()
        url = headline.get("url", "")
        post = emoji + " <b>" + category + "</b>\n\n" + summary + "\n\n" + url
        return post
    except Exception as e:
        log.error("Groq summarization failed: " + str(e))
        return None


def run_bot_cycle():
    log.info("Bot cycle starting at " + datetime.now(timezone.utc).isoformat())

    groq = get_groq_client()

    all_headlines = []
    all_headlines += fetch_rss_headlines(max_per_feed=5)
    all_headlines += fetch_newsapi_headlines(max_per_category=3)

    log.info("Total raw headlines fetched: " + str(len(all_headlines)))

    unique = deduplicate(all_headlines)
    log.info("After deduplication: " + str(len(unique)) + " headlines")

    SOURCE_PRIORITY = {"NewsAPI": 0, "RSS": 1}
    category_best = {}
    for h in sorted(unique, key=lambda x: SOURCE_PRIORITY.get(x["source"], 9)):
        cat = h["category"]
        if cat not in category_best:
            category_best[cat] = h

    log.info("Categories to post: " + str(list(category_best.keys())))

    posted = 0
    for category, headline in category_best.items():
        post_text = summarize_to_post(groq, headline)
        if not post_text:
            continue
        success = send_telegram_message(post_text)
        if success:
            posted_titles.add(headline["title"].lower().strip()[:80])
            posted += 1
        time.sleep(5)

    log.info("Cycle complete. Posted " + str(posted) + "/" + str(len(category_best)) + " messages.")


if __name__ == "__main__":
    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
    log.info("News Bot starting up...")
    log.info("DRY RUN mode: " + str(dry_run))

    run_bot_cycle()
