# Heyra — Vegetarian Menu Planner

LLM-driven canteen menu generator. Run three scripts in order to go from a product catalogue to a validated, client-ready HTML menu.

```bash
python engine.py
python validator.py
python report.py
```

---

## engine.py

Generates one vegetarian main meal per weekday using Claude.

- Samples a shortlist of real products from the catalogue per component role (carb base, protein, vegetables, sauce)
- Sends each day to the LLM with grounded candidates — the model picks products and portion sizes
- Captures per-day errors so one failure doesn't abort the full week
- Saves the result to `week.json`

## validator.py

Deterministic checks on `week.json` — no LLM involved.

- Verifies all required component roles are present (carb base, protein, vegetables)
- Checks every product ID exists in the catalogue (catches hallucinations)
- Confirms no meal contains a meat product
- Computes and reports totals: kcal, weight (g), and cost (€) per meal

## report.py

Renders `week.json` into a client-facing `menu.html`.

- Refuses to run if validation has not fully passed
- Shows one card per day: meal name, description, ingredients with weights
- Displays allergen status (gluten, nuts, dairy) per meal
- Shows per-meal totals: weight, kcal, cost
