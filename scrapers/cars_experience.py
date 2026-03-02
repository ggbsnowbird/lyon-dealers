"""
scrapers/cars_experience.py — Cars Experience (cars-experience.fr)
Plateforme : WordPress + Elementor + Infolio theme (Portfolio CPT)
Stratégie  : Phase 1 httpx sur /index.php/a-la-vente/ (grille de voitures),
             Phase 2 httpx sur chaque page détail /index.php/portfolio/{slug}/
Options    : Structurées en listes (Extérieur / Intérieur / Entretien) sur les pages détail.
"""

import httpx
import json
import re
import time
import random
from bs4 import BeautifulSoup
from pathlib import Path

DEALER_KEY  = "cars_experience"
DEALER_NAME = "Cars Experience"
DEALER_URL  = "https://cars-experience.fr"
LISTING_URL = "https://cars-experience.fr/index.php/a-la-vente/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://cars-experience.fr/",
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

def _parse_brand_model(title):
    known_brands = [
        "Porsche", "Ferrari", "Lamborghini", "McLaren", "Bentley", "Maserati",
        "Aston Martin", "Rolls-Royce", "BMW", "Mercedes", "Audi", "Alpine",
        "Lotus", "Jaguar", "Land Rover", "Bugatti", "Pagani", "Abarth",
    ]
    title_clean = title.strip()
    for brand in known_brands:
        if brand.lower() in title_clean.lower():
            return brand, title_clean
    # Première partie du titre comme marque
    parts = title_clean.split()
    if parts:
        return parts[0], title_clean
    return "", title_clean


# ---------------------------------------------------------------------------
# Phase 1 — Listing Elementor Portfolio
# ---------------------------------------------------------------------------

def _fetch_listing_urls(client, max_pages=20):
    """
    Cars Experience : grille Elementor Portfolio server-rendée.
    Page 1 = /index.php/a-la-vente/
    Page N = /index.php/a-la-vente/page/N/ (WordPress pagination)
    """
    urls = []
    for page_num in range(1, max_pages + 1):
        if page_num == 1:
            page_url = LISTING_URL
        else:
            page_url = f"{LISTING_URL}page/{page_num}/"

        print(f"  [cars_experience] Listing page {page_num}: {page_url}")
        try:
            html = _get(page_url, client)
        except Exception as e:
            print(f"  [cars_experience] Erreur page {page_num}: {e}")
            break

        soup = BeautifulSoup(html, "html.parser")

        # Elementor Portfolio : liens vers les articles du portfolio
        page_urls = []
        for a in soup.select("article a, .elementor-portfolio-item a, .portfolio-item a"):
            href = str(a.get("href") or "")
            if href and "portfolio" in href:
                if not href.startswith("http"):
                    href = DEALER_URL + href
                if href not in urls and href not in page_urls:
                    page_urls.append(href)

        # Fallback : tous les liens qui pointent vers des slugs sous /portfolio/
        if not page_urls:
            for a in soup.select("a[href*='/portfolio/']"):
                href = str(a.get("href") or "")
                if href:
                    if not href.startswith("http"):
                        href = DEALER_URL + href
                    if href not in urls and href not in page_urls:
                        page_urls.append(href)

        if not page_urls:
            print(f"  [cars_experience] Plus de produits à la page {page_num} — arrêt.")
            break

        urls.extend(page_urls)
        print(f"  [cars_experience]   → {len(page_urls)} annonces (total: {len(urls)})")
        time.sleep(random.uniform(0.8, 1.5))

    return list(dict.fromkeys(urls))


# ---------------------------------------------------------------------------
# Phase 2 — Page détail portfolio
# ---------------------------------------------------------------------------

def _parse_detail(url, html):
    """
    Parse une page portfolio Elementor WordPress.
    Structure attendue :
    - H1 : titre complet de la voiture
    - Sections Extérieur / Intérieur / Entretien (listes ul/ol)
    - Caractéristiques dans un widget dédié (tableau ou liste)
    """
    soup = BeautifulSoup(html, "html.parser")

    # Titre
    h1 = soup.select_one("h1.elementor-heading-title, h1.entry-title, h1")
    title_raw = h1.get_text(strip=True) if h1 else ""
    marque, modele = _parse_brand_model(title_raw)

    # Image principale
    img_el = (soup.select_one(".elementor-widget-image img") or
              soup.select_one("figure.wp-block-image img") or
              soup.select_one(".wp-post-image") or
              soup.select_one("img.attachment-full") or
              soup.select_one("img"))
    image_url = None
    if img_el:
        src = str(img_el.get("src") or img_el.get("data-src") or img_el.get("data-lazy-src") or "")
        if src and not src.startswith("http"):
            src = DEALER_URL + src
        image_url = src or None

    # Caractéristiques: prix, km, année, tx, couleur, puissance
    prix, km, annee, tx, couleur, puissance_cv, carrosserie = None, None, None, None, None, None, None
    description = ""
    options_brutes = []

    # Tous les textes dans des widgets Elementor (tables + listes de caractéristiques)
    # Cars Experience a une section "caractéristiques" avec des paires label/valeur
    all_text = soup.get_text(" ", strip=True)

    # Prix — chercher patterns communs
    for el in soup.select("[class*='price'], [class*='prix'], .elementor-text-editor strong, strong, b"):
        v = _clean_price(el.get_text())
        if v and 5000 < v < 2000000:
            prix = v
            break

    # Tableau ou liste de specs Elementor
    for row in soup.select("table tr"):
        cells = row.select("td, th")
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True).lower()
            value = cells[1].get_text(strip=True)
            _apply_spec(label, value,
                        locals_dict={"km": km, "annee": annee, "tx": tx,
                                     "couleur": couleur, "puissance_cv": puissance_cv,
                                     "carrosserie": carrosserie})

    # Réassignation manuelle (Python closures ne modifient pas les locals)
    for row in soup.select("table tr"):
        cells = row.select("td, th")
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True).lower()
            value = cells[1].get_text(strip=True)
            if any(k in label for k in ["kilométrage", "km", "kilometrage"]):
                km = km or _clean_km(value)
            elif any(k in label for k in ["année", "annee", "mise en circulation", "date"]):
                annee = annee or _clean_year(value)
            elif any(k in label for k in ["boîte", "boite", "transmission"]):
                tx = _clean_tx(value)
            elif "couleur" in label:
                couleur = couleur or value
            elif "puissance" in label:
                m = re.search(r"(\d+)", value)
                puissance_cv = puissance_cv or (int(m.group(1)) if m else None)
            elif "carrosserie" in label:
                carrosserie = carrosserie or value

    # Listes Elementor (souvent sous forme de colonnes label/valeur en li)
    for li in soup.select(".elementor-text-editor li, .car-specs li, .specs li"):
        text = li.get_text(strip=True)
        if ":" in text:
            parts = text.split(":", 1)
            label, value = parts[0].lower(), parts[1].strip()
            if any(k in label for k in ["km", "kilométrage"]):
                km = km or _clean_km(value)
            elif any(k in label for k in ["année", "annee"]):
                annee = annee or _clean_year(value)
            elif any(k in label for k in ["boîte", "boite", "tx", "transmission"]):
                tx = tx or _clean_tx(value)
            elif "couleur" in label:
                couleur = couleur or value
            elif "puissance" in label:
                m_pw = re.search(r"(\d+)", value)
                puissance_cv = puissance_cv or (int(m_pw.group(1)) if m_pw else None)
            elif "carrosserie" in label:
                carrosserie = carrosserie or value

    # Options : sections Extérieur / Intérieur / Entretien
    current_section = ""
    for el in soup.select("h2, h3, h4, ul li, ol li"):
        if el.name in ["h2", "h3", "h4"]:
            heading = el.get_text(strip=True).lower()
            if any(k in heading for k in ["extérieur", "intérieur", "entretien", "option", "équipement"]):
                current_section = el.get_text(strip=True)
        elif el.name == "li":
            t = el.get_text(strip=True)
            if t and 3 < len(t) < 120:
                options_brutes.append(t)

    # Description
    for sel in [".elementor-text-editor p", ".entry-content p", "article p"]:
        for p in soup.select(sel):
            t = p.get_text(" ", strip=True)
            if len(t) > 50 and not re.search(r"cookie|gdpr|privacy|©", t, re.IGNORECASE):
                description = t[:500]
                break
        if description:
            break

    # Fallback km/année depuis URL ou titre
    if not km:
        m = re.search(r"(\d[\d\s]{2,6})\s*km", all_text, re.IGNORECASE)
        if m:
            km = _clean_km(m.group(1))
    if not annee:
        m = re.search(r"\b(20\d{2}|19\d{2})\b", title_raw)
        if m:
            annee = int(m.group(1))

    slug = url.rstrip("/").split("/")[-1]
    return {
        "id":            slug,
        "source":        DEALER_KEY,
        "dealer_name":   DEALER_NAME,
        "dealer_url":    DEALER_URL,
        "marque":        marque,
        "modele":        modele,
        "annee":         annee,
        "km":            km,
        "prix":          prix,
        "tx_clean":      tx or "?",
        "couleur":       couleur,
        "carrosserie":   carrosserie,
        "puissance_cv":  puissance_cv,
        "puissance_kw":  None,
        "description":   description,
        "options_brutes":list(dict.fromkeys(options_brutes)),  # dédoublonnage
        "url":           url,
        "image_url":     image_url,
    }

def _apply_spec(label, value, locals_dict):
    """Helper no-op utilisé pour éviter les closures."""
    pass


# ---------------------------------------------------------------------------
# Entrée principale
# ---------------------------------------------------------------------------

def scrape(max_pages=20):
    print(f"\n{'='*60}")
    print(f"  Cars Experience — {LISTING_URL}")
    print(f"{'='*60}")

    listings = []
    with httpx.Client(follow_redirects=True, timeout=20) as client:
        detail_urls = _fetch_listing_urls(client, max_pages=max_pages)
        print(f"\n  {len(detail_urls)} annonces à visiter...")

        if not detail_urls:
            try:
                html = _get(LISTING_URL, client)
                debug_path = Path(__file__).parent.parent / "debug_cars_experience_listing.html"
                with open(debug_path, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"  [!] Aucune URL trouvée — HTML sauvé: {debug_path}")
            except Exception as e:
                print(f"  [!] Erreur: {e}")
            return listings

        for i, url in enumerate(detail_urls, 1):
            print(f"  [{i}/{len(detail_urls)}] {url}")
            try:
                html = _get(url, client)
                listing = _parse_detail(url, html)
                if listing:
                    listings.append(listing)
                    prix_str = f"{listing['prix']:,}" if listing.get('prix') else '?'
                    print(f"    → {listing.get('marque')} {listing.get('modele')} | "
                          f"{prix_str} € | {listing.get('km') or '?'} km | "
                          f"{len(listing.get('options_brutes', []))} options")
            except Exception as e:
                print(f"    [!] Erreur: {e}")
            time.sleep(random.uniform(0.7, 1.4))

    print(f"\n  Total Cars Experience: {len(listings)} annonces")
    return listings


if __name__ == "__main__":
    results = scrape()
    out = Path(__file__).parent.parent / "debug_cars_experience.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"  Debug: {out}")
