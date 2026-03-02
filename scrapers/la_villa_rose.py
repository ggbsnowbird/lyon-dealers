"""
scrapers/la_villa_rose.py — La Villa Rose (lavillarose.fr)
Plateforme : WordPress + Oxygen/Cornerstone builder (custom CSS classes)
Spécialité : Porsche (911, Boxster, Cayman)
Stratégie  : Phase 1 httpx sur /nos-voitures/ — cards ct-div-block.div-liste-voiture
             Phase 2 httpx sur chaque page détail — labels texte-fiche-1 + values text-fiche-2/3
"""

import httpx
import json
import re
import time
import random
from bs4 import BeautifulSoup
from pathlib import Path

DEALER_KEY  = "la_villa_rose"
DEALER_NAME = "La Villa Rose"
DEALER_URL  = "https://www.lavillarose.fr"
LISTING_URL = "https://www.lavillarose.fr/nos-voitures/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.lavillarose.fr/",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_price(s):
    if not s:
        return None
    digits = re.sub(r"[^\d]", "", str(s))
    v = int(digits) if digits else None
    return v if v and 3000 < v < 5000000 else None

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
    if any(k in t for k in ["manuelle", "mécanique", "mecanique", "manual"]):
        return "Manuelle"
    if any(k in t for k in ["automatique", "automatic", "pdk", "dct", "s-tronic", "dsg", "séquentielle", "robotisée"]):
        return "Automatique"
    return str(s)[:20]

def _get(url, client):
    resp = client.get(url, headers=HEADERS, follow_redirects=True, timeout=20)
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# Phase 1 — Listing /nos-voitures/
# La Villa Rose : les liens vers les fiches sont dans des <a href="/nos-voitures/slug/">
# On récupère aussi le prix et km depuis la card de listing si dispo
# ---------------------------------------------------------------------------

def _fetch_listing_cards(html):
    """
    Retourne une liste de dicts {url, title, prix, km, annee, image_url}
    extraits depuis la page listing.

    La Villa Rose : chaque voiture est dans un div.ct-div-block.div-liste-voiture
    qui contient : h2/h3 (titre), a[href=/nos-voitures/slug/], .liste-infos-voiture
    (km + cv), .prix-voiture (prix TTC), img (photo).
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = []
    seen_urls = set()

    # Iterate over car containers directly
    containers = soup.select("div.div-liste-voiture")
    if not containers:
        # Fallback: any div that has both a car link and a prix-voiture
        containers = [
            div for div in soup.select("div")
            if div.select_one("a[href*='/nos-voitures/']") and
               div.select_one("[class*='prix-voiture']")
        ]

    for container in containers:
        # Car URL
        link_el = container.select_one("a[href*='/nos-voitures/']")
        if not link_el:
            continue
        href = str(link_el.get("href") or "")
        if not href or href in seen_urls or href in (LISTING_URL, DEALER_URL + "/nos-voitures/"):
            continue
        seen_urls.add(href)

        # Title from h2/h3
        title_el = container.select_one("h2, h3")
        title = title_el.get_text(strip=True) if title_el else link_el.get_text(strip=True)
        # Clean status suffixes
        title = re.sub(r"\s*(Réservée?|Bientôt dispo.*|Vendue?)$", "", title, flags=re.IGNORECASE).strip()
        title = re.sub(r"\s*de\s*(20\d{2}|19\d{2})\s*$", "", title).strip()

        # Price: look for a ct-text-block with class prix-voiture that has only digits+€
        prix = None
        for p_el in container.select("[class*='prix-voiture']"):
            classes = " ".join(p_el.get("class") or [])
            # Skip combined blocks like "financement-label"; prefer the clean price sub-block
            t = p_el.get_text(strip=True)
            # Pattern: "182600€" or "58 800 €"
            m_p = re.match(r"^([\d\s\u202f]+)€", t)
            if m_p:
                prix = _clean_price(m_p.group(1))
                if prix:
                    break
        # Fallback: extract first large number before € in the container
        if not prix:
            raw = container.get_text(strip=True)
            m_p = re.search(r"(\d[\d\s\u202f]{3,8})€", raw)
            if m_p:
                prix = _clean_price(m_p.group(1))

        # Year
        annee = None
        card_text = container.get_text(" ", strip=True)
        m_year = re.search(r"\bde\s*(20\d{2}|19\d{2})\b", card_text)
        if m_year:
            annee = int(m_year.group(1))

        # KM from liste-infos-voiture
        km = None
        km_el = container.select_one("[class*='liste-infos-voiture']")
        if km_el:
            km_text = km_el.get_text(strip=True)
            m_km = re.search(r"(\d[\d\s\u202f]{2,6})\s*kms?", km_text, re.IGNORECASE)
            if m_km:
                km = _clean_km(m_km.group(1))

        # Image
        image_url = None
        for img in container.select("img"):
            src = str(img.get("src") or img.get("data-src") or "")
            if "wp-content/uploads" in src and "logo" not in src.lower():
                image_url = src
                break

        cards.append({
            "url":       href,
            "title":     title,
            "prix":      prix,
            "km":        km,
            "annee":     annee,
            "image_url": image_url,
        })

    return cards


# ---------------------------------------------------------------------------
# Phase 2 — Parse page détail
# Structure Oxygen builder :
#   .ct-text-block.texte-fiche-1  → label  (ex: "Kilométrage :")
#   .ct-text-block.text-fiche-2   → valeur (ex: "43500kms")
#   .ct-text-block.text-fiche-3   → valeur (variante couleur)
#   p.my-list-item                → option (ex: "250%Boite de Vitesses PDK")
# ---------------------------------------------------------------------------

def _parse_detail(url, html, base=None):
    """
    Parse la page détail d'une voiture La Villa Rose.
    base = dict partiellement rempli depuis la page listing.
    """
    soup = BeautifulSoup(html, "html.parser")
    b = base or {}

    # Title from h1
    h1 = soup.select_one("h1")
    title = h1.get_text(strip=True) if h1 else b.get("title", "")

    # Image from page (first car upload image)
    image_url = b.get("image_url")
    if not image_url:
        for img in soup.select("img"):
            src = str(img.get("src") or img.get("data-src") or "")
            if "wp-content/uploads" in src and "logo" not in src.lower():
                image_url = src
                break

    # --- Specs: walk ct-text-block elements in order ---
    # texte-fiche-1 → label, text-fiche-2/text-fiche-3 → value
    km       = b.get("km")
    annee    = b.get("annee")
    prix     = b.get("prix")
    tx       = None
    couleur  = None
    puissance_cv = None
    carrosserie  = None
    cylindree    = None
    options_brutes = []

    all_blocks = soup.select(".ct-text-block")
    i = 0
    while i < len(all_blocks):
        block = all_blocks[i]
        classes = " ".join(block.get("class") or [])
        if "texte-fiche-1" in classes:
            label = block.get_text(strip=True).lower().rstrip(":").strip()
            # Next block is the value
            if i + 1 < len(all_blocks):
                val_block = all_blocks[i + 1]
                value = val_block.get_text(strip=True)
                i += 2
                # Map label → field
                if any(k in label for k in ["kilométrage", "km"]):
                    km = km or _clean_km(value)
                elif any(k in label for k in ["année", "annee"]):
                    annee = annee or _clean_year(value)
                elif any(k in label for k in ["boîte", "boite", "type de boite"]):
                    tx = tx or _clean_tx(value)
                elif "coloris" in label or "couleur" in label:
                    couleur = couleur or value.split(" - ")[0].strip()
                elif any(k in label for k in ["cv din", "puissance"]):
                    m_cv = re.search(r"(\d+)", value)
                    puissance_cv = puissance_cv or (int(m_cv.group(1)) if m_cv else None)
                elif "cylindrée" in label or "cylindree" in label:
                    cylindree = value
                continue
        i += 1

    # --- Options from p.my-list-item ---
    # Format: "250%Boite de Vitesses PDK" → strip code prefix
    for li in soup.select("p.my-list-item"):
        raw = li.get_text(strip=True)
        # Remove leading code like "250%" or "250%260%"
        clean = re.sub(r"^[\d%]+", "", raw).strip()
        if clean and 3 < len(clean) < 120:
            options_brutes.append(clean)

    # Description from first big text block (not nav, not specs)
    description = ""
    for el in soup.select(".ct-text-block"):
        t = el.get_text(" ", strip=True)
        classes = " ".join(el.get("class") or [])
        if (len(t) > 80 and
                not any(k in classes for k in ["texte-fiche", "text-fiche", "text-prix", "fil-ariane"]) and
                not any(k in t for k in ["Accueil", "Qui sommes-nous", "crédit"])):
            description = t[:500]
            break

    return {
        "id":            url.rstrip("/").split("/")[-1],
        "source":        DEALER_KEY,
        "dealer_name":   DEALER_NAME,
        "dealer_url":    DEALER_URL,
        "marque":        "Porsche",
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
    print(f"  La Villa Rose — {LISTING_URL}")
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
            debug_path = Path(__file__).parent.parent / "debug_lvr_listing.html"
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
                    print(f"    → {listing['modele']} | {prix_str} € | "
                          f"{listing.get('km') or '?'} km | {listing.get('tx_clean','?')}")
            except Exception as e:
                print(f"    [!] Erreur: {e}")
            time.sleep(random.uniform(0.5, 1.2))

    print(f"\n  Total La Villa Rose: {len(listings)} annonces")
    return listings


if __name__ == "__main__":
    results = scrape()
    out = Path(__file__).parent.parent / "debug_la_villa_rose.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"  Debug: {out}")
