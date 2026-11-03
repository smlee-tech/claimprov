# claimprov

[![PyPI](https://img.shields.io/pypi/v/claimprov?include_prereleases)](https://pypi.org/project/claimprov/)
[![CI](https://github.com/smlee-tech/claimprov/actions/workflows/ci.yml/badge.svg)](https://github.com/smlee-tech/claimprov/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Claim-level provenance and epistemic status for multi-agent systems. A small extension of W3C PROV-O, SHACL shapes that enforce it, and (coming) middleware and an MCP server that apply it between agents.

**Status: pre-release.** The data model, ontology and shapes are in and tested. Storage/retrieval middleware, the worked configurations, and the MCP server are in progress. APIs will change before v0.1.0.

## Why this exists

AI agents now write interpretations into enterprise records: a churn score into a CRM field, a supplier classification into a procurement table, a lead-time estimate into a planning store. Another agent later retrieves the value and acts on it. Between those two steps something happens to the value's standing. The producing agent may have marked it *provisional*; the consuming agent treats it as *fact*. No one mislabeled anything. The qualification simply did not travel with the value.

claimprov is built around that observation. It distinguishes a claim's **declared** epistemic status (what the producer attached) from its **enacted** status (how a consumer actually used it), and it records both, so that the gap between production and reuse can be measured rather than assumed away.

It is the companion implementation of a working paper in information systems research. The paper supplies the theory; this library is the part that can be run. [docs/concepts.md](docs/concepts.md) has the full argument, the design decisions it forces, and what the code does and does not claim.

## What it does

- **Claims as the unit of governance.** Every proposition an agent puts into circulation is a `cp:Claim` with its own status, attribution, lineage, evidence and verifications: a representation at the grain at which agents actually reason, alongside asset-level governance (certified tables, semantic views).
- **A status lattice with teeth.** `asserted` = `derived` (rank 0) < `tool-verified` (1) < `human-verified` (2). Derivation adds lineage, not warrant; only a deterministic tool or a person can raise a claim's rank. SHACL shapes enforce the minimum evidence each status requires and reject *status laundering*: a claim declaring a higher rank than its sources without a verification of its own.
- **Retrieval as a provenance event.** `cp:Retrieval` records which agent took which claim and what status it *enacted*. Enacting a higher status than was declared produces a SHACL *warning*, not a violation. That warning is the declared/enacted gap, measured.

## Status lattice

| status | trust rank | requires |
|---|---|---|
| `asserted` | 0 | attribution to an agent |
| `derived` | 0 | at least one source claim via `prov:wasDerivedFrom` |
| `tool-verified` | 1 | a passed `cp:Verification` by a `cp:Tool` (or person) citing evidence |
| `human-verified` | 2 | a passed `cp:Verification` by a `prov:Person` citing evidence |

## Quickstart

Requires Python 3.10+.

```bash
pip install --pre claimprov        # pre-release from PyPI
# or, for development:
pip install -e ".[dev]" && pytest
```

```python
from claimprov import (AgentRef, AgentKind, Claim, ClaimGraph,
                       EpistemicStatus, RetrievalEvent)

analyst = AgentRef(kind=AgentKind.LLM_AGENT, name="analysis-agent", model="claude-sonnet-4-5")
planner = AgentRef(kind=AgentKind.LLM_AGENT, name="planning-agent", model="claude-sonnet-4-5")

c = Claim(statement="Supplier S-17 average lead time is 14 days",
          declared_status=EpistemicStatus.ASSERTED, asserted_by=analyst)

g = ClaimGraph()
g.add_claim(c)
g.add_retrieval(RetrievalEvent(claim_id=c.id, retrieved_by=planner,
                               enacted_status=EpistemicStatus.TOOL_VERIFIED,
                               rationale="cited as verified in the plan"))

report = g.validate()
report.conforms        # True: nothing stored is malformed
report.warnings        # one: status inflation at retrieval, rank 1 enacted for a rank-0 claim
print(g.serialize())   # PROV-O Turtle
```

## Layout

```
src/claimprov/
  model.py              Claim, EpistemicStatus, Evidence, Verification, RetrievalEvent (pydantic)
  rdf.py                ClaimGraph: model → PROV-O graph; SHACL validation
  ontology/claimprov.ttl   the PROV-O extension
  ontology/shapes.ttl      the shapes (violations at storage, warnings at retrieval)
docs/concepts.md        theory, design decisions, scope
examples/               worked graphs
tests/
```

## Roadmap to v0.1.0

- `cp:Asset`, so that claims can be placed inside the assets they are written to.
- Storage and retrieval middleware for LangGraph-style agent chains.
- Worked configurations as runnable scripts.
- MCP server: `record_claim`, `get_claim_status`, `check_retrieval`.

## Scope

This is a reference implementation of a theoretical distinction, not a detection product and not an empirical finding about any platform or organization. It uses no proprietary data and makes no claim about any vendor's behavior.

## Citing

See [CITATION.cff](CITATION.cff). A citation for the companion paper will be added when a public version exists.

## License

Apache-2.0