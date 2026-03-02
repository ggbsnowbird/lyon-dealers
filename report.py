"""
report.py — Générateur de rapport HTML dark-mode pour lyon-dealers
Style identique à gt3-agent, adapté sans scoring.
"""

import json
import os
import webbrowser
import csv
from datetime import datetime
from collections import Counter
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers de formatage
# ---------------------------------------------------------------------------

def _fmt_prix(prix):
    if not prix:
        return "—"
    return f"{prix:,}".replace(",", "\u202f") + " €"

def _fmt_km(km):
    if not km:
        return "—"
    return f"{km:,}".replace(",", "\u202f") + " km"

def _dealer_badge_color(dealer_key):
    """Couleur distincte par vendeur — palette cohérente dark-mode."""
    palette = {
        "symbol_cars":     "#1e3a5f",
        "stark_motors":    "#1e3a2f",
        "flat69":          "#3a1e1e",
        "my_exclusive_car":"#2d1e3a",
        "cars_experience": "#1e2d3a",
        "la_villa_rose":   "#3a2d1e",
        "west_motors":     "#1e3a3a",
    }
    return palette.get(dealer_key, "#1e293b")

def _dealer_text_color(dealer_key):
    palette = {
        "symbol_cars":     "#93c5fd",
        "stark_motors":    "#86efac",
        "flat69":          "#fca5a5",
        "my_exclusive_car":"#d8b4fe",
        "cars_experience": "#7dd3fc",
        "la_villa_rose":   "#fcd34d",
        "west_motors":     "#67e8f9",
    }
    return palette.get(dealer_key, "#94a3b8")

def _tx_class(tx_clean):
    t = (tx_clean or "").lower().replace(" ", "_").replace("-", "_")
    return f"tx-{t}"


# ---------------------------------------------------------------------------
# Rapport HTML (même structure que gt3-agent)
# ---------------------------------------------------------------------------

def save_html_report(listings, path, title="Voitures Sport Lyon"):
    timestamp   = datetime.now().strftime("%d/%m/%Y %H:%M")
    sorted_lst  = sorted(listings, key=lambda x: (x.get("prix") or 999999999))

    # --- Stats globales ---
    prices   = [l["prix"] for l in listings if l.get("prix")]
    kms      = [l["km"]   for l in listings if l.get("km")]
    tx_cnt   = Counter(l.get("tx_clean", "?") for l in listings)
    dlr_cnt  = Counter(l.get("dealer_name", "?") for l in listings)
    brand_cnt= Counter(l.get("marque", "?") for l in listings)

    stats_html = f"""
      <div class="stat"><span class="stat-val">{len(listings)}</span><span class="stat-lbl">Annonces</span></div>
      <div class="stat"><span class="stat-val">{len(dlr_cnt)}</span><span class="stat-lbl">Vendeurs</span></div>
      {''.join([f'<div class="stat"><span class="stat-val">{_fmt_prix(min(prices))}</span><span class="stat-lbl">Prix min</span></div><div class="stat"><span class="stat-val">{_fmt_prix(max(prices))}</span><span class="stat-lbl">Prix max</span></div>']) if prices else ''}
      {''.join([f'<div class="stat"><span class="stat-val">{int(sum(prices)/len(prices)):,} €</span><span class="stat-lbl">Prix moyen</span></div>']) if prices else ''}
      {''.join([f'<div class="stat"><span class="stat-val">{int(sum(kms)/len(kms)):,} km</span><span class="stat-lbl">Km moyen</span></div>']) if kms else ''}

    """

    # --- Lignes du tableau ---
    rows_html = ""
    dealer_map   = dict(sorted(
                       {l["source"]: l["dealer_name"] for l in listings if l.get("source")}.items(),
                       key=lambda x: x[1]))

    all_brands   = sorted(brand_cnt.keys())


    for i, l in enumerate(sorted_lst, 1):
        prix_fmt   = _fmt_prix(l.get("prix"))
        km_fmt     = _fmt_km(l.get("km"))
        url        = l.get("url", "#")
        couleur    = l.get("couleur") or "—"
        marque     = l.get("marque") or "—"
        modele     = l.get("modele") or "—"
        annee      = l.get("annee") or "—"
        tx_clean   = l.get("tx_clean") or "?"
        dealer_key = l.get("source", "")
        dealer_nm  = l.get("dealer_name", "—")
        opts       = l.get("options_brutes") or []
        opts_str   = ", ".join(str(o) for o in opts[:5]) if opts else "—"
        desc       = (l.get("description") or "")[:120]
        img        = l.get("image_url") or ""
        puissance  = l.get("puissance_cv") or l.get("puissance_kw") or ""
        carrosserie= l.get("carrosserie") or ""

        dlr_bg  = _dealer_badge_color(dealer_key)
        dlr_col = _dealer_text_color(dealer_key)

        puissance_str = f"{puissance} CV" if puissance else ""

        # Silhouette voiture sportive — fond bleu dégradé + trait blanc fin (fidèle à l'image de référence)
        _svg = (
            '<svg class="car-thumb-placeholder" viewBox="0 0 72 48" xmlns="http://www.w3.org/2000/svg">'
            '<defs>'
            '<radialGradient id="bg" cx="50%" cy="50%" r="70%">'
            '<stop offset="0%" stop-color="#1e4080"/>'
            '<stop offset="100%" stop-color="#0d1f45"/>'
            '</radialGradient>'
            '</defs>'
            '<rect width="72" height="48" rx="4" fill="url(#bg)"/>'
            # Carrosserie principale — ligne de toit très fuyante, coupé sportif
            '<path d="M6 33 Q7 33 10 32 Q13 31 17 27 Q22 22 29 20 Q36 18.5 43 19 Q50 19.5 56 22 Q61 25 64 29 Q66 31 66 33" '
            'stroke="white" stroke-width="1.3" fill="none" stroke-linecap="round"/>'
            # Bas de caisse / plancher
            '<path d="M6 33 Q6 35 8 36 L62 36 Q65 36 66 33" '
            'stroke="white" stroke-width="1.1" fill="none" stroke-linecap="round"/>'
            # Liaison avant (nez plongeant)
            '<path d="M6 33 Q5.5 34 6 35 Q6.5 35.5 8 36" '
            'stroke="white" stroke-width="1.1" fill="none" stroke-linecap="round"/>'
            # Prise d\'air / bouclier avant
            '<path d="M6 34.5 Q7 33.8 10 33.5 Q9.5 34.8 8 35.5 Q7 35.5 6 34.5 Z" '
            'fill="white" opacity=".9"/>'
            # Spoiler arrière / queue relevée
            '<path d="M64 29 Q67 27.5 68 28 Q68 29 66.5 30" '
            'stroke="white" stroke-width="1.1" fill="none" stroke-linecap="round"/>'
            '<path d="M66 30 Q68 29.5 68.5 30.5 Q68 31.5 66 31.5 Z" '
            'fill="white" opacity=".85"/>'
            # Ligne de caisse (character line) — ombre portée
            '<path d="M9 32.5 Q30 31 55 31.5 Q61 31.8 65 32.5" '
            'stroke="white" stroke-width=".45" fill="none" opacity=".35" stroke-linecap="round"/>'
            '</svg>'
        )
        if img:
            # SVG hidden by default; revealed if the img fails to load
            _svg_hidden = _svg.replace('class="car-thumb-placeholder"',
                                       'class="car-thumb-placeholder" style="display:none"')
            thumb = (
                f'<img src="{img}" class="car-thumb" loading="lazy" '
                f'onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'block\'">'
                f'{_svg_hidden}'
            )
        else:
            thumb = _svg

        rows_html += f"""
        <tr data-dealer="{dealer_key}" data-brand="{marque}" data-tx="{tx_clean}">
          <td class="rank">#{i}</td>
          <td class="thumb-cell">{thumb}</td>
          <td class="car-name">
            <strong>{marque} {modele}</strong>
            {'<span class="carrosserie-chip">' + carrosserie + '</span>' if carrosserie else ''}
            <br><small class="puissance">{puissance_str}</small>
          </td>
          <td class="prix">{prix_fmt}</td>
          <td>{km_fmt}</td>
          <td>{annee}</td>
          <td><span class="tx {_tx_class(tx_clean)}">{tx_clean}</span></td>
          <td class="couleur-cell">{couleur}</td>
          <td class="opts">{opts_str}</td>
          <td class="desc">{desc}</td>
          <td class="vendeur">
            <span class="dealer-badge" style="background:{dlr_bg};color:{dlr_col}">{dealer_nm}</span>
          </td>
          <td><a href="{url}" target="_blank" rel="noopener">Voir</a></td>
        </tr>"""

    # Options pour les filtres
    dealer_opts = "".join(f'<option value="{k}">{v}</option>' for k, v in dealer_map.items())
    brand_opts  = "".join(f'<option value="{b}">{b}</option>' for b in all_brands)


    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} — {timestamp}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #0f172a; color: #e2e8f0; font-size: 13px; }}

    /* Header */
    header {{ background: #1e293b; padding: 18px 28px; display: flex;
              align-items: center; justify-content: space-between;
              border-bottom: 1px solid #334155; }}
    header h1 {{ font-size: 20px; font-weight: 700; color: #f8fafc; letter-spacing: -.3px; }}
    header p  {{ font-size: 11px; color: #94a3b8; margin-top: 3px; }}
    .header-right {{ text-align: right; font-size: 11px; color: #475569; }}

    /* Stats bar */
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; padding: 16px 28px;
              background: #1e293b; border-bottom: 1px solid #334155; }}
    .stat {{ background: #0f172a; border: 1px solid #334155; border-radius: 8px;
             padding: 10px 16px; min-width: 110px; text-align: center; }}
    .stat-val {{ display: block; font-size: 16px; font-weight: 700; color: #f8fafc; }}
    .stat-lbl {{ display: block; font-size: 10px; color: #64748b; margin-top: 2px; }}

    /* Filter bar */
    .filter-bar {{ padding: 12px 28px; background: #0f172a; display: flex;
                   gap: 10px; align-items: center; flex-wrap: wrap;
                   border-bottom: 1px solid #1e293b; }}
    .filter-bar input {{ background: #1e293b; border: 1px solid #334155; color: #e2e8f0;
                         border-radius: 6px; padding: 7px 12px; font-size: 13px; width: 220px; }}
    .filter-bar input:focus {{ outline: none; border-color: #38bdf8; }}
    .filter-bar label {{ color: #64748b; font-size: 12px; white-space: nowrap; }}
    .filter-bar select {{ background: #1e293b; border: 1px solid #334155; color: #e2e8f0;
                          border-radius: 6px; padding: 7px 10px; font-size: 12px; cursor: pointer; }}
    .filter-bar select:focus {{ outline: none; border-color: #38bdf8; }}
    .filter-count {{ margin-left: auto; color: #475569; font-size: 11px; }}

    /* Table */
    .table-wrap {{ overflow-x: auto; padding: 20px 28px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th {{ background: #1e293b; color: #94a3b8; font-size: 11px; font-weight: 600;
          text-transform: uppercase; letter-spacing: .05em; padding: 10px 12px;
          text-align: left; cursor: pointer; user-select: none;
          border-bottom: 2px solid #334155; white-space: nowrap; position: sticky; top: 0; z-index: 1; }}
    th:hover {{ color: #f8fafc; }}
    th.sorted-asc::after  {{ content: " ↑"; color: #38bdf8; }}
    th.sorted-desc::after {{ content: " ↓"; color: #38bdf8; }}
    td {{ padding: 8px 12px; border-bottom: 1px solid #1e293b; vertical-align: middle; }}
    tr:hover td {{ background: #1e293b; }}

    /* Specific cells */
    .rank {{ color: #475569; font-size: 11px; font-weight: 600; width: 30px; }}
    .thumb-cell {{ width: 80px; padding: 4px 8px; }}
    .car-thumb {{ width: 72px; height: 48px; object-fit: cover; border-radius: 4px;
                  border: 1px solid #334155; display: block; }}
    .car-thumb-placeholder {{ width: 72px; height: 48px; border-radius: 4px;
                               border: 1px solid #334155; display: block; }}
    .car-name {{ min-width: 160px; }}
    .car-name strong {{ font-size: 13px; color: #f8fafc; }}
    .car-name small.puissance {{ color: #64748b; font-size: 10px; }}
    .carrosserie-chip {{ padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 600;
                         background: #1e3a5f; color: #7dd3fc; margin-left: 4px; }}
    .prix {{ font-weight: 700; color: #f8fafc; white-space: nowrap; font-size: 14px; }}
    .couleur-cell {{ font-size: 12px; color: #cbd5e1; }}
    .tx {{ padding: 2px 7px; border-radius: 4px; font-size: 11px; font-weight: 600; }}
    .tx-manuelle  {{ background: #14532d; color: #86efac; }}
    .tx-automatique {{ background: #1e3a5f; color: #93c5fd; }}
    .tx-pdk       {{ background: #1e3a5f; color: #93c5fd; }}
    .tx-dct       {{ background: #1e3a5f; color: #93c5fd; }}
    .tx-robotisee {{ background: #1e3a5f; color: #93c5fd; }}
    .opts {{ font-size: 11px; color: #94a3b8; max-width: 200px; }}
    .desc {{ font-size: 11px; color: #64748b; max-width: 240px; font-style: italic; }}
    .vendeur {{ white-space: nowrap; }}
    .dealer-badge {{ padding: 3px 8px; border-radius: 5px; font-size: 11px; font-weight: 600;
                     display: inline-block; }}
    a {{ color: #38bdf8; text-decoration: none; font-weight: 600; }}
    a:hover {{ text-decoration: underline; }}

    /* Footer */
    footer {{ text-align: center; padding: 20px; color: #334155; font-size: 11px;
              border-top: 1px solid #1e293b; margin-top: 10px; }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>{title}</h1>
      <p>Vendeurs lyonnais · {len(listings)} annonces · {len(dlr_cnt)} vendeurs · Généré le {timestamp}</p>
    </div>
    <div class="header-right">
      Sport Car Match
    </div>
  </header>

  <div class="stats">{stats_html}</div>

  <div class="filter-bar">
    <input id="search" placeholder="Marque, modèle, couleur, options..." oninput="filterRows()">
    <label>Vendeur :
      <select id="dealer-filter" onchange="filterRows()">
        <option value="">Tous</option>
        {dealer_opts}
      </select>
    </label>
    <label>Marque :
      <select id="brand-filter" onchange="filterRows()">
        <option value="">Toutes</option>
        {brand_opts}
      </select>
    </label>
    <label>Prix max :
      <select id="prix-filter" onchange="filterRows()">
        <option value="0">Tous</option>
        <option value="50000">≤ 50k€</option>
        <option value="100000">≤ 100k€</option>
        <option value="150000">≤ 150k€</option>
        <option value="200000">≤ 200k€</option>
        <option value="300000">≤ 300k€</option>
      </select>
    </label>
    <span class="filter-count" id="filter-count">{len(listings)} résultats</span>
  </div>

  <div class="table-wrap">
    <table id="main-table">
      <thead>
        <tr>
          <th>#</th>
          <th></th>
          <th data-col="2">Voiture</th>
          <th data-col="3">Prix</th>
          <th data-col="4">Km</th>
          <th data-col="5">Année</th>
          <th data-col="6">Tx</th>
          <th>Couleur</th>
          <th>Options</th>
          <th>Description</th>
          <th>Vendeur</th>
          <th>Lien</th>
        </tr>
      </thead>
      <tbody id="table-body">
        {rows_html}
      </tbody>
    </table>
  </div>

  <footer>
    Sport Car Match — Vendeurs lyonnais · {len(listings)} annonces scrapées le {timestamp}
  </footer>

  <script>
    let sortCol = null, sortDir = 1;
    document.querySelectorAll("th[data-col]").forEach(th => {{
      th.addEventListener("click", () => {{
        const col = parseInt(th.dataset.col);
        if (sortCol === col) sortDir *= -1; else {{ sortCol = col; sortDir = 1; }}
        document.querySelectorAll("th").forEach(t => t.classList.remove("sorted-asc","sorted-desc"));
        th.classList.add(sortDir === 1 ? "sorted-desc" : "sorted-asc");
        sortTable(col, sortDir);
      }});
    }});

    function sortTable(col, dir) {{
      const tbody = document.getElementById("table-body");
      const rows  = Array.from(tbody.querySelectorAll("tr:not([style*='none'])"));
      const all   = Array.from(tbody.querySelectorAll("tr"));
      rows.sort((a, b) => {{
        const av = cellVal(a, col), bv = cellVal(b, col);
        return (av < bv ? -1 : av > bv ? 1 : 0) * dir;
      }});
      rows.forEach(r => tbody.appendChild(r));
    }}

    function cellVal(row, col) {{
      const cell = row.cells[col];
      if (!cell) return "";
      const text = cell.textContent.replace(/[^\\d.,]/g, "").replace(/\\s/g, "").replace(",",".");
      return parseFloat(text) || cell.textContent.trim();
    }}

    function filterRows() {{
      const q      = document.getElementById("search").value.toLowerCase();
      const dealer = document.getElementById("dealer-filter").value;
      const brand  = document.getElementById("brand-filter").value;
      const maxPrix= parseFloat(document.getElementById("prix-filter").value) || 0;
      let visible  = 0;
      document.querySelectorAll("#table-body tr").forEach(row => {{
        const text      = row.textContent.toLowerCase();
        const rowDealer = row.dataset.dealer || "";
        const rowBrand  = row.dataset.brand  || "";
        const prixCell  = row.cells[3] ? row.cells[3].textContent.replace(/[^\\d]/g,"") : "0";
        const prixVal   = parseFloat(prixCell) || 0;
        const ok = text.includes(q)
                && (dealer === "" || rowDealer.includes(dealer))
                && (brand  === "" || rowBrand.toLowerCase().includes(brand.toLowerCase()))
                && (maxPrix === 0  || prixVal <= maxPrix);
        row.style.display = ok ? "" : "none";
        if (ok) visible++;
      }});
      document.getElementById("filter-count").textContent = visible + " résultat" + (visible > 1 ? "s" : "");
    }}
  </script>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  HTML: {path}")
    webbrowser.open(f"file://{os.path.abspath(path)}")


# ---------------------------------------------------------------------------
# Save JSON + CSV + HTML
# ---------------------------------------------------------------------------

def save_results(listings, label="lyon_dealers"):
    if not listings:
        print("\n  Aucune annonce à sauvegarder.")
        return

    ts        = datetime.now().strftime("%Y%m%d_%H%M")
    base_name = f"annonces_{label}_{ts}"

    # JSON
    json_path = f"{base_name}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(listings, f, indent=2, ensure_ascii=False)
    print(f"\n  JSON: {json_path}")

    # CSV
    csv_path = f"{base_name}.csv"
    fields = ["source", "dealer_name", "marque", "modele", "annee", "km", "prix",
              "tx_clean", "couleur", "carrosserie", "puissance_cv",
              "description", "options_brutes", "url", "image_url"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for l in listings:
            row = {k: l.get(k) for k in fields}
            row["options_brutes"] = "; ".join(str(o) for o in (l.get("options_brutes") or []))
            writer.writerow(row)
    print(f"  CSV:  {csv_path}")

    # Stats console
    prices    = [l["prix"] for l in listings if l.get("prix")]
    kms       = [l["km"]   for l in listings if l.get("km")]
    tx_cnt    = Counter(l.get("tx_clean", "?") for l in listings)
    dlr_cnt   = Counter(l.get("dealer_name", "?") for l in listings)
    brand_cnt = Counter(l.get("marque", "?") for l in listings)

    print(f"\n  Résumé:")
    print(f"    Annonces totales   : {len(listings)}")
    if prices: print(f"    Prix min/max/moy   : {min(prices):,} / {max(prices):,} / {int(sum(prices)/len(prices)):,} EUR")
    if kms:    print(f"    Km   min/max/moy   : {min(kms):,} / {max(kms):,} / {int(sum(kms)/len(kms)):,}")
    print(f"    Transmissions      : " + " | ".join(f"{t}: {n}" for t, n in tx_cnt.most_common()))
    print(f"    Par vendeur        : " + " | ".join(f"{d}: {n}" for d, n in dlr_cnt.most_common()))
    print(f"    Par marque (top 5) : " + " | ".join(f"{b}: {n}" for b, n in brand_cnt.most_common(5)))

    html_path = f"rapport_{label}_{ts}.html"
    save_html_report(listings, html_path, title="Voitures Sport Lyon")
    return json_path, csv_path, html_path
