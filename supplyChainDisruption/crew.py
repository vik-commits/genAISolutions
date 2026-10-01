"""Agents, tasks, and crew for supply disruption response."""
from crewai import LLM, Agent, Crew, Process, Task

import config
from models import Communications, DisruptionAssessment, ImpactReport, RecoveryOptions, RecoveryPlan
from tools import (AlternateSupplierTool, ExpediteCostTool, ImpactSimulationTool, InventoryPositionTool,
                   ScenarioTestTool, ShipmentLookupTool, TransferOptionsTool)


def build_llm() -> LLM:
    return LLM(model=config.MODEL, temperature=config.TEMPERATURE)


def build_crew(human_review: bool = False, verbose: bool = True) -> Crew:
    llm = build_llm()
    scenario_tool = ScenarioTestTool()

    # ------------------------------------------------------------------ agents
    monitor = Agent(
        role="Supply Disruption Monitor",
        goal="Turn a raw disruption signal into a precise, structured description of what is delayed, by how much, and how confident we are.",
        backstory=("You run the control tower for inbound logistics. You have seen every kind of delay, from port "
                   "congestion to quality holds, and you know that vague alerts waste everyone's time. You always "
                   "tie a disruption back to exact shipment lines and quantities."),
        tools=[ShipmentLookupTool()],
        llm=llm, allow_delegation=False, max_iter=8, verbose=verbose,
    )

    analyst = Agent(
        role="Supply Chain Impact Analyst",
        goal="Quantify exactly which customer orders a disruption puts at risk, the revenue and penalty exposure, and how many units are needed by when.",
        backstory=("You are a planner who lives in inventory projections. You never estimate in your head when a "
                   "simulation tool can give you the answer, and you report numbers exactly as the tools return them."),
        tools=[ImpactSimulationTool(), InventoryPositionTool()],
        llm=llm, allow_delegation=False, max_iter=12, verbose=verbose,
    )

    strategist = Agent(
        role="Sourcing and Recovery Strategist",
        goal="Find every realistic way to close the supply gap and verify each option with a scenario test.",
        backstory=("You are a senior buyer with deep supplier relationships and a logistics background. You think in "
                   "terms of transfers, alternate sources, and expediting, and you know that an option that has not "
                   "been tested against the order book is just a guess."),
        tools=[AlternateSupplierTool(), TransferOptionsTool(), ExpediteCostTool(), InventoryPositionTool(), scenario_tool],
        llm=llm, allow_delegation=False, max_iter=20, verbose=verbose,
    )

    planner = Agent(
        role="Supply Chain Decision Planner",
        goal="Choose the recovery plan that best protects priority customers at the lowest justified cost, strictly within business rules.",
        backstory=("You are the operations leader who signs off on recovery plans. You weigh cost against customer "
                   "impact, you follow policy, and you make tradeoffs explicit so approvers can decide quickly."),
        tools=[scenario_tool],
        llm=llm, allow_delegation=False, max_iter=12, verbose=verbose,
    )

    communicator = Agent(
        role="Supply Chain Communications Lead",
        goal="Draft clear, accurate, professional messages for the supplier, affected customers, and internal stakeholders.",
        backstory=("You write the messages that keep trust intact when things go wrong. You are direct, never "
                   "overpromise, and only commit to dates that the plan actually supports."),
        tools=[],
        llm=llm, allow_delegation=False, max_iter=5, verbose=verbose,
    )

    # ------------------------------------------------------------------ tasks
    assess = Task(
        description=(
            "A disruption event has been received.\n"
            "Event id: {event_id}\nShipment: {shipment_id}\nType: {event_type}\n"
            "Description: {description}\nNew ETA: {new_eta}\nReported: {as_of} via {source}\n\n"
            "Use shipment_lookup to find every affected line and its delay. Judge how confident we can be in the new "
            "ETA given the event type (quality holds and port congestion often slip further). Assign an initial "
            "severity based on delay length and quantity."
        ),
        expected_output="A DisruptionAssessment covering every line on the shipment.",
        agent=monitor,
        output_pydantic=DisruptionAssessment,
    )

    impact = Task(
        description=(
            "For every affected line in the assessment, call impact_simulation with shipment {shipment_id}, the "
            "line's SKU, new ETA {new_eta} and as_of {as_of}. Use inventory_position if you need network context.\n"
            "Report only orders that become later than they would have been without the disruption. Copy numbers "
            "exactly from the tool output; do not recalculate. Summarize the 3 to 5 most important findings, calling "
            "out Tier A customers explicitly. Set overall severity to critical if any Tier A order is at risk, high "
            "if penalty exposure exceeds 10000 USD, otherwise use judgment."
        ),
        expected_output="An ImpactReport with per-SKU impacts and every at-risk order.",
        agent=analyst,
        context=[assess],
        output_pydantic=ImpactReport,
    )

    options = Task(
        description=(
            "Generate recovery options for each SKU with at-risk orders. Consider, in this order: transfers from "
            "other DCs (dc_transfer_options), alternate approved suppliers (alternate_suppliers, excluding the "
            "disrupted supplier), and expedited freight (expedite_freight_quote, only if goods can physically ship; "
            "not for quality holds). Also consider allocation changes or partial shipments where useful.\n"
            "Use as_of {as_of} for all dates. Size quantities using units_needed_for_zero_late and needed_by from the "
            "impact report. For EVERY option, call scenario_test (shipment {shipment_id}, new ETA {new_eta}) with the "
            "option's receipts and record orders_protected and orders_still_late from the result. Combining a "
            "transfer with a purchase is a valid option if you test it.\n\n"
            "Business rules:\n{business_rules}\n\nMark complies_with_rules false for any option that breaks a rule."
        ),
        expected_output="RecoveryOptions with 2 to 6 tested options per affected SKU where possible.",
        agent=strategist,
        context=[assess, impact],
        output_pydantic=RecoveryOptions,
    )

    plan = Task(
        description=(
            "Select the recovery plan. You may combine options. Business rules:\n{business_rules}\n\n"
            "Before finalizing, run scenario_test for each SKU with ALL receipts from your selected options combined "
            "(shipment {shipment_id}, new ETA {new_eta}, as_of {as_of}) and use that result for orders_still_late. "
            "Compute total_incremental_cost as the sum of selected option costs and penalty_exposure_avoided as the "
            "impact report's total exposure minus remaining exposure. Set approval_required from the cost thresholds. "
            "List concrete actions with an owner role for each."
        ),
        expected_output="A RecoveryPlan that is verified by scenario test and compliant with every business rule.",
        agent=planner,
        context=[assess, impact, options],
        output_pydantic=RecoveryPlan,
        human_input=human_review,
    )

    comms = Task(
        description=(
            "Draft communications for event {event_id}. These are DRAFTS for human review, not sent automatically.\n"
            "1. Supplier message to the disrupted supplier: confirm the new ETA, ask for daily status and root-cause "
            "details, and state any PO changes from the plan.\n"
            "2. One customer notice per customer that still has a late order after the plan. Use the projected ship "
            "dates from the plan's final scenario test; never promise an earlier date. Tier A notices should be "
            "personal and mention what we are doing to recover. Customers whose orders are fully protected get no notice.\n"
            "3. An internal markdown summary for the operations manager: what happened, impact, the plan, cost, "
            "approvals needed, and open risks. Keep it under 300 words."
        ),
        expected_output="Communications with supplier message, customer notices, and internal summary.",
        agent=communicator,
        context=[assess, impact, plan],
        output_pydantic=Communications,
    )

    return Crew(
        agents=[monitor, analyst, strategist, planner, communicator],
        tasks=[assess, impact, options, plan, comms],
        process=Process.sequential,
        verbose=verbose,
    )
