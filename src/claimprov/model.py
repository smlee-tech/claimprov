"""Claim-level data model.

Design notes
------------
* The unit of governance here is the *claim*, not the asset. A claim is one
  proposition an agent put into circulation ("Supplier S-17 has a 14-day lead
  time"), together with who asserted it, from what, and under what declared
  epistemic status.

* ``EpistemicStatus`` is a small lattice. ``asserted`` and ``derived`` share
  trust rank 0: derivation adds *lineage*, not *verification*. Only an actual
  verification activity, performed by a tool or a human, lifts a claim to
  rank 1 or 2. This is the rule the SHACL shapes enforce and the rule that
  "status laundering" violates.

* The same enum is used for the status a consumer *enacts* at retrieval time
  (``RetrievalEvent.enacted_status``). Declared vs enacted is the comparison
  the whole library exists to make observable.

* Pydantic validation covers what can be checked on one claim in isolation.
  Cross-claim rules (laundering through a derivation chain) live in SHACL,
  because they need the graph.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# --------------------------------------------------------------------------- #
# Namespaces
# --------------------------------------------------------------------------- #

CP_NS = "https://w3id.org/claimprov#"  # ontology namespace (register w3id before release)
INSTANCE_NS = "urn:claimprov:"  # default base for instance IRIs


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(kind: str) -> str:
    return f"{INSTANCE_NS}{kind}:{uuid.uuid4()}"


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class EpistemicStatus(str, Enum):
    """Declared (or enacted) epistemic status of a claim.

    trust_rank:  asserted = derived = 0  <  tool-verified = 1  <  human-verified = 2
    """

    ASSERTED = "asserted"  # produced by an agent, no verification, no lineage required
    DERIVED = "derived"  # computed/inferred from other claims; lineage required
    TOOL_VERIFIED = "tool-verified"  # checked by a deterministic tool against evidence
    HUMAN_VERIFIED = "human-verified"  # checked and signed off by a person

    @property
    def trust_rank(self) -> int:
        return _TRUST_RANK[self]

    @property
    def iri(self) -> str:
        return CP_NS + _STATUS_LOCAL[self]

    def __lt__(self, other: "EpistemicStatus") -> bool:  # type: ignore[override]
        return self.trust_rank < other.trust_rank


_TRUST_RANK = {
    EpistemicStatus.ASSERTED: 0,
    EpistemicStatus.DERIVED: 0,
    EpistemicStatus.TOOL_VERIFIED: 1,
    EpistemicStatus.HUMAN_VERIFIED: 2,
}

_STATUS_LOCAL = {
    EpistemicStatus.ASSERTED: "Asserted",
    EpistemicStatus.DERIVED: "Derived",
    EpistemicStatus.TOOL_VERIFIED: "ToolVerified",
    EpistemicStatus.HUMAN_VERIFIED: "HumanVerified",
}

# Name used in the project plan; kept as an alias.
DeclaredStatus = EpistemicStatus


class AgentKind(str, Enum):
    LLM_AGENT = "llm_agent"
    TOOL = "tool"
    HUMAN = "human"
    ORGANIZATION = "organization"


class EvidenceKind(str, Enum):
    DATASET = "dataset"
    DOCUMENT = "document"
    TOOL_OUTPUT = "tool_output"
    OBSERVATION = "observation"
    HUMAN_REVIEW = "human_review"


class VerificationOutcome(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


# --------------------------------------------------------------------------- #
# Building blocks
# --------------------------------------------------------------------------- #


class AgentRef(BaseModel):
    """Who did something. Maps to prov:Agent (+ cp:LLMAgent / cp:Tool / prov:Person)."""

    id: str = Field(default_factory=lambda: _new_id("agent"))
    kind: AgentKind
    name: str
    model: Optional[str] = None  # e.g. "claude-sonnet-4-5" for LLM agents
    version: Optional[str] = None

    model_config = {"frozen": True}


class Evidence(BaseModel):
    """Something a claim or verification points at. Maps to cp:Evidence (prov:Entity)."""

    id: str = Field(default_factory=lambda: _new_id("evidence"))
    kind: EvidenceKind
    source: str = Field(description="URI, path, or dataset identifier")
    retrieved_at: datetime = Field(default_factory=_now)
    content_hash: Optional[str] = Field(default=None, description="sha256 of the bytes used")
    excerpt: Optional[str] = Field(default=None, max_length=2000)
    license: Optional[str] = Field(default=None, description="SPDX id or URL; required for public data")

    @staticmethod
    def hash_bytes(data: bytes) -> str:
        return "sha256:" + hashlib.sha256(data).hexdigest()


class Verification(BaseModel):
    """A verification activity. Maps to cp:Verification (prov:Activity)."""

    id: str = Field(default_factory=lambda: _new_id("verification"))
    verifier: AgentRef
    method: str = Field(description="e.g. 'sql-recount', 'schema-check', 'analyst-review'")
    outcome: VerificationOutcome
    performed_at: datetime = Field(default_factory=_now)
    evidence: list[Evidence] = Field(default_factory=list, description="what the verifier used")
    note: Optional[str] = None

    @property
    def confers(self) -> Optional[EpistemicStatus]:
        """Status this verification can confer, or None if it confers nothing."""
        if self.outcome is not VerificationOutcome.PASSED:
            return None
        if self.verifier.kind is AgentKind.HUMAN:
            return EpistemicStatus.HUMAN_VERIFIED
        if self.verifier.kind is AgentKind.TOOL:
            return EpistemicStatus.TOOL_VERIFIED
        return None  # an LLM "checking" a claim is not verification


# --------------------------------------------------------------------------- #
# Claim
# --------------------------------------------------------------------------- #


class Claim(BaseModel):
    """One proposition with its declared status and provenance. Maps to cp:Claim (prov:Entity)."""

    id: str = Field(default_factory=lambda: _new_id("claim"))
    statement: str = Field(min_length=1, description="natural-language proposition")

    # Optional structured form, for claims that are a single relation.
    subject: Optional[str] = None
    predicate: Optional[str] = None
    object: Optional[str] = None

    declared_status: EpistemicStatus
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    asserted_by: AgentRef
    asserted_at: datetime = Field(default_factory=_now)
    generated_by: Optional[str] = Field(default=None, description="IRI of the producing activity/run")

    derived_from: list[str] = Field(default_factory=list, description="IRIs of source claims")
    evidence: list[Evidence] = Field(default_factory=list)
    verifications: list[Verification] = Field(default_factory=list)

    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    tags: list[str] = Field(default_factory=list)

    # ---- validation of what can be checked on a single claim ---------------

    @field_validator("derived_from")
    @classmethod
    def _no_duplicate_sources(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("derived_from contains duplicates")
        return v

    @model_validator(mode="after")
    def _status_requirements(self) -> "Claim":
        s = self.declared_status
        if self.id in self.derived_from:
            raise ValueError("a claim cannot be derived from itself")

        if s is EpistemicStatus.DERIVED and not self.derived_from:
            raise ValueError("declared_status=derived requires at least one derived_from source")

        if s in (EpistemicStatus.TOOL_VERIFIED, EpistemicStatus.HUMAN_VERIFIED):
            conferred = {v.confers for v in self.verifications} - {None}
            if not any(c is not None and c.trust_rank >= s.trust_rank for c in conferred):
                raise ValueError(
                    f"declared_status={s.value} requires a passed verification by a "
                    f"{'human' if s is EpistemicStatus.HUMAN_VERIFIED else 'tool or human'}; "
                    f"found {[v.verifier.kind.value + ':' + v.outcome.value for v in self.verifications]}"
                )
            if not any(v.evidence for v in self.verifications if v.confers is not None):
                raise ValueError(f"declared_status={s.value} requires the verification to cite evidence")

        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to precedes valid_from")
        return self

    # ---- convenience --------------------------------------------------------

    @property
    def trust_rank(self) -> int:
        return self.declared_status.trust_rank

    def highest_conferred(self) -> EpistemicStatus:
        """Highest status the attached verifications could justify."""
        best = EpistemicStatus.DERIVED if self.derived_from else EpistemicStatus.ASSERTED
        for v in self.verifications:
            c = v.confers
            if c is not None and c.trust_rank > best.trust_rank:
                best = c
        return best


# --------------------------------------------------------------------------- #
# Retrieval (where enacted status is observed)
# --------------------------------------------------------------------------- #


class RetrievalEvent(BaseModel):
    """A consumer agent retrieved a claim and treated it as ``enacted_status``.

    Maps to cp:Retrieval (prov:Activity). Divergence is measured here:
        enacted_status.trust_rank - declared_status.trust_rank > 0  ->  inflation
    """

    id: str = Field(default_factory=lambda: _new_id("retrieval"))
    claim_id: str
    retrieved_by: AgentRef
    retrieved_at: datetime = Field(default_factory=_now)
    enacted_status: EpistemicStatus
    query: Optional[str] = Field(default=None, description="the retrieval query/context")
    used_in: Optional[str] = Field(default=None, description="IRI of the consuming activity/run")
    rationale: Optional[str] = Field(default=None, description="why the consumer treated it this way")

    def divergence(self, declared: EpistemicStatus) -> int:
        """Positive = consumer inflated the status; negative = consumer discounted it."""
        return self.enacted_status.trust_rank - declared.trust_rank
