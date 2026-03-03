"""
nightly/diff.py — Comparaison IDs live vs base JSON

Retourne :
  - nouvelles  : annonces dans le listing live mais absentes de la base
  - disparues  : annonces dans la base (non sold) mais absentes du listing live
  - inchangees : count des annonces inchangées
"""

from datetime import datetime


def _base_id(listing):
    """Retourne l'ID normalisé d'un listing de la base."""
    return str(listing.get("id") or "").strip()


def compute_diff(base_listings: list, live_ids_by_dealer: dict) -> dict:
    """
    Compare la base JSON avec les IDs live du quick_check.

    base_listings     : liste complète des listings en base (JSON)
    live_ids_by_dealer: {"dealer_key": set_of_ids, ...}  (depuis quick_check)

    Retourne un dict :
    {
        "nouvelles":  [{"source": dealer_key, "live_id": id}, ...],
        "disparues":  [listing, ...],    # listings complets à marquer sold
        "inchangees": int,
        "timestamp":  str,
    }
    """
    nouvelles = []
    disparues = []
    inchangees = 0

    # Index base par dealer → set d'IDs connus (non sold)
    base_by_dealer: dict[str, dict] = {}
    for l in base_listings:
        if l.get("sold"):
            continue
        dealer = l.get("source", "")
        bid = _base_id(l)
        if dealer not in base_by_dealer:
            base_by_dealer[dealer] = {}
        base_by_dealer[dealer][bid] = l

    for dealer_key, live_ids in live_ids_by_dealer.items():
        known = base_by_dealer.get(dealer_key, {})

        # Nouvelles : dans live mais pas dans la base
        for lid in live_ids:
            lid = str(lid).strip()
            if lid not in known:
                nouvelles.append({"source": dealer_key, "live_id": lid})

        # Disparues : dans la base mais plus dans live
        live_normalized = {str(i).strip() for i in live_ids}
        for bid, listing in known.items():
            if bid not in live_normalized:
                disparues.append(listing)

        # Inchangées
        inchangees += len(live_ids & set(known.keys()))

    return {
        "nouvelles":  nouvelles,
        "disparues":  disparues,
        "inchangees": inchangees,
        "timestamp":  datetime.now().isoformat(),
    }


def apply_diff(base_listings: list, diff: dict, new_listings: list) -> list:
    """
    Applique le diff sur la base :
    - Marque les disparues sold=True + sold_at
    - Ajoute les nouvelles annonces scrappées
    Retourne la liste mise à jour.
    """
    sold_at = datetime.now().strftime("%Y-%m-%d")
    sold_ids = {str(l.get("id","")).strip() for l in diff["disparues"]}

    updated = []
    for l in base_listings:
        bid = str(l.get("id","")).strip()
        if bid in sold_ids and not l.get("sold"):
            l = dict(l)
            l["sold"] = True
            l["sold_at"] = sold_at
        updated.append(l)

    # Ajouter les nouvelles
    updated.extend(new_listings)
    return updated
