import os
import time
import logging
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
    "Indian Market": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Indian Economy": "https://economictimes.indiatimes.com/economy/rssfeeds/1373380680.cms",
    "Indian Companies": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "Commodities": "https://economictimes.indiatimes.com/markets/commodities/rssfeeds/1808152121.cms",
    "Global Markets": "https://feeds.bloomberg.com/markets/news.rss",
    "US Weather Energy": "https://feeds.feedburner.com/ndtvnews-energy",
}

NEWSAPI_CATEGORIES = {
    "World News": "general",
    "Sports": "sports",
    "Tech and AI": "technology",
    "Politics": "general",
    "Business": "business",
}

NEWSAPI_QUERIES = {
    "Indian Market": "NSE BSE Sensex Nifty stock market India",
    "RBI Policy": "RBI Reserve Bank India interest rate policy",
    "Indian Companies": "India earnings results Reliance TCS Infosys HDFC",
    "Global Markets": "global markets stocks bonds impact economy",
    "Commodities": "gold silver crude oil commodity prices",
    "US Weather Energy": "USA weather natural gas energy prices impact",
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
    "Indian Market": "📈",
    "Indian Economy": "🇮🇳",
    "Indian Companies": "🏢",
    "RBI Policy": "🏦",
    "Global Markets": "🌐",
    "Commodities": "🥇",
    "US Weather Energy": "⛽",
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

    for category, query in NEWSAPI_QUERIES.items():
        try:
            params = {
                "apiKey": api_key,
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": max_per_category * 2,
            }
            resp = requests.get(
                "https://newsapi.org/v2/everything",
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
            log.info("NewsAPI query " + category + ": fetched " + str(count) + " items")
        except Exception as e:
            log.warning("NewsAPI query failed " + category + ": " + str(e))

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

    market_categories = [
        "Indian Market", "Indian Economy", "Indian Companies",
        "RBI Policy", "Global Markets", "Commodities", "US Weather Energy"
    ]

    if category in market_categories:
        prompt = (
            "You are a financial news analyst. Summarize this news in max 200 characters. "
            "Mention the market impact clearly (positive/negative/neutral). "
            "Be factual and concise. No hashtags or emojis. "
            "Output ONLY the summary. Nothing else.\n\n"
            "Headline: " + headline["title"] + "\n"
            "Context: " + headline["summary"]
        )
    else:
        prompt = (
            "Write a short news update about this story. "
            "Max 200 characters. Factual and punchy tone. "
            "No hashtags or emojis. "
            "Output ONLY the summary. Nothing else.\n\n"
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
    all_headlines += fetch_rss_headlines(max_per_feed=3)
    all_headlines += fetch_newsapi_headlines(max_per_category=2)

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


def is_paused():
    ist_offset = 5.5 * 3600
    now_ist = datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() + ist_offset
    )
    weekday = now_ist.weekday()
    hour = now_ist.hour
    minute = now_ist.minute
    time_in_minutes = hour * 60 + minute

    saturday_start = 10 * 60
    sunday_end = 18 * 60

    if weekday == 5 and time_in_minutes >= saturday_start:
        log.info("Weekend pause active (Sat 10AM - Sun 6PM IST). Skipping this run.")
        return True
    if weekday == 6 and time_in_minutes <= sunday_end:
        log.info("Weekend pause active (Sat 10AM - Sun 6PM IST). Skipping this run.")
        return True

    if hour >= 23 or hour < 6:
        log.info("Night pause active (11PM - 6AM IST). Skipping this run.")
        return True

    return False


if __name__ == "__main__":
    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
    log.info("News Bot starting up...")
    log.info("DRY RUN mode: " + str(dry_run))

    if is_paused():
        log.info("Weekend pause active (Sat 10AM - Sun 6PM IST). Skipping this run.")
    else:
        run_bot_cycle()
