"""Structured outputs for each task, so handoffs between agents are reliable."""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical"]


# ---------- 1. Disruption assessment (Monitor) ----------
class AffectedLine(BaseModel):
    sku: str
    quantity_delayed: int
    destination_warehouse: str
    original_eta: str
    new_eta: str
    delay_days: int


class DisruptionAssessment(BaseModel):
    event_id: str
    shipment_id: str
    supplier_id: str
    supplier_name: str
    event_type: str
    root_cause_summary: str = Field(description="One or two sentences on what happened")
    affected_lines: List[AffectedLine]
    confidence_in_new_eta: Literal["low", "medium", "high"]
    initial_severity: Severity


# ---------- 2. Impact report (Impact Analyst) ----------
class AtRiskOrder(BaseModel):
    order_id: str
    customer: str
    customer_tier: str
    sku: str
    quantity: int
    due_date: str
    projected_ship_date: Optional[str] = Field(None, description="None if unfulfillable in horizon")
    additional_days_late: int
    revenue_at_risk: float
    penalty_exposure: float


class SkuImpact(BaseModel):
    sku: str
    warehouse: str
    projected_stockout_date: Optional[str]
    units_needed_for_zero_late: int
    needed_by: Optional[str]


class ImpactReport(BaseModel):
    event_id: str
    sku_impacts: List[SkuImpact]
    at_risk_orders: List[AtRiskOrder]
    total_revenue_at_risk: float
    total_penalty_exposure: float
    overall_severity: Severity
    key_findings: List[str]


# ---------- 3. Recovery options (Sourcing Strategist) ----------
class RecoveryOption(BaseModel):
    option_id: str = Field(description="Short id such as OPT-1")
    option_type: Literal["alternate_supplier", "dc_transfer", "expedite_freight", "allocation_change", "partial_ship", "other"]
    sku: str
    description: str
    quantity: int
    source: str = Field(description="Supplier id, DC, or carrier mode")
    arrival_date: str
    incremental_cost: float
    orders_protected: List[str]
    orders_still_late: List[str]
    risks: List[str]
    complies_with_rules: bool


class RecoveryOptions(BaseModel):
    event_id: str
    options: List[RecoveryOption]
    notes: List[str]


# ---------- 4. Recovery plan (Planner) ----------
class RecoveryPlan(BaseModel):
    event_id: str
    selected_option_ids: List[str]
    plan_summary: str
    rationale: str
    total_incremental_cost: float
    penalty_exposure_avoided: float
    orders_still_late: List[str]
    residual_risks: List[str]
    approval_required: Literal["none", "ops_manager", "vp_supply_chain"]
    approval_reason: str
    actions: List[str] = Field(description="Concrete next steps with owners, e.g. 'Buyer: issue PO to SUP-MX02 for 400 MTR-220'")


# ---------- 5. Communications (Comms) ----------
class CustomerNotice(BaseModel):
    customer: str
    order_ids: List[str]
    subject: str
    body: str


class Communications(BaseModel):
    event_id: str
    supplier_message_subject: str
    supplier_message_body: str
    customer_notices: List[CustomerNotice]
    internal_summary_markdown: str
