"""
scrapers/west_motors.py — West Motors (westmotors.fr)
Plateforme : WordPress custom (IzisCAR plugin)
Stratégie  : httpx — site entièrement server-rendered (pas besoin de Playwright)
             Phase 1 : GET /showroom/ — cards a.car-item dans div#car-listing
             Phase 2 : GET /voiture/{slug}/ — specs dans .spec-item, prix dans .car-single-price
"""

import httpx
import json
import re
import time
import random
from bs4 import BeautifulSoup
from pathlib import Path

DEALER_KEY  = "west_motors"
DEALER_NAME = "West Motors"
DEALER_URL  = "https://www.westmotors.fr"
LISTING_URL = "https://www.westmotors.fr/showroom/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.westmotors.fr/",
}

# Known brands for title parsing
KNOWN_BRANDS = [
    "Aston Martin", "Rolls-Royce", "Land Rover", "De Tomaso", "Alfa Romeo",
    "Porsche", "Ferrari", "Lamborghini", "McLaren", "Bentley", "Maserati",
    "BMW", "Mercedes", "Audi", "Alpine", "Lotus", "Jaguar", "Bugatti",
    "Pagani", "Ford", "Chevrolet", "Dodge", "Chrysler", "Koenigsegg",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_price(s):
    if not s:
        return None
    digits = re.sub(r"[^\d]", "", str(s))
    v = int(digits) if digits else None
    return v if v and 3000 < v < 10000000 else None

def _clean_km(s):
    if not s:
        return None
    digits = re.sub(r"[^\d]", "", str(s))
    return int(digits) if digits else None

def _clean_year(s):
    if not s:
        return None
    m = re.search(r"(20\d{2}|19\d{2})", str(s))
    return int(m.group(1)) if m else None

def _clean_tx(s):
    if not s:
        return "?"
    t = str(s).lower()
    if any(k in t for k in ["manuelle", "mécanique", "mecanique", "manual", "manuel"]):
        return "Manuelle"
    if any(k in t for k in ["automatique", "automatic", "pdk", "dct", "s-tronic", "dsg",
                              "séquentielle", "robotisée"]):
        return "Automatique"
    if "tiptronic" in t:
        return "Automatique"
    return str(s)[:20]

def _parse_brand(title):
    """Extract brand from car title."""
    for brand in KNOWN_BRANDS:
        if title.lower().startswith(brand.lower()):
            return brand
    # Fallback: first word
    parts = title.strip().split()
    return parts[0] if parts else ""

def _get(url, client):
    resp = client.get(url, headers=HEADERS, follow_redirects=True, timeout=20)
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# Phase 1 — Listing /showroom/
# Structure: div#car-listing > a.car-item (66 items)
# Each a.car-item has: img, h3.car-title (.car-brand + .car-name), .car-km, .car-price
# ---------------------------------------------------------------------------

def _fetch_listing_cards(html):
    soup = BeautifulSoup(html, "html.parser")
    cards = []

    car_listing = soup.select_one("div#car-listing, div.car-listing")
    if not car_listing:
        # Fallback: any a.car-item anywhere on page
        items = soup.select("a.car-item[href*='/voiture/']")
    else:
        items = car_listing.select("a.car-item")

    for item in items:
        href = str(item.get("href") or "")
        if not href or "/voiture/" not in href:
            continue
        if not href.startswith("http"):
            href = DEALER_URL + href

        # Title
        name_el = item.select_one(".car-name") or item.select_one(".car-title")
        title = name_el.get_text(strip=True) if name_el else item.get_text(strip=True)[:60]

        # KM
        km_el = item.select_one(".car-km")
        km = _clean_km(km_el.get_text() if km_el else "")

        # Price
        prix_el = item.select_one(".car-price")
        prix = _clean_price(prix_el.get_text() if prix_el else "")

        # Image
        img_el = item.select_one("img")
        image_url = None
        if img_el:
            src = str(img_el.get("src") or img_el.get("data-src") or "")
            if src and "logo" not in src.lower():
                image_url = src if src.startswith("http") else DEALER_URL + src

        cards.append({
            "url":       href,
            "title":     title,
            "km":        km,
            "prix":      prix,
            "image_url": image_url,
        })

    return cards


# ---------------------------------------------------------------------------
# Phase 2 — Page détail /voiture/{slug}/
# Prix : .car-single-price
# Specs: .spec-item (label=.spec-label, value=.spec-value)
#        also .car-details on listing embedded in page (ignore, use .spec-item only)
# Description : .car-description p
# Options : li items in .car-options, .car-equipment, .features-list
# ---------------------------------------------------------------------------

def _parse_detail(url, html, base=None):
    soup = BeautifulSoup(html, "html.parser")
    b = base or {}

    # Title
    h1 = soup.select_one("h1.car-title, h1")
    title = h1.get_text(strip=True) if h1 else b.get("title", "")
    marque = _parse_brand(title)

    # Price: prefer .car-single-price on the page (not cards for other cars)
    prix = b.get("prix")
    if not prix:
        car_single_price = soup.select_one(".car-single-price, .car-pricing")
        if car_single_price:
            prix = _clean_price(car_single_price.get_text())

    # Image
    image_url = b.get("image_url")
    if not image_url:
        for img in soup.select("img"):
            src = str(img.get("src") or img.get("data-src") or img.get("data-lazy-src") or "")
            if "app/uploads/iziscar" in src and "logo" not in src.lower():
                image_url = src if src.startswith("http") else DEALER_URL + src
                break

    # Specs from .spec-item elements (only within the main car section)
    # These appear on the main car detail — ignore any from recommended cars below
    km       = b.get("km")
    annee    = None
    tx       = None
    couleur  = None
    puissance_cv = None
    carrosserie  = None

    # Find the main car content area to limit spec parsing scope
    main_area = (soup.select_one(".car-single-content, .car-single, .car-page, main") or
                 soup.select_one(".content, #content"))

    spec_scope = main_area if main_area else soup
    spec_items = spec_scope.select(".spec-item")
    # Only take the first batch of spec items (for the main car, not the recommended ones)
    # Recommended cars appear later — identify by repeated patterns
    parsed_specs = 0
    for spec in spec_items:
        label_el = spec.select_one(".spec-label")
        value_el = spec.select_one(".spec-value")
        if not label_el or not value_el:
            continue
        label = label_el.get_text(strip=True).lower().rstrip(":")
        value = value_el.get_text(strip=True)

        if any(k in label for k in ["kilométrage", "km"]):
            km = km or _clean_km(value)
        elif any(k in label for k in ["année", "annee", "mise en circulation"]):
            annee = annee or _clean_year(value)
        elif any(k in label for k in ["transmission", "boîte", "boite"]):
            tx = tx or _clean_tx(value)
        elif "couleur" in label or "color" in label:
            couleur = couleur or value
        elif any(k in label for k in ["puissance din", "puissance"]):
            m_cv = re.search(r"(\d+)", value)
            puissance_cv = puissance_cv or (int(m_cv.group(1)) if m_cv else None)
        elif any(k in label for k in ["carrosserie", "type de véhicule"]):
            carrosserie = carrosserie or value

        parsed_specs += 1
        # Stop after 10 main specs (avoid parsing recommended car specs)
        if parsed_specs >= 10:
            break

    # Description — prefer car-specific description, skip generic contact text
    description = ""
    for sel in [".car-description", ".car-content", ".entry-content", ".description"]:
        for p in soup.select(f"{sel} p"):
            t = p.get_text(" ", strip=True)
            if len(t) > 50 and not re.search(r"cookie|gdpr|©|contactez|téléphone", t, re.IGNORECASE):
                description = t[:500]
                break
        if description:
            break

    # Options
    options_brutes = []
    for el in soup.select(".car-options li, .car-equipment li, .features-list li, "
                          ".equipment-list li, [class*='option'] li, [class*='equip'] li"):
        t = el.get_text(strip=True)
        if t and 3 < len(t) < 120:
            options_brutes.append(t)

    slug = url.rstrip("/").split("/")[-1]
    return {
        "id":            slug,
        "source":        DEALER_KEY,
        "dealer_name":   DEALER_NAME,
        "dealer_url":    DEALER_URL,
        "marque":        marque,
        "modele":        title,
        "annee":         annee,
        "km":            km,
        "prix":          prix,
        "tx_clean":      tx or "?",
        "couleur":       couleur,
        "carrosserie":   carrosserie,
        "puissance_cv":  puissance_cv,
        "puissance_kw":  None,
        "description":   description,
        "options_brutes":options_brutes,
        "url":           url,
        "image_url":     image_url,
    }


# ---------------------------------------------------------------------------
# Entrée principale
# ---------------------------------------------------------------------------

def scrape():
    print(f"\n{'='*60}")
    print(f"  West Motors — {LISTING_URL}")
    print(f"{'='*60}")

    listings = []
    with httpx.Client(follow_redirects=True, timeout=20) as client:
        print(f"  Chargement de la page listing...")
        try:
            html = _get(LISTING_URL, client)
        except Exception as e:
            print(f"  [!] Erreur listing: {e}")
            return []

        cards = _fetch_listing_cards(html)
        print(f"  {len(cards)} voitures trouvées")

        if not cards:
            debug_path = Path(__file__).parent.parent / "debug_west_listing.html"
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"  [!] Aucune voiture — HTML sauvé: {debug_path}")
            return []

        for i, card in enumerate(cards, 1):
            url = card["url"]
            print(f"  [{i}/{len(cards)}] {url}")
            try:
                detail_html = _get(url, client)
                listing = _parse_detail(url, detail_html, base=card)
                if listing:
                    listings.append(listing)
                    prix_str = f"{listing['prix']:,}" if listing.get("prix") else "?"
                    print(f"    → {listing['marque']} {listing['modele'][:40]} | "
                          f"{prix_str} € | {listing.get('km') or '?'} km | "
                          f"{listing.get('tx_clean', '?')}")
            except Exception as e:
                print(f"    [!] Erreur: {e}")
            time.sleep(random.uniform(0.4, 1.0))

    print(f"\n  Total West Motors: {len(listings)} annonces")
    return listings


if __name__ == "__main__":
    results = scrape()
    out = Path(__file__).parent.parent / "debug_west_motors.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"  Debug: {out}")
