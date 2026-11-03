"""RareVinyl sealed-first discovery; read-only, no DB writes or publication."""
import argparse
import json
import re
import time
from decimal import Decimal
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE = "https://eu.rarevinyl.com"
COLLECTION = BASE + "/collections/brand-new-factory-sealed-vinyl-records-and-cds"
UA = "VinylofyRareVinylResearch/0.1 (+https://vinylofy.com)"
HEADERS = {"User-Agent": UA, "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8"}
SEALED = re.compile(r"\\b(?:factory[ -]?sealed|sealed from new|still sealed)\\b", re.I)
VINYL = re.compile(r"\\b(?:vinyl|LP|12[ -]?inch|7[ -]?inch|picture disc)\\b", re.I)
CD_ONLY = re.compile(r"\\b(?:CD|compact disc|DVD|cassette)\\b", re.I)
GTIN = re.compile(r"(?:Barcode|GTIN|Global Trade Item Number)\\s*[:\\-]?\\s*([0-9][0-9 -]{7,20})", re.I)
PRICE = re.compile(r"(?:€\\s*([0-9.,]+)|([0-9.,]+)\\s*€)")
def normalize_gtin(value):
    digits = re.sub(r"\\D", "", value or "")
    if len(digits) not in (8, 12, 13, 14):
        return None
    total = sum(int(d) * (3 if (len(digits) - i) % 2 == 0 else 1) for i, d in enumerate(digits[:-1]))
    return digits if (10 - total % 10) % 10 == int(digits[-1]) else None

def parse_price(text):
    match = PRICE.search(text or "")
    if not match:
        return None
    raw = next(g for g in match.groups() if g)
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        return str(Decimal(raw))
    except Exception:
        return None

def extract_cards(html):
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for a in soup.select('a[href*="/products/"]'):
        href = urljoin(BASE, a.get("href", "")).split("?")[0]
        if urlparse(href).netloc != urlparse(BASE).netloc:
            continue
        card = a.find_parent(["article", "li"]) or a.parent
        if not card:
            continue
        text = card.get_text(" ", strip=True)
        image = card.find("img")
        image_alt = image.get("alt", "") if image else ""
        title = a.get_text(" ", strip=True) or image_alt
        sealed = bool(SEALED.search(" ".join([text, image_alt, title])))
        price = parse_price(text)
        if href not in found or (sealed and not found[href]["sealed_signal"]):
            found[href] = {"url": href, "title_raw": title, "price_eur": price,
                           "sealed_signal": sealed, "detail_status": "PRIORITY" if sealed else "DEFERRED"}
    return list(found.values())

def extract_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    barcode_match = GTIN.search(text)
    condition = re.search(r"Condition\\s*[:\\-]?\\s*(.{0,140})", text, re.I)
    condition_raw = condition.group(1) if condition else ""
    sealed = bool(SEALED.search(condition_raw))
    return {"gtin": normalize_gtin(barcode_match.group(1)) if barcode_match else None,
            "condition_raw": condition_raw, "condition_normalized": "NEW" if sealed else "UNKNOWN",
            "sealed_confirmed": sealed, "detail_price_eur": parse_price(text)}

def allowed(url, robots):
    return robots.can_fetch(UA, url)

def run(max_pages, max_details, delay, output):
    session = requests.Session()
    session.headers.update(HEADERS)
    robots = RobotFileParser()
    robots.set_url(BASE + "/robots.txt")
    robots.read()
    rows = {}
    for page in range(1, max_pages + 1):
        url = COLLECTION + f"?page={page}"
        if not allowed(url, robots):
            raise RuntimeError("robots.txt disallows collection")
        response = session.get(url, timeout=25)
        response.raise_for_status()
        cards = extract_cards(response.text)
        if not cards:
            break
        for card in cards:
            rows[card["url"]] = card
        time.sleep(delay)
    count = 0
    for row in rows.values():
        if not row["sealed_signal"] or count >= max_details:
            continue
        if not allowed(row["url"], robots):
            row["detail_status"] = "ROBOTS_BLOCKED"
            continue
        response = session.get(row["url"], timeout=25)
        response.raise_for_status()
        row.update(extract_detail(response.text))
        row["detail_status"] = "VALIDATED" if row["sealed_confirmed"] else "REVIEW"
        count += 1
        time.sleep(delay)
    with open(output, "w", encoding="utf-8") as handle:
        for row in rows.values():
            handle.write(json.dumps(row, ensure_ascii=False) + "\\n")
    print(json.dumps({"discovered": len(rows), "details": count, "validated": sum(r.get("detail_status") == "VALIDATED" for r in rows.values()), "output": output}))

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--pages", type=int, default=2)
    p.add_argument("--details", type=int, default=20)
    p.add_argument("--delay", type=float, default=2)
    p.add_argument("--output", default="rarevinyl-pilot.jsonl")
    a = p.parse_args()
    run(a.pages, a.details, a.delay, a.output)
