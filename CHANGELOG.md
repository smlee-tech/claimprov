# Changelog

## 0.1.0a2 — 2026-11-04

Definitions tightened after review; the record path and three record kinds added.

- `RetrievalEvent`: `enacted_status` is now derived, not supplied. New fields `observed_use` (the kind of record the consumer produced), `required_status` (the minimum input status the consumer's policy demanded, or taken from `policy`), `reviewed`, `produced`. Inflation = required > declared and not reviewed. A provisional input used for a purpose the policy permits on provisional evidence is not inflation.
- `RecordKind` (prediction / decision / event) on every claim; `cp:RecordKind` individuals in the ontology.
- `AcceptancePolicy`: per-record-kind minimum input status; `reads_status`.
- `Asset` with `default_status`; `Claim.stored_in`; SHACL warning when a stored claim declares less than its asset confers (the record path).
- `StatusPolicy`: the trust ranking is a configurable deployment policy. `DEFAULT_POLICY` (human > tool) and `TOOL_FIRST_POLICY`. Invariant enforced: asserted = derived < both verified.
- SHACL: inflation rule rewritten on `requiredStatus`; `ReviewedGapShape` (Info); `AssetInheritanceShape` (Warning); enacted must equal required (Violation).
- `examples/churn_three_uses.py`: one provisional inference, three downstream uses; only the confirmed-as-fact use is flagged. Tested.
- Renderer shows record kind, required status, review, assets and policies.
- Scope statement: illustrations and boundary cases, not evidence.

## 0.1.0a1 — 2026-11-02

First public pre-release: claim-level data model, PROV-O extension, SHACL shapes (storage-time violations, retrieval-time warnings), 24 tests.
