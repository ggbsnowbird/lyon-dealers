"""
scrapers/flat69.py — Flat69 (flat69.fr)
Plateforme : PHP old-school statique, Bootstrap 4
Stratégie  : Phase 1 httpx sur /occasion-porsche-lyon/ pour lister les voitures,
             Phase 2 httpx sur chaque page détail (fragment #fiche inclus dans URL).
Spécialité : Porsche uniquement, petit stock (~7 véhicules).
"""

import httpx
import json
import re
import time
import random
from bs4 import BeautifulSoup
from pathlib import Path

DEALER_KEY  = "flat69"
DEALER_NAME = "Flat69"
DEALER_URL  = "https://www.flat69.fr"
LISTING_URL = "https://www.flat69.fr/occasion-porsche-lyon/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.flat69.fr/",
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
    # Flat69 utilise #fiche comme fragment — on retire le fragment pour httpx
    clean_url = url.split("#")[0]
    resp = client.get(clean_url, headers=HEADERS, follow_redirects=True, timeout=20)
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# Phase 1 — Parse la page listing
# ---------------------------------------------------------------------------

def _fetch_listing_urls(html):
    """
    Flat69 : chaque voiture dans un div.miniature_occasions.
    Les URLs sont du type /occasion-porsche-lyon/{SLUG}#fiche
    """
    soup = BeautifulSoup(html, "html.parser")

    # Sélecteurs possibles
    cards = soup.select("div.miniature_occasions, .car-card, .vehicle-item")
    if not cards:
        # Fallback : chercher tous les liens contenant "occasion" ou des slugs de voitures
        cards = soup.select("a[href*='PORSCHE'], a[href*='occasion']")

    urls = []
    for card in cards:
        # Lien principal de la carte
        link = None
        if card.name == "a":
            link = card
        else:
            link = card.select_one("a[href*='PORSCHE'], a[href*='porsche'], a[href*='#fiche'], a")
        if link:
                    href = str(link.get("href") or "")
                    if href:
                        if not href.startswith("http"):
                            # Flat69 : hrefs relatifs sans slash initial
                            if not href.startswith("/"):
                                href = LISTING_URL + href
                            else:
                                href = DEALER_URL + href
                        if href not in urls:
                            urls.append(href)

    # Si rien trouvé avec les cartes, chercher tous les liens vers des fiches détail
    if not urls:
        for a in soup.select("a[href*='#fiche'], a[href*='PORSCHE']"):
            href = str(a.get("href") or "")
            if href:
                if not href.startswith("http"):
                    href = DEALER_URL + href
                full_url = href.split("#")[0]  # URL de base sans fragment
                if full_url not in [u.split("#")[0] for u in urls]:
                    urls.append(href)

    return urls


# ---------------------------------------------------------------------------
# Phase 2 — Parse une page détail Flat69
# ---------------------------------------------------------------------------

def _parse_detail(url, html):
    """
    Flat69 : la page listing EST la page détail — toutes les fiches sont
    sur la même page /occasion-porsche-lyon/ avec des ancres #fiche.
    On récupère l'id depuis l'URL et on cherche la section correspondante.
    """
    soup = BeautifulSoup(html, "html.parser")
    listings = []

    # Chercher toutes les fiches voiture sur la page
    # Flat69 utilise une structure répétée pour chaque voiture
    vehicle_sections = (soup.select(".fiche_occasion, .vehicle-detail, div[id*='fiche']") or
                        soup.select("div.col-md-6, div.col-lg-6"))

    # Si on ne trouve pas de sections structurées, parse la page entière
    # et extrait tous les véhicules des miniatures
    miniatures = soup.select("div.miniature_occasions, .car-item, .occasion-item")

    if miniatures:
        for mini in miniatures:
            # Flat69 structure : .modele_min, .type_min, .annee_min, .km_min, .prix_min
            title_el = (mini.select_one(".modele_min a") or
                        mini.select_one(".modele_min") or
                        mini.select_one("h2, h3, .car-name"))
            type_el  = mini.select_one(".type_min")
            prix_el  = (mini.select_one(".prix_min") or
                        mini.select_one(".price, .prix, [class*='prix'], strong, b"))
            km_el    = (mini.select_one(".km_min") or mini.select_one(".km, [class*='km']"))
            year_el  = (mini.select_one(".annee_min") or
                        mini.select_one(".year, .annee, [class*='annee']"))
            link_el  = mini.select_one("a")
            img_el   = mini.select_one("img")

            title  = title_el.get_text(strip=True) if title_el else ""
            type_str = type_el.get_text(strip=True) if type_el else ""  # ex: "(992)"
            # title_el already contains e.g. "911 Carrera S" — just prepend "Porsche"
            # type_str adds the generation suffix "(992)"
            if type_str and type_str not in title:
                title_full = f"Porsche {title} {type_str}".strip() if title else f"Porsche {type_str}"
            else:
                title_full = f"Porsche {title}".strip() if title else "Porsche 911"
            prix   = _clean_price(prix_el.get_text() if prix_el else "")
            km     = _clean_km(km_el.get_text() if km_el else "")
            annee  = _clean_year(year_el.get_text() if year_el else "")
            href   = str(link_el.get("href") or "") if link_el else ""
            # Flat69 : la vraie image est dans l'attribut style de l'img
            # ex: style="background:url(photos_listing/mini_9983202664.jpg) no-repeat;"
            # On préfère l'image _1.jpg (grande) depuis img-occasion-mobile si dispo,
            # sinon la miniature depuis l'img principale.
            img = None
            # 1. Chercher img-occasion-mobile avec background photo _1.jpg
            for mobile_img in mini.select("img.img-occasion-mobile"):
                style = str(mobile_img.get("style") or "")
                m_url = re.search(r"url\(([^)]+)\)", style)
                if m_url:
                    raw = m_url.group(1).strip("'\"")
                    if "_1.jpg" in raw or "_2.jpg" in raw:
                        img = raw
                        break
            # 2. Fallback : miniature depuis l'img principale (style background)
            if not img and img_el:
                style = str(img_el.get("style") or "")
                m_url = re.search(r"url\(([^)]+)\)", style)
                if m_url:
                    img = m_url.group(1).strip("'\"")

            # Flat69 : hrefs relatifs (sans slash initial)
            if href and not href.startswith("http"):
                if not href.startswith("/"):
                    href = LISTING_URL + href
                else:
                    href = DEALER_URL + href
            if not href:
                href = LISTING_URL
            # Résoudre l'URL image relative — base = DEALER_URL/occasion-porsche-lyon/
            if img and not img.startswith("http"):
                img = f"{DEALER_URL}/occasion-porsche-lyon/{img}"

            # Chercher km et année dans le titre si vide
            if not km:
                m = re.search(r"(\d[\d\s]{2,6})\s*km", mini.get_text(), re.IGNORECASE)
                if m:
                    km = _clean_km(m.group(1))
            if not annee:
                m = re.search(r"\b(20\d{2}|19\d{2})\b", mini.get_text())
                if m:
                    annee = int(m.group(1))

            # Type/modèle depuis le titre — toujours Porsche
            modele = title_full
            carrosserie = None
            m_type = re.search(r"\((\d{3})\)", title)  # ex. (992)
            if m_type:
                carrosserie = m_type.group(1)

            # Couleur dans le titre
            couleur = None
            # Flat69 met la couleur dans l'URL-slug et le titre : "Argent GT Métallisé"
            couleur_patterns = [
                r"(Noir|Blanc|Rouge|Bleu|Argent|Gris|Vert|Jaune|Orange|Violet|Beige|Marron|"
                r"GT Silver|Guards Red|Racing Yellow|Basalt|Craie|Python|Aventurine)",
            ]
            for pat in couleur_patterns:
                m_c = re.search(pat, title, re.IGNORECASE)
                if m_c:
                    couleur = m_c.group(1)
                    break

            slug = href.rstrip("/").split("/")[-1].split("#")[0]
            listing = {
                "id":            slug or title.replace(" ", "_")[:30],
                "source":        DEALER_KEY,
                "dealer_name":   DEALER_NAME,
                "dealer_url":    DEALER_URL,
                "marque":        "Porsche",
                "modele":        modele,
                "annee":         annee,
                "km":            km,
                "prix":          prix,
                "tx_clean":      "?",
                "couleur":       couleur,
                "carrosserie":   carrosserie,
                "puissance_cv":  None,
                "puissance_kw":  None,
                "description":   "",
                "options_brutes":[],
                "url":           href,
                "image_url":     img or None,
            }
            listings.append(listing)

    return listings


# ---------------------------------------------------------------------------
# Parse page détail individuelle (URL#fiche)
# ---------------------------------------------------------------------------

def _parse_single_fiche(url, html, base_listing=None):
    """
    Enrichit un listing avec les données de la page détail complète.
    Flat69 affiche tout sur la page listing — mais on peut aller sur
    la page individuelle pour récupérer les specs complètes.
    """
    soup = BeautifulSoup(html, "html.parser")
    l = base_listing or {}

    # Tableau de caractéristiques
    tx = l.get("tx_clean", "?")
    puissance_cv = l.get("puissance_cv")
    couleur = l.get("couleur")
    options_brutes = l.get("options_brutes", [])
    description = l.get("description", "")

    for row in soup.select("table tr"):
        cells = row.select("td, th")
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True).lower()
            value = cells[1].get_text(strip=True)
            if "boîte" in label or "transmission" in label:
                tx = _clean_tx(value)
            elif "couleur" in label:
                couleur = couleur or value
            elif "puissance" in label:
                m = re.search(r"(\d+)", value)
                puissance_cv = puissance_cv or (int(m.group(1)) if m else None)

    # Chercher équipements / options
    for el in soup.select(".options li, .equipements li, .caracteristiques li, ul li"):
        t = el.get_text(strip=True)
        if t and 3 < len(t) < 100:
            if t not in options_brutes:
                options_brutes.append(t)

    # Description
    for sel in [".description-fiche", ".text-occasion", ".car-description", "p.description"]:
        desc_el = soup.select_one(sel)
        if desc_el:
            description = desc_el.get_text(" ", strip=True)[:500]
            break

    l.update({
        "tx_clean":      tx,
        "couleur":       couleur,
        "puissance_cv":  puissance_cv,
        "options_brutes":options_brutes,
        "description":   description,
    })
    return l


# ---------------------------------------------------------------------------
# Entrée principale
# ---------------------------------------------------------------------------

def scrape():
    print(f"\n{'='*60}")
    print(f"  Flat69 — {LISTING_URL}")
    print(f"{'='*60}")

    listings = []
    with httpx.Client(follow_redirects=True, timeout=20) as client:
        print(f"  Chargement de la page listing...")
        try:
            html = _get(LISTING_URL, client)
        except Exception as e:
            print(f"  [!] Erreur page listing: {e}")
            return listings

        # Parse toutes les voitures directement depuis la page listing
        base_listings = _parse_detail(LISTING_URL, html)
        print(f"  {len(base_listings)} voitures trouvées")

        if not base_listings:
            debug_path = Path(__file__).parent.parent / "debug_flat69_listing.html"
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"  [!] Aucune voiture trouvée — HTML sauvé dans {debug_path}")
            return listings

        # Enrichir chaque voiture avec sa page détail si URL distincte
        detail_urls_visited = set()
        for base in base_listings:
            url = base.get("url", LISTING_URL)
            clean_url = url.split("#")[0]

            if clean_url in detail_urls_visited or clean_url == LISTING_URL:
                listings.append(base)
                continue

            detail_urls_visited.add(clean_url)
            print(f"  Détail: {url}")
            try:
                detail_html = _get(url, client)
                enriched = _parse_single_fiche(url, detail_html, base_listing=dict(base))
                listings.append(enriched)
                prix_str = f"{enriched['prix']:,}" if enriched.get('prix') else '?'
                print(f"    → {enriched.get('marque')} {enriched.get('modele')} | "
                      f"{prix_str} € | {enriched.get('km') or '?'} km | "
                      f"{enriched.get('tx_clean', '?')}")
            except Exception as e:
                print(f"    [!] Erreur: {e}")
                listings.append(base)
            time.sleep(random.uniform(0.5, 1.0))

        if not listings:
            listings = base_listings

    print(f"\n  Total Flat69: {len(listings)} annonces")
    return listings


if __name__ == "__main__":
    results = scrape()
    out = Path(__file__).parent.parent / "debug_flat69.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"  Debug: {out}")
