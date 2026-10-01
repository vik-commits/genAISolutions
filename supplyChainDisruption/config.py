"""Central configuration: paths, model choice, and business rules."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("SUPPLY_DATA_DIR", BASE_DIR / "data"))
OUTPUT_DIR = Path(os.getenv("SUPPLY_OUTPUT_DIR", BASE_DIR / "outputs"))

# Any LiteLLM / CrewAI model string works, e.g. "openai/gpt-4o" or "anthropic/claude-sonnet-5-5"
MODEL = os.getenv("CREW_MODEL", "anthropic/claude-sonnet-5-5")
TEMPERATURE = float(os.getenv("CREW_TEMPERATURE", "0.1"))

# Lower number = higher priority
TIER_PRIORITY = {"A": 1, "B": 2, "C": 3}

# Planning horizon used when checking whether a DC can spare inventory for a transfer
TRANSFER_HORIZON_DAYS = 21

BUSINESS_RULES = [
    "Tier A orders must be protected (0 days late) whenever any feasible option exists.",
    "Only suppliers with approved = Y may be used now. Unapproved suppliers may be mentioned only as a future qualification idea.",
    "Prefer inventory transfers between DCs before new purchases, as long as the source DC stays at or above safety stock.",
    "Air freight is allowed only if it protects a Tier A order, or if the penalty exposure it avoids is greater than its cost.",
    "Plans with total incremental cost above 10000 USD require operations manager approval.",
    "Plans with total incremental cost above 25000 USD require VP of Supply Chain approval.",
    "Every order that remains late by 1 day or more after the plan must get a customer notice. Tier A customers get a personalized notice.",
    "Never promise customers a date that the scenario test does not support.",
]


def business_rules_text() -> str:
    return "\n".join(f"- {rule}" for rule in BUSINESS_RULES)
