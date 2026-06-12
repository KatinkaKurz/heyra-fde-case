"""
engine.py — LLM-driven meal generation.

The LLM is the creative composer; this file has no offline fallback.
Validation lives in validator.py (next module).

Design boundary (deliberate):
  - The prompt carries only what code cannot recover after the fact:
      1. the task shape (one product per required component),
      2. grounding (use only product_ids we hand it),
      3. the output format (parseable JSON).
  - The gram ranges and calorie band are given as GUIDANCE, not hard rules.
    The validator (deterministic code) owns those numeric guarantees, so we
    don't duplicate them as commandments here. This keeps the LLM free to be
    creative within a brief, and keeps a clean line between "LLM composes" and
    "code checks".
  - temperature=0 is for reproducibility (same inputs -> same dish each run),
    which is separate from how strict the rules are.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import anthropic
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
MODEL = "claude-sonnet-4-6"

CONSTRAINTS: dict[str, Any] = {
    "calorie_band_kcal": {"min": 550, "target": 650, "max": 900},
    "plate_mass_g": {"min": 400, "max": 700},
    "components": {
        "carb_base":  {"min_g": 150, "max_g": 240, "required": True},
        "protein":    {"min_g": 80,  "max_g": 150, "required": True},
        "vegetables": {"min_g": 100, "max_g": 250, "required": True},
        "sauce":      {"min_g": 30,  "max_g": 120, "required": False},
    },
}

# df meal_component value -> shortlist / prompt role
_ROLE_MAP: dict[str, str] = {
    "carb_base":      "carb_base",
    "protein":        "protein",
    "vegetables":     "vegetables",
    "sauce_dressing": "sauce",
}

_REQUIRED_ROLES = ("carb_base", "protein", "vegetables")

_KEEP_COLS = [
    "product_id", "product_name", "ingredient_group",
    "energy_kcal_per_100g", "cost_per_100g_eur",
]

# ---------------------------------------------------------------------------
# System prompt — three hard rules + soft guidance. Constant across all days.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a canteen chef for a university canteen. For each request you compose ONE vegetarian \
main dish for a university canteen, grounded in a list of real candidate products. Make sure the dishes you create are common and appealing, and that the components go well together. You can base this on common culinary patterns (e.g. "rice + beans + veggies + hot sauce" or "pasta + tomato sauce + veggies + cheese") but feel free to be creative within those patterns. You can use the same product in multiple dishes across the week.

HARD RULES (these must hold):
1. Choose exactly one product for each required component: carb_base, protein, and vegetables. \
You may optionally add one sauce.
2. Use ONLY product_ids that appear in the candidate list you are given. Never invent an id.
3. Respond with ONLY a single JSON object in the exact shape below — no markdown, no code \
fences, no commentary.

GUIDANCE (aim for these; you don't have to hit them exactly — a downstream checker handles the limits):
- Aim for roughly 650 kcal total; a sensible main usually lands between 550 and 900 kcal. \
Per item, kcal = grams / 100 x energy_kcal_per_100g.
- Keep each component near the suggested gram amounts shown next to it, and the whole plate \
around 400-700 g.
- Above all, make it a coherent, appealing dish a canteen could actually plate and serve. \

OUTPUT SHAPE:
{
  "day": "<the day you were given>",
  "name": "<dish name>",
  "summary": "<one-sentence description>",
  "components": [
    {"role": "carb_base", "product_id": <int>, "grams": <int>},
    {"role": "protein", "product_id": <int>, "grams": <int>},
    {"role": "vegetables", "product_id": <int>, "grams": <int>}
  ]
}
Add a sauce object to "components" only if you chose one. Do NOT output calories, cost, or \
allergens — those are computed downstream."""


# ---------------------------------------------------------------------------
# 1. build_shortlist
# ---------------------------------------------------------------------------

def build_shortlist(
    components_df: pd.DataFrame,
    seed: int,
    per_component: int = 12,
) -> dict[str, list[dict]]:
    """
    Deterministically sample up to `per_component` real products per role.
    Returns {role: [product_dict, ...]}. The LLM may only pick ids from this set.

    Raises ValueError if a required component has no available products, so the
    failure is loud and informative rather than a silent "(no candidates)".
    """
    shortlist: dict[str, list[dict]] = {}
    for df_role, prompt_role in _ROLE_MAP.items():
        subset = components_df[components_df["meal_component"] == df_role][_KEEP_COLS]
        n = min(per_component, len(subset))
        if prompt_role in _REQUIRED_ROLES and n == 0:
            raise ValueError(
                f"No available products for required component '{prompt_role}'. "
                f"Check the meal_component mapping or the upstream filters."
            )
        sampled = subset.sample(n=n, random_state=seed)
        shortlist[prompt_role] = sampled.to_dict(orient="records")
    return shortlist


# ---------------------------------------------------------------------------
# 2. build_prompt — the per-day user message (just the grounded data)
# ---------------------------------------------------------------------------

def build_prompt(
    day: str,
    shortlist: dict[str, list[dict]],
    constraints: dict,
) -> str:
    """Return the per-day user prompt: the candidate products for this day."""
    comp = constraints["components"]

    def fmt_candidates(role: str) -> str:
        rows = [
            f"  - id={p['product_id']:>4}  \"{p['product_name']}\"  "
            f"{p['energy_kcal_per_100g']} kcal/100g  €{p['cost_per_100g_eur']:.2f}/100g"
            for p in shortlist.get(role, [])
        ]
        return "\n".join(rows) if rows else "  (no candidates)"

    return f"""Day: {day}

CANDIDATES — choose only from these product_ids:

carb_base (suggested ~{comp['carb_base']['min_g']}-{comp['carb_base']['max_g']} g, required):
{fmt_candidates('carb_base')}

protein (suggested ~{comp['protein']['min_g']}-{comp['protein']['max_g']} g, required):
{fmt_candidates('protein')}

vegetables (suggested ~{comp['vegetables']['min_g']}-{comp['vegetables']['max_g']} g, required):
{fmt_candidates('vegetables')}

sauce (suggested ~{comp['sauce']['min_g']}-{comp['sauce']['max_g']} g, optional):
{fmt_candidates('sauce')}

Compose the dish for {day}. Return only the JSON object."""


# ---------------------------------------------------------------------------
# 3. generate_meal_llm
# ---------------------------------------------------------------------------

def generate_meal_llm(day: str, shortlist: dict[str, list[dict]]) -> dict:
    """
    Call the model and return a parsed meal dict.

    Robust JSON extraction:
      - strips ``` code fences
      - takes the first { ... } block in the response

    Raises ValueError with a clear message on malformed output.
    Sets source="llm" on the returned dict.
    """
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    prompt = build_prompt(day, shortlist, CONSTRAINTS)

    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        temperature=1,                 # creative variety across runs
        system=SYSTEM_PROMPT,          # fixed rules live here, not in every user msg
        messages=[{"role": "user", "content": prompt}],
    )
    raw: str = message.content[0].text

    # Strip code fences, then take the first {...} block.
    cleaned = re.sub(r"```(?:json)?", "", raw).strip("`").strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(
            f"[{day}] LLM returned no JSON object.\n--- raw response ---\n{raw}"
        )

    try:
        meal = json.loads(match.group())
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"[{day}] JSON parse error: {exc}\n"
            f"--- extracted block ---\n{match.group()}"
        ) from exc

    meal["source"] = "llm"
    return meal


# ---------------------------------------------------------------------------
# 4. generate_week
# ---------------------------------------------------------------------------

def generate_week(components_df: pd.DataFrame, run_seed: int | None = None) -> list[dict]:
    """
    Generate one vegetarian main per weekday (Mon-Fri).

    Per-day failures are captured as {"day": ..., "error": ...} so one bad day
    never crashes the whole run. Each day's outcome is printed immediately.

    Raises EnvironmentError up front if ANTHROPIC_API_KEY is missing.
    Returns a list of 5 dicts (each a meal or an error record).
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise EnvironmentError(
            "ANTHROPIC_API_KEY is not set.\n"
            "Add it to your .env file or export it in your shell before running."
        )

    if run_seed is None:
        import random
        run_seed = random.randint(0, 10_000)
    print(f"run_seed={run_seed}  (pass this to reproduce the same shortlists)\n")

    results: list[dict] = []
    for idx, day in enumerate(WEEKDAYS):
        print(f"-> {day}: generating ...", end=" ", flush=True)
        try:
            shortlist = build_shortlist(components_df, seed=run_seed * len(WEEKDAYS) + idx)
            meal = generate_meal_llm(day, shortlist)
            results.append(meal)
            print(f"OK  {meal.get('name', '(unnamed)')}")
        except Exception as exc:
            results.append({"day": day, "error": str(exc)})
            print(f"FAILED  {exc}")

    return results


# ---------------------------------------------------------------------------
# CLI — run directly: python engine.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()  # loads .env from the current directory

    MEAL_COMPONENT_MAP = {
        "grains": "carb_base", "rices": "carb_base",
        "pastas": "carb_base", "breads": "carb_base",
        "legumes": "protein", "eggs": "protein",
        "plant proteins": "protein", "nuts": "protein",
        "seeds": "protein", "cheeses": "protein",
        "vegetables": "vegetables", "mushrooms": "vegetables",
        "fruits": "vegetables",
        "sauces": "sauce_dressing", "condiments": "sauce_dressing",
        "oils": "sauce_dressing", "creams and butters": "sauce_dressing",
        "yogurts": "sauce_dressing",
        "flours": "other", "milks": "other",
        "plant-based beverages": "other", "sweeteners": "other",
        "spices": "other", "herbs": "other",
    }

    df = pd.read_csv("products.csv")
    df_filtered = df[
        df["dietary_class"].isin(["vegan", "vegetarian"]) &
        (df["is_available"] == 1)
    ].copy()
    df_filtered["meal_component"] = df_filtered["ingredient_group"].map(MEAL_COMPONENT_MAP)

    week = generate_week(df_filtered)

    out_path = "week.json"
    with open(out_path, "w") as f:
        json.dump(week, f, indent=2)
    print(f"\nSaved to {out_path}. Run `python validator.py` to validate.")