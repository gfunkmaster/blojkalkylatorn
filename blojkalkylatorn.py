#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Blöjkalkylatorn
===============

Hämtar aktuella priser på blöjor (Libero, Pampers m.fl.) från svenska butiker
och testar kuponger/rabatter för att räkna fram billigaste priset per blöja.

Butiker som stöds just nu:
  * Willys  – ren JSON (jämförpris = kr/blöja direkt)
  * Hemköp  – samma JSON-API som Willys (samma koncern, Axfood)
  * Apotea  – parsar serverrenderad HTML (kr/blöja från antal i namnet)
  * ICA     – parsar serverrenderad HTML (kräver val av butik)

Kör exempel (utan kuponger):
    python3 blojkalkylatorn.py
    python3 blojkalkylatorn.py --marke Libero
    python3 blojkalkylatorn.py --sok "blöjor,libero,pampers"
    python3 blojkalkylatorn.py --butiker willys,hemkop,apotea,ica --ica-butik "maxi stockholm"

Kör med kuponger (läses från en JSON-fil):
    python3 blojkalkylatorn.py --kuponger kuponger.json

Snabbkuponger direkt på kommandoraden:
    python3 blojkalkylatorn.py --procent 20          # 20 % rabatt på allt
    python3 blojkalkylatorn.py --fast 10             # 10 kr rabatt per förpackning
    python3 blojkalkylatorn.py --kop-betala 3/2      # köp 3, betala 2

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
    price_per: Optional[float]      # kr per blöja (bas, utan kupong)
    jmf: Optional[str]              # officiellt jämförpris i klartext
    url: str = ""


@dataclass
class Coupon:
    typ: str                        # "procent" | "fast" | "kop_betala"
    varde: float = 0.0              # procent (20 = 20 %) eller kr för "fast"
    kop: int = 1                    # "kop_betala": köp X ...
    betala: int = 1                 # ... betala för Y
    marke: Optional[str] = None     # gäller bara detta märke (t.ex. "Libero")
    butik: Optional[str] = None     # gäller bara denna butik (t.ex. "Willys")
    beskrivning: str = ""

    def galler(self, p: Product) -> bool:
        if self.marke and self.marke.lower() not in (p.brand or "").lower():
            return False
        if self.butik and self.butik.lower() != (p.store or "").lower():
            return False
        return True

    def applicera(self, p: Product) -> Optional[float]:
        """Returnerar nytt kr/blöja efter kupongen, eller None om det inte går."""
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
        out.append(Product(
            store=store_name,
            name=name,
            brand=brand,
            price=price,
            count=count,
            price_per=per,
            jmf=(jmf + " " + (r.get("comparePriceUnit") or "")).strip() if jmf else None,
            url=base_url + "/search?q=" + urllib.parse.quote(query),
        ))
    return out


def fetch_willys(query: str) -> List[Product]:
    return fetch_axfood(query, "https://www.willys.se", "Willys")


def fetch_hemkop(query: str) -> List[Product]:
    return fetch_axfood(query, "https://www.hemkop.se", "Hemköp")


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
# Huvudlogik
# --------------------------------------------------------------------------

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
            marke=item.get("marke"),
            butik=item.get("butik"),
            beskrivning=item.get("beskrivning", ""),
        ))
    return coupons


def format_kr(x: Optional[float]) -> str:
    if x is None:
        return "-"
    return f"{x:.2f}".replace(".", ",") + " kr"


def apply_coupons(p: Product, coupons: List[Coupon]) -> Optional[float]:
    """Tillämpar alla kuponger som gäller produkten i tur och ordning (staplas)."""
    cur = p.price_per
    if cur is None:
        return None
    for c in coupons:
        if not c.galler(p):
            continue
        # Låt varje kupong räkna på det ackumulerade priset så att rabatter staplas.
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
        description="Jämför blöjpriser och testa kuponger (kr/blöja).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--sok", default="blöjor",
                    help="Sökord, kommaseparerade (t.ex. 'blöjor,libero,pampers')")
    ap.add_argument("--butiker", default="willys,apotea",
                    help="Butiker att söka i (willys,hemkop,apotea,ica)")
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
                    help="Sökväg till JSON-fil med kuponger")
    ap.add_argument("--topp", type=int, default=25,
                    help="Antal resultat att visa")
    ap.add_argument("--max-sidor", type=int, default=3,
                    help="Max antal sidor per butik (Apotea)")
    ap.add_argument("--jmf-pris", action="store_true",
                    help="Hämta officiellt jämförpris från Apoteas produktsidor (långsammare)")
    ap.add_argument("--visa-alla", action="store_true",
                    help="Visa även produkter som inte är blöjor")
    # Snabbkuponger
    ap.add_argument("--procent", type=float, default=None, help="Procentrabatt på allt (t.ex. 20)")
    ap.add_argument("--fast", type=float, default=None, help="Fast rabatt i kr per förpackning")
    ap.add_argument("--kop-betala", default=None, help="Köp X betala Y, t.ex. '3/2'")
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
    if args.procent is not None:
        coupons.append(Coupon("procent", varde=args.procent, beskrivning=f"{args.procent:g} % rabatt"))
    if args.fast is not None:
        coupons.append(Coupon("fast", varde=args.fast, beskrivning=f"{args.fast:g} kr rabatt"))
    if args.kop_betala:
        parts = args.kop_betala.split("/")
        if len(parts) == 2:
            coupons.append(Coupon("kop_betala", kop=int(parts[0]), betala=int(parts[1]),
                                  beskrivning=f"köp {parts[0]} betala {parts[1]}"))


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
                elif store == "ica":
                    if ica_account_id:
                        products.extend(fetch_ica(q, ica_account_id, prefer_browser=not args.ica_http))
                else:
                    print(f"⚠️  Okänd butik: {store} (stöds: willys, hemkop, apotea, ica)", file=sys.stderr)
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

    # Beräkna slutpris efter kuponger
    for p in unique:
        if coupons:
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
        print(" Kuponger:")
        for c in coupons:
            tag = " ".join(x for x in [c.marke, c.butik] if x)
            print("   •", c.beskrivning or c.typ, ("(" + tag + ")" if tag else ""))
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
        line = (f"{i:>3}{mark}  {p.store:<7} {format_kr(p.price):>9} {count_s:>7} "
                f"{format_kr(p.price_per):>9}  {p.brand:<8} {p.name}")
        print(line[:100])

    if len(unique) > shown:
        print(f"... ({len(unique) - shown} fler, öka --topp för att se alla)")

    without_price = [p for p in unique if p.price_per is None]
    if without_price:
        print()
        print(f"ℹ️  {len(without_price)} produkt(er) saknar antal/jämförpris och kunde inte "
              f"räknas per blöja. Använd --jmf-pris för Apotea för mer täckning.")


if __name__ == "__main__":
    main()
