"""
scrapers/my_exclusive_car.py — My Exclusive Car (myexclusivecar.fr)
Plateforme : PHP custom (annonces-auto)
Stratégie  : Phase 1 httpx sur /voitures (listing) + RSS feed optionnel,
             Phase 2 httpx sur chaque page annonce détail.
"""

import httpx
import json
import re
import time
import random
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from pathlib import Path

DEALER_KEY  = "my_exclusive_car"
DEALER_NAME = "My Exclusive Car"
DEALER_URL  = "https://www.myexclusivecar.fr"
LISTING_URL = "https://www.myexclusivecar.fr/voitures"
RSS_URL     = "https://www.myexclusivecar.fr/rss/annonces.xml"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.myexclusivecar.fr/",
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
# Stratégie A — RSS Feed (rapide et structuré)
# ---------------------------------------------------------------------------

def _fetch_from_rss(client):
    """Essaie de récupérer les annonces via le flux RSS."""
    try:
        resp = client.get(RSS_URL, headers=HEADERS, follow_redirects=True, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except Exception as e:
        print(f"  [mec] RSS non disponible: {e}")
        return []

    items = []
    for item in root.findall(".//item"):
        title = item.findtext("title") or ""
        link  = item.findtext("link") or ""
        desc  = item.findtext("description") or ""

        # Extraire les données depuis la description RSS (souvent du HTML)
        soup_desc = BeautifulSoup(desc, "html.parser")
        full_text = soup_desc.get_text(" ", strip=True)

        prix = None
        m_prix = re.search(r"(\d[\d\s]{3,8})\s*€", full_text)
        if m_prix:
            prix = _clean_price(m_prix.group(1))

        km = None
        m_km = re.search(r"(\d[\d\s]{2,6})\s*km", full_text, re.IGNORECASE)
        if m_km:
            km = _clean_km(m_km.group(1))

        annee = _clean_year(full_text)

        # Image depuis description HTML
        img_el = soup_desc.select_one("img")
        image_url = str(img_el.get("src") or "") if img_el else None

        # Marque/modèle depuis le titre
        marque, modele = _parse_brand_model(title)

        items.append({
            "title": title,
            "url":   link,
            "prix":  prix,
            "km":    km,
            "annee": annee,
            "image_url": image_url,
            "marque": marque,
            "modele": modele,
            "description": full_text[:300],
        })

    print(f"  [mec] RSS: {len(items)} annonces")
    return items


# ---------------------------------------------------------------------------
# Stratégie B — Page listing HTML
# ---------------------------------------------------------------------------

def _fetch_listing_urls(client, max_pages=10):
    """Récupère les URLs de détail depuis la page /voitures."""
    urls = []
    for page_num in range(1, max_pages + 1):
        # myexclusivecar.fr utilise probablement ?page=N ou /voitures/page/N
        if page_num == 1:
            page_url = LISTING_URL
        else:
            page_url = f"{LISTING_URL}?page={page_num}"

        print(f"  [mec] Listing page {page_num}: {page_url}")
        try:
            html = _get(page_url, client)
        except Exception as e:
            print(f"  [mec] Erreur: {e}")
            break

        soup = BeautifulSoup(html, "html.parser")

        # Chercher tous les liens d'annonces
        page_urls = []
        for a in soup.select("a[href*='/voiture/'], a[href*='/annonce/'], a[href*='-occasion'], "
                             "a.car-link, a.annonce-link, .car-item a, .annonce-item a"):
            href = str(a.get("href") or "")
            if href:
                if not href.startswith("http"):
                    href = DEALER_URL + href
                if href not in urls and href != LISTING_URL:
                    page_urls.append(href)

        if not page_urls:
            if page_num > 1:
                break
            # Essai : trouver des liens d'annonces de manière générique
            for a in soup.select("h2 a, h3 a, .title a, .car-title a"):
                href = str(a.get("href") or "")
                if href and DEALER_URL in href or (href and href.startswith("/")):
                    if not href.startswith("http"):
                        href = DEALER_URL + href
                    if href not in urls:
                        page_urls.append(href)

        urls.extend(page_urls)
        if not page_urls:
            break
        time.sleep(random.uniform(0.8, 1.5))

    return list(dict.fromkeys(urls))


# ---------------------------------------------------------------------------
# Parse page détail
# ---------------------------------------------------------------------------

def _parse_brand_model(title):
    """Extrait marque et modèle depuis un titre type 'Porsche 911 Carrera 4S 2019'."""
    # Marques communes
    known_brands = [
        "Porsche", "Ferrari", "Lamborghini", "McLaren", "Bentley", "Maserati",
        "Aston Martin", "Rolls-Royce", "BMW", "Mercedes", "Audi", "Alpine",
        "Lotus", "Jaguar", "Land Rover", "Bugatti", "Pagani", "Koenigsegg",
    ]
    for brand in known_brands:
        if brand.lower() in title.lower():
            modele = title.strip()
            return brand, modele
    return "", title.strip()

def _parse_detail(url, html):
    """Parse une page annonce My Exclusive Car."""
    soup = BeautifulSoup(html, "html.parser")

    # Titre
    h1 = soup.select_one("h1") or soup.select_one(".car-title, .annonce-title")
    title_raw = h1.get_text(strip=True) if h1 else ""
    marque, modele = _parse_brand_model(title_raw)

    # Prix — myexclusivecar.fr : <div class="second" id="prix"><span>219.900</span> €</div>
    prix = None
    prix_el = soup.select_one("#prix span, #prix")
    if prix_el:
        raw = prix_el.get_text(strip=True).replace(".", "").replace("\xa0", "").replace(" ", "")
        raw = re.sub(r"[^\d]", "", raw)
        if raw and len(raw) <= 8:
            prix = int(raw)
    # Fallback générique
    if not prix:
        for el in soup.select(".price, .prix, [class*='price'], [class*='prix']"):
            v = _clean_price(el.get_text())
            if v and 3000 < v < 5000000:
                prix = v
                break

    # Image — myexclusivecar.fr : photos sur auto.cdn-rivamedia.com, classe "bigimg"
    img_el = (soup.select_one("img.bigimg") or
              soup.select_one("img[src*='cdn-rivamedia']") or
              soup.select_one(".car-photo img, .main-photo img, .photo-principale img") or
              soup.select_one("img[src*='upload'], img[src*='photo'], img[class*='main']"))
    image_url = None
    if img_el:
        image_url = str(img_el.get("src") or img_el.get("data-src") or "")
        if image_url and not image_url.startswith("http"):
            image_url = DEALER_URL + image_url
        if not image_url or "logo" in image_url.lower():
            image_url = None

    # Caractéristiques
    km, annee, tx, couleur, puissance_cv, carrosserie = None, None, None, None, None, None
    options_brutes = []
    description = ""

    # myexclusivecar.fr : tableau HTML avec td.legend (label) + td sans class (valeur)
    for row in soup.select("table tr"):
        cells = row.select("td")
        if not cells:
            continue
        # Format: td.legend / td (valeur) paires
        for i in range(0, len(cells) - 1, 2):
            label = cells[i].get_text(strip=True).lower()
            value = cells[i+1].get_text(strip=True) if i+1 < len(cells) else ""
            if any(k in label for k in ["kilométrage", "km", "kilometrage"]):
                km = km or _clean_km(value)
            elif any(k in label for k in ["année", "annee", "mise en circulation"]):
                annee = annee or _clean_year(value)
            elif any(k in label for k in ["boîte", "boite", "transmission", "gearbox"]):
                tx = tx or _clean_tx(value)
            elif any(k in label for k in ["couleur ext", "couleur"]):
                couleur = couleur or value
            elif "puissance" in label:
                m = re.search(r"(\d+)", value)
                puissance_cv = puissance_cv or (int(m.group(1)) if m else None)
            elif any(k in label for k in ["carrosserie", "catégorie"]):
                carrosserie = carrosserie or value
            elif "marque" in label:
                if not marque:
                    marque = value
            elif "modèle" in label or "modele" in label:
                if not modele or modele == title_raw:
                    modele = modele  # garder le titre complet

    # Description — myexclusivecar.fr utilise .box
    desc_el = soup.select_one(".box")
    if desc_el:
        description = desc_el.get_text(" ", strip=True)[:500]
    if not description:
        for sel in [".description", ".car-description", ".annonce-description", "article p"]:
            desc_el = soup.select_one(sel)
            if desc_el:
                t = desc_el.get_text(" ", strip=True)
                if len(t) > 30:
                    description = t[:500]
                    break

    # Options — chercher dans les listes de la page
    for el in soup.select(".options li, .equipements li, .features li, .equipment li, ul li"):
        t = el.get_text(strip=True)
        if t and 3 < len(t) < 100 and t not in options_brutes:
            options_brutes.append(t)

    # Extraire km depuis texte si pas trouvé
    if not km:
        m = re.search(r"(\d[\d\s]{2,6})\s*km", soup.get_text(), re.IGNORECASE)
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
        "options_brutes":options_brutes,
        "url":           url,
        "image_url":     image_url,
    }


# ---------------------------------------------------------------------------
# Entrée principale
# ---------------------------------------------------------------------------

def scrape(max_pages=10):
    print(f"\n{'='*60}")
    print(f"  My Exclusive Car — {LISTING_URL}")
    print(f"{'='*60}")

    listings = []
    with httpx.Client(follow_redirects=True, timeout=20) as client:
        # Essai RSS d'abord
        rss_items = _fetch_from_rss(client)

        # Listing HTML
        detail_urls = _fetch_listing_urls(client, max_pages=max_pages)

        # Fusionner les URLs (RSS peut donner des liens directs aussi)
        rss_urls = {item["url"] for item in rss_items if item.get("url")}
        all_urls = list(dict.fromkeys(detail_urls + list(rss_urls)))

        if not all_urls:
            print(f"  [!] Aucune URL d'annonce trouvée")
            # Sauvegarder HTML debug
            try:
                html = _get(LISTING_URL, client)
                debug_path = Path(__file__).parent.parent / "debug_mec_listing.html"
                with open(debug_path, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"  [!] HTML sauvé: {debug_path}")
            except Exception as e:
                print(f"  [!] Impossible de récupérer la page: {e}")
            return listings

        print(f"\n  {len(all_urls)} annonces à visiter...")
        rss_by_url = {item["url"]: item for item in rss_items}

        for i, url in enumerate(all_urls, 1):
            print(f"  [{i}/{len(all_urls)}] {url}")
            try:
                html = _get(url, client)
                listing = _parse_detail(url, html)

                # Enrichir avec données RSS si disponibles
                if url in rss_by_url:
                    rss = rss_by_url[url]
                    listing["prix"]  = listing["prix"]  or rss.get("prix")
                    listing["km"]    = listing["km"]    or rss.get("km")
                    listing["annee"] = listing["annee"] or rss.get("annee")
                    listing["image_url"] = listing["image_url"] or rss.get("image_url")

                if listing:
                    listings.append(listing)
                    prix_str = f"{listing['prix']:,}" if listing.get('prix') else '?'
                    print(f"    → {listing.get('marque')} {listing.get('modele')} | "
                          f"{prix_str} € | {listing.get('km') or '?'} km")
            except Exception as e:
                print(f"    [!] Erreur: {e}")
            time.sleep(random.uniform(0.6, 1.3))

    print(f"\n  Total My Exclusive Car: {len(listings)} annonces")
    return listings


if __name__ == "__main__":
    results = scrape()
    out = Path(__file__).parent.parent / "debug_my_exclusive_car.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"  Debug: {out}")
