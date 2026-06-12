# Heyra - Vegetarian Menu Planner

LLM-driven canteen menu generator. Produces a validated weekly meal plan from a product catalogue and renders it as an HTML overview.

---

## Setup

**1. Install dependencies**
```bash
pip install anthropic python-dotenv pandas
```

**2. Add your API key**

Create a `.env` file in the project root:
```
ANTHROPIC_API_KEY=your-key-here
```

**3. Make sure `products.csv` is in the project root** — it is the product catalogue the engine draws from.

---

## Workflow

Run the three scripts in order:

```bash
python engine.py      # generate week.json
python validator.py   # validate week.json (prints pass/fail report)
python report.py      # write menu.html (only succeeds if validation passes)
```

Then open the result:
```bash
open menu.html
```

---

## Files

| File | Role |
|---|---|
| `engine.py` | Calls the Claude API to compose one vegetarian meal per weekday. Saves output to `week.json`. |
| `validator.py` | Deterministic checks on `week.json`: required components present, product IDs exist in catalogue, no meat. Computes kcal, weight, and cost totals. |
| `report.py` | Reads `week.json` + validation results and renders `menu.html`. Refuses to run if validation failed. |
| `products.csv` | Product catalogue (3 137 items, 11 columns). Source of truth for IDs, nutrition, cost, and allergens. |
| `week.json` | Generated at runtime by `engine.py`. Input to `validator.py` and `report.py`. |
| `menu.html` | Generated at runtime by `report.py`. Open in any browser. |

---

## Constraints (engine)

| | |
|---|---|
| Dietary | Vegetarian / vegan only |
| Calories | 550–900 kcal target (soft guidance to LLM) |
| Plate weight | 400–700 g |
| Required components | Carb base, protein, vegetables |
| Optional component | Sauce / dressing |
