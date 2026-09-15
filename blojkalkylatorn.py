#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Blöjkalkylatorn
===============

Hämtar aktuella priser på blöjor (Libero, Pampers m.fl.) från svenska butiker
och visar butikernas riktiga aktuella kampanjer, för att hitta billigaste
priset per blöja.

Du kan även mata in egna kuponger (via --kuponger) med sina villkor – källa,
märke/storlek, giltighet, minsta köp, medlemskrav, engångs/flergångs och var de
gäller – så filtrerar programmet rätt produkter, räknar ut priset och visar
villkoren tydligt så att du kan verifiera dem.

Butiker som stöds just nu:
  * Willys  – ren JSON (jämförpris = kr/blöja direkt)
  * Hemköp  – samma JSON-API som Willys (samma koncern, Axfood)
  * Apotea  – parsar serverrenderad HTML (kr/blöja från antal i namnet)
  * Coop    – personaliserings-API (ger pris, antal och jämförpris direkt)
  * Apoteket – sök-API (ger pris, antal och kampanjpris direkt)
  * Mathem  – sök-API (ger pris, antal och jämförpris direkt)
  * City Gross – Loop54-sök-API (ger pris, antal och jämförpris direkt)
  * ICA     – parsar serverrenderad HTML (kräver val av butik, Playwright för bot-skydd)

Kör exempel:
    python3 blojkalkylatorn.py
    python3 blojkalkylatorn.py --marke Libero
    python3 blojkalkylatorn.py --sok "blöjor,libero,pampers"
    python3 blojkalkylatorn.py --butiker willys,hemkop,apotea,coop,apoteket,mathem,citygross,ica

Riktiga aktuella kampanjer (hämtas direkt från butikernas API:er) markeras med ★.

Alla belopp i svenska kronor (kr). Sorterar alltid på billigast kr/blöja.
"""

import argparse
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional, List

# --------------------------------------------------------------------------
# Gemensamma HTTP-hjälpare
# --------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
}


def http_get(url: str, timeout: int = 20) -> str:
    """Hämtar en URL och returnerar text (utf-8)."""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def parse_se_number(s: str) -> Optional[float]:
    """Tolkar svenskt talformat, t.ex. '3,66 kr' -> 3.66, '98,90' -> 98.9."""
    if not s:
        return None
    s = s.replace("kr", "").replace("\u00a0", " ").strip()
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Datamodell
# --------------------------------------------------------------------------

@dataclass
class Product:
    store: str                      # t.ex. "Willys"
    name: str                       # produktnamn
    brand: str                      # "Libero", "Pampers", "Övrigt"
    price: Optional[float]          # kr per förpackning
    count: Optional[int]            # antal blöjor per förpackning
    price_per: Optional[float]      # kr per blöja (aktuellt pris)
    jmf: Optional[str]              # officiellt jämförpris i klartext
    url: str = ""
    kampanj: str = ""               # riktig aktuell kampanj hos butiken (om någon)


@dataclass
class Coupon:
    """En riktig kupong med sina villkor, som användaren matar in för att verifiera.

    Programmet kan bara FILTRERA (märke/storlek) och RÄKNA (rabatt), medan de
    övriga villkoren (källa, giltighet, medlemskrav, minsta köp, engångs,
    plats) visas tydligt så att användaren själv kan kontrollera dem.
    """
    typ: str = "procent"            # "procent" | "fast" | "kop_betala"
    varde: float = 0.0              # procent (20) eller kr för "fast"
    kop: int = 1                    # "kop_betala": köp X ...
    betala: int = 1                 # ... betala för Y
    beskrivning: str = ""           # t.ex. "20 % på Libero Comfort strl 4"
    # Villkor att verifiera:
    kalla: str = ""                 # var kupongen kommer ifrån (t.ex. "ICA Stammis")
    marke: Optional[str] = None     # vilket märke den gäller (t.ex. "Libero")
    storlek: Optional[str] = None   # vilken storlek (matchas mot produktnamnet)
    minsta_kop: float = 0.0         # minsta köp i kr (gäller hela korgen)
    endast_medlem: bool = False     # kräver medlemskap
    giltig_till: str = ""           # t.ex. "2026-12-31"
    engangs: bool = False           # engångsrabatt
    gallplats: str = "båda"         # "online" | "butik" | "båda"

    def galler(self, p: "Product") -> bool:
        if self.marke and self.marke.lower() not in (p.brand or "").lower():
            return False
        if self.storlek and self.storlek.lower() not in (p.name or "").lower():
            return False
        return True

    def applicera(self, p: "Product") -> Optional[float]:
        if p.price_per is None:
            return None
        if self.typ == "procent":
            return p.price_per * (1 - self.varde / 100.0)
        if self.typ == "fast":
            if p.count and p.price is not None:
                return max(0.0, p.price - self.varde) / p.count
            return None
        if self.typ == "kop_betala":
            if self.kop > 0:
                return p.price_per * (self.betala / self.kop)
        return None


# --------------------------------------------------------------------------
# Klassificering (är det en blöja, vilket märke)
# --------------------------------------------------------------------------

# Viktintervall som "2-5 kg" eller "11kg-17kg" är ett starkt tecken på blöja.
_WEIGHT_RANGE = (
    r"\d+\s*kg\s*-\s*\d+\s*kg"     # 11kg-17kg
    r"|\d+\s*-\s*\d+\s*kg"         # 2-5 kg, 13-20kg
)

_NON_DIAPER_WORDS = [
    "refill", "hink", "påse", "påsar", "bag", "våtservett", "våtservetter",
    "wet wipe", "underlägg", "skötbord", "baby oil", "shampoo", "bubble bath",
    "baby wash", "talc", "kräm", "creme", "lotion", "tvätt", "sol", "solskydd",
]


def is_diaper(name: str) -> bool:
    n = html.unescape(name).lower()
    if re.search(_WEIGHT_RANGE, n):
        return True
    if re.search(r"bl[öøo]j", n) and not any(w in n for w in _NON_DIAPER_WORDS):
        return True
    return False


def guess_brand(name: str, manufacturer: Optional[str] = None) -> str:
    if manufacturer:
        m = manufacturer.lower()
        if "pampers" in m:
            return "Pampers"
        if "libero" in m:
            return "Libero"
    n = name.lower()
    if "pampers" in n:
        return "Pampers"
    if "libero" in n:
        return "Libero"
    # Libero-linjer (Willys listar dem utan "Libero" i produktnamnet)
    if any(k in n for k in ("up&go", "up & go", "comfort", "touch")):
        return "Libero"
    return "Övrigt"


# --------------------------------------------------------------------------
# Butiks-hämtare
# --------------------------------------------------------------------------

def fetch_axfood(query: str, base_url: str, store_name: str) -> List[Product]:
    """Hämtar från Axfood-koncernens butiker (Willys, Hemköp) som delar samma JSON-API."""
    url = base_url + "/search?q=" + urllib.parse.quote(query) + "&size=200"
    data = json.loads(http_get(url))
    out: List[Product] = []
    for r in data.get("results", []):
        name = r.get("name") or ""
        brand = guess_brand(name, r.get("manufacturer"))
        price = r.get("priceValue")
        if price is None:
            price = parse_se_number(r.get("price"))
        else:
            price = float(price)
        jmf = r.get("comparePrice") or ""
        per = parse_se_number(jmf)
        count = None
        if per and price:
            count = round(price / per)
        kampanj = ""
        promos = r.get("potentialPromotions") or []
        if promos:
            p0 = promos[0]
            delar = [x for x in (p0.get("textLabel"), p0.get("conditionLabel"),
                                 p0.get("rewardLabel"), p0.get("splashTitleText")) if x]
            kampanj = " · ".join(delar)
        out.append(Product(
            store=store_name,
            name=name,
            brand=brand,
            price=price,
            count=count,
            price_per=per,
            jmf=(jmf + " " + (r.get("comparePriceUnit") or "")).strip() if jmf else None,
            url=base_url + "/search?q=" + urllib.parse.quote(query),
            kampanj=kampanj,
        ))
    return out


def fetch_willys(query: str) -> List[Product]:
    return fetch_axfood(query, "https://www.willys.se", "Willys")


def fetch_hemkop(query: str) -> List[Product]:
    return fetch_axfood(query, "https://www.hemkop.se", "Hemköp")


# --------------------------------------------------------------------------
# Coop (personaliserings-API bakom Azure API Management)
# --------------------------------------------------------------------------

COOP_SEARCH_URL = "https://external.api.coop.se/personalization/search/products"
COOP_SUBSCRIPTION_KEY = "3becf0ce306f41a1ae94077c16798187"
COOP_DEFAULT_STORE = "251300"


def _normalize_brand(manufacturer: Optional[str]) -> str:
    if not manufacturer:
        return "Övrigt"
    low = manufacturer.strip().lower()
    if "libero" in low:
        return "Libero"
    if "pampers" in low:
        return "Pampers"
    return manufacturer.strip()


def fetch_coop(query: str, store_id: str = COOP_DEFAULT_STORE, take: int = 100) -> List[Product]:
    url = (COOP_SEARCH_URL + "?api-version=v1&store=" + store_id
           + "&groups=CUSTOMER_PRIVATE&device=desktop&direct=false")
    body = {
        "query": query,
        "resultsOptions": {"skip": 0, "take": take, "sortBy": [], "facets": []},
        "relatedResultsOptions": {"skip": 0, "take": 16},
        "customData": {"consent": False},
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={**HEADERS, "Content-Type": "application/json",
                 "ocp-apim-subscription-key": COOP_SUBSCRIPTION_KEY},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))

    out: List[Product] = []
    for it in data.get("results", {}).get("items", []):
        name = it.get("name") or ""
        brand = _normalize_brand(it.get("manufacturerName"))
        price = (it.get("salesPriceData") or {}).get("b2cPrice")
        per = (it.get("comparativePriceData") or {}).get("b2cPrice")
        count = it.get("packageSize")
        if count is not None:
            count = int(round(count))
        out.append(Product(
            store="Coop",
            name=name,
            brand=brand,
            price=price,
            count=count,
            price_per=per,
            jmf=it.get("comparativePriceText"),
            url="https://www.coop.se/handla/sok/?q=" + urllib.parse.quote(query),
        ))
    return out


# --------------------------------------------------------------------------
# ICA (kräver val av butik – priserna skiljer sig mellan butiker)
# --------------------------------------------------------------------------

def fetch_ica_stores() -> List[dict]:
    """Hämtar listan över ICA-butiker som går att handla i på nätet."""
    url = "https://handla.ica.se/api/store/v1?customerType=B2C"
    return json.loads(http_get(url))


def find_ica_store(term: str) -> Optional[dict]:
    """Hittar första ICA-butiken där ALLA ord i söktermen matchar namn/stad/format."""
    return _match_ica_stores(term, first_only=True)


def _match_ica_stores(term: str, first_only: bool = True):
    stores = fetch_ica_stores()
    words = [w for w in term.lower().split() if w]
    matches = []
    for s in stores:
        hay = (s.get("name", "") + " " + s.get("city", "") + " "
               + s.get("area", "") + " " + s.get("storeFormat", "")).lower()
        if all(w in hay for w in words):
            if first_only:
                return s
            matches.append(s)
    return matches if not first_only else None


_ICA_CARD_RE = re.compile(r'data-test="fop-wrapper:[^"]+"')


def _ica_parse(html_text: str, account_id: str) -> List[Product]:
    """Parsar ICA:s serverrenderade sökresultat, ett produktkort i taget."""
    positions = [m.start() for m in _ICA_CARD_RE.finditer(html_text)]
    positions.append(len(html_text))

    out: List[Product] = []
    for idx in range(len(positions) - 1):
        seg = html_text[positions[idx]:positions[idx + 1]]

        title_m = re.search(r'data-test="fop-title"[^>]*>\s*([^<]+?)\s*</h3>', seg)
        if not title_m:
            continue
        name = html.unescape(title_m.group(1).strip())

        price_m = re.search(r'data-test="fop-price">\s*([\d,]+)', seg)
        price = parse_se_number(price_m.group(1)) if price_m else None

        per_m = re.search(r'data-test="fop-price-per-unit">\s*\(?\s*([\d,]+)', seg)
        per = parse_se_number(per_m.group(1)) if per_m else None

        link_m = re.search(r'data-test="fop-product-link"[^>]*href="([^"]+)"', seg)
        link = link_m.group(1) if link_m else ""

        brand = guess_brand(name + " " + link)
        count = round(price / per) if (price and per) else None
        full_url = ("https://handlaprivatkund.ica.se" + link) if link.startswith("/") else link

        out.append(Product(
            store="ICA",
            name=name,
            brand=brand,
            price=price,
            count=count,
            price_per=per,
            jmf=(f"{per:.2f}".replace(".", ",") + " kr/st") if per else None,
            url=full_url,
        ))
    return out


def fetch_ica_http(query: str, account_id: str) -> List[Product]:
    """Hämtar ICA via vanlig HTTP (snabbt, men kan blockas av AWS WAF)."""
    url = ("https://handlaprivatkund.ica.se/stores/" + account_id + "/search?q="
           + urllib.parse.quote(query))
    text = http_get(url)
    # ICA skyddas av AWS WAF som ibland svarar med en JS-utmaning i stället för produkter.
    if "gokuProps" in text or "awsWaf" in text or "aws-waf" in text:
        raise RuntimeError("ICA blockerade begäran (AWS WAF-bot-skydd).")
    if not _ICA_CARD_RE.search(text):
        raise RuntimeError("Inga produkter hittades på ICA (bot-skydd eller tomt resultat).")
    return _ica_parse(text, account_id)


def _ica_browser_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def fetch_ica_browser(query: str, account_id: str) -> List[Product]:
    """Hämtar ICA via en riktig webbläsare (Playwright) som löser WAF-utmaningen."""
    from playwright.sync_api import sync_playwright
    url = ("https://handlaprivatkund.ica.se/stores/" + account_id + "/search?q="
           + urllib.parse.quote(query))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=HEADERS["User-Agent"], locale="sv-SE")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            # Vänta tills WAF-utmaningen lösts och produktkorten renderats.
            try:
                page.wait_for_selector('[data-test="fop-title"]', timeout=30000)
            except Exception:
                pass
            # Scrolla för att ladda fler produkter (listan är lat-laddad).
            for _ in range(12):
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(500)
            html_text = page.content()
        finally:
            browser.close()
    if not _ICA_CARD_RE.search(html_text):
        raise RuntimeError("Inga produkter hittades på ICA via webbläsaren.")
    return _ica_parse(html_text, account_id)


def fetch_ica(query: str, account_id: str, prefer_browser: bool = True) -> List[Product]:
    """Hämtar ICA. Använder webbläsare (Playwright) om möjligt, annars vanlig HTTP."""
    if prefer_browser and _ica_browser_available():
        try:
            return fetch_ica_browser(query, account_id)
        except Exception as e:
            print(f"⚠️  Webbläsare misslyckades ({e}). Faller tillbaka till HTTP.", file=sys.stderr)
    return fetch_ica_http(query, account_id)



_APOTEA_ARTICLE_RE = re.compile(r'data-article-id="(\d+)"')


def _extract_count(name: str, url: str) -> Optional[int]:
    text = (name + "  " + url).lower()
    patterns = [
        r"(\d+)\s*st\b",              # "24 st", "24st"
        r"(\d+)\s*bl[öøo]j[oa]r?\b",  # "111 blöjor"
        r"(\d+)\s*antal\b",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return int(m.group(1))
    return None


def _apotea_parse(html_text: str, query: str) -> List[Product]:
    out: List[Product] = []
    for m in _APOTEA_ARTICLE_RE.finditer(html_text):
        block = html_text[m.start(): m.start() + 4000]

        slug_m = re.search(r'data-article-url="([^"]+)"', block)
        slug = slug_m.group(1) if slug_m else ""

        name_m = re.search(r'class="name[^"]*"[^>]*>\s*<a[^>]*>([^<]+)</a>', block)
        name = html.unescape(name_m.group(1).strip()) if name_m else slug

        price_m = re.search(r'<span class="">([^<]+)</span>', block)
        price = parse_se_number(price_m.group(1)) if price_m else None

        count = _extract_count(name, slug)
        brand = guess_brand(name)
        per = (price / count) if (price and count) else None

        out.append(Product(
            store="Apotea",
            name=name,
            brand=brand,
            price=price,
            count=count,
            price_per=per,
            jmf=None,
            url="https://www.apotea.se" + slug,
        ))
    return out


def _apotea_fetch_jmf(slug: str) -> Optional[float]:
    """Hämtar officiellt jämförpris (kr/st) från Apoteas produktsida."""
    try:
        detail = http_get("https://www.apotea.se" + slug)
    except Exception:
        return None
    m = re.search(r"(\d+,\d+)\s*kr\s*/\s*(st|bl[öøo]ja)", detail, re.I)
    if m:
        return parse_se_number(m.group(1))
    return None


def fetch_apotea(query: str, max_pages: int = 3, fill_jmf: bool = False,
                 delay: float = 0.3) -> List[Product]:
    out: List[Product] = []
    for page in range(1, max_pages + 1):
        url = "https://www.apotea.se/sok?q=" + urllib.parse.quote(query)
        if page > 1:
            url += "&p=" + str(page)
        html_text = http_get(url)
        page_products = _apotea_parse(html_text, query)
        out.extend(page_products)
        if len(page_products) < 60:      # sista sidan
            break
        time.sleep(delay)

    if fill_jmf:
        prefix = "https://www.apotea.se"
        for p in out:
            if p.price_per is None and p.price is not None and p.url.startswith(prefix):
                jmf = _apotea_fetch_jmf(p.url[len(prefix):])
                if jmf and p.price:
                    p.price_per = jmf
                    p.count = round(p.price / jmf)
                time.sleep(delay)
    return out


# --------------------------------------------------------------------------
# Apoteket (sök-API bakom en 54proxy-proxy)
# --------------------------------------------------------------------------

APOTEKET_SEARCH_URL = "https://apoteket-se.54proxy.com/search"


def fetch_apoteket(query: str, take: int = 100) -> List[Product]:
    body = {
        "query": query,
        "resultsOptions": {"take": take, "skip": 0},
        "customData": {"personalize": False},
    }
    req = urllib.request.Request(
        APOTEKET_SEARCH_URL, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={**HEADERS, "Content-Type": "application/json",
                 "api-version": "V3", "lib-version": "JS:1.16.186",
                 "user-id": "blojkalkylatorn"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))

    out: List[Product] = []
    for it in data.get("results", {}).get("items", []):
        attrs = {a.get("name"): a.get("values", []) for a in it.get("attributes", [])}
        name = (attrs.get("Name") or [""])[0]
        brand = _normalize_brand((attrs.get("Brand") or [None])[0])
        price = (attrs.get("Price") or [None])[0]
        campaign = (attrs.get("CampaignPrice") or [0])[0]
        kampanj = ""
        if campaign and price is not None and campaign > 0:
            kampanj = f"Kampanj {campaign} kr (ord. {price} kr)"
            price = campaign
        pkg = (attrs.get("PackageText") or [None])[0]
        count = _extract_count(pkg or "", "") if pkg else None
        if count is None:
            count = _extract_count(name, "")
        per = (price / count) if (price is not None and count) else None
        slug = (attrs.get("ProductURL") or [""])[0]
        full_url = ("https://www.apoteket.se" + slug) if slug.startswith("/") else slug
        out.append(Product(
            store="Apoteket",
            name=name,
            brand=brand,
            price=price,
            count=count,
            price_per=per,
            jmf=None,
            url=full_url,
            kampanj=kampanj,
        ))
    return out


# --------------------------------------------------------------------------
# Mathem (öppet sök-API)
# --------------------------------------------------------------------------

MATHEM_SEARCH_URL = "https://www.mathem.se/api/v1/search/mixed/"


def fetch_mathem(query: str, max_pages: int = 2) -> List[Product]:
    out: List[Product] = []
    for page in range(1, max_pages + 1):
        url = (MATHEM_SEARCH_URL + "?q=" + urllib.parse.quote(query)
               + "&type=product&page=" + str(page))
        data = json.loads(http_get(url))
        items = data.get("items", [])
        for it in items:
            a = it.get("attributes", {})
            name = a.get("full_name") or a.get("name") or ""
            brand = _normalize_brand(a.get("brand"))
            price = parse_se_number(str(a.get("gross_price")) if a.get("gross_price") else None)
            per = parse_se_number(str(a.get("gross_unit_price")) if a.get("gross_unit_price") else None)
            count = _extract_count(a.get("name_extra") or "", "") or _extract_count(name, "")
            full_url = a.get("front_url") or a.get("absolute_url") or ""
            kampanj = ""
            discount = a.get("discount") or {}
            if discount.get("is_discounted"):
                orig = discount.get("undiscounted_gross_price")
                if orig and price is not None:
                    try:
                        if float(orig) > price:
                            kampanj = f"Kampanj {price} kr (ord. {orig} kr)"
                    except (ValueError, TypeError):
                        pass
            out.append(Product(
                store="Mathem",
                name=name,
                brand=brand,
                price=price,
                count=count,
                price_per=per,
                jmf=(f"{per:.2f}".replace(".", ",") + " kr/st") if per else None,
                url=full_url,
                kampanj=kampanj,
            ))
        if not data.get("attributes", {}).get("has_more_items"):
            break
    return out


# --------------------------------------------------------------------------
# City Gross (Loop54-sök-API)
# --------------------------------------------------------------------------

CITYGROSS_SEARCH_URL = "https://www.citygross.se/api/v1/Loop54/search"


def fetch_citygross(query: str, take: int = 60) -> List[Product]:
    url = (CITYGROSS_SEARCH_URL + "?SearchQuery=" + urllib.parse.quote(query)
           + "&skip=0&take=" + str(take))
    data = json.loads(http_get(url))
    out: List[Product] = []
    for p in data.get("searchResults", {}).get("products", []):
        name = p.get("name") or ""
        brand = _normalize_brand(p.get("brand"))
        psd = p.get("productStoreDetails") or {}
        prices = psd.get("prices") or {}
        cur = prices.get("currentPrice") or {}
        price = cur.get("price")
        per = cur.get("comparativePrice")
        # antal från "27P" (pieces) i descriptiveSize/subtitle
        count = None
        for field in (p.get("descriptiveSize"), p.get("subtitle")):
            if field:
                m = re.search(r"(\d+)\s*[Pp]\b", field)
                if m:
                    count = int(m.group(1))
                    break
        if count is None:
            count = _extract_count(p.get("subtitle") or "", "")
        slug = p.get("url") or ""
        full_url = ("https://www.citygross.se" + slug) if slug.startswith("/") else slug
        kampanj = ""
        active = prices.get("activePromotion") or {}
        if prices.get("hasPromotion") or prices.get("hasDiscount"):
            kampanj = str(active.get("name") or "Kampanj")
            pd = active.get("priceDetails") or {}
            if pd.get("price"):
                kampanj += f" ({pd.get('price')} kr)"
            if active.get("membersOnly"):
                kampanj += " [medlem]"
        out.append(Product(
            store="City Gross",
            name=name,
            brand=brand,
            price=price,
            count=count,
            price_per=per,
            jmf=(f"{per:.2f}".replace(".", ",") + " kr/st") if per else None,
            url=full_url,
            kampanj=kampanj,
        ))
    return out


# --------------------------------------------------------------------------
# Huvudlogik
# --------------------------------------------------------------------------

def format_kr(x: Optional[float]) -> str:
    if x is None:
        return "-"
    return f"{x:.2f}".replace(".", ",") + " kr"


def load_coupons(path: str) -> List[Coupon]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    coupons: List[Coupon] = []
    for item in raw.get("kuponger", []):
        coupons.append(Coupon(
            typ=item.get("typ", "procent"),
            varde=float(item.get("varde", 0)),
            kop=int(item.get("kop", 1)),
            betala=int(item.get("betala", 1)),
            beskrivning=item.get("beskrivning", ""),
            kalla=item.get("kalla", ""),
            marke=item.get("marke"),
            storlek=item.get("storlek"),
            minsta_kop=float(item.get("minsta_kop", 0)),
            endast_medlem=bool(item.get("endast_medlem", False)),
            giltig_till=item.get("giltig_till", ""),
            engangs=bool(item.get("engangs", False)),
            gallplats=item.get("gallplats", "båda"),
        ))
    return coupons


def coupon_villkor(c: Coupon) -> str:
    """Formaterar kupongens villkor som en rad för verifiering."""
    delar = []
    if c.kalla:
        delar.append("Källa: " + c.kalla)
    if c.marke:
        delar.append("Märke: " + c.marke)
    if c.storlek:
        delar.append("Storlek: " + c.storlek)
    if c.minsta_kop:
        delar.append(f"Minsta köp: {c.minsta_kop:g} kr")
    if c.endast_medlem:
        delar.append("Endast medlem")
    if c.giltig_till:
        delar.append("Giltig t.o.m. " + c.giltig_till)
    if c.engangs:
        delar.append("Engångsrabatt")
    delar.append("Gäller: " + c.gallplats)
    return " · ".join(delar)


def apply_coupons(p: Product, coupons: List[Coupon]) -> Optional[float]:
    """Tillämpar alla kuponger som gäller produkten (staplas i ordning)."""
    cur = p.price_per
    if cur is None:
        return None
    for c in coupons:
        if not c.galler(p):
            continue
        p.price_per = cur
        if p.count and p.price is not None:
            p.price = cur * p.count
        nxt = c.applicera(p)
        if nxt is None:
            continue
        cur = nxt
    if p.count:
        p.price = cur * p.count
    return cur


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Jämför blöjpriser och visar riktiga kampanjer (kr/blöja).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--sok", default="blöjor",
                    help="Sökord, kommaseparerade (t.ex. 'blöjor,libero,pampers')")
    ap.add_argument("--butiker", default="willys,apotea",
                    help="Butiker att söka i (willys,hemkop,apotea,coop,apoteket,mathem,citygross,ica)")
    ap.add_argument("--marke", default=None,
                    help="Filtrera på märke (Libero, Pampers)")
    ap.add_argument("--ica-butik", default=None,
                    help="ICA-butik att hämta priser från (sök på namn eller stad, t.ex. 'maxi stockholm')")
    ap.add_argument("--ica-id", default=None,
                    help="ICA-butikens accountId direkt (t.ex. '1003723')")
    ap.add_argument("--lista-ica-butiker", default=None,
                    help="Lista ICA-butiker som matchar söktermen och avsluta (t.ex. 'maxi stockholm')")
    ap.add_argument("--ica-http", action="store_true",
                    help="Tvinga ICA-hämtning via vanlig HTTP (utan webbläsare)")
    ap.add_argument("--kuponger", default=None,
                    help="Sökväg till JSON-fil med kuponger (med villkor att verifiera)")
    ap.add_argument("--topp", type=int, default=25,
                    help="Antal resultat att visa")
    ap.add_argument("--max-sidor", type=int, default=3,
                    help="Max antal sidor per butik (Apotea)")
    ap.add_argument("--jmf-pris", action="store_true",
                    help="Hämta officiellt jämförpris från Apoteas produktsidor (långsammare)")
    ap.add_argument("--visa-alla", action="store_true",
                    help="Visa även produkter som inte är blöjor")
    args = ap.parse_args()

    # Lista ICA-butiker och avsluta (hjälpfunktion)
    if args.lista_ica_butiker:
        matches = _match_ica_stores(args.lista_ica_butiker, first_only=False)
        if not matches:
            print(f"Inga ICA-butiker matchade '{args.lista_ica_butiker}'.")
        else:
            print(f"ICA-butiker som matchar '{args.lista_ica_butiker}':")
            for s in matches[:30]:
                print(f"  {s.get('name')} – {s.get('city')} (accountId {s.get('accountId')})")
            if len(matches) > 30:
                print(f"  ... ({len(matches)} totalt, förfina sökningen)")
        return

    stores = [s.strip().lower() for s in args.butiker.split(",") if s.strip()]
    queries = [q.strip() for q in args.sok.split(",") if q.strip()]

    coupons: List[Coupon] = []
    if args.kuponger:
        coupons = load_coupons(args.kuponger)


    # Bestäm ICA-butik om ICA valts (priserna skiljer sig mellan butiker)
    ica_account_id: Optional[str] = None
    ica_store_name: str = ""
    if "ica" in stores:
        if args.ica_id:
            ica_account_id = args.ica_id
        elif args.ica_butik:
            found = find_ica_store(args.ica_butik)
            if found:
                ica_account_id = found.get("accountId")
                ica_store_name = found.get("name", "")
            else:
                print(f"⚠️  Hittade ingen ICA-butik som matchar '{args.ica_butik}'. "
                      f"Använder första butiken i listan.", file=sys.stderr)
        if not ica_account_id:
            first = fetch_ica_stores()[0]
            ica_account_id = first.get("accountId")
            ica_store_name = first.get("name", "")
        print(f"ℹ️  ICA-butik: {ica_store_name} (accountId {ica_account_id})", file=sys.stderr)

    products: List[Product] = []
    for store in stores:
        for q in queries:
            try:
                if store == "willys":
                    products.extend(fetch_willys(q))
                elif store == "hemkop":
                    products.extend(fetch_hemkop(q))
                elif store == "apotea":
                    products.extend(fetch_apotea(q, max_pages=args.max_sidor, fill_jmf=args.jmf_pris))
                elif store == "coop":
                    products.extend(fetch_coop(q))
                elif store == "apoteket":
                    products.extend(fetch_apoteket(q))
                elif store == "mathem":
                    products.extend(fetch_mathem(q))
                elif store == "citygross":
                    products.extend(fetch_citygross(q))
                elif store == "ica":
                    if ica_account_id:
                        products.extend(fetch_ica(q, ica_account_id, prefer_browser=not args.ica_http))
                else:
                    print(f"⚠️  Okänd butik: {store} (stöds: willys, hemkop, apotea, coop, apoteket, mathem, citygross, ica)", file=sys.stderr)
            except Exception as e:
                print(f"⚠️  Kunde inte hämta från {store} ('{q}'): {e}", file=sys.stderr)

    # Rensa dubbletter (samma butik + namn)
    seen = set()
    unique: List[Product] = []
    for p in products:
        key = (p.store, p.name.lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)

    # Filtrera: blöjor + märke
    if not args.visa_alla:
        unique = [p for p in unique if is_diaper(p.name)]
    if args.marke:
        wanted = args.marke.lower()
        unique = [p for p in unique if wanted in p.brand.lower()]

    # Tillämpa inmatade kuponger (filtrerar på märke/storlek och räknar rabatt)
    if coupons:
        for p in unique:
            p.price_per = apply_coupons(p, coupons)

    # Sortera på billigast kr/blöja (okända sist)
    unique.sort(key=lambda p: (p.price_per is None, p.price_per if p.price_per is not None else 0))

    # Utskrift
    print()
    print("=" * 100)
    print(" BLÖJKALKYLATORN  —  billigast blöja per styck (kr/blöja)")
    print(" Sökord:", ", ".join(queries), "| Butiker:", ", ".join(stores))
    if args.marke:
        print(" Märke:", args.marke)
    if coupons:
        print(" Kuponger (med villkor att verifiera):")
        for c in coupons:
            print("   •", c.beskrivning or c.typ)
            print("     └", coupon_villkor(c))
    print(" Priserna är butikernas aktuella priser (riktiga kampanjer markeras med ★).")
    print("=" * 100)

    header = f"{'#':>3}  {'Butik':<7} {'Pris/fp':>9} {'Antal':>7} {'kr/blöja':>9}  {'Märke':<8} Produkt"
    print(header)
    print("-" * 100)

    shown = 0
    for i, p in enumerate(unique, 1):
        if shown >= args.topp:
            break
        shown += 1
        count_s = f"{p.count} st" if p.count else "-"
        mark = "*" if p.price_per is None else " "
        star = " ★" if p.kampanj else ""
        line = (f"{i:>3}{mark}  {p.store:<7} {format_kr(p.price):>9} {count_s:>7} "
                f"{format_kr(p.price_per):>9}  {p.brand:<8} {p.name}{star}")
        print(line[:100])

    if len(unique) > shown:
        print(f"... ({len(unique) - shown} fler, öka --topp för att se alla)")

    campaign_products = [p for p in unique if p.kampanj]
    if campaign_products:
        print()
        print("★ Erbjudanden/kampanjer som butikerna visar just nu (kan kräva medlemskap")
        print("  eller minsta köp – oftast inte inräknade i priset ovan):")
        for p in campaign_products:
            print(f"  ★ {p.store}: {p.name} → {p.kampanj}")

    without_price = [p for p in unique if p.price_per is None]
    if without_price:
        print()
        print(f"ℹ️  {len(without_price)} produkt(er) saknar antal/jämförpris och kunde inte "
              f"räknas per blöja. Använd --jmf-pris för Apotea för mer täckning.")


if __name__ == "__main__":
    main()
