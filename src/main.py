"""Steam Localization Gap Finder.

Finds Steam games whose players in one language community (Japanese, Chinese,
Korean, German, ...) are noticeably unhappier than the global player base, and
surfaces the evidence: negative-review gap, translation complaints quoted from
reviews, untranslated store pages, and the developer's public contact.

Data source: Steam's public store endpoints documented by Valve
(store.steampowered.com/appreviews, /api/appdetails, /search/results).
"""

from __future__ import annotations

import asyncio
import html
import re
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from apify import Actor

STORE = "https://store.steampowered.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SteamLocalizationGapFinder/1.0; +https://apify.com)",
    "Accept-Language": "en-US,en;q=0.9",
}

# Steam language codes (as used by ?language= and ?l=) -> complaint keywords.
COMPLAINT_KW: dict[str, list[str]] = {
    "japanese": ["翻訳", "日本語", "機械翻訳", "誤訳", "ローカライズ", "文字化け", "直訳", "意味不明", "英語のまま", "ローカライゼーション"],
    "schinese": ["翻译", "汉化", "机翻", "中文", "简体", "本地化", "乱码", "没有中文", "文本"],
    "tchinese": ["翻譯", "中文", "機翻", "繁體", "在地化", "亂碼", "沒有中文", "文本"],
    "koreana": ["번역", "한국어", "한글", "기계번역", "현지화", "오역", "깨짐", "한국어 미지원"],
    "german": ["übersetzung", "deutsch", "lokalisierung", "übersetzt", "maschinell", "google übersetzer"],
    "french": ["traduction", "français", "localisation", "traduit", "google trad", "francais"],
    "spanish": ["traducción", "traduccion", "español", "espanol", "localización", "traducido", "castellano"],
    "latam": ["traducción", "traduccion", "español", "espanol", "localización", "traducido", "latino"],
    "brazilian": ["tradução", "traducao", "português", "portugues", "localização", "traduzido", "pt-br"],
    "portuguese": ["tradução", "traducao", "português", "portugues", "localização", "traduzido"],
    "russian": ["перевод", "русск", "локализац", "машинн", "промт", "нет русского"],
    "polish": ["tłumaczenie", "tlumaczenie", "polski", "lokalizacj", "przetłumacz", "spolszczenie"],
    "italian": ["traduzione", "italiano", "localizzazione", "tradotto"],
    "turkish": ["çeviri", "ceviri", "türkçe", "turkce", "yerelleştirme", "yerellestirme"],
    "thai": ["แปล", "ภาษาไทย", "ไทย"],
    "vietnamese": ["dịch", "tiếng việt", "việt hóa", "viet hoa"],
    "ukrainian": ["переклад", "українськ", "локалізац"],
    "czech": ["překlad", "preklad", "čeština", "cestina", "lokalizace"],
    "hungarian": ["fordítás", "forditas", "magyar", "lokalizáció"],
    "dutch": ["vertaling", "nederlands", "lokalisatie"],
    "swedish": ["översättning", "svenska", "lokalisering"],
    "danish": ["oversættelse", "dansk", "lokalisering"],
    "finnish": ["käännös", "suomi", "lokalisointi"],
    "norwegian": ["oversettelse", "norsk", "lokalisering"],
    "romanian": ["traducere", "română", "romana", "localizare"],
    "greek": ["μετάφραση", "ελληνικά"],
    "bulgarian": ["превод", "български"],
    "indonesian": ["terjemahan", "bahasa indonesia", "lokalisasi"],
    "arabic": ["ترجمة", "العربية", "تعريب"],
}

# Search endpoint uses a different "supportedlang" vocabulary for a few languages.
SEARCH_LANG = {"schinese": "schinese", "tchinese": "tchinese", "koreana": "koreana", "latam": "latam"}


def parse_release(s: str) -> date | None:
    s = s.strip()
    for f in ("%d %b, %Y", "%b %d, %Y", "%b %Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


class Steam:
    def __init__(self, client: httpx.AsyncClient, delay: float):
        self.c = client
        self.delay = delay
        self.lock = asyncio.Lock()
        self.requests = 0

    async def get(self, url: str, **params: Any) -> httpx.Response | None:
        for attempt in range(4):
            async with self.lock:
                self.requests += 1
                await asyncio.sleep(self.delay)
            try:
                r = await self.c.get(url, params=params, headers=HEADERS, timeout=30)
            except httpx.HTTPError as e:
                Actor.log.debug(f"retry {url}: {e}")
                await asyncio.sleep(3)
                continue
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                await asyncio.sleep(10 * (attempt + 1))
                continue
            return None
        return None

    async def search(self, lang: str, tags: list[str], months: int, min_rev: int, max_rev: int, max_games: int) -> list[dict]:
        cutoff = date.today() - timedelta(days=30 * months)
        found: dict[str, dict] = {}
        start = 0
        while True:
            params: dict[str, Any] = {
                "query": "", "start": start, "count": 100, "infinite": 1,
                "supportedlang": SEARCH_LANG.get(lang, lang), "sort_by": "Released_DESC", "l": "english",
            }
            if tags:
                params["tags"] = ",".join(tags)
            r = await self.get(f"{STORE}/search/results/", **params)
            if not r:
                break
            h = r.json().get("results_html", "")
            blocks = re.split(r'(?=<a href="[^"]*?/app/\d+/)', h)
            n, stop = 0, False
            for b in blocks:
                m = re.search(r"/app/(\d+)/", b)
                if not m:
                    continue
                n += 1
                appid = m.group(1)
                title = re.search(r'<span class="title">(.*?)</span>', b)
                rel = re.search(r"search_released[^>]*>(.*?)</div>", b, re.S)
                tip = re.search(r'data-tooltip-html="([^"]*)"', b)
                d = parse_release(html.unescape(rel.group(1))) if rel else None
                if d and d < cutoff:
                    stop = True
                cnt = 0
                if tip:
                    mm = re.search(r"of the ([\d,]+) user reviews", html.unescape(tip.group(1)))
                    if mm:
                        cnt = int(mm.group(1).replace(",", ""))
                if min_rev <= cnt <= max_rev:
                    found[appid] = {
                        "appId": int(appid),
                        "title": html.unescape(title.group(1)) if title else "",
                        "released": d.isoformat() if d else None,
                        "totalReviews": cnt,
                    }
            Actor.log.info(f"search offset={start} listed={n} candidates={len(found)}")
            if stop or n == 0 or start >= 20000 or len(found) >= max_games * 3:
                break
            start += 100
        return sorted(found.values(), key=lambda x: -x["totalReviews"])[:max_games]

    async def reviews(self, appid: int, lang: str, pages: int) -> dict | None:
        out: dict[str, Any] = {"summary": None, "reviews": []}
        cursor = "*"
        for _ in range(pages):
            r = await self.get(
                f"{STORE}/appreviews/{appid}", json=1, language=lang, filter="recent",
                num_per_page=100, purchase_type="all", review_type="all", cursor=cursor,
            )
            if not r:
                break
            j = r.json()
            if out["summary"] is None:
                out["summary"] = j.get("query_summary", {})
            revs = j.get("reviews", [])
            out["reviews"].extend(revs)
            cursor = j.get("cursor")
            if not revs or not cursor or len(revs) < 100:
                break
        return out if out["summary"] is not None else None

    async def details(self, appid: int, lang: str) -> dict | None:
        r = await self.get(f"{STORE}/api/appdetails", appids=appid, l=lang)
        if not r:
            return None
        try:
            return r.json()[str(appid)]["data"]
        except (KeyError, TypeError, ValueError):
            return None


def analyse(cand: dict, lang: str, kws: list[str], target: dict, world: dict, det_en: dict | None, det_t: dict | None, max_quotes: int) -> dict:
    ts, ws = target["summary"], world["summary"]
    t_tot = ts.get("total_reviews", 0) or 0
    t_neg = ts.get("total_negative", 0) or 0
    w_tot = ws.get("total_reviews", 0) or 0
    w_neg = ws.get("total_negative", 0) or 0
    t_rate = round(t_neg / t_tot, 3) if t_tot else None
    w_rate = round(w_neg / w_tot, 3) if w_tot else None

    hits = hits_neg = 0
    quotes: list[dict] = []
    kws_l = [k.lower() for k in kws]
    for rv in target["reviews"]:
        text = rv.get("review", "") or ""
        low = text.lower()
        matched = next((k for k in kws_l if k in low), None)
        if not matched:
            continue
        hits += 1
        negative = not rv.get("voted_up", True)
        if negative:
            hits_neg += 1
        if len(quotes) < max_quotes:
            i = low.find(matched)
            quotes.append({
                "excerpt": text[max(0, i - 60): i + 90].replace("\n", " ").strip(),
                "votedUp": not negative,
                "playtimeHours": round((rv.get("author", {}).get("playtime_forever", 0) or 0) / 60, 1),
                "recommendationId": rv.get("recommendationid"),
            })

    short_en = (det_en or {}).get("short_description", "") or ""
    short_t = (det_t or {}).get("short_description", "") or ""
    store_untranslated = bool(short_en) and short_en == short_t
    supported = bool(re.search(re.escape(LANG_LABEL.get(lang, lang)), (det_en or {}).get("supported_languages", "") or "", re.I))

    gap = (t_rate or 0) - (w_rate or 0)
    enough = t_tot >= 5
    score = round(
        (gap * 100 if enough else 0)
        + hits_neg * 20
        + (hits - hits_neg) * 2
        + (15 if store_untranslated else 0)
        + min(t_tot, 50) * 0.2,
        1,
    )
    si = (det_en or {}).get("support_info") or {}
    return {
        **cand,
        "url": f"{STORE}/app/{cand['appId']}/",
        "language": lang,
        "languageReviews": t_tot,
        "languageNegativeRate": t_rate,
        "globalReviews": w_tot,
        "globalNegativeRate": w_rate,
        "negativeGapPoints": round(gap * 100, 1) if enough and w_rate is not None else None,
        "complaintHits": hits,
        "complaintHitsNegative": hits_neg,
        "complaintQuotes": quotes,
        "storePageUntranslated": store_untranslated,
        "languageListedAsSupported": supported,
        "opportunityScore": score,
        "developer": ", ".join((det_en or {}).get("developers", []) or []),
        "publisher": ", ".join((det_en or {}).get("publishers", []) or []),
        "website": (det_en or {}).get("website") or "",
        "supportEmail": si.get("email", "") or "",
        "supportUrl": si.get("url", "") or "",
        "genres": [g.get("description") for g in (det_en or {}).get("genres", []) or []],
        "isFree": bool((det_en or {}).get("is_free")),
        "priceUsd": ((det_en or {}).get("price_overview") or {}).get("final_formatted", ""),
    }


LANG_LABEL = {
    "japanese": "Japanese", "schinese": "Simplified Chinese", "tchinese": "Traditional Chinese", "koreana": "Korean",
    "german": "German", "french": "French", "spanish": "Spanish - Spain", "latam": "Spanish - Latin America",
    "brazilian": "Portuguese - Brazil", "portuguese": "Portuguese - Portugal", "russian": "Russian", "polish": "Polish",
    "italian": "Italian", "turkish": "Turkish", "thai": "Thai", "vietnamese": "Vietnamese", "ukrainian": "Ukrainian",
    "czech": "Czech", "hungarian": "Hungarian", "dutch": "Dutch", "swedish": "Swedish", "danish": "Danish",
    "finnish": "Finnish", "norwegian": "Norwegian", "romanian": "Romanian", "greek": "Greek", "bulgarian": "Bulgarian",
    "indonesian": "Indonesian", "arabic": "Arabic",
}


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}
        lang: str = (inp.get("language") or "japanese").strip().lower()
        app_ids: list[int] = [int(a) for a in (inp.get("appIds") or []) if str(a).strip().isdigit()]
        tags: list[str] = [str(t).strip() for t in (inp.get("steamTagIds") or ["492"]) if str(t).strip()]
        months = int(inp.get("releasedWithinMonths") or 18)
        min_rev = int(inp.get("minReviews") or 30)
        max_rev = int(inp.get("maxReviews") or 4000)
        max_games = int(inp.get("maxGames") or 50)
        pages = max(1, min(int(inp.get("reviewPagesPerGame") or 1), 5))
        max_quotes = int(inp.get("maxQuotes") or 3)
        min_score = float(inp.get("minOpportunityScore") or 0)
        extra_kw = [str(k).strip() for k in (inp.get("extraKeywords") or []) if str(k).strip()]
        delay = float(inp.get("requestDelaySeconds") or 0.35)
        concurrency = max(1, min(int(inp.get("concurrency") or 2), 5))

        if lang not in COMPLAINT_KW:
            Actor.log.warning(f"No built-in complaint keywords for '{lang}'. Only extraKeywords will be used.")
        kws = COMPLAINT_KW.get(lang, []) + extra_kw

        await Actor.charge(event_name="actor-start")

        async with httpx.AsyncClient(http2=False) as client:
            steam = Steam(client, delay)
            if app_ids:
                cands = [{"appId": a, "title": "", "released": None, "totalReviews": None} for a in app_ids[:max_games]]
            else:
                cands = await steam.search(lang, tags, months, min_rev, max_rev, max_games)
            Actor.log.info(f"{len(cands)} games to analyse for language={lang}")

            sem = asyncio.Semaphore(concurrency)
            pushed = skipped = 0

            async def work(cand: dict) -> None:
                nonlocal pushed, skipped
                async with sem:
                    cm = Actor.get_charging_manager()
                    if cm.is_event_charge_limit_reached("game-analyzed"):
                        Actor.log.warning("Charge limit reached, stopping early.")
                        return
                    a = cand["appId"]
                    target = await steam.reviews(a, lang, pages)
                    world = await steam.reviews(a, "all", 1)
                    if not target or not world:
                        skipped += 1
                        return
                    det_en = await steam.details(a, "english")
                    det_t = await steam.details(a, lang)
                    if det_en and not cand.get("title"):
                        cand["title"] = det_en.get("name", "")
                        rd = det_en.get("release_date") or {}
                        d = parse_release(rd.get("date", "") or "")
                        cand["released"] = d.isoformat() if d else None
                        cand["totalReviews"] = (world["summary"] or {}).get("total_reviews")
                    row = analyse(cand, lang, kws, target, world, det_en, det_t, max_quotes)
                    if row["opportunityScore"] < min_score:
                        skipped += 1
                        return
                    await Actor.push_data(row, charged_event_name="game-analyzed")
                    pushed += 1

            await asyncio.gather(*(work(c) for c in cands))

        report = {
            "language": lang,
            "candidates": len(cands),
            "analysed": pushed,
            "skipped": skipped,
            "steamRequests": steam.requests,
            "finishedAt": datetime.utcnow().isoformat() + "Z",
        }
        await Actor.set_value("RUN_REPORT", report)
        Actor.log.info(f"Done: {report}")
