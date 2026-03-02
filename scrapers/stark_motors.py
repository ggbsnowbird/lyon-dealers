"""
scrapers/stark_motors.py — Stark Motors (starkmotors.fr)
Plateforme : PHP custom + Bulma CSS
Stratégie  : Toutes les autos sont dans le HTML de /shop en une seule page.
             Phase 1 httpx sur /shop, parse chaque article.filter-car
             Phase 2 httpx sur chaque page détail.
"""

import httpx
import json
import re
import time
import random
from bs4 import BeautifulSoup
from pathlib import Path

DEALER_KEY  = "stark_motors"
DEALER_NAME = "Stark Motors"
DEALER_URL  = "https://www.starkmotors.fr"
LISTING_URL = "https://www.starkmotors.fr/shop"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.starkmotors.fr/",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_price(s):
    if not s:
        return None
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None

def _clean_km(s):
    if not s:
        return None
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None

def _clean_year(s):
    if not s:
        return None
    m = re.search(r"(20\d{2}|19\d{2})", s)
    return int(m.group(1)) if m else None

def _clean_tx(s):
    if not s:
        return "?"
    t = s.lower()
    if any(k in t for k in ["manuelle", "mécanique", "mecanique", "manual"]):
        return "Manuelle"
    if any(k in t for k in ["automatique", "automatic", "pdk", "dct", "s-tronic", "dsg", "séquentielle", "robotisée"]):
        return "Automatique"
    return s[:20]

def _get(url, client):
    resp = client.get(url, headers=HEADERS, follow_redirects=True, timeout=20)
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# Phase 1 — Parse la page shop (toutes les autos en un seul HTML)
# ---------------------------------------------------------------------------

def _parse_listing_cards(html):
    """
    Retourne liste de (url_detail, data_partielle) depuis la page /shop.
    Chaque article.filter-car contient: data-category, h3, km, date, prix, lien.
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("article.filter-car")
    if not cards:
        # Fallback selectors
        cards = soup.select(".car-item, .vehicle-card, article[class*='car']")

    items = []
    for card in cards:
        # URL détail
        link = card.select_one("a[href*='/shop/']") or card.select_one("a")
        url = ""
        if link:
            href = str(link.get("href") or "")
            if href and not href.startswith("http"):
                href = DEALER_URL + href
            url = href

        # Marque (data-category) — normalize casing and separators
        marque = str(card.get("data-category") or "").strip()
        marque = marque.replace("_", " ").replace("-", " ").title()

        # Titre H3
        h3 = card.select_one("h3")
        title = h3.get_text(strip=True) if h3 else ""

        # Prix
        prix_el = (card.select_one(".price") or card.select_one("[class*='prix']") or
                   card.select_one("strong") or card.select_one("b"))
        prix = _clean_price(prix_el.get_text() if prix_el else "")

        # Km et Année — structure Stark Motors : div.mec-km > p
        km = None
        annee = None
        mec_km_div = card.select_one(".mec-km")
        if mec_km_div:
            for p in mec_km_div.select("p"):
                text = p.get_text(strip=True)
                if "km" in text.lower():
                    km = _clean_km(text)
                elif re.search(r"\d{2}\.\d{2}\.\d{4}", text):
                    annee = _clean_year(text)
                elif re.search(r"\b(20\d{2}|19\d{2})\b", text):
                    annee = _clean_year(text)

        # Fallback: chercher dans le texte brut
        if not km:
            m = re.search(r"(\d[\d\s]{2,6})\s*km", card.get_text(), re.IGNORECASE)
            if m:
                km = _clean_km(m.group(1))
        if not annee:
            m = re.search(r"\b(20\d{2}|19\d{2})\b", card.get_text())
            if m:
                annee = int(m.group(1))

        if url:
            items.append({
                "url":    url,
                "marque": marque,
                "modele": title,
                "prix":   prix,
                "km":     km,
                "annee":  annee,
            })

    return items


# ---------------------------------------------------------------------------
# Phase 2 — Page détail
# ---------------------------------------------------------------------------

def _parse_detail(url, html, partial=None):
    """Parse la page détail Stark Motors."""
    soup = BeautifulSoup(html, "html.parser")
    p = partial or {}

    # Titre principal
    h1 = soup.select_one("h1") or soup.select_one(".car-title")
    title_raw = h1.get_text(strip=True) if h1 else p.get("modele", "")

    # Marque depuis breadcrumb ou partial
    marque = p.get("marque", "")
    if not marque:
        bc = soup.select("nav.breadcrumb li, .breadcrumb a")
        if bc and len(bc) >= 2:
            marque = bc[-2].get_text(strip=True).replace("_", " ").replace("-", " ").title()

    # Prix
    prix = p.get("prix")
    if not prix:
        for el in soup.select(".price, .prix, [class*='price'] span, strong"):
            v = _clean_price(el.get_text())
            if v and v > 5000:
                prix = v
                break

    # Image
    img_el = soup.select_one(".swiper-slide img, .gallery img, .car-photo img, img.main-photo")
    if not img_el:
        img_el = soup.select_one("img[src*='upload'], img[src*='photo'], img[src*='car']")
    image_url = None
    if img_el:
        image_url = str(img_el.get("src") or img_el.get("data-src") or "")
        if image_url and not image_url.startswith("http"):
            image_url = DEALER_URL + image_url

    # Caractéristiques structurées
    km = p.get("km")
    annee = p.get("annee")
    tx, couleur, puissance_cv, carrosserie = None, None, None, None
    description = ""
    options_brutes = []

    # Structure Stark Motors : .info-car-detail > p (chaque p = un champ)
    # Format: <span><i class="fas ..."></i>Label</span><br/>Valeur
    for p in soup.select(".info-car-detail p"):
        span = p.select_one("span")
        if span:
            label = span.get_text(strip=True).lower()
            # La valeur est le texte du p après le span
            span.extract()
            value = p.get_text(strip=True)
        else:
            full = p.get_text(strip=True)
            if not full:
                continue
            label, value = full, full

        if any(k in label for k in ["kilométrage", "km", "kilometrage"]):
            km = km or _clean_km(value)
        elif any(k in label for k in ["mise en circulation", "année", "annee", "date"]):
            annee = annee or _clean_year(value)
        elif any(k in label for k in ["boîte", "boite", "transmission"]):
            tx = _clean_tx(value)
        elif "couleur" in label:
            couleur = value
        elif "puissance" in label:
            m = re.search(r"(\d+)", value)
            puissance_cv = int(m.group(1)) if m else None
        elif any(k in label for k in ["carrosserie", "type"]):
            carrosserie = value

    # Fallback tableau standard
    for row in soup.select("table tr"):
        cells = row.select("td, th")
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True).lower()
            value = cells[1].get_text(strip=True)
            if any(k in label for k in ["kilométrage", "km"]):
                km = km or _clean_km(value)
            elif any(k in label for k in ["année", "mise en"]):
                annee = annee or _clean_year(value)
            elif any(k in label for k in ["boîte", "transmission"]):
                tx = tx or _clean_tx(value)
            elif "couleur" in label:
                couleur = couleur or value

    # Chercher km dans n'importe quel texte si pas trouvé
    if not km:
        m = re.search(r"(\d[\d\s]{2,6})\s*km", soup.get_text(), re.IGNORECASE)
        if m:
            km = _clean_km(m.group(1))

    # Description
    for sel in [".description", ".car-description", ".content", "article p", ".text-content"]:
        desc_el = soup.select_one(sel)
        if desc_el:
            description = desc_el.get_text(" ", strip=True)[:500]
            break

    # Équipements / options
    for sel in [".equipements li", ".options li", ".features li",
                ".equipment li", "ul[class*='equip'] li", "ul[class*='option'] li"]:
        for eq in soup.select(sel):
            t = eq.get_text(strip=True)
            if t and len(t) > 2:
                options_brutes.append(t)

    listing = {
        "id":            url.rstrip("/").split("/")[-1],
        "source":        DEALER_KEY,
        "dealer_name":   DEALER_NAME,
        "dealer_url":    DEALER_URL,
        "marque":        marque,
        "modele":        title_raw,
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
    return listing


# ---------------------------------------------------------------------------
# Entrée principale
# ---------------------------------------------------------------------------

def scrape():
    print(f"\n{'='*60}")
    print(f"  Stark Motors — {LISTING_URL}")
    print(f"{'='*60}")

    listings = []
    with httpx.Client(follow_redirects=True, timeout=20) as client:
        # Phase 1 : récupérer toutes les cartes de la page /shop
        print(f"  Chargement de la page shop...")
        try:
            html = _get(LISTING_URL, client)
        except Exception as e:
            print(f"  [!] Erreur page shop: {e}")
            return listings

        items = _parse_listing_cards(html)
        print(f"  {len(items)} voitures trouvées sur la page listing")

        if not items:
            # Debug : sauvegarder le HTML brut pour inspection
            debug_path = Path(__file__).parent.parent / "debug_stark_listing.html"
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"  [!] Aucune carte trouvée — HTML sauvé dans {debug_path}")
            return listings

        # Phase 2 : pages détail
        for i, item in enumerate(items, 1):
            url = item["url"]
            print(f"  [{i}/{len(items)}] {url}")
            try:
                detail_html = _get(url, client)
                listing = _parse_detail(url, detail_html, partial=item)
                if listing:
                    listings.append(listing)
                    prix_str = f"{listing['prix']:,}" if listing.get('prix') else '?'
                    print(f"    → {listing.get('marque')} {listing.get('modele')} | "
                          f"{prix_str} € | {listing.get('km') or '?'} km")
            except Exception as e:
                print(f"    [!] Erreur: {e}")
            time.sleep(random.uniform(0.6, 1.3))

    print(f"\n  Total Stark Motors: {len(listings)} annonces")
    return listings


if __name__ == "__main__":
    results = scrape()
    out = Path(__file__).parent.parent / "debug_stark_motors.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"  Debug: {out}")
