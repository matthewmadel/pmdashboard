#!/usr/bin/env python3
"""
scrape_news.py — Fetch, score, and write news-data.json
Sections: markets | ai | endowment (staff & board changes)

Run daily via GitHub Actions, or manually:
    pip install requests feedparser
    python scrape_news.py
"""

import json, re, math, time, hashlib, os, sys
from datetime import datetime, timezone

try:
    import requests
    import feedparser
except ImportError:
    sys.exit("Run: pip install requests feedparser")

HEADERS = {
    'User-Agent': 'PM-Dashboard/2.0 matthewmadel@gmail.com',
    'Accept-Encoding': 'gzip, deflate',
}

# ── Source tier registry ───────────────────────────────────────────────────────
SOURCE_TIERS = {
    'pensions & investments': (1, 'Pensions & Investments'),
    'pionline':               (1, 'Pensions & Investments'),
    'institutional investor': (1, 'Institutional Investor'),
    'wall street journal':    (1, 'WSJ'),
    'wsj.com':                (1, 'WSJ'),
    'financial times':        (1, 'Financial Times'),
    'ft.com':                 (1, 'Financial Times'),
    'bloomberg':              (1, 'Bloomberg'),
    'ai-cio':                 (1, 'AI-CIO Magazine'),
    'chief investment officer magazine': (1, 'AI-CIO Magazine'),
    'nacubo':                 (1, 'NACUBO'),
    'reuters':                (2, 'Reuters'),
    'ap news':                (2, 'AP'),
    'associated press':       (2, 'AP'),
    'marketwatch':            (2, 'MarketWatch'),
    'cnbc':                   (2, 'CNBC'),
    'techcrunch':             (2, 'TechCrunch'),
    'mit technology review':  (2, 'MIT Tech Review'),
    'the verge':              (2, 'The Verge'),
    'ars technica':           (2, 'Ars Technica'),
    'venturebeat':            (2, 'VentureBeat'),
    'wired':                  (2, 'Wired'),
    'fortune':                (2, 'Fortune'),
    'business insider':       (2, 'Business Insider'),
    'yahoo finance':          (3, 'Yahoo Finance'),
    'seeking alpha':          (3, 'Seeking Alpha'),
    'google news':            (3, 'Google News'),
}

def get_source_info(raw):
    s = (raw or '').lower()
    for key, (tier, display) in SOURCE_TIERS.items():
        if key in s:
            return tier, display
    return 3, (raw or 'Unknown')[:40]


# ── Keyword detection ──────────────────────────────────────────────────────────
_DEP  = ['resign', 'step down', 'depart', 'leav', 'retir', 'exit', 'successor', 'replac', 'fired', 'ousted']
_HIRE = ['appoint', 'named', 'hire', 'join', 'welcom', 'elect', 'select', 'promot', 'tapped']

_PATTERNS = [
    (['chief investment officer', ' cio ', ',cio', 'cio,'], 'CIO'),
    (['chief financial officer',  ' cfo ', ',cfo', 'cfo,'], 'CFO'),
    (['chief operating officer',  ' coo '],                  'COO'),
    (['controller', 'comptroller', 'treasurer'],             'controller'),
    (['board chair', 'chairman', 'chairwoman', 'chair of the board'], 'board_chair'),
    (['board of trustees', 'trustee', 'board member',
      'board of directors', 'board of regents'],             'board_member'),
    (['vice president of finance', 'vp finance',
      'president and cfo', 'svp finance'],                   'VP_finance'),
]

def detect_change(title, summary):
    text = (' ' + title + ' ' + (summary or '') + ' ').lower()
    is_dep  = any(w in text for w in _DEP)
    is_hire = any(w in text for w in _HIRE)
    action  = 'departure' if is_dep else ('hire' if is_hire else 'change')
    for patterns, role in _PATTERNS:
        if any(p in text for p in patterns):
            return f'{role}_{action}'
    return 'general_endowment'

def extract_person(title, summary):
    """Heuristic: first two consecutive title-case words not in a stop list."""
    STOP = {'The','New','Chief','Former','Vice','Board','Senior','University',
            'College','Fund','Investment','Capital','Asset','Financial'}
    m = re.search(r'\b([A-Z][a-z]+) ([A-Z][a-z]+)\b', title + ' ' + (summary or ''))
    if m and m.group(1) not in STOP and m.group(2) not in STOP:
        return f'{m.group(1)} {m.group(2)}'
    return None


# ── Scoring ────────────────────────────────────────────────────────────────────
def recency_score(ts):
    if not ts:
        return 0
    hours = (datetime.now(timezone.utc).timestamp() - ts) / 3600
    return 100 * math.exp(-0.015 * hours)

def aum_score(aum_m):
    if not aum_m or aum_m <= 0:
        return 30
    return min(100, math.log10(max(aum_m, 1)) / math.log10(50000) * 100)

_CT_WEIGHT = {
    'CIO_departure':100,'CIO_hire':100,'CIO_change':85,
    'CFO_departure':85, 'CFO_hire':85, 'CFO_change':70,
    'board_chair_departure':75,'board_chair_hire':75,'board_chair_change':75,
    'COO_departure':65, 'COO_hire':65, 'COO_change':55,
    'controller_departure':60,'controller_hire':60,'controller_change':50,
    'VP_finance_departure':60,'VP_finance_hire':60,
    'board_member_departure':50,'board_member_hire':45,'board_member_change':40,
    'general_endowment':15,
}

def score(article, section, aum=None):
    r = recency_score(article.get('published_ts'))
    tier, _ = get_source_info(article.get('source',''))
    s = {1:100, 2:70, 3:40}.get(tier, 40)
    if section == 'endowment':
        a  = aum_score(aum)
        ct = _CT_WEIGHT.get(article.get('change_type','general_endowment'), 15)
        sp = (10 if article.get('person_name') else 0) + \
             (10 if article.get('change_type','').endswith(('_hire','_departure')) else 0)
        return round(r*0.30 + s*0.20 + a*0.20 + ct*0.20 + sp*0.10, 1)
    else:
        return round(r*0.60 + s*0.40, 1)


# ── Deduplication ─────────────────────────────────────────────────────────────
def article_id(url):
    return hashlib.sha1((url or '').encode()).hexdigest()[:12]

def norm_title(t):
    t = re.sub(r'[^a-z0-9 ]', '', t.lower())
    return ' '.join(t.split())[:80]


# ── RSS parsing ────────────────────────────────────────────────────────────────
def parse_ts(entry):
    for key in ('published_parsed', 'updated_parsed'):
        t = entry.get(key)
        if t:
            try:
                return int(time.mktime(t))
            except Exception:
                pass
    return int(datetime.now(timezone.utc).timestamp())

def fetch_rss(url, max_items=40):
    try:
        feed = feedparser.parse(url, request_headers=HEADERS)
        items = []
        for entry in feed.entries[:max_items]:
            title = (entry.get('title') or '').strip()
            if not title:
                continue
            raw_sum = entry.get('summary') or entry.get('description') or ''
            summary = re.sub(r'<[^>]+>', '', raw_sum).strip()
            link    = entry.get('link') or ''
            # Google News per-entry source overrides feed title
            src_raw = (entry.get('source') or {}).get('title') \
                   or feed.feed.get('title') or ''
            items.append({
                'id':           article_id(link),
                'title':        title,
                'summary':      summary[:500],
                'url':          link,
                '_src_raw':     src_raw,
                'published_ts': parse_ts(entry),
            })
        return items
    except Exception as e:
        print(f'  RSS error {url[:60]}: {e}')
        return []


# ── Institution matcher ────────────────────────────────────────────────────────
def load_endowments():
    path = os.path.join(os.path.dirname(__file__), 'endowments.json')
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []

def find_institution(title, summary, endowments):
    text = (title + ' ' + (summary or '')).lower()
    best_name, best_aum = None, 0
    for e in endowments:
        name  = e['name'].lower()
        short = re.sub(r'\b(university|college|institute|system|foundation)\b', '', name).strip()
        if name in text:
            return e['name'], e.get('aum', 0)          # exact match wins immediately
        if len(short) > 4 and short in text:
            if e.get('aum', 0) > best_aum:
                best_name, best_aum = e['name'], e.get('aum', 0)
    return best_name, best_aum


# ── Snapshot diff (leadership pages) ──────────────────────────────────────────
def check_snapshot(institution, url):
    """Returns True if the page has changed since the last run."""
    slug = re.sub(r'[^a-z0-9]', '_', institution.lower())[:40]
    snap_dir  = os.path.join(os.path.dirname(__file__), 'snapshots')
    snap_path = os.path.join(snap_dir, f'{slug}.json')
    os.makedirs(snap_dir, exist_ok=True)
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        # Strip scripts/styles, collapse whitespace
        text = re.sub(r'<(script|style)[^>]*>.*?</(script|style)>', '', r.text, flags=re.S|re.I)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = ' '.join(text.split())[:6000]
        h = hashlib.md5(text[:3000].encode()).hexdigest()

        prev_h = None
        if os.path.exists(snap_path):
            with open(snap_path) as f:
                prev_h = json.load(f).get('hash')

        with open(snap_path, 'w') as f:
            json.dump({'hash': h, 'text': text[:3000],
                       'url': url,
                       'checked': datetime.now(timezone.utc).isoformat()}, f)

        return (prev_h is not None and prev_h != h)
    except Exception as e:
        print(f'  Snapshot error {institution}: {e}')
        return False


# ── Feed lists ────────────────────────────────────────────────────────────────
GN = 'https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q='

MARKETS_FEEDS = [
    'https://feeds.reuters.com/reuters/businessNews',
    'https://feeds.content.dowjones.io/public/rss/mw_topstories',
    'https://feeds.a.dj.com/rss/RSSMarketsMain.xml',
    'https://finance.yahoo.com/news/rssindex',
    GN + 'federal+reserve+interest+rates+inflation+economy',
    GN + 'S%26P+500+stocks+earnings+market+rally',
    GN + 'bonds+yields+treasury+credit+markets',
    GN + 'hedge+fund+private+equity+institutional+investor',
]

AI_FEEDS = [
    'https://techcrunch.com/category/artificial-intelligence/feed/',
    'https://www.technologyreview.com/feed/',
    'https://www.theverge.com/rss/ai-artificial-intelligence/index.xml',
    'https://feeds.arstechnica.com/arstechnica/technology-lab',
    'https://venturebeat.com/category/ai/feed/',
    GN + 'artificial+intelligence+OpenAI+Anthropic+ChatGPT+LLM',
    GN + 'AI+model+funding+regulation+machine+learning+2026',
    GN + 'large+language+model+agent+AI+safety+benchmark',
]

ENDOWMENT_FEEDS = [
    'https://www.pionline.com/rss/all-news',
    'https://www.ai-cio.com/feed/',
    GN + '%22chief+investment+officer%22+endowment+%22appointed%22+OR+%22named%22+OR+%22resigns%22',
    GN + '%22chief+financial+officer%22+university+%22appointed%22+OR+%22hired%22+OR+%22resigns%22',
    GN + '%22board+of+trustees%22+university+endowment+%22appointed%22+OR+%22elected%22',
    GN + 'university+endowment+CIO+CFO+%22steps+down%22+OR+%22named%22+OR+%22joins%22',
    GN + '%22investment+office%22+university+college+endowment+hire+OR+appoint+OR+depart',
    GN + 'endowment+%22chief+investment%22+OR+%22investment+committee%22+board+trustee',
]

# Top endowments to snapshot (leadership URLs from endowments.json)
def get_snapshot_targets(endowments):
    return [(e['name'], e['leadership_url'])
            for e in endowments
            if e.get('leadership_url')]


# ── Endowment keyword filter ───────────────────────────────────────────────────
_ENDO_KW = ['endowment','university','college','foundation','cio','cfo',
            'trustee','chief investment','chief financial','investment office',
            'board of trustees','board of regents']

def is_endowment_relevant(title, summary):
    text = (title + ' ' + summary).lower()
    return any(w in text for w in _ENDO_KW)


# ── Main ──────────────────────────────────────────────────────────────────────
MAX_PER = 100
PAUSE   = 0.4

def main():
    endowments = load_endowments()
    print(f'Loaded {len(endowments)} endowments')

    output = {
        'meta': {'generated': datetime.now(timezone.utc).isoformat()},
        'markets':   [],
        'ai':        [],
        'endowment': [],
    }

    # ── Markets ────────────────────────────────────────────────────────────────
    print('\n─── Markets feeds ───')
    seen = {}
    for url in MARKETS_FEEDS:
        print(f'  {url[:70]}')
        for item in fetch_rss(url):
            nt = norm_title(item['title'])
            if nt in seen:
                continue
            seen[nt] = True
            tier, display = get_source_info(item['_src_raw'])
            item['source']      = display
            item['source_tier'] = tier
            item['score']       = score(item, 'markets')
            del item['_src_raw']
            output['markets'].append(item)
        time.sleep(PAUSE)

    output['markets'].sort(key=lambda a: a['score'], reverse=True)
    output['markets'] = output['markets'][:MAX_PER]
    print(f'  → {len(output["markets"])} articles')

    # ── AI News ────────────────────────────────────────────────────────────────
    print('\n─── AI feeds ───')
    seen = {}
    for url in AI_FEEDS:
        print(f'  {url[:70]}')
        for item in fetch_rss(url):
            nt = norm_title(item['title'])
            if nt in seen:
                continue
            seen[nt] = True
            tier, display = get_source_info(item['_src_raw'])
            item['source']      = display
            item['source_tier'] = tier
            item['score']       = score(item, 'ai')
            del item['_src_raw']
            output['ai'].append(item)
        time.sleep(PAUSE)

    output['ai'].sort(key=lambda a: a['score'], reverse=True)
    output['ai'] = output['ai'][:MAX_PER]
    print(f'  → {len(output["ai"])} articles')

    # ── Endowment ──────────────────────────────────────────────────────────────
    print('\n─── Endowment feeds ───')
    seen = {}
    for url in ENDOWMENT_FEEDS:
        print(f'  {url[:70]}')
        for item in fetch_rss(url):
            nt = norm_title(item['title'])
            if nt in seen:
                continue
            if not is_endowment_relevant(item['title'], item.get('summary','')):
                continue
            seen[nt] = True
            tier, display    = get_source_info(item['_src_raw'])
            inst_name, inst_aum = find_institution(item['title'], item.get('summary',''), endowments)
            ct               = detect_change(item['title'], item.get('summary',''))
            person           = extract_person(item['title'], item.get('summary',''))
            item['source']      = display
            item['source_tier'] = tier
            if inst_name:
                item['institution']     = inst_name
                item['institution_aum'] = inst_aum
            item['change_type'] = ct
            if person:
                item['person_name'] = person
            item['score'] = score(item, 'endowment', inst_aum)
            del item['_src_raw']
            output['endowment'].append(item)
        time.sleep(PAUSE)

    # ── Leadership page snapshots ──────────────────────────────────────────────
    print('\n─── Leadership page snapshots ───')
    now_ts = int(datetime.now(timezone.utc).timestamp())
    for inst, url in get_snapshot_targets(endowments):
        print(f'  {inst}...')
        changed = check_snapshot(inst, url)
        if changed:
            print(f'  *** CHANGED: {inst}')
            aum = next((e.get('aum',0) for e in endowments
                        if e['name'] == inst), 0)
            output['endowment'].insert(0, {
                'id':           article_id(url + str(now_ts // 86400)),
                'title':        f'Leadership page updated: {inst}',
                'summary':      (f'The leadership/board page for {inst} changed since the last '
                                 f'daily check. Visit the page to review staff or board updates.'),
                'url':          url,
                'source':       'Direct Page Monitor',
                'source_tier':  2,
                'published_ts': now_ts,
                'institution':  inst,
                'institution_aum': aum,
                'change_type':  'general_endowment',
                'score':        70.0,
            })
        time.sleep(1.0)

    output['endowment'].sort(key=lambda a: a['score'], reverse=True)
    output['endowment'] = output['endowment'][:MAX_PER]
    print(f'  → {len(output["endowment"])} articles')

    out_path = os.path.join(os.path.dirname(__file__), 'news-data.json')
    with open(out_path, 'w') as f:
        json.dump(output, f, separators=(',', ':'))

    print(f'\n✓ Wrote {out_path}')
    print(f'  Markets:   {len(output["markets"])}')
    print(f'  AI:        {len(output["ai"])}')
    print(f'  Endowment: {len(output["endowment"])}')


if __name__ == '__main__':
    main()
