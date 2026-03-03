"""
nightly/quick_check.py — Vérification rapide des listings (listing-only, pas de détail)

Pour chaque dealer, scrape uniquement la page listing et retourne un set d'IDs
actuellement en vente. Une seule requête HTTP par dealer (~1-2s chacune).

L'ID retourné doit correspondre au champ "id" dans le JSON de base.
"""

import re
import time
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}

TIMEOUT = 20


def _get(url, client):
    r = client.get(url, headers=HEADERS, follow_redirects=True, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


# ---------------------------------------------------------------------------
# Symbol Cars — PrestaShop, ID numérique dans /NNN-slug.html
# ---------------------------------------------------------------------------

def symbol_cars(client) -> set:
    html = _get("https://symbolcars.fr/3-decouvrez-notre-collection", client)
    # URLs type: symbolcars.fr/465-mercedes-amg-gt → ID = "465-mercedes-amg-gt"
    # (correspond au champ "id" du scraper : dernier segment de l'URL sans .html)
    paths = re.findall(r"symbolcars\.fr/(\d+-[\w-]+)(?:\.html|\")", html)
    ids = set(paths)
    # Exclure les pages catégorie/navigation
    ids = {i for i in ids if not i.startswith("3-") and not i.startswith("738-")
           and "decouvrez" not in i and "collection" not in i}
    return ids


# ---------------------------------------------------------------------------
# Stark Motors — PHP custom, slug /shop/SLUG-ID (ID numérique en fin)
# ---------------------------------------------------------------------------

def stark_motors(client) -> set:
    html = _get("https://starkmotors.fr/shop", client)
    # /shop/alfa-romeo-stelvio-2-9-v6-510-q4-quadrifoglio-at8-184
    slugs = set(re.findall(r"/shop/([\w-]+-\d{2,6})(?:/|\")", html))
    return slugs


# ---------------------------------------------------------------------------
# Flat69 — PHP statique, ID numérique dans l'URL de la fiche
# Listing = page unique /occasion-porsche-lyon/
# IDs extraits du slug : PORSCHE-911-...-{ID10chiffres}
# ---------------------------------------------------------------------------

def flat69(client) -> set:
    html = _get("https://www.flat69.fr/occasion-porsche-lyon/", client)
    # hrefs type : href='PORSCHE-911-...-9983202664#fiche'
    # L'ID dans la base = slug complet sans #fiche : "PORSCHE-911-...-9983202664"
    slugs = re.findall(r"href=[\"'](PORSCHE-[^\"'#\s]+)(?:#fiche)?[\"']", html)
    ids = set(slugs)
    return ids


# ---------------------------------------------------------------------------
# My Exclusive Car — PHP custom, slug /annonce-SLUG dans les hrefs
# ID = dernier segment de l'URL (/annonce-...-5954130)
# ---------------------------------------------------------------------------

def my_exclusive_car(client) -> set:
    html = _get("https://www.myexclusivecar.fr/voitures", client)
    # URL complète dans le HTML : href="https://www.myexclusivecar.fr/annonce-SLUG"
    # On extrait le slug complet (sans domaine)
    slugs = set(re.findall(
        r"myexclusivecar\.fr/(annonce-[\w-]+)",
        html
    ))
    return slugs


# ---------------------------------------------------------------------------
# Cars Experience — WP/Elementor Portfolio, slug /portfolio/SLUG/
# ---------------------------------------------------------------------------

def cars_experience(client) -> set:
    html = _get("https://cars-experience.fr/index.php/a-la-vente/", client)
    slugs = set(re.findall(r"/portfolio/([\w-]+)/", html))
    return slugs


# ---------------------------------------------------------------------------
# La Villa Rose — WP/Oxygen, slug /nos-voitures/SLUG/
# ---------------------------------------------------------------------------

def la_villa_rose(client) -> set:
    html = _get("https://www.lavillarose.fr/nos-voitures/", client)
    slugs = set(re.findall(r"/nos-voitures/([\w-]+)/", html))
    # Exclure la page listing elle-même
    slugs.discard("")
    return slugs


# ---------------------------------------------------------------------------
# West Motors — WP/IzisCAR, slug /voiture/SLUG/ dans /showroom/
# ---------------------------------------------------------------------------

def west_motors(client) -> set:
    html = _get("https://www.westmotors.fr/showroom/", client)
    slugs = set(re.findall(r"/voiture/([\w-]+)", html))
    return slugs


# ---------------------------------------------------------------------------
# Evo Cars — JALIS CMS, href="details-SLUG-ID"
# ---------------------------------------------------------------------------

def evo_cars(client) -> set:
    html = _get(
        "https://www.evocars.fr/nos-voitures-prestiges-sportives-nos-vehicules-en-vente-w1",
        client
    )
    slugs = set(re.findall(r'href="(details-[\w+%-]+-\d+)"', html))
    # Exclure les pages SEO (mêmes mots-clés que dans scrapers/evo_cars.py)
    seo_keywords = ["vendre", "depot-vente", "specialiste", "guide", "estimation",
                    "recherche", "showroom", "services", "financement", "reprise"]
    slugs = {s for s in slugs if not any(k in s.replace("+", "-").lower() for k in seo_keywords)}
    return slugs


# ---------------------------------------------------------------------------
# Orchestrateur
# ---------------------------------------------------------------------------

CHECKERS = {
    "symbol_cars":     symbol_cars,
    "stark_motors":    stark_motors,
    "flat69":          flat69,
    "my_exclusive_car":my_exclusive_car,
    "cars_experience": cars_experience,
    "la_villa_rose":   la_villa_rose,
    "west_motors":     west_motors,
    "evo_cars":        evo_cars,
}


def get_all_live_ids() -> dict:
    """
    Scrape les pages listing de tous les dealers.
    Retourne {"dealer_key": set_of_ids, ...}
    Durée estimée : ~16s (8 dealers × ~2s)
    """
    results = {}
    with httpx.Client(follow_redirects=True, timeout=TIMEOUT) as client:
        for dealer_key, fn in CHECKERS.items():
            t0 = time.time()
            try:
                ids = fn(client)
                elapsed = time.time() - t0
                print(f"  [{dealer_key:<20}] {len(ids):3d} annonces en vente  ({elapsed:.1f}s)")
                results[dealer_key] = ids
            except Exception as e:
                elapsed = time.time() - t0
                print(f"  [{dealer_key:<20}] ERREUR: {e}  ({elapsed:.1f}s)")
                results[dealer_key] = set()
            time.sleep(0.3)
    return results


if __name__ == "__main__":
    print("Quick check — tous les dealers\n")
    live = get_all_live_ids()
    total = sum(len(v) for v in live.values())
    print(f"\nTotal live: {total} annonces")
