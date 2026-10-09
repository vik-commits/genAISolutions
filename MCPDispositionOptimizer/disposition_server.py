"""Reverse logistics disposition optimizer, exposed as an MCP server.

Run:  pip install mcp pulp highspy
      python disposition_server.py
"""
from mcp.server.mcpserver import MCPServer  # mcp SDK 2.x (was FastMCP in 1.x)
import pulp

mcp = MCPServer("disposition-optimizer")

# --- Synthetic data: today's returned units by condition grade -------------
RETURNS = {"A": 1200, "B": 1800, "C": 900, "D": 600}

# Net value per unit ($) after processing cost; None = not allowed
VALUE = {
    #        Refurbish  Parts  Liquidate  Recycle
    "A": {"refurb": 210, "parts": 60, "liquidate": 95, "recycle": 8},
    "B": {"refurb": 140, "parts": 55, "liquidate": 70, "recycle": 8},
    "C": {"refurb": 45,  "parts": 50, "liquidate": 30, "recycle": 8},
    "D": {"refurb": None, "parts": 35, "liquidate": 5, "recycle": 8},
}

DEFAULTS = {"refurb_capacity": 2000, "resale_demand": 2500, "parts_demand": 1000}


def solve(refurb_capacity: int, resale_demand: int, parts_demand: int) -> dict:
    """Linear program: maximize total recovery value across all channels."""
    model = pulp.LpProblem("disposition", pulp.LpMaximize)
    lanes = [(g, c) for g in VALUE for c, v in VALUE[g].items() if v is not None]
    x = {(g, c): model.add_variable(f"x_{g}_{c}", lowBound=0) for g, c in lanes}

    model += pulp.lpSum(VALUE[g][c] * x[g, c] for g, c in lanes)

    for g, qty in RETURNS.items():  # every unit gets exactly one disposition
        model += pulp.lpSum(x[g, c] for gg, c in lanes if gg == g) == qty, f"units_{g}"
    refurb = pulp.lpSum(x[g, "refurb"] for g in VALUE if (g, "refurb") in x)
    model += refurb <= refurb_capacity, "refurb_capacity"
    model += refurb <= resale_demand, "resale_demand"
    model += pulp.lpSum(x[g, "parts"] for g in VALUE) <= parts_demand, "parts_demand"

    result = model.solve(pulp.HiGHS(msg=False))
    if result.status != pulp.LpSolveStatus.Optimal:
        return {"status": result.status.name}  # e.g. Infeasible -> agent explains why

    plan = {g: {c: round(x[g, c].value()) for gg, c in lanes if gg == g and x[g, c].value() > 0.5}
            for g in VALUE}
    # Shadow price = how much total value rises if a limit grows by one unit
    binding = {}
    for name in ("refurb_capacity", "resale_demand", "parts_demand"):
        price = abs(model.get_constraint_by_name(name).pi)
        if price > 1e-6:
            binding[name] = {"value_of_one_more_unit": round(price, 2)}
    return {"status": "Optimal",
            "total_recovery_value": round(pulp.value(model.objective)),
            "plan_by_grade": plan,
            "binding_constraints": binding}


@mcp.tool()
def get_returns_snapshot() -> dict:
    """Today's returned units by grade, net value per channel, and default limits."""
    return {"returns": RETURNS, "unit_value": VALUE, "default_limits": DEFAULTS}


@mcp.tool()
def solve_disposition_plan(refurb_capacity: int = 2000,
                           resale_demand: int = 2500,
                           parts_demand: int = 1000) -> dict:
    """Find the value-maximizing disposition plan. Override any limit to run a what-if."""
    return solve(refurb_capacity, resale_demand, parts_demand)


if __name__ == "__main__":
    mcp.run()
