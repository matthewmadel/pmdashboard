"""
fetch_news.py
=============
Hourly news aggregator using the Alpha Vantage News & Sentiment API.
Fetches macro/markets headlines, deduplicates against stored articles,
scores by recency + sentiment strength, and writes the top 50 to
news_data.json for the dashboard frontend.

Schedule: hourly, 8 AM – 6 PM ET weekdays (see update_news.yml)

Add/remove topics in TOPICS below. Valid AV topic values:
  financial_markets, economy_fiscal, economy_monetary, economy_macro,
  energy_transportation, earnings, technology, real_estate, manufacturing
"""

import os
import json
import logging
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

API_KEY   = os.environ["AV_API_KEY"]
DATA_FILE = Path("news_data.json")
BASE_URL  = "https://www.alphavantage.co/query"

# Topics to monitor — no ticker filtering
TOPICS = [
    "financial_markets",
    "economy_monetary",
    "economy_fiscal",
    "economy_macro",
    "energy_transportation",
]

# Rolling window: drop articles older than this from the stored set.
# AV free tier has a ~24-48h publication delay, so use 72h to ensure
# fresh fetches always survive the window and appear in the dashboard.
WINDOW_HOURS = 72

# Max articles to store / display
MAX_ARTICLES = 50

# Scoring weights: recency vs. sentiment strength
W_RECENCY   = 0.55
W_SENTIMENT = 0.45

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch_articles() -> list[dict]:
    """Fetch latest 50 articles from Alpha Vantage for configured topics."""
    params = {
        "function": "NEWS_SENTIMENT",
        "topics":   ",".join(TOPICS),
        "sort":     "LATEST",
        "limit":    "50",
        "apikey":   API_KEY,
    }
    try:
        resp = requests.get(BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
        j = resp.json()
    except Exception as e:
        log.error("Request failed: %s", e)
        return []

    feed = j.get("feed")
    if not feed:
        msg = j.get("Note") or j.get("Information") or j.get("Error Message") or str(j)
        log.warning("No feed in response: %s", msg[:300])
        return []

    articles = []
    for item in feed:
        try:
            # Parse published timestamp: "20240522T143000" → ISO
            raw_ts = item.get("time_published", "")
            published = datetime.strptime(raw_ts, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)

            # Primary topic: highest-relevance topic in our TOPICS list
            topic_scores = {t["topic"]: float(t.get("relevance_score", 0))
                            for t in item.get("topics", [])}
            primary_topic = max(topic_scores, key=topic_scores.get) if topic_scores else "General"

            articles.append({
                "url":             item.get("url", ""),
                "title":           item.get("title", ""),
                "source":          item.get("source", ""),
                "summary":         item.get("summary", ""),
                "published":       published.isoformat(),
                "sentiment_score": float(item.get("overall_sentiment_score", 0)),
                "sentiment_label": item.get("overall_sentiment_label", "Neutral"),
                "primary_topic":   primary_topic,
                "topics":          list(topic_scores.keys()),
            })
        except Exception as e:
            log.debug("Skipping malformed article: %s", e)
            continue

    log.info("Fetched %d articles from Alpha Vantage", len(articles))
    return articles

# ── Scoring ───────────────────────────────────────────────────────────────────

def score(article: dict, now: datetime) -> float:
    """
    Score = weighted sum of recency and sentiment strength.
    Recency decays linearly over WINDOW_HOURS.
    Sentiment strength is the absolute sentiment score (strong opinions
    in either direction are more newsworthy than neutral coverage).
    """
    try:
        published = datetime.fromisoformat(article["published"])
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        age_hours = (now - published).total_seconds() / 3600
        recency   = max(0.0, 1.0 - age_hours / WINDOW_HOURS)
    except Exception:
        recency = 0.0

    sentiment_strength = min(abs(article.get("sentiment_score", 0)), 1.0)
    return W_RECENCY * recency + W_SENTIMENT * sentiment_strength

# ── Merge & prune ─────────────────────────────────────────────────────────────

def merge(existing: list[dict], fresh: list[dict], now: datetime) -> list[dict]:
    """
    Merge fresh articles into existing, deduplicate by URL,
    drop articles outside the rolling window, re-rank by score.
    """
    cutoff = (now - timedelta(hours=WINDOW_HOURS)).isoformat()

    # Index existing by URL
    by_url = {a["url"]: a for a in existing if a.get("published", "") >= cutoff}

    # Add all fresh articles regardless of age — recency score handles ranking.
    # This is necessary because AV free tier delays publication by 24-48h,
    # meaning fresh fetches would otherwise all fail the cutoff filter.
    for a in fresh:
        if a.get("url"):
            by_url[a["url"]] = a

    # Score and sort
    ranked = sorted(by_url.values(), key=lambda a: score(a, now), reverse=True)
    return ranked[:MAX_ARTICLES]

# ── Persistence ───────────────────────────────────────────────────────────────

def load_existing() -> dict:
    if DATA_FILE.exists():
        try:
            with DATA_FILE.open() as f:
                return json.load(f)
        except Exception as e:
            log.warning("Could not load %s: %s — starting fresh", DATA_FILE, e)
    return {"updated_at": None, "articles": []}


def save(data: dict) -> None:
    tmp = DATA_FILE.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, separators=(",", ":"))
    tmp.replace(DATA_FILE)
    kb = DATA_FILE.stat().st_size / 1024
    log.info("Saved %s (%.1f KB, %d articles)", DATA_FILE, kb, len(data["articles"]))

# ── Main ──────────────────────────────────────────────────────────────────────

def run() -> None:
    now      = datetime.now(timezone.utc)
    existing = load_existing()

    fresh    = fetch_articles()
    merged   = merge(existing.get("articles", []), fresh, now)

    log.info("Total after merge/prune: %d articles (window=%dh, max=%d)",
             len(merged), WINDOW_HOURS, MAX_ARTICLES)

    save({
        "updated_at": now.isoformat(),
        "articles":   merged,
    })

    if merged:
        log.info("Top story: %s [%s]", merged[0]["title"][:80], merged[0]["sentiment_label"])


if __name__ == "__main__":
    run()
