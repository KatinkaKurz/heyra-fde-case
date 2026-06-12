"""
validator.py — deterministic checks on engine output.

Checks (in order):
  1. Engine error pass-through  — day already failed upstream
  2. Required roles present      — carb_base, protein, vegetables
  3. Product IDs exist           — no hallucinated ids
  4. Dietary class               — nothing with dietary_class='meat'

Totals computed (always, for every valid id found):
  - kcal, grams, cost_eur
"""

from __future__ import annotations

import json
import sys

import pandas as pd

REQUIRED_ROLES = {"carb_base", "protein", "vegetables"}


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def validate_meal(meal: dict, catalogue: pd.DataFrame) -> dict:
    """Validate one meal dict. Returns {day, passed, errors, totals}."""

    # Engine already failed this day — surface the error unchanged
    if "error" in meal:
        return {
            "day": meal["day"],
            "passed": False,
            "errors": [f"Engine error: {meal['error']}"],
            "totals": None,
        }

    errors: list[str] = []

    # 1. Required roles
    roles_present = {c["role"] for c in meal.get("components", [])}
    missing = REQUIRED_ROLES - roles_present
    if missing:
        errors.append(f"Missing required roles: {sorted(missing)}")

    # 2 & 3. Per-component: id exists + dietary check + accumulate totals
    totals = {"kcal": 0.0, "grams": 0, "cost_eur": 0.0}
    for comp in meal.get("components", []):
        pid   = comp["product_id"]
        grams = comp["grams"]
        role  = comp["role"]

        row = catalogue[catalogue["product_id"] == pid]
        if row.empty:
            errors.append(f"[{role}] product_id {pid} not found in catalogue (hallucinated)")
            continue

        row = row.iloc[0]

        if row["dietary_class"] == "meat":
            errors.append(
                f"[{role}] product_id {pid} ({row['product_name']}) "
                f"has dietary_class='meat'"
            )

        totals["kcal"]     += grams / 100 * row["energy_kcal_per_100g"]
        totals["grams"]    += grams
        totals["cost_eur"] += grams / 100 * row["cost_per_100g_eur"]

    totals["kcal"]     = round(totals["kcal"], 1)
    totals["cost_eur"] = round(totals["cost_eur"], 2)

    return {
        "day":    meal.get("day"),
        "passed": len(errors) == 0,
        "errors": errors,
        "totals": totals,
    }


def validate_week(week: list[dict], catalogue: pd.DataFrame) -> list[dict]:
    return [validate_meal(meal, catalogue) for meal in week]


# ---------------------------------------------------------------------------
# CLI — python validator.py [week.json]
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    in_path = sys.argv[1] if len(sys.argv) > 1 else "week.json"

    with open(in_path) as f:
        week = json.load(f)

    catalogue = pd.read_csv("products.csv")
    results = validate_week(week, catalogue)

    print(f"\n{'='*58}")
    print(f"  VALIDATION REPORT  —  {in_path}")
    print(f"{'='*58}")

    all_passed = True
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        if not r["passed"]:
            all_passed = False

        print(f"\n{r['day']:10s}  [{status}]")

        if r["totals"]:
            t = r["totals"]
            print(
                f"             {t['grams']} g  |  "
                f"{t['kcal']} kcal  |  "
                f"€{t['cost_eur']:.2f}"
            )

        for err in r["errors"]:
            print(f"  ✗  {err}")

    print(f"\n{'='*58}")
    print(f"  {'ALL DAYS PASSED' if all_passed else 'SOME DAYS FAILED'}")
    print(f"{'='*58}\n")

    sys.exit(0 if all_passed else 1)
