"""
scrapers/symbol_cars.py — Symbol Cars (symbolcars.fr)
Plateforme : PrestaShop — HTML server-rendered
Stratégie  : Phase 1 httpx sur la page listing (avec pagination ?page=N),
             Phase 2 httpx sur chaque page détail produit.
"""

import httpx
import json
import re
import time
import random
from bs4 import BeautifulSoup
from pathlib import Path

DEALER_KEY  = "symbol_cars"
DEALER_NAME = "Symbol Cars"
DEALER_URL  = "https://symbolcars.fr"
LISTING_URL = "https://symbolcars.fr/3-decouvrez-notre-collection"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_price(s):
    """'189 900 €' → 189900"""
    if not s:
        return None
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None

def _clean_km(s):
    """'12 500 km' → 12500"""
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
    if any(k in t for k in ["automatique", "automatic", "pdk", "dct", "s-tronic", "dsg", "séquentielle"]):
        return "Automatique"
    return s[:20]

def _get(url, client):
    resp = client.get(url, headers=HEADERS, follow_redirects=True, timeout=20)
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# Phase 1 — Listing (toutes les pages)
# ---------------------------------------------------------------------------

def _fetch_listing_urls(client, max_pages=10):
    """Retourne la liste des URLs de pages détail trouvées sur le listing."""
    urls = []
    for page_num in range(1, max_pages + 1):
        page_url = LISTING_URL if page_num == 1 else f"{LISTING_URL}?page={page_num}"
        print(f"  [symbol_cars] Listing page {page_num}: {page_url}")
        try:
            html = _get(page_url, client)
        except Exception as e:
            print(f"  [symbol_cars] Erreur page {page_num}: {e}")
            break

        soup = BeautifulSoup(html, "html.parser")

        # Chaque article produit PrestaShop
        articles = soup.select("article.product-miniature")
        if not articles:
            # Essai alternatif : liens directs avec .html
            articles = soup.select(".product-miniature")

        page_urls = []
        for art in articles:
            link = art.select_one("a.thumbnail") or art.select_one("a[href*='.html']") or art.select_one("a")
            if link:
                href = str(link.get("href") or "")
                if href and not href.startswith("http"):
                    href = DEALER_URL + href
                if href and href not in urls:
                    page_urls.append(href)

        if not page_urls:
            print(f"  [symbol_cars] Plus de produits à la page {page_num} — arrêt.")
            break

        urls.extend(page_urls)
        print(f"  [symbol_cars]   → {len(page_urls)} produits trouvés (total: {len(urls)})")
        time.sleep(random.uniform(0.8, 1.5))

    return list(dict.fromkeys(urls))  # dédoublonnage ordre-préservé


# ---------------------------------------------------------------------------
# Phase 2 — Page détail produit
# ---------------------------------------------------------------------------

def _parse_detail(url, html):
    """Parse une page produit PrestaShop — retourne un listing dict ou None."""
    soup = BeautifulSoup(html, "html.parser")

    # --- Titre / Marque / Modèle ---
    h1 = soup.select_one("h1.page-product-heading") or soup.select_one("h1")
    title_raw = h1.get_text(strip=True) if h1 else ""

    # Breadcrumb pour extraire marque
    # Structure: Accueil > Nos véhicules > MARQUE > MODELE > Titre
    # breadcrumbs[2] = MARQUE (ex: "MCLAREN"), breadcrumbs[-2] = MODELE slug
    breadcrumbs = soup.select("nav.breadcrumb li span")
    marque = ""
    if len(breadcrumbs) >= 3:
        marque = breadcrumbs[2].get_text(strip=True).title()  # "MCLAREN" → "Mclaren"
    modele = title_raw

    # --- Prix ---
    # Symbol Cars : prix dans un script JSON (pas dans le HTML visible)
    # Pattern: "price":"107900" ou 'prix': 107900
    # Symbol Cars : le script JSON contient souvent prix HT (ex: 89916) puis prix TTC (107900)
    # On prend le dernier prix valide dans la plage réaliste (> 5000 ET <= 2M€)
    prix = None
    prix_candidates = []
    for m in re.finditer(r"[\"'](?:price|prix)[\"']\s*:\s*[\"']?([\d.,\s]+)[\"']?",
                         html, re.IGNORECASE):
        raw = re.sub(r"[^\d.,]", "", m.group(1)).replace(",", ".")
        try:
            val = int(float(raw))
        except Exception:
            continue
        if 5000 < val < 2000000:
            prix_candidates.append(val)
    # Prendre le prix le plus élevé (TTC > HT)
    if prix_candidates:
        prix = max(prix_candidates)
    # Fallback éléments HTML
    if not prix:
        for el in soup.select(".current-price, .product-price, meta[itemprop='price']"):
            content = el.get("content") or el.get_text()
            v = _clean_price(content)
            if v and 3000 < v < 5000000:
                prix = v
                break

    # --- Image ---
    img_el = soup.select_one(".product-cover img") or soup.select_one("img.js-qv-product-cover")
    image_url = img_el.get("src") or img_el.get("data-src") if img_el else None

    # --- Caractéristiques Symbol Cars (thème custom PrestaShop) ---
    # Structure: div.prdtInfo.prdt-km / div.prdtInfo.prdt-year / etc.
    # + span.prdtValue pour les valeurs
    km, annee, tx, couleur, puissance_cv, carrosserie = None, None, None, None, None, None
    options_brutes = []
    description = ""

    # Méthode 1 : divs prdtInfo — Symbol Cars concatène label:valeur dans le div
    # ex: div.prdt-km -> "Kilométrage :51400 Km"
    # ex: div.prdt-year -> "Année :2019"
    for el in soup.select(".prdtInfo"):
        full = el.get_text(strip=True)
        # Format "Label :Valeur"
        if ":" in full:
            parts = full.split(":", 1)
            label = parts[0].lower().strip()
            value = parts[1].strip()
        else:
            label, value = full.lower(), full

        if any(k in label for k in ["kilométrage", "km", "kilometrage"]):
            km = km or _clean_km(value)
        elif any(k in label for k in ["année", "annee"]):
            annee = annee or _clean_year(value)
        elif "puissance" in label:
            m_pw = re.search(r"(\d+)", value)
            puissance_cv = puissance_cv or (int(m_pw.group(1)) if m_pw else None)
        elif any(k in label for k in ["boîte", "boite", "transmission"]):
            tx = tx or _clean_tx(value)

    # Méthode 3 : features (span.feature-label + span suivant)
    for label_el in soup.select("span.feature-label"):
        label = label_el.get_text(strip=True).lower().rstrip(":")
        val_el = label_el.find_next_sibling("span") or label_el.find_next_sibling()
        value = val_el.get_text(strip=True) if val_el else ""
        if not value and label_el.parent:
            # Essai: texte du parent après le label
            parent_text = label_el.parent.get_text(strip=True)
            value = parent_text.replace(label_el.get_text(strip=True), "").strip()

        if any(k in label for k in ["couleur ext", "couleur"]):
            couleur = couleur or value
        elif "puissance" in label:
            m_pw = re.search(r"(\d+)", value)
            puissance_cv = puissance_cv or (int(m_pw.group(1)) if m_pw else None)
        elif any(k in label for k in ["carrosserie", "type"]):
            carrosserie = carrosserie or value
        elif any(k in label for k in ["boîte", "boite", "transmission"]):
            tx = tx or _clean_tx(value)

    # Méthode 4 : fallback global via regex sur le texte
    all_text = soup.get_text()
    if not km:
        m = re.search(r"(\d[\d\s\u202f]{2,6})\s*[Kk]m", all_text)
        if m:
            km = _clean_km(m.group(1))
    if not annee:
        m = re.search(r"Année\s*[:\s]+(\d{4})", all_text)
        if m:
            annee = int(m.group(1))

    # Description — JSON-LD ou meta description
    import json as _json
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            d = _json.loads(script.string or "")
            if isinstance(d, dict) and d.get("description"):
                description = d["description"][:500]
                break
        except Exception:
            pass
    if not description:
        desc_el = (soup.select_one(".product-description-short") or
                   soup.select_one(".product-description") or
                   soup.select_one("[itemprop='description']"))
        if desc_el:
            description = desc_el.get_text(" ", strip=True)[:500]

    # Options / équipements
    for eq in soup.select(".product-features li, .equipements li, .options li,  "
                          "ul.features-list li, .feature-list li"):
        t = eq.get_text(strip=True)
        if t and 3 < len(t) < 120:
            options_brutes.append(t)

    # Extraction km/année depuis le titre si toujours vide
    if not km:
        m = re.search(r"(\d{2,3}[\s\u202f]?\d{3})\s*km", title_raw, re.IGNORECASE)
        if m:
            km = _clean_km(m.group(1))
    if not annee:
        m = re.search(r"\b(20\d{2}|19\d{2})\b", title_raw)
        if m:
            annee = int(m.group(1))

    listing = {
        "id":            url.split("/")[-1].replace(".html", ""),
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
        "options_brutes":options_brutes,
        "url":           url,
        "image_url":     image_url,
    }
    return listing


# ---------------------------------------------------------------------------
# Entrée principale
# ---------------------------------------------------------------------------

def scrape(max_pages=10):
    print(f"\n{'='*60}")
    print(f"  Symbol Cars — {LISTING_URL}")
    print(f"{'='*60}")

    listings = []
    with httpx.Client(follow_redirects=True, timeout=20) as client:
        detail_urls = _fetch_listing_urls(client, max_pages=max_pages)
        print(f"\n  {len(detail_urls)} pages détail à visiter...")

        for i, url in enumerate(detail_urls, 1):
            print(f"  [{i}/{len(detail_urls)}] {url}")
            try:
                html = _get(url, client)
                listing = _parse_detail(url, html)
                if listing:
                    listings.append(listing)
                    print(f"    → {listing.get('marque')} {listing.get('modele')} | {listing.get('prix'):,} € | {listing.get('km') or '?'} km")
            except Exception as e:
                print(f"    [!] Erreur: {e}")
            time.sleep(random.uniform(0.5, 1.2))

    print(f"\n  Total Symbol Cars: {len(listings)} annonces")
    return listings


if __name__ == "__main__":
    results = scrape()
    out = Path(__file__).parent.parent / "debug_symbol_cars.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"  Debug: {out}")
