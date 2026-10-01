"""
Deterministic, CSV-backed tools.

The agents reason and decide; these tools do the lookups and the math, so the
numbers in the final plan come from your data rather than from the LLM.
Every tool returns a JSON string, and returns {"error": ...} instead of raising,
so an agent can recover from a bad argument.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional, Tuple, Type

import pandas as pd
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

import config

# --------------------------------------------------------------------------
# Data store
# --------------------------------------------------------------------------
REQUIRED_COLUMNS = {
    "shipments.csv": ["shipment_id", "supplier_id", "sku", "quantity", "destination_warehouse", "original_eta", "status"],
    "inventory.csv": ["sku", "warehouse", "on_hand", "safety_stock", "avg_daily_demand", "unit_weight_kg"],
    "open_orders.csv": ["order_id", "customer", "customer_tier", "sku", "quantity", "due_date",
                        "ship_from_warehouse", "order_value", "late_penalty_per_day"],
    "suppliers.csv": ["supplier_id", "supplier_name", "sku", "unit_cost", "lead_time_days",
                      "available_capacity", "reliability_score", "approved"],
    "lanes.csv": ["from_warehouse", "to_warehouse", "transit_days", "cost_per_unit"],
    "freight_rates.csv": ["mode", "cost_per_kg", "transit_days", "min_charge", "handling_days"],
}
DATE_COLUMNS = {"shipments.csv": ["original_eta"], "open_orders.csv": ["due_date"]}


class DataStore:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.shipments = self._load("shipments.csv")
        self.inventory = self._load("inventory.csv")
        self.orders = self._load("open_orders.csv")
        self.suppliers = self._load("suppliers.csv")
        self.lanes = self._load("lanes.csv")
        self.freight = self._load("freight_rates.csv")
        self.suppliers["approved"] = self.suppliers["approved"].astype(str).str.upper().str.startswith("Y")

    def _load(self, name: str) -> pd.DataFrame:
        path = self.data_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Missing input file: {path}")
        df = pd.read_csv(path)
        df.columns = [c.strip() for c in df.columns]
        missing = set(REQUIRED_COLUMNS[name]) - set(df.columns)
        if missing:
            raise ValueError(f"{name} is missing columns: {sorted(missing)}")
        for col in df.select_dtypes(include="object").columns:
            df[col] = df[col].str.strip()
        for col in DATE_COLUMNS.get(name, []):
            df[col] = pd.to_datetime(df[col]).dt.date
        return df


_STORE: Optional[DataStore] = None


def init_store(data_dir: Path) -> DataStore:
    global _STORE
    _STORE = DataStore(data_dir)
    return _STORE


def store() -> DataStore:
    if _STORE is None:
        init_store(config.DATA_DIR)
    return _STORE


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _d(value) -> date:
    return value if isinstance(value, date) else pd.to_datetime(str(value)).date()


def _json(obj) -> str:
    return json.dumps(obj, default=str, indent=2)


def _inventory_row(sku: str, warehouse: str):
    inv = store().inventory
    rows = inv[(inv.sku == sku) & (inv.warehouse == warehouse)]
    return rows.iloc[0] if len(rows) else None


def _scheduled_receipts(sku: str, warehouse: str, as_of: date,
                        override_shipment: Optional[str] = None,
                        override_eta: Optional[date] = None) -> List[Tuple[date, int]]:
    """All in-transit receipts for a SKU/DC. Optionally move one shipment to a new ETA."""
    s = store().shipments
    rows = s[(s.sku == sku) & (s.destination_warehouse == warehouse) & (s.status != "received")]
    receipts = []
    for _, r in rows.iterrows():
        eta = override_eta if (override_shipment and r.shipment_id == override_shipment) else r.original_eta
        receipts.append((max(eta, as_of), int(r.quantity)))
    return sorted(receipts)


def simulate_fulfillment(sku: str, warehouse: str, as_of: date,
                         receipts: List[Tuple[date, int]]) -> List[dict]:
    """
    Allocate on-hand + incoming supply to open orders in due-date order
    (ties broken by customer tier). Returns a projected ship date per order.
    Orders already past due are treated as due today for allocation purposes.
    """
    inv = _inventory_row(sku, warehouse)
    on_hand = int(inv.on_hand) if inv is not None else 0
    o = store().orders
    orders = o[(o.sku == sku) & (o.ship_from_warehouse == warehouse)].copy()
    orders["tier_rank"] = orders.customer_tier.map(config.TIER_PRIORITY).fillna(9)
    orders = orders.sort_values(["due_date", "tier_rank"])

    receipts = sorted(receipts)
    supply_dates = sorted({as_of} | {d for d, _ in receipts})

    def supply_by(d: date) -> int:
        return on_hand + sum(q for rd, q in receipts if rd <= d)

    results, cumulative = [], 0
    for _, row in orders.iterrows():
        cumulative += int(row.quantity)
        due = max(row.due_date, as_of)
        if supply_by(due) >= cumulative:
            ship = due
        else:
            ship = next((d for d in supply_dates if d > due and supply_by(d) >= cumulative), None)
        days_late = None if ship is None else max(0, (ship - row.due_date).days)
        results.append({
            "order_id": row.order_id,
            "customer": row.customer,
            "customer_tier": row.customer_tier,
            "sku": sku,
            "quantity": int(row.quantity),
            "due_date": row.due_date,
            "projected_ship_date": ship,
            "days_late": days_late,
            "shortfall_at_due": max(0, cumulative - supply_by(due)),
            "order_value": float(row.order_value),
            "late_penalty_per_day": float(row.late_penalty_per_day),
        })
    return results


def projected_stockout(sku: str, warehouse: str, as_of: date,
                       receipts: List[Tuple[date, int]], horizon: int = 90) -> dict:
    """Day-by-day projection using average daily demand."""
    inv = _inventory_row(sku, warehouse)
    if inv is None:
        return {"stockout_date": None, "below_safety_stock_date": None}
    stockout = below_ss = None
    for i in range(horizon + 1):
        day = as_of + timedelta(days=i)
        level = int(inv.on_hand) + sum(q for rd, q in receipts if rd <= day) - float(inv.avg_daily_demand) * i
        if below_ss is None and level < int(inv.safety_stock):
            below_ss = day
        if stockout is None and level <= 0:
            stockout = day
    return {"stockout_date": stockout, "below_safety_stock_date": below_ss}


def compare_scenarios(baseline: List[dict], disrupted: List[dict]) -> dict:
    base = {r["order_id"]: r for r in baseline}
    at_risk, penalty, revenue = [], 0.0, 0.0
    horizon_penalty_days = 30  # used when an order can't be filled at all in the horizon
    for r in disrupted:
        b = base[r["order_id"]]
        b_late = b["days_late"] if b["days_late"] is not None else horizon_penalty_days
        d_late = r["days_late"] if r["days_late"] is not None else horizon_penalty_days
        extra = d_late - b_late
        if extra > 0:
            exposure = extra * r["late_penalty_per_day"]
            at_risk.append({**r, "additional_days_late": extra,
                            "revenue_at_risk": r["order_value"], "penalty_exposure": exposure})
            penalty += exposure
            revenue += r["order_value"]
    return {"at_risk_orders": at_risk,
            "total_revenue_at_risk": round(revenue, 2),
            "total_penalty_exposure": round(penalty, 2)}


def _shipment_line(shipment_id: str, sku: str):
    s = store().shipments
    rows = s[(s.shipment_id == shipment_id) & (s.sku == sku)]
    return rows.iloc[0] if len(rows) else None


def impact_for_line(shipment_id: str, sku: str, new_eta: str, as_of: str,
                    extra_receipts: Optional[List[Tuple[date, int]]] = None) -> dict:
    line = _shipment_line(shipment_id, sku)
    if line is None:
        return {"error": f"No line for sku {sku} on shipment {shipment_id}"}
    as_of_d, new_eta_d = _d(as_of), _d(new_eta)
    wh = line.destination_warehouse
    baseline_r = _scheduled_receipts(sku, wh, as_of_d)
    disrupted_r = _scheduled_receipts(sku, wh, as_of_d, shipment_id, new_eta_d) + list(extra_receipts or [])
    baseline = simulate_fulfillment(sku, wh, as_of_d, baseline_r)
    disrupted = simulate_fulfillment(sku, wh, as_of_d, disrupted_r)
    comparison = compare_scenarios(baseline, disrupted)
    short = [r for r in disrupted if r["shortfall_at_due"] > 0]
    return {
        "sku": sku,
        "warehouse": wh,
        "as_of": as_of_d,
        "baseline_stock_projection": projected_stockout(sku, wh, as_of_d, baseline_r),
        "disrupted_stock_projection": projected_stockout(sku, wh, as_of_d, disrupted_r),
        "units_needed_for_zero_late": max([r["shortfall_at_due"] for r in disrupted], default=0),
        "needed_by": short[0]["due_date"] if short else None,
        **comparison,
        "all_orders_disrupted_scenario": [
            {k: r[k] for k in ("order_id", "customer_tier", "quantity", "due_date", "projected_ship_date", "days_late")}
            for r in disrupted
        ],
    }


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------
class ShipmentLookupInput(BaseModel):
    shipment_id: str = Field(..., description="Shipment id from the disruption event, e.g. SHP-1001")
    new_eta: str = Field(..., description="New ETA in YYYY-MM-DD format")


class ShipmentLookupTool(BaseTool):
    name: str = "shipment_lookup"
    description: str = ("Look up every line on a shipment (SKU, quantity, destination DC, original ETA) plus "
                        "supplier details, and compute the delay in days for each line given the new ETA.")
    args_schema: Type[BaseModel] = ShipmentLookupInput

    def _run(self, shipment_id: str, new_eta: str) -> str:
        try:
            s = store().shipments
            rows = s[s.shipment_id == shipment_id]
            if rows.empty:
                return _json({"error": f"Shipment {shipment_id} not found"})
            sup_id = rows.iloc[0].supplier_id
            sup = store().suppliers[store().suppliers.supplier_id == sup_id]
            new_eta_d = _d(new_eta)
            lines = [{
                "sku": r.sku, "quantity": int(r.quantity), "destination_warehouse": r.destination_warehouse,
                "original_eta": r.original_eta, "new_eta": new_eta_d,
                "delay_days": (new_eta_d - r.original_eta).days, "mode": r.get("mode", ""), "origin": r.get("origin", ""),
            } for _, r in rows.iterrows()]
            return _json({
                "shipment_id": shipment_id, "po_number": rows.iloc[0].get("po_number", ""),
                "supplier_id": sup_id,
                "supplier_name": sup.iloc[0].supplier_name if len(sup) else "unknown",
                "supplier_reliability": float(sup.reliability_score.mean()) if len(sup) else None,
                "lines": lines,
            })
        except Exception as e:  # noqa: BLE001
            return _json({"error": str(e)})


class SkuInput(BaseModel):
    sku: str = Field(..., description="SKU code, e.g. MTR-220")


class InventoryPositionTool(BaseTool):
    name: str = "inventory_position"
    description: str = "Show on-hand, safety stock, daily demand and days of cover for a SKU in every DC."
    args_schema: Type[BaseModel] = SkuInput

    def _run(self, sku: str) -> str:
        inv = store().inventory[store().inventory.sku == sku]
        if inv.empty:
            return _json({"error": f"No inventory records for {sku}"})
        out = []
        for _, r in inv.iterrows():
            cover = round(r.on_hand / r.avg_daily_demand, 1) if r.avg_daily_demand else None
            out.append({"warehouse": r.warehouse, "on_hand": int(r.on_hand), "safety_stock": int(r.safety_stock),
                        "avg_daily_demand": float(r.avg_daily_demand), "days_of_cover": cover})
        return _json({"sku": sku, "positions": out})


class ImpactInput(BaseModel):
    shipment_id: str = Field(..., description="Delayed shipment id")
    sku: str = Field(..., description="SKU on that shipment")
    new_eta: str = Field(..., description="New ETA YYYY-MM-DD")
    as_of: str = Field(..., description="Analysis date YYYY-MM-DD (the event's reported date)")


class ImpactSimulationTool(BaseTool):
    name: str = "impact_simulation"
    description: str = ("Simulate order fulfillment for one SKU at its destination DC with the original ETA vs the "
                        "new ETA. Returns orders that become late (with added days, revenue and penalty exposure), "
                        "projected stockout dates, and how many extra units are needed and by when to make every "
                        "order on time.")
    args_schema: Type[BaseModel] = ImpactInput

    def _run(self, shipment_id: str, sku: str, new_eta: str, as_of: str) -> str:
        try:
            return _json(impact_for_line(shipment_id, sku, new_eta, as_of))
        except Exception as e:  # noqa: BLE001
            return _json({"error": str(e)})


class AlternateSupplierInput(BaseModel):
    sku: str = Field(..., description="SKU to source")
    exclude_supplier_id: str = Field(..., description="The disrupted supplier, excluded from results")
    quantity_needed: int = Field(..., description="Units needed")
    as_of: str = Field(..., description="Order placement date YYYY-MM-DD")


class AlternateSupplierTool(BaseTool):
    name: str = "alternate_suppliers"
    description: str = ("List alternate suppliers for a SKU with approval status, earliest arrival date, "
                        "capacity, reliability, and the cost premium versus the disrupted supplier.")
    args_schema: Type[BaseModel] = AlternateSupplierInput

    def _run(self, sku: str, exclude_supplier_id: str, quantity_needed: int, as_of: str) -> str:
        try:
            sup = store().suppliers[store().suppliers.sku == sku]
            base = sup[sup.supplier_id == exclude_supplier_id]
            base_cost = float(base.unit_cost.iloc[0]) if len(base) else None
            out = []
            for _, r in sup[sup.supplier_id != exclude_supplier_id].iterrows():
                qty = min(int(quantity_needed), int(r.available_capacity))
                premium = (float(r.unit_cost) - base_cost) * qty if base_cost is not None else None
                out.append({
                    "supplier_id": r.supplier_id, "supplier_name": r.supplier_name, "approved": bool(r.approved),
                    "unit_cost": float(r.unit_cost), "lead_time_days": int(r.lead_time_days),
                    "earliest_arrival": _d(as_of) + timedelta(days=int(r.lead_time_days)),
                    "can_supply_qty": qty, "covers_full_need": qty >= quantity_needed,
                    "reliability_score": float(r.reliability_score),
                    "incremental_cost_vs_original": round(premium, 2) if premium is not None else None,
                })
            out.sort(key=lambda x: (not x["approved"], x["earliest_arrival"]))
            return _json({"sku": sku, "original_unit_cost": base_cost, "alternates": out})
        except Exception as e:  # noqa: BLE001
            return _json({"error": str(e)})


class TransferInput(BaseModel):
    sku: str = Field(..., description="SKU to move")
    destination_warehouse: str = Field(..., description="DC that needs stock")
    as_of: str = Field(..., description="Date the transfer would ship YYYY-MM-DD")


class TransferOptionsTool(BaseTool):
    name: str = "dc_transfer_options"
    description: str = ("Find other DCs that can spare a SKU without dropping below safety stock after covering "
                        "their own open orders in the next few weeks. Returns transferable units, arrival date "
                        "and cost.")
    args_schema: Type[BaseModel] = TransferInput

    def _run(self, sku: str, destination_warehouse: str, as_of: str) -> str:
        try:
            as_of_d = _d(as_of)
            horizon = as_of_d + timedelta(days=config.TRANSFER_HORIZON_DAYS)
            inv = store().inventory
            orders, lanes = store().orders, store().lanes
            out = []
            for _, r in inv[(inv.sku == sku) & (inv.warehouse != destination_warehouse)].iterrows():
                committed = int(orders[(orders.sku == sku) & (orders.ship_from_warehouse == r.warehouse)
                                       & (orders.due_date <= horizon)].quantity.sum())
                spare = int(r.on_hand) - int(r.safety_stock) - committed
                lane = lanes[(lanes.from_warehouse == r.warehouse) & (lanes.to_warehouse == destination_warehouse)]
                if lane.empty:
                    continue
                lane = lane.iloc[0]
                out.append({
                    "from_warehouse": r.warehouse, "on_hand": int(r.on_hand), "safety_stock": int(r.safety_stock),
                    "committed_next_%d_days" % config.TRANSFER_HORIZON_DAYS: committed,
                    "transferable_units": max(0, spare),
                    "arrival_date": as_of_d + timedelta(days=int(lane.transit_days)),
                    "cost_per_unit": float(lane.cost_per_unit),
                    "cost_for_all_transferable": round(max(0, spare) * float(lane.cost_per_unit), 2),
                })
            return _json({"sku": sku, "destination": destination_warehouse, "sources": out})
        except Exception as e:  # noqa: BLE001
            return _json({"error": str(e)})


class ExpediteInput(BaseModel):
    sku: str = Field(..., description="SKU to expedite")
    quantity: int = Field(..., description="Units to expedite")
    as_of: str = Field(..., description="Booking date YYYY-MM-DD")


class ExpediteCostTool(BaseTool):
    name: str = "expedite_freight_quote"
    description: str = ("Quote expedited freight (air and expedited ground) for a quantity of a SKU: cost from unit "
                        "weight and rate card, and arrival date. Only meaningful if the goods are ready to ship "
                        "(not for quality holds).")
    args_schema: Type[BaseModel] = ExpediteInput

    def _run(self, sku: str, quantity: int, as_of: str) -> str:
        try:
            inv = store().inventory[store().inventory.sku == sku]
            if inv.empty:
                return _json({"error": f"No unit weight for {sku}"})
            weight = float(inv.unit_weight_kg.iloc[0]) * int(quantity)
            quotes = []
            for _, f in store().freight.iterrows():
                cost = max(float(f.min_charge), weight * float(f.cost_per_kg))
                days = int(f.handling_days) + int(f.transit_days)
                quotes.append({"mode": f["mode"], "total_weight_kg": round(weight, 1), "cost": round(cost, 2),
                               "arrival_date": _d(as_of) + timedelta(days=days)})
            return _json({"sku": sku, "quantity": quantity, "quotes": quotes})
        except Exception as e:  # noqa: BLE001
            return _json({"error": str(e)})


class ExtraReceipt(BaseModel):
    quantity: int = Field(..., description="Units arriving")
    arrival_date: str = Field(..., description="Arrival date YYYY-MM-DD")


class ScenarioInput(BaseModel):
    shipment_id: str = Field(..., description="Delayed shipment id")
    sku: str = Field(..., description="SKU to test")
    new_eta: str = Field(..., description="New ETA of the delayed shipment YYYY-MM-DD")
    as_of: str = Field(..., description="Analysis date YYYY-MM-DD")
    extra_receipts: List[ExtraReceipt] = Field(default_factory=list,
                                               description="Recovery supply to add, e.g. transfers or alternate POs")


class ScenarioTestTool(BaseTool):
    name: str = "scenario_test"
    description: str = ("Re-run the fulfillment simulation with extra recovery receipts added (transfers, alternate "
                        "supplier POs, expedited freight) to verify which orders are still late and the remaining "
                        "penalty exposure. Use this to check every option and the final plan.")
    args_schema: Type[BaseModel] = ScenarioInput

    def _run(self, shipment_id: str, sku: str, new_eta: str, as_of: str,
             extra_receipts: Optional[List] = None) -> str:
        try:
            extra = []
            for r in extra_receipts or []:
                r = r if isinstance(r, dict) else r.model_dump()
                extra.append((max(_d(r["arrival_date"]), _d(as_of)), int(r["quantity"])))
            result = impact_for_line(shipment_id, sku, new_eta, as_of, extra)
            if "error" in result:
                return _json(result)
            return _json({
                "extra_receipts_applied": extra,
                "orders_still_late_vs_baseline": [
                    {k: o[k] for k in ("order_id", "customer_tier", "projected_ship_date",
                                       "additional_days_late", "penalty_exposure")}
                    for o in result["at_risk_orders"]],
                "remaining_penalty_exposure": result["total_penalty_exposure"],
                "units_still_needed_for_zero_late": result["units_needed_for_zero_late"],
            })
        except Exception as e:  # noqa: BLE001
            return _json({"error": str(e)})
