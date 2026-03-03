"""
scoring.py — Deal scoring pour Lugdunum Cars (inspiré CarGurus)

Principe :
  1. Normaliser marque + modèle → clé de groupe courte (ex. "porsche 911", "ferrari 488")
  2. Grouper les annonces par cette clé (groupes larges, toutes générations confondues)
  3. Pour chaque groupe ≥ 3 annonces avec prix + km :
     - Régression linéaire prix ~ km pour estimer le coeff de dépréciation/km
     - Calculer le prix de référence de chaque annonce (prix attendu à son km)
     - Écart = (prix_affiché - prix_ref) / prix_ref
  4. Assigner label + couleur selon les seuils

Seuils :
  < -10%          Excellent Deal   vert
  -10% à -3%      Bon Deal         bleu
  -3%  à  +3%     Prix correct     gris
  +3%  à +10%     Prix élevé       orange
  > +10%          Hors marché      rouge
  groupe < 3      (non évalué)     —
"""

import re
from statistics import median

# ---------------------------------------------------------------------------
# Seuils et labels
# ---------------------------------------------------------------------------

THRESHOLDS = [
    (-0.10, "Excellent Deal", "#15803d", "#dcfce7"),
    (-0.03, "Bon Deal",       "#1d4ed8", "#dbeafe"),
]

def _deal_label(ecart):
    """Retourne (label, color, bg) uniquement pour les bons deals, None sinon."""
    for threshold, label, color, bg in THRESHOLDS:
        if ecart < threshold:
            return label, color, bg
    return None, None, None


# ---------------------------------------------------------------------------
# Normalisation du modèle → clé de groupe
# ---------------------------------------------------------------------------

# Modèles de base à extraire (ordre important : plus long en premier)
_BASE_MODELS = [
    # Porsche
    "911", "718", "boxster", "cayman", "cayenne", "macan", "panamera", "taycan",
    # Ferrari
    "488", "458", "f8", "296", "812", "portofino", "sf90", "f12", "ff", "f430",
    "california", "roma", "gtc4",
    # Lamborghini
    "huracan", "urus", "gallardo", "aventador",
    # McLaren
    "720s", "570s", "600lt", "650s", "765lt", "artura", "mp4",
    # Aston Martin
    "vantage", "db11", "dbs", "dbx", "db9",
    # Maserati
    "granturismo", "ghibli", "grecale", "levante", "mc20", "grancabrio", "gransport",
    "4200",
    # Mercedes
    "amg gt", "slr", "sl", "slc",
    # BMW
    "m3", "m4", "m5", "m8", "z4", "z8", "i8",
    # Audi
    "r8", "rs6", "rs3",
    # Jaguar
    "f-type",
    # Autres
    "nsx", "viper", "mustang", "corvette",
]

# Générations connues par modèle — pour affiner le groupe
_GENERATIONS = {
    "911":  ["992", "991", "997", "996", "993", "964", "930"],
    "718":  ["982"],
    "cayenne": ["e-hybrid"],
    "488":  [],
    "f8":   [],
    "812":  [],
    "granturismo": [],
    "artura": [],
    "720s": [],
    "f-type": [],
    "vantage": [],
}

def _normalize_group_key(marque, modele):
    """
    Retourne une clé de groupe précise : 'porsche 911 992', 'ferrari 488', etc.
    Retourne None si aucun modèle de base reconnu (évite les groupes fourre-tout).
    """
    marque_l = (marque or "").lower().strip()
    modele_l = (modele or "").lower().strip()

    # Supprimer la marque en doublon au début du modèle
    if modele_l.startswith(marque_l):
        modele_l = modele_l[len(marque_l):].strip()

    # Chercher le modèle de base
    found_base = None
    for base in _BASE_MODELS:
        pattern = r'\b' + re.escape(base) + r'\b'
        if re.search(pattern, modele_l):
            found_base = base
            break

    # Pas de modèle reconnu → pas de scoring (évite "jaguar", "bmw", etc.)
    if not found_base:
        return None

    # Chercher la génération dans le modèle
    gens = _GENERATIONS.get(found_base, [])
    for gen in gens:
        if re.search(r'\b' + re.escape(gen) + r'\b', modele_l):
            return f"{marque_l} {found_base} {gen}"

    return f"{marque_l} {found_base}"


# ---------------------------------------------------------------------------
# Régression linéaire simple (sans numpy)
# ---------------------------------------------------------------------------

def _linear_regression(xs, ys):
    """Retourne (slope, intercept) de la droite y = slope*x + intercept."""
    n = len(xs)
    if n < 2:
        return 0.0, median(ys)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0:
        return 0.0, mean_y
    slope = num / den
    intercept = mean_y - slope * mean_x
    return slope, intercept


# ---------------------------------------------------------------------------
# Scoring principal
# ---------------------------------------------------------------------------

def score(listings):
    """
    Enrichit chaque listing avec un champ 'deal_score' :
    {
        "label":  "Bon Deal",
        "color":  "#1d4ed8",
        "bg":     "#dbeafe",
        "ecart":  -0.07,        # -7%
        "groupe": "porsche 911",
        "groupe_n": 8,          # nb annonces dans le groupe
    }
    Ou None si non évalué.
    """

    # -- Étape 1 : construire les groupes --
    groups = {}  # clé → liste de listings
    for l in listings:
        if not l.get("prix") or not l.get("km"):
            continue
        key = _normalize_group_key(l.get("marque", ""), l.get("modele", ""))
        if key is None:
            continue
        groups.setdefault(key, []).append(l)

    # -- Étape 2 : calculer la régression par groupe --
    group_models = {}  # clé → (slope, intercept, n)
    for key, members in groups.items():
        if len(members) < 3:
            continue
        xs = [m["km"] for m in members]
        ys = [m["prix"] for m in members]
        slope, intercept = _linear_regression(xs, ys)
        group_models[key] = (slope, intercept, len(members))

    # -- Étape 3 : assigner le score à chaque listing --
    # Index rapide : url → listing
    scored = {id(l): None for l in listings}

    for l in listings:
        if not l.get("prix") or not l.get("km"):
            l["deal_score"] = None
            continue
        key = _normalize_group_key(l.get("marque", ""), l.get("modele", ""))
        if key is None or key not in group_models:
            l["deal_score"] = None
            continue

        slope, intercept, n = group_models[key]
        prix_ref = slope * l["km"] + intercept

        if prix_ref <= 0:
            l["deal_score"] = None
            continue

        ecart = (l["prix"] - prix_ref) / prix_ref
        label, color, bg = _deal_label(ecart)

        l["deal_score"] = {
            "label":    label,
            "color":    color,
            "bg":       bg,
            "ecart":    round(ecart, 3),
            "groupe":   key,
            "groupe_n": n,
        }

    return listings


# ---------------------------------------------------------------------------
# Debug / stats
# ---------------------------------------------------------------------------

def print_stats(listings):
    from collections import Counter
    scored = [l for l in listings if l.get("deal_score")]
    unscored = [l for l in listings if not l.get("deal_score")]
    cnt = Counter(l["deal_score"]["label"] for l in scored if l["deal_score"].get("label"))
    print(f"\n  Scoring — {len(scored)} évalués / {len(unscored)} non évalués")
    for label, n in cnt.most_common():
        print(f"    {label:<20} : {n}")
    # Groupes utilisés
    groupes = Counter(l["deal_score"]["groupe"] for l in scored)
    print(f"\n  Groupes ({len(groupes)}) :")
    for g, n in groupes.most_common(15):
        print(f"    {g:<30} : {n} annonces")
