"""
run_all.py — Orchestrateur lyon-dealers
Lance tous les scrapers actifs, agrège les résultats, génère le rapport HTML.

Usage:
    python run_all.py                       # Tous les vendeurs actifs
    python run_all.py --dealers symbol_cars stark_motors flat69
    python run_all.py --no-playwright       # Exclut West Motors
    python run_all.py --debug               # Sauvegarde les JSONs de debug
"""

import json
import sys
import argparse
import time
from datetime import datetime
from pathlib import Path

# Ajouter le répertoire parent au path pour les imports
sys.path.insert(0, str(Path(__file__).parent))

from report import save_results

# ---------------------------------------------------------------------------
# Registre des scrapers
# ---------------------------------------------------------------------------

SCRAPERS = {
    "symbol_cars":     {"module": "scrapers.symbol_cars",     "playwright": False, "active": True},
    "stark_motors":    {"module": "scrapers.stark_motors",    "playwright": False, "active": True},
    "flat69":          {"module": "scrapers.flat69",          "playwright": False, "active": True},
    "my_exclusive_car":{"module": "scrapers.my_exclusive_car","playwright": False, "active": True},
    "cars_experience": {"module": "scrapers.cars_experience", "playwright": False, "active": True},
    "la_villa_rose":   {"module": "scrapers.la_villa_rose",   "playwright": False, "active": True},
    "west_motors":     {"module": "scrapers.west_motors",     "playwright": False, "active": True},
    "evo_cars":        {"module": "scrapers.evo_cars",        "playwright": False, "active": True},
}


# ---------------------------------------------------------------------------
# Runner principal
# ---------------------------------------------------------------------------

def run_scraper(dealer_key, meta):
    """Lance un scraper et retourne la liste des annonces."""
    import importlib
    try:
        mod = importlib.import_module(meta["module"])
        t0 = time.time()
        listings = mod.scrape()
        elapsed = time.time() - t0
        print(f"  [{dealer_key}] {len(listings)} annonces en {elapsed:.1f}s")
        return listings
    except ImportError as e:
        print(f"  [{dealer_key}] Module non trouvé: {e}")
        return []
    except Exception as e:
        print(f"  [{dealer_key}] Erreur: {e}")
        import traceback
        traceback.print_exc()
        return []


def main():
    parser = argparse.ArgumentParser(description="Lyon Dealers scraper orchestrator")
    parser.add_argument(
        "--dealers", nargs="+",
        help="Clés des vendeurs à scraper (ex: symbol_cars stark_motors)",
        choices=list(SCRAPERS.keys()),
    )
    parser.add_argument(
        "--no-playwright", action="store_true",
        help="Exclure les scrapers qui nécessitent Playwright"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Sauvegarder les JSONs de debug individuels"
    )
    parser.add_argument(
        "--output", default="lyon_dealers",
        help="Préfixe du fichier de sortie (défaut: lyon_dealers)"
    )
    parser.add_argument(
        "--base-json",
        help="JSON existant à conserver — seuls les dealers re-scrapés sont remplacés",
        metavar="FILE",
    )
    args = parser.parse_args()

    print(f"\n{'='*70}")
    print(f"  LYON DEALERS — Scraping global")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"{'='*70}")

    # Sélection des scrapers
    if args.dealers:
        selected = {k: SCRAPERS[k] for k in args.dealers}
    else:
        selected = {k: v for k, v in SCRAPERS.items() if v["active"]}

    if args.no_playwright:
        selected = {k: v for k, v in selected.items() if not v["playwright"]}
        print(f"  Mode sans Playwright — scrapers Playwright exclus")

    print(f"\n  Vendeurs sélectionnés: {', '.join(selected.keys())}\n")

    all_listings = []
    results_by_dealer = {}

    for dealer_key, meta in selected.items():
        print(f"\n  {'—'*60}")
        print(f"  Scraping: {dealer_key}")
        print(f"  {'—'*60}")
        listings = run_scraper(dealer_key, meta)
        results_by_dealer[dealer_key] = listings
        all_listings.extend(listings)

        # Debug individuel si demandé
        if args.debug and listings:
            debug_path = Path(__file__).parent / f"debug_{dealer_key}.json"
            with open(debug_path, "w", encoding="utf-8") as f:
                json.dump(listings, f, indent=2, ensure_ascii=False)
            print(f"  Debug: {debug_path}")

    # Résumé global
    print(f"\n{'='*70}")
    print(f"  RÉSUMÉ GLOBAL")
    print(f"{'='*70}")
    for dealer_key, listings in results_by_dealer.items():
        status = "OK" if listings else "VIDE"
        print(f"  {dealer_key:<25} → {len(listings):3d} annonces  [{status}]")
    print(f"  {'—'*45}")
    print(f"  TOTAL                     → {len(all_listings):3d} annonces")

    if not all_listings:
        print(f"\n  Aucune annonce récupérée. Vérifiez les scrapers.")
        return

    # Si --base-json : charger les annonces existantes et remplacer les dealers re-scrapés
    if args.base_json:
        base_path = Path(args.base_json)
        if base_path.exists():
            with open(base_path, encoding="utf-8") as f:
                base_listings = json.load(f)
            # Supprimer les annonces des dealers re-scrapés dans la base
            scraped_keys = set(selected.keys())
            base_listings = [l for l in base_listings if l.get("source") not in scraped_keys]
            all_listings = base_listings + all_listings
            print(f"\n  Fusion: {len(base_listings)} annonces conservées + {len(all_listings) - len(base_listings)} nouvelles = {len(all_listings)} total")
        else:
            print(f"\n  [!] --base-json introuvable: {base_path}")

    # Génération du rapport
    print(f"\n{'='*70}")
    print(f"  Génération du rapport...")
    save_results(all_listings, label=args.output)

    print(f"\n  Terminé.")


if __name__ == "__main__":
    main()
