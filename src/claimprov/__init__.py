"""claimprov: claim-level provenance and epistemic status for multi-agent systems.

Core idea
---------
Governance usually certifies *assets* (a table, a document, a report).
Agents reason over *claims* ("Supplier S has a 14-day lead time").
The mismatch lets a claim's *declared* epistemic status (what the producer
attached) drift from its *enacted* status (how a consumer actually treats it),
and the drift is created at retrieval time, between agents, not at storage time.

claimprov makes that drift observable: every claim carries a declared status
with PROV-O provenance, SHACL enforces the minimum evidence each status
requires, and retrieval events record the status a consumer enacted.
"""

from .model import (
    DEFAULT_POLICY,
    TOOL_FIRST_POLICY,
    AcceptancePolicy,
    AgentKind,
    AgentRef,
    Asset,
    Claim,
    DeclaredStatus,
    EpistemicStatus,
    Evidence,
    EvidenceKind,
    RecordKind,
    RetrievalEvent,
    StatusPolicy,
    Verification,
    VerificationOutcome,
)
from .rdf import ClaimGraph, validate

__all__ = [
    "DEFAULT_POLICY",
    "TOOL_FIRST_POLICY",
    "AcceptancePolicy",
    "AgentKind",
    "AgentRef",
    "Asset",
    "Claim",
    "ClaimGraph",
    "DeclaredStatus",
    "EpistemicStatus",
    "Evidence",
    "EvidenceKind",
    "RecordKind",
    "RetrievalEvent",
    "StatusPolicy",
    "Verification",
    "VerificationOutcome",
    "validate",
]

__version__ = "0.1.0a2"
