"""
report.py — generate menu.html from week.json.

Reads week.json + products.csv, runs validation, and writes menu.html.
Exits with an error if validation fails — fix the engine output first.

Usage: python report.py [week.json]
"""

import json
import sys

import pandas as pd

from validator import validate_week

ALLERGEN_COLS = ["allergen_gluten", "allergen_nuts", "allergen_dairy"]
ALLERGEN_LABELS = {"allergen_gluten": "Gluten", "allergen_nuts": "Nuts", "allergen_dairy": "Dairy"}

ROLE_LABELS = {
    "carb_base": "Carb base",
    "protein": "Protein",
    "vegetables": "Vegetables",
    "sauce": "Sauce",
}


def build_meal_html(meal: dict, catalogue: pd.DataFrame, totals: dict) -> str:
    allergens_in_meal = {col: False for col in ALLERGEN_COLS}
    rows = ""
    for comp in meal.get("components", []):
        pid = comp["product_id"]
        grams = comp["grams"]
        role = comp["role"]
        row = catalogue[catalogue["product_id"] == pid].iloc[0]
        for col in ALLERGEN_COLS:
            if row[col] == 1:
                allergens_in_meal[col] = True
        rows += f"""
        <tr>
          <td>{ROLE_LABELS.get(role, role)}</td>
          <td>{row['product_name']}</td>
          <td class="num">{grams} g</td>
        </tr>"""

    allergen_tags = ""
    for col, present in allergens_in_meal.items():
        label = ALLERGEN_LABELS[col]
        cls = "tag-allergen" if present else "tag-free"
        text = label if present else f"{label}-free"
        allergen_tags += f'<span class="{cls}">{text}</span>'

    return f"""
  <div class="card">
    <div class="card-header">
      <span class="day">{meal['day']}</span>
      <span class="meal-name">{meal.get('name', '—')}</span>
    </div>
    <p class="summary">{meal.get('summary', '')}</p>
    <table>
      <thead><tr><th>Role</th><th>Ingredient</th><th>Amount</th></tr></thead>
      <tbody>{rows}
      </tbody>
    </table>
    <div class="footer">
      <div class="allergens">{allergen_tags}</div>
      <div class="totals">
        <span>{totals['grams']} g total</span>
        <span>{totals['kcal']} kcal</span>
        <span>€{totals['cost_eur']:.2f}</span>
      </div>
    </div>
  </div>"""


def build_html(meals: list[dict], catalogue: pd.DataFrame, results: list[dict]) -> str:
    cards = ""
    for meal, result in zip(meals, results):
        cards += build_meal_html(meal, catalogue, result["totals"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Weekly Vegetarian Menu</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: system-ui, sans-serif; background: #f5f5f0; color: #1a1a1a; padding: 2rem; }}
    h1 {{ font-size: 1.5rem; font-weight: 600; margin-bottom: 0.25rem; }}
    .subtitle {{ color: #666; margin-bottom: 2rem; font-size: 0.9rem; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 1.25rem; }}
    .card {{ background: #fff; border-radius: 10px; padding: 1.25rem; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
    .card-header {{ display: flex; align-items: baseline; gap: 0.6rem; margin-bottom: 0.5rem; }}
    .day {{ font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: #4a7c59; background: #e8f4ec; padding: 0.2rem 0.5rem; border-radius: 4px; }}
    .meal-name {{ font-size: 1rem; font-weight: 600; }}
    .summary {{ font-size: 0.82rem; color: #666; margin-bottom: 0.9rem; line-height: 1.4; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.83rem; margin-bottom: 0.9rem; }}
    th {{ text-align: left; color: #888; font-weight: 500; padding: 0.25rem 0; border-bottom: 1px solid #eee; }}
    td {{ padding: 0.3rem 0; border-bottom: 1px solid #f0f0f0; vertical-align: top; }}
    td.num {{ text-align: right; color: #555; white-space: nowrap; }}
    .footer {{ display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.5rem; }}
    .allergens {{ display: flex; flex-wrap: wrap; gap: 0.3rem; }}
    .tag-allergen {{ background: #fff3cd; color: #7a5c00; font-size: 0.72rem; padding: 0.15rem 0.45rem; border-radius: 20px; border: 1px solid #f0d060; }}
    .tag-free {{ background: #f0f0f0; color: #999; font-size: 0.72rem; padding: 0.15rem 0.45rem; border-radius: 20px; }}
    .totals {{ display: flex; gap: 0.75rem; font-size: 0.8rem; color: #555; white-space: nowrap; }}
    .totals span {{ font-weight: 500; }}
  </style>
</head>
<body>
  <h1>Weekly Vegetarian Menu</h1>
  <p class="subtitle">Canteen menu overview &mdash; all meals verified vegetarian / vegan</p>
  <div class="grid">
    {cards}
  </div>
</body>
</html>"""


if __name__ == "__main__":
    in_path = sys.argv[1] if len(sys.argv) > 1 else "week.json"

    with open(in_path) as f:
        week = json.load(f)

    catalogue = pd.read_csv("products.csv")
    results = validate_week(week, catalogue)

    failed = [r for r in results if not r["passed"]]
    if failed:
        print("Validation failed — fix these days before generating the report:")
        for r in failed:
            print(f"  {r['day']}: {r['errors']}")
        sys.exit(1)

    html = build_html(week, catalogue, results)

    out_path = "menu.html"
    with open(out_path, "w") as f:
        f.write(html)

    print(f"Saved to {out_path}")
