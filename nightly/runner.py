"""
nightly/runner.py — Orchestrateur cron Lugdunum Cars

Flux :
  1. Charger le JSON base (dernier annonces_*.json)
  2. Quick check → IDs live par dealer (~16s, listing-only)
  3. Diff → nouvelles annonces + disparues
  4. Si nouvelles → scraper leurs fiches détail (scrapers existants, 1 URL ciblée)
  5. Mettre à jour le JSON base
  6. Regénérer docs/index.html
  7. git commit + push
  8. Notification osascript

Usage :
  python -m nightly.runner
  python -m nightly.runner --dry-run   (pas de commit/push)
"""

import argparse
import importlib
import json
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

# Assurer que le répertoire projet est dans le path
PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from nightly.quick_check import get_all_live_ids
from nightly.diff import compute_diff, apply_diff
from nightly.notifier import notify


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_base_json() -> tuple[list, Path]:
    """Charge le JSON le plus récent dans le répertoire projet."""
    jsons = sorted(PROJECT_DIR.glob("annonces_lyon_dealers_*.json"), reverse=True)
    if not jsons:
        raise FileNotFoundError("Aucun fichier annonces_lyon_dealers_*.json trouvé")
    path = jsons[0]
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    print(f"  Base : {path.name} ({len(data)} annonces)")
    return data, path


def _save_json(listings: list, path: Path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(listings, f, indent=2, ensure_ascii=False)
    print(f"  JSON sauvegardé : {path.name} ({len(listings)} annonces)")


def _scrape_new(nouvelles: list) -> list:
    """
    Scrape uniquement les fiches détail des nouvelles annonces.
    Appelle scraper.scrape() avec une liste d'URLs ciblées si supporté,
    sinon scrape l'intégralité du dealer (fallback).
    """
    if not nouvelles:
        return []

    # Grouper par dealer
    by_dealer: dict[str, list] = {}
    for n in nouvelles:
        by_dealer.setdefault(n["source"], []).append(n["live_id"])

    scraped = []
    for dealer_key, live_ids in by_dealer.items():
        print(f"\n  Scraping nouvelles fiches — {dealer_key} ({len(live_ids)} annonce(s))")
        module_name = f"scrapers.{dealer_key}"
        try:
            mod = importlib.import_module(module_name)
        except ImportError:
            print(f"    [!] Module {module_name} introuvable")
            continue

        # Idéalement chaque scraper accepte scrape(ids=...) pour cibler
        # Par défaut on re-scrape tout le dealer et on filtre par ID
        t0 = time.time()
        try:
            all_listings = mod.scrape()
            # Filtrer uniquement les nouvelles annonces par ID
            new_ids_set = set(str(i) for i in live_ids)
            filtered = [l for l in all_listings if str(l.get("id","")) in new_ids_set]
            if filtered:
                scraped.extend(filtered)
                print(f"    → {len(filtered)} nouvelles annonces récupérées en {time.time()-t0:.1f}s")
            else:
                # Si le filtre donne rien (IDs quick_check ≠ IDs scraper), on prend tout
                print(f"    → Filtre vide, ajout des {len(all_listings)} annonces du dealer")
                scraped.extend(all_listings)
        except Exception as e:
            print(f"    [!] Erreur scraping {dealer_key}: {e}")

    return scraped


def _regen_html(listings: list):
    """Regénère docs/index.html."""
    import report
    webbrowser.open = lambda *a, **k: None  # désactiver l'ouverture du browser
    html_path = PROJECT_DIR / "docs" / "index.html"
    report.save_html_report(listings, str(html_path), title="Lugdunum Cars")
    print(f"  HTML régénéré : {html_path}")


def _git_push(n_new: int, n_sold: int):
    """git add / commit / push."""
    msg = f"nightly: {n_new} nouvelles annonces, {n_sold} vendues — {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    cmds = [
        ["git", "add", "docs/index.html", "annonces_lyon_dealers_*.json"],
        ["git", "commit", "-m", msg],
        ["git", "push"],
    ]
    for cmd in cmds:
        result = subprocess.run(cmd, cwd=PROJECT_DIR, capture_output=True, text=True)
        if result.returncode != 0:
            # commit vide = normal si rien n'a changé
            if "nothing to commit" in result.stdout + result.stderr:
                print("  Git : rien à committer")
                return
            print(f"  [!] Git erreur ({' '.join(cmd)}): {result.stderr.strip()}")
            return
    print(f"  Git : pushé — {msg}")


# ---------------------------------------------------------------------------
# Runner principal
# ---------------------------------------------------------------------------

def main(dry_run: bool = False):
    start = time.time()
    print(f"\n{'='*65}")
    print(f"  LUGDUNUM CARS — Nightly runner")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"{'='*65}\n")

    # 1. Charger la base
    print("[ 1/7 ] Chargement de la base JSON...")
    try:
        base_listings, base_path = _load_base_json()
    except FileNotFoundError as e:
        print(f"  [!] {e}")
        notify("Lugdunum Cars", "Erreur nightly : base JSON introuvable")
        return

    # 2. Quick check
    print("\n[ 2/7 ] Quick check des listings...")
    live_ids = get_all_live_ids()

    # 3. Diff
    print("\n[ 3/7 ] Calcul du diff...")
    diff = compute_diff(base_listings, live_ids)
    n_new  = len(diff["nouvelles"])
    n_sold = len(diff["disparues"])
    n_same = diff["inchangees"]
    print(f"  Nouvelles  : {n_new}")
    print(f"  Disparues  : {n_sold}")
    print(f"  Inchangées : {n_same}")

    if n_new == 0 and n_sold == 0:
        elapsed = time.time() - start
        print(f"\n  Aucun changement détecté. Terminé en {elapsed:.1f}s")
        notify("Lugdunum Cars", f"Nightly OK — aucun changement ({n_same} annonces stables)")
        return

    # 4. Scraper les nouvelles fiches
    new_scraped = []
    if n_new > 0:
        print(f"\n[ 4/7 ] Scraping de {n_new} nouvelle(s) fiche(s)...")
        if not dry_run:
            new_scraped = _scrape_new(diff["nouvelles"])
        else:
            print("  [dry-run] Scraping ignoré")

    # 5. Mettre à jour le JSON
    print(f"\n[ 5/7 ] Mise à jour de la base JSON...")
    if not dry_run:
        updated = apply_diff(base_listings, diff, new_scraped)
        _save_json(updated, base_path)
    else:
        updated = base_listings
        print("  [dry-run] Sauvegarde ignorée")

    # 6. Regénérer HTML
    print(f"\n[ 6/7 ] Régénération du rapport HTML...")
    if not dry_run:
        _regen_html(updated)
    else:
        print("  [dry-run] HTML ignoré")

    # 7. Git push
    print(f"\n[ 7/7 ] Git commit + push...")
    if not dry_run:
        _git_push(len(new_scraped), n_sold)
    else:
        print("  [dry-run] Push ignoré")

    # Notification
    elapsed = time.time() - start
    parts = []
    if new_scraped:
        parts.append(f"{len(new_scraped)} nouvelle(s)")
    if n_sold:
        parts.append(f"{n_sold} vendue(s)")
    msg = " · ".join(parts) if parts else "aucun changement"
    print(f"\n  Terminé en {elapsed:.1f}s — {msg}")
    notify("Lugdunum Cars", f"Nightly — {msg}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Simuler sans écrire ni pusher")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
