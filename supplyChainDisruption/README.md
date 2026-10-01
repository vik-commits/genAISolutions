# Supply Disruption Response Crew (CrewAI)

A five-agent CrewAI crew that turns a supply disruption into a verified recovery plan and draft communications.
A row in `data/disruption_events.csv` is the trigger: each new row starts one crew run.

## Flow
1. **Disruption Monitor** – maps the event to shipment lines and delay days (`shipment_lookup`).
2. **Impact Analyst** – simulates order fulfillment with original vs new ETA to find at-risk orders, revenue and penalty exposure (`impact_simulation`, `inventory_position`).
3. **Sourcing Strategist** – finds DC transfers, alternate suppliers and expedited freight, and tests each option (`dc_transfer_options`, `alternate_suppliers`, `expedite_freight_quote`, `scenario_test`).
4. **Decision Planner** – picks the plan within business rules and re-verifies it with `scenario_test`.
5. **Communications Lead** – drafts supplier message, customer notices and an internal summary.

Agents reason and decide; the tools do the lookups and math, so numbers come from your data, not the LLM.
Every handoff is a Pydantic model (`models.py`).

## Setup
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your API key
```

## Run
```bash
python main.py --dry-run            # validate CSVs, no LLM calls
python main.py                      # process all new events
python main.py --event-id EVT-001   # one event
python main.py --review             # human feedback step on the plan
python main.py --watch --interval 60  # poll the events CSV for new rows
python main.py --force              # re-run already processed events
```

Outputs go to `outputs/<event_id>/`: one JSON per task, `internal_summary.md`, and `drafts/` with messages.
Nothing is sent automatically. Processed ids are tracked in `outputs/processed_events.txt`.
Screenshots folder contains output samples and what you should expect the script to generate


## Input CSVs (`data/`)
| File | Key columns |
|---|---|
| disruption_events.csv (trigger) | event_id, shipment_id, event_type, description, new_eta, reported_at, source |
| shipments.csv | shipment_id, supplier_id, sku, quantity, destination_warehouse, original_eta, status |
| inventory.csv | sku, warehouse, on_hand, safety_stock, avg_daily_demand, unit_weight_kg |
| open_orders.csv | order_id, customer, customer_tier, sku, quantity, due_date, ship_from_warehouse, order_value, late_penalty_per_day |
| suppliers.csv | supplier_id, supplier_name, sku, unit_cost, lead_time_days, available_capacity, reliability_score, approved |
| lanes.csv | from_warehouse, to_warehouse, transit_days, cost_per_unit |
| freight_rates.csv | mode, cost_per_kg, transit_days, min_charge, handling_days |

Dates are YYYY-MM-DD. Business rules live in `config.py`.

## Simulation assumptions
- Stock is allocated to open orders in due-date order, ties broken by customer tier.
- Only orders that become *later than without the disruption* count as at-risk.
- Safety stock can be consumed for customer orders; transfers never take a source DC below safety stock after its own orders in the next 21 days.

