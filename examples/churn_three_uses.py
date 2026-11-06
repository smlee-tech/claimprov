"""One provisional inference, three downstream uses.

    python examples/churn_three_uses.py            # prints the findings
    python examples/churn_three_uses.py --ttl out.ttl

Agent A infers "Account A has high churn risk" and stores it as ASSERTED
(provisional). Three consumers then use it. The same input, three different
kinds of record, three different justification conditions:

  B1  records "Churn is confirmed"         -> an EVENT record that requires
      verified input. Required > declared, no review: STATUS INFLATION.
  B2  decides "Escalate for retention review" -> a DECISION the policy permits
      on provisional evidence. Required = declared: NOT inflation. Provisional
      evidence legitimately used.
  C   records "Review initiated on Nov 3"   -> an EVENT record of something
      that happened. Its truth does not depend on whether A's inference was
      right. Required = asserted (the event is its own warrant): NOT inflation.

Then A's inference is corrected (it was wrong). What happens downstream:
  B1's record was never warranted; the inflation warning already said so.
  B2's decision keeps its procedural legitimacy: the policy allowed it on the
      evidence available at the time.
  C's record stays true: the review did happen.

No LLM is involved. The point is to see what the definitions say about each
case, not whether an agent behaves.
"""

from __future__ import annotations

import argparse

from claimprov import (
    AcceptancePolicy,
    AgentKind,
    AgentRef,
    Asset,
    Claim,
    ClaimGraph,
    EpistemicStatus,
    RecordKind,
    RetrievalEvent,
)

A = EpistemicStatus.ASSERTED
T = EpistemicStatus.TOOL_VERIFIED
H = EpistemicStatus.HUMAN_VERIFIED


def build() -> ClaimGraph:
    g = ClaimGraph()

    sales = AgentRef(id="urn:claimprov:agent:sales-intel", kind=AgentKind.LLM_AGENT, name="sales-intelligence-agent")
    ops = AgentRef(id="urn:claimprov:agent:ops", kind=AgentKind.LLM_AGENT, name="retention-ops-agent")
    crm_writer = AgentRef(id="urn:claimprov:agent:crm-writer", kind=AgentKind.LLM_AGENT, name="crm-writer-agent")
    scheduler = AgentRef(id="urn:claimprov:agent:scheduler", kind=AgentKind.TOOL, name="review-scheduler")

    # The certified CRM table. Anything read from it carries human-verified standing.
    crm = Asset(id="urn:claimprov:asset:crm-accounts", name="CRM.accounts (certified)", default_status=H)
    g.add_asset(crm)

    # Agent A: provisional inference, written into the certified table.
    churn = Claim(
        id="urn:claimprov:claim:churn-A",
        statement="Account A has high churn risk",
        record_kind=RecordKind.PREDICTION,
        declared_status=A,
        confidence=0.62,
        asserted_by=sales,
        stored_in=crm.id,
    )
    g.add_claim(churn)

    # Two acceptance policies. Both *read* the status; they differ in what they require.
    strict = AcceptancePolicy(
        id="urn:claimprov:policy:strict-records",
        name="records policy: confirmed facts need verification",
        required={RecordKind.PREDICTION: A, RecordKind.DECISION: A, RecordKind.EVENT: T},
    )
    retention = AcceptancePolicy(
        id="urn:claimprov:policy:retention",
        name="retention policy: provisional risk signals may trigger review",
        required={RecordKind.PREDICTION: A, RecordKind.DECISION: A, RecordKind.EVENT: A},
    )

    # --- B1: writes "churn confirmed" as a fact. Policy says a fact needs T. ---
    confirmed = Claim(
        id="urn:claimprov:claim:churn-confirmed",
        statement="Account A churn is confirmed",
        record_kind=RecordKind.EVENT,
        declared_status=EpistemicStatus.DERIVED,
        asserted_by=crm_writer,
        derived_from=[churn.id],
        stored_in=crm.id,
    )
    g.add_claim(confirmed)
    g.add_retrieval(RetrievalEvent(
        id="urn:claimprov:retrieval:B1",
        claim_id=churn.id, retrieved_by=crm_writer,
        observed_use=RecordKind.EVENT, policy=strict, produced=confirmed.id,
        rationale="wrote the risk flag into the account record as a confirmed status",
    ))

    # --- B2: decides to escalate. Retention policy allows that on provisional evidence. ---
    escalate = Claim(
        id="urn:claimprov:claim:escalate-A",
        statement="Escalate Account A for retention review",
        record_kind=RecordKind.DECISION,
        declared_status=EpistemicStatus.DERIVED,
        asserted_by=ops,
        derived_from=[churn.id],
    )
    g.add_claim(escalate)
    g.add_retrieval(RetrievalEvent(
        id="urn:claimprov:retrieval:B2",
        claim_id=churn.id, retrieved_by=ops,
        observed_use=RecordKind.DECISION, policy=retention, produced=escalate.id,
        rationale="retention policy permits review on a provisional risk signal",
    ))

    # --- C: the scheduler records that the review happened. ---
    initiated = Claim(
        id="urn:claimprov:claim:review-initiated",
        statement="Retention review for Account A initiated on 2026-11-03",
        record_kind=RecordKind.EVENT,
        declared_status=EpistemicStatus.DERIVED,
        asserted_by=scheduler,
        derived_from=[escalate.id],
    )
    g.add_claim(initiated)
    g.add_retrieval(RetrievalEvent(
        id="urn:claimprov:retrieval:C",
        claim_id=escalate.id, retrieved_by=scheduler,
        observed_use=RecordKind.EVENT, policy=retention, produced=initiated.id,
        rationale="the review was scheduled; the record describes an event the scheduler performed",
    ))
    return g


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ttl", help="write the graph as Turtle to this path")
    args = ap.parse_args()

    g = build()
    rep = g.validate()
    print(f"conforms (no violations): {rep.conforms}")
    print(f"warnings: {len(rep.warnings)}   info: {len([f for f in rep.findings if f.severity == 'Info'])}\n")
    for f in sorted(rep.findings, key=lambda f: (f.severity, f.focus)):
        print(f"[{f.severity}] {f.message}")
    if args.ttl:
        open(args.ttl, "w").write(g.serialize())
        print(f"\nwrote {args.ttl}")


if __name__ == "__main__":
    main()
