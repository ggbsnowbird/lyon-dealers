"""
scrapers/evo_cars.py — Evo Cars (evocars.fr)
Plateforme : JALIS CMS (CMS français pour pros de l'auto) — server-rendered
Localisation : Villefranche-sur-Saône (nord Lyon)
Stratégie  : httpx — listing /nos-voitures-prestiges-sportives-nos-vehicules-en-vente-w1
             Liens fiches : a[href^="details-"] — ID numérique en suffixe
             Détail : specs en blocs label/valeur, options en ul li, prix en texte brut
"""

import httpx
import json
import re
import time
import random
from bs4 import BeautifulSoup
from pathlib import Path

DEALER_KEY  = "evo_cars"
DEALER_NAME = "Evo Cars"
DEALER_URL  = "https://www.evocars.fr"
LISTING_URL = "https://www.evocars.fr/nos-voitures-prestiges-sportives-nos-vehicules-en-vente-w1"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.evocars.fr/",
}

KNOWN_BRANDS = [
    "Aston Martin", "Rolls-Royce", "Land Rover", "Alfa Romeo", "De Tomaso",
    "Porsche", "Ferrari", "Lamborghini", "McLaren", "Bentley", "Maserati",
    "BMW", "Mercedes-Benz", "Mercedes", "Audi", "Alpine", "Lotus", "Jaguar",
    "Bugatti", "Pagani", "Ford", "Renault", "Volkswagen", "Morgan",
    "Chevrolet", "Dodge", "Koenigsegg",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_price(s):
    if not s:
        return None
    digits = re.sub(r"[^\d]", "", str(s))
    v = int(digits) if digits else None
    return v if v and 3000 < v < 10_000_000 else None

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
    if any(k in t for k in ["automatique", "automatic", "pdk", "dct",
                              "s-tronic", "dsg", "séquentielle", "bva", "bva7"]):
        return "Automatique"
    return str(s)[:30]

def _parse_brand(title):
    for brand in KNOWN_BRANDS:
        if title.lower().startswith(brand.lower()):
            return brand
    parts = title.strip().split()
    return parts[0] if parts else ""

def _get(url, client):
    resp = client.get(url, headers=HEADERS, follow_redirects=True, timeout=20)
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# Phase 1 — Listing
# Structure : grille de cartes avec a[href^="details-"]
# Chaque carte : h2 (titre), prix en texte, img src="public/img/medium/..."
# ---------------------------------------------------------------------------

def _fetch_listing_cards(html):
    soup = BeautifulSoup(html, "html.parser")
    cards = []
    seen = set()

    for a in soup.select("a[href]"):
        href = str(a.get("href") or "")
        # Liens de fiche : "details-marque+modele-ID"
        if not href.startswith("details-"):
            continue
        # Reconstruire l'URL absolue
        url = f"{DEALER_URL}/{href}"
        if url in seen:
            continue
        seen.add(url)

        # ID interne = dernier segment numérique
        m_id = re.search(r"-(\d+)$", href)
        if not m_id:
            continue  # pas une fiche voiture
        car_id = m_id.group(1)

        # Ignorer les pages SEO/éditoriales en détectant des mots-clés dans le href
        seo_keywords = [
            "vendre-ma-", "depot-vente", "specialiste-du-depot",
            "guide-local", "mentions", "politique", "contact", "estimation",
            "recherche-personnalisee", "showroom", "nos-services", "financement",
            "reprise", "actualite", "actualité", "faq", "garantie",
        ]
        href_normalized = href.replace("+", "-").lower()
        if any(k in href_normalized for k in seo_keywords):
            continue

        # Les fiches voitures ont un titre court (marque + modèle) — pas plus de 6 mots
        # Les pages SEO ont des slugs très longs
        href_words = href_normalized.replace("details-", "").split("-")
        # Supprimer l'ID final pour compter les mots du slug
        slug_words = [w for w in href_words if not w.isdigit()]
        if len(slug_words) > 12:
            continue

        # Titre depuis h2 dans le parent
        container = a
        for _ in range(6):
            container = container.parent
            if container is None:
                break
            if container.select_one("h2"):
                break

        title_el = container.select_one("h2") if container else None
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            title = a.get_text(strip=True)[:80]

        # Prix : texte contenant "€" dans le container
        prix = None
        if container:
            raw = container.get_text(" ", strip=True)
            m_p = re.search(r"([\d\s\u202f]+)\s*€", raw)
            if m_p:
                prix = _clean_price(m_p.group(1))

        # Image : src="public/img/medium/..."
        image_url = None
        if container:
            img = container.select_one("img[src*='public/img']")
            if img:
                src = str(img.get("src") or "")
                if src.startswith("public/"):
                    src = f"{DEALER_URL}/{src}"
                image_url = src

        cards.append({
            "id":        car_id,
            "url":       url,
            "title":     title,
            "prix":      prix,
            "image_url": image_url,
        })

    return cards


# ---------------------------------------------------------------------------
# Phase 2 — Page détail
# Specs : blocs texte label/valeur (Année, Boite de vitesse, Kilomètrage, etc.)
# Options : liste ul li dans la description
# Prix : texte "107 990 €" en bas de page
# Image HD : public/img/big/...
# ---------------------------------------------------------------------------

def _parse_detail(url, html, base=None):
    soup = BeautifulSoup(html, "html.parser")
    b = base or {}

    # Titre depuis h1
    h1 = soup.select_one("h1")
    title = h1.get_text(strip=True) if h1 else b.get("title", "")
    marque = _parse_brand(title)

    # Supprimer la marque du début du titre pour éviter "Maserati Maserati Granturismo"
    modele = title
    if marque and modele.lower().startswith(marque.lower()):
        modele = modele[len(marque):].strip()

    # --- Specs : chercher les paires label/valeur ---
    # Le CMS JALIS génère des blocs texte bruts : "Année\n2019\nBoite de vitesse\nAutomatique\n..."
    # On cherche les éléments qui contiennent ces labels connus
    km           = None
    annee        = None
    tx           = None
    puissance_cv = None
    carrosserie  = None
    couleur      = None

    SPEC_LABELS = {
        "kilométrage": "km",
        "kilomètrage": "km",
        "année":       "annee",
        "boite de vitesse": "tx",
        "boîte de vitesse": "tx",
        "puissance din":    "cv",
        "puissance":        "cv",
        "carrosserie":      "carrosserie",
        "couleur":          "couleur",
    }

    # Chercher dans tous les éléments texte leaf qui matchent un label connu
    all_text_els = soup.find_all(string=True)
    for i, txt in enumerate(all_text_els):
        clean = txt.strip().lower()
        for label, field in SPEC_LABELS.items():
            if clean == label:
                # La valeur est dans le texte suivant non-vide
                for j in range(i + 1, min(i + 5, len(all_text_els))):
                    val = all_text_els[j].strip()
                    if val and val.lower() not in SPEC_LABELS:
                        if field == "km" and not km:
                            km = _clean_km(val)
                        elif field == "annee" and not annee:
                            annee = _clean_year(val)
                        elif field == "tx" and not tx:
                            tx = _clean_tx(val)
                        elif field == "cv" and not puissance_cv:
                            m_cv = re.search(r"(\d+)", val)
                            puissance_cv = int(m_cv.group(1)) if m_cv else None
                        elif field == "carrosserie" and not carrosserie:
                            carrosserie = val
                        elif field == "couleur" and not couleur:
                            couleur = val
                        break
                break

    # --- Options : liste ul li dans le corps ---
    options_brutes = []
    # Les options sont dans des <li> dans la description principale
    # Filtrer les li de nav (menus)
    main_content = soup.select_one("main, .content, article, #content, .detail-content")
    scope = main_content if main_content else soup
    for li in scope.select("li"):
        t = li.get_text(strip=True)
        # Exclure les items de navigation (courts, contiennent des mots de nav)
        if (5 < len(t) < 150 and
                not any(k in t.lower() for k in ["accueil", "showroom", "contact",
                                                   "estimation", "recherche", "voitures"])):
            options_brutes.append(t)

    # --- Description : paragraphes texte ---
    description = ""
    for p in soup.select("p"):
        t = p.get_text(" ", strip=True)
        if len(t) > 60 and not re.search(r"cookie|gdpr|©|mentions|politique", t, re.IGNORECASE):
            description = t[:500]
            break

    # --- Prix : chercher "xxx xxx €" dans toute la page ---
    prix = b.get("prix")
    if not prix:
        raw = soup.get_text(" ", strip=True)
        # Chercher un prix standalone (pas dans une URL)
        for m in re.finditer(r"([\d][\d\s\u202f]{3,8})\s*€", raw):
            v = _clean_price(m.group(1))
            if v and v > 5000:
                prix = v
                break

    # --- Image HD : public/img/big/ ---
    image_url = b.get("image_url")
    if not image_url:
        for img in soup.select("img[src*='public/img']"):
            src = str(img.get("src") or "")
            if "big" in src or "medium" in src:
                if src.startswith("public/"):
                    src = f"{DEALER_URL}/{src}"
                image_url = src
                break
    # Préférer la version /big/ si on a /medium/
    if image_url and "/medium/" in image_url:
        big_url = image_url.replace("/medium/", "/big/")
        image_url = big_url

    slug = url.rstrip("/").split("/")[-1]
    return {
        "id":             slug,
        "source":         DEALER_KEY,
        "dealer_name":    DEALER_NAME,
        "dealer_url":     DEALER_URL,
        "marque":         marque,
        "modele":         modele,
        "annee":          annee,
        "km":             km,
        "prix":           prix,
        "tx_clean":       tx or "?",
        "couleur":        couleur,
        "carrosserie":    carrosserie,
        "puissance_cv":   puissance_cv,
        "puissance_kw":   None,
        "description":    description,
        "options_brutes": options_brutes,
        "url":            url,
        "image_url":      image_url,
    }


# ---------------------------------------------------------------------------
# Entrée principale
# ---------------------------------------------------------------------------

def scrape():
    print(f"\n{'='*60}")
    print(f"  Evo Cars — {LISTING_URL}")
    print(f"{'='*60}")

    listings = []
    with httpx.Client(follow_redirects=True, timeout=20) as client:
        print("  Chargement de la page listing...")
        try:
            html = _get(LISTING_URL, client)
        except Exception as e:
            print(f"  [!] Erreur listing: {e}")
            return []

        cards = _fetch_listing_cards(html)
        print(f"  {len(cards)} voitures trouvées")

        if not cards:
            debug_path = Path(__file__).parent.parent / "debug_evo_cars_listing.html"
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
            time.sleep(random.uniform(0.5, 1.0))

    print(f"\n  Total Evo Cars: {len(listings)} annonces")
    return listings


if __name__ == "__main__":
    results = scrape()
    out = Path(__file__).parent.parent / "debug_evo_cars.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"  Debug: {out}")
