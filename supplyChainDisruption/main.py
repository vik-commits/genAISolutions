"""
Entry point. A disruption events CSV triggers the crew: one crew run per new event row.

    python main.py                          # process all new events in data/disruption_events.csv
    python main.py --event-id EVT-001       # run a single event
    python main.py --dry-run                # run only the deterministic tools, no LLM calls
    python main.py --watch --interval 60    # poll the events CSV and run on new rows
    python main.py --review                 # pause for human feedback on the recovery plan
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

import config  # noqa: E402
import tools  # noqa: E402

EVENT_COLUMNS = ["event_id", "shipment_id", "event_type", "description", "new_eta", "reported_at"]


def load_events(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str).fillna("")
    df.columns = [c.strip() for c in df.columns]
    missing = set(EVENT_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")
    if "source" not in df.columns:
        df["source"] = "csv"
    return df


def ledger_path(output_dir: Path) -> Path:
    return output_dir / "processed_events.txt"


def processed_ids(output_dir: Path) -> set:
    p = ledger_path(output_dir)
    return set(p.read_text().split()) if p.exists() else set()


def mark_processed(output_dir: Path, event_id: str) -> None:
    with ledger_path(output_dir).open("a") as f:
        f.write(event_id + "\n")


def event_inputs(row: pd.Series) -> dict:
    return {
        "event_id": row.event_id,
        "shipment_id": row.shipment_id,
        "event_type": row.event_type,
        "description": row.description,
        "new_eta": row.new_eta,
        "as_of": row.reported_at,
        "source": row.source or "csv",
        "business_rules": config.business_rules_text(),
    }


def dry_run(inputs: dict) -> None:
    """Exercise the deterministic layer only; useful for validating your CSVs."""
    print(f"\n=== DRY RUN {inputs['event_id']} ===")
    lookup = json.loads(tools.ShipmentLookupTool().run(shipment_id=inputs["shipment_id"], new_eta=inputs["new_eta"]))
    print(json.dumps(lookup, indent=2))
    for line in lookup.get("lines", []):
        impact = tools.impact_for_line(inputs["shipment_id"], line["sku"], inputs["new_eta"], inputs["as_of"])
        print(f"\n--- Impact for {line['sku']} ---")
        print(json.dumps({k: v for k, v in impact.items() if k != "all_orders_disrupted_scenario"},
                         indent=2, default=str))


def save_outputs(crew, event_id: str, output_dir: Path) -> Path:
    out = output_dir / event_id
    out.mkdir(parents=True, exist_ok=True)
    names = ["1_assessment", "2_impact", "3_options", "4_plan", "5_communications"]
    parsed = {}
    for name, task in zip(names, crew.tasks):
        if task.output is None:
            continue
        if task.output.pydantic is not None:
            parsed[name] = task.output.pydantic
            (out / f"{name}.json").write_text(task.output.pydantic.model_dump_json(indent=2))
        else:
            (out / f"{name}.txt").write_text(task.output.raw)

    comms = parsed.get("5_communications")
    if comms:
        drafts = out / "drafts"
        drafts.mkdir(exist_ok=True)
        (drafts / "supplier_message.txt").write_text(
            f"Subject: {comms.supplier_message_subject}\n\n{comms.supplier_message_body}\n")
        for notice in comms.customer_notices:
            safe = "".join(c if c.isalnum() else "_" for c in notice.customer)
            (drafts / f"customer_{safe}.txt").write_text(f"Subject: {notice.subject}\n\n{notice.body}\n")
        (out / "internal_summary.md").write_text(comms.internal_summary_markdown)

    plan = parsed.get("4_plan")
    if plan:
        print(f"\n[{event_id}] Plan: {plan.plan_summary}")
        print(f"[{event_id}] Cost: ${plan.total_incremental_cost:,.0f} | "
              f"Penalty avoided: ${plan.penalty_exposure_avoided:,.0f} | Approval: {plan.approval_required}")
        print(f"[{event_id}] Still late: {', '.join(plan.orders_still_late) or 'none'}")
    return out


def run_event(row: pd.Series, args) -> bool:
    inputs = event_inputs(row)
    if args.dry_run:
        dry_run(inputs)
        return True
    from crew import build_crew  # imported here so --dry-run works without an API key

    print(f"\n>>> Running crew for {row.event_id} ({row.event_type}) at {datetime.now():%H:%M:%S}")
    crew = build_crew(human_review=args.review, verbose=not args.quiet)
    try:
        crew.kickoff(inputs=inputs)
    except Exception as e:  # noqa: BLE001
        print(f"!!! Crew failed for {row.event_id}: {e}", file=sys.stderr)
        return False
    out = save_outputs(crew, row.event_id, args.output_dir)
    mark_processed(args.output_dir, row.event_id)
    print(f"<<< Outputs written to {out}")
    return True


def process_file(args) -> int:
    events = load_events(args.events)
    if args.event_id:
        events = events[events.event_id == args.event_id]
    elif not args.dry_run and not args.force:
        done = processed_ids(args.output_dir)
        events = events[~events.event_id.isin(done)]
    if events.empty:
        return 0
    count = 0
    for _, row in events.iterrows():
        count += run_event(row, args)
    return count


def main() -> None:
    p = argparse.ArgumentParser(description="CrewAI supply disruption response")
    p.add_argument("--events", type=Path, default=config.DATA_DIR / "disruption_events.csv")
    p.add_argument("--data-dir", type=Path, default=config.DATA_DIR)
    p.add_argument("--output-dir", type=Path, default=config.OUTPUT_DIR)
    p.add_argument("--event-id", help="Run a single event id")
    p.add_argument("--force", action="store_true", help="Re-run events already processed")
    p.add_argument("--dry-run", action="store_true", help="Deterministic tools only, no LLM")
    p.add_argument("--review", action="store_true", help="Human review step on the recovery plan")
    p.add_argument("--watch", action="store_true", help="Poll the events CSV for new rows")
    p.add_argument("--interval", type=int, default=60, help="Watch polling interval in seconds")
    p.add_argument("--quiet", action="store_true", help="Less agent logging")
    args = p.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    tools.init_store(args.data_dir)

    if not args.watch:
        n = process_file(args)
        print(f"\nProcessed {n} event(s).")
        return

    print(f"Watching {args.events} every {args.interval}s. Ctrl+C to stop.")
    last_mtime = None
    while True:
        try:
            mtime = args.events.stat().st_mtime
            if mtime != last_mtime:
                last_mtime = mtime
                tools.init_store(args.data_dir)  # reload reference data in case it changed too
                n = process_file(args)
                if n:
                    print(f"Processed {n} new event(s).")
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("Stopped.")
            break


if __name__ == "__main__":
    main()
