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
  "status laundering" violates. The ranks are a *deployment policy*
  (``StatusPolicy``), not a universal epistemic ordering; the default puts
  human verification above tool verification, and a deployment where a
  reproducible tool check is the stronger warrant can invert that.

* A claim has a ``RecordKind``: a prediction, a decision, or an event record.
  These have different justification conditions. A prediction needs factual
  warrant. A decision needs procedural legitimacy (the policy allowed it on the
  evidence it had). An event record is true if the event happened, whatever
  the standing of the inference that triggered it. One inference can produce
  all three downstream, and a correction to the inference does not falsify the
  event record.

* Enacted status is *derived*, not annotated. A ``RetrievalEvent`` records
  what the consumer observably did (``observed_use``), what minimum status the
  consumer's acceptance policy required for that use (``required_status``),
  and whether the use passed through review. Enacted status is the status the
  use presupposed. Status inflation is then

      required_status > declared_status  and  not reviewed

  Using a provisional inference as input to a use the policy permits on
  provisional evidence is *not* inflation. This keeps the behavioral
  definition from collapsing into "every decision uses uncertain inputs".

* Pydantic validation covers what can be checked on one claim in isolation.
  Cross-claim rules (laundering through a derivation chain, inheritance from
  an asset) live in SHACL, because they need the graph.
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

    Default trust_rank:  asserted = derived = 0  <  tool-verified = 1  <  human-verified = 2
    See ``StatusPolicy`` to change the ranking for a deployment.
    """

    ASSERTED = "asserted"  # produced by an agent, no verification, no lineage required
    DERIVED = "derived"  # computed/inferred from other claims; lineage required
    TOOL_VERIFIED = "tool-verified"  # checked by a deterministic tool against evidence
    HUMAN_VERIFIED = "human-verified"  # checked and signed off by a person

    @property
    def trust_rank(self) -> int:
        return DEFAULT_POLICY.rank(self)

    @property
    def iri(self) -> str:
        return CP_NS + _STATUS_LOCAL[self]

    def __lt__(self, other: "EpistemicStatus") -> bool:  # type: ignore[override]
        return self.trust_rank < other.trust_rank


_STATUS_LOCAL = {
    EpistemicStatus.ASSERTED: "Asserted",
    EpistemicStatus.DERIVED: "Derived",
    EpistemicStatus.TOOL_VERIFIED: "ToolVerified",
    EpistemicStatus.HUMAN_VERIFIED: "HumanVerified",
}

# Name used in the project plan; kept as an alias.
DeclaredStatus = EpistemicStatus


class StatusPolicy(BaseModel):
    """Trust ranking for a deployment. The default is the lattice in the docstring.

    Only the *order* matters to the rules; ranks are integers for comparison.
    Invariant kept by validation: asserted and derived share a rank, because
    derivation is lineage, not verification.
    """

    ranks: dict[EpistemicStatus, int] = Field(
        default_factory=lambda: {
            EpistemicStatus.ASSERTED: 0,
            EpistemicStatus.DERIVED: 0,
            EpistemicStatus.TOOL_VERIFIED: 1,
            EpistemicStatus.HUMAN_VERIFIED: 2,
        }
    )

    @model_validator(mode="after")
    def _well_formed(self) -> "StatusPolicy":
        if set(self.ranks) != set(EpistemicStatus):
            raise ValueError("ranks must cover every EpistemicStatus")
        if self.ranks[EpistemicStatus.ASSERTED] != self.ranks[EpistemicStatus.DERIVED]:
            raise ValueError("asserted and derived must share a rank: derivation is not verification")
        unverified = self.ranks[EpistemicStatus.ASSERTED]
        for s in (EpistemicStatus.TOOL_VERIFIED, EpistemicStatus.HUMAN_VERIFIED):
            if self.ranks[s] <= unverified:
                raise ValueError(f"{s.value} must rank above unverified statuses")
        return self

    def rank(self, s: EpistemicStatus) -> int:
        return self.ranks[s]

    def inflation(self, declared: EpistemicStatus, required: EpistemicStatus) -> int:
        """Positive = the use presupposed more warrant than was declared."""
        return self.rank(required) - self.rank(declared)


DEFAULT_POLICY = StatusPolicy()

# A deployment that treats reproducible tool checks as the stronger warrant.
TOOL_FIRST_POLICY = StatusPolicy(
    ranks={
        EpistemicStatus.ASSERTED: 0,
        EpistemicStatus.DERIVED: 0,
        EpistemicStatus.HUMAN_VERIFIED: 1,
        EpistemicStatus.TOOL_VERIFIED: 2,
    }
)


class RecordKind(str, Enum):
    """What kind of thing a claim is, which fixes its justification condition."""

    PREDICTION = "prediction"  # an inference about the world; needs factual warrant
    DECISION = "decision"  # a commitment to act; needs procedural legitimacy
    EVENT = "event"  # a record that something happened; true iff it happened


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


class Asset(BaseModel):
    """A governed container a claim can be written into: a table, a view, a field.

    Maps to cp:Asset (prov:Entity). ``default_status`` is the standing the
    asset's certification confers on whatever is read from it. A claim written
    into an asset *without its own declared status* inherits this default at
    retrieval; that inheritance is the record-path mechanism.
    """

    id: str = Field(default_factory=lambda: _new_id("asset"))
    name: str
    default_status: EpistemicStatus = Field(description="status conferred by the asset's certification")
    certified_by: Optional[AgentRef] = None


# --------------------------------------------------------------------------- #
# Claim
# --------------------------------------------------------------------------- #


class Claim(BaseModel):
    """One proposition with its declared status and provenance. Maps to cp:Claim (prov:Entity)."""

    id: str = Field(default_factory=lambda: _new_id("claim"))
    statement: str = Field(min_length=1, description="natural-language proposition")
    record_kind: RecordKind = RecordKind.PREDICTION

    # Optional structured form, for claims that are a single relation.
    subject: Optional[str] = None
    predicate: Optional[str] = None
    object: Optional[str] = None

    declared_status: EpistemicStatus
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    asserted_by: AgentRef
    asserted_at: datetime = Field(default_factory=_now)
    generated_by: Optional[str] = Field(default=None, description="IRI of the producing activity/run")
    stored_in: Optional[str] = Field(default=None, description="IRI of the cp:Asset this claim was written into")

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


class AcceptancePolicy(BaseModel):
    """What a consumer requires before it will use a claim for a given purpose.

    Maps to cp:AcceptancePolicy. ``required`` maps the kind of record the
    consumer is about to produce to the minimum declared status it demands of
    its input. ``reads_status`` says whether the consumer's retrieval path
    exposes the declared status to the policy at all; a policy that cannot see
    the status cannot enforce ``required``, whatever it says.
    """

    id: str = Field(default_factory=lambda: _new_id("policy"))
    name: str
    required: dict[RecordKind, EpistemicStatus] = Field(
        description="minimum input status required to produce each kind of record"
    )
    reads_status: bool = Field(default=True, description="does the retrieval interface expose declared status to this policy?")

    def required_for(self, kind: RecordKind) -> EpistemicStatus:
        return self.required[kind]


class RetrievalEvent(BaseModel):
    """A consumer agent retrieved a claim and did something observable with it.

    Maps to cp:Retrieval (prov:Activity). Three things are recorded:

    * ``observed_use``: the kind of record the consumer produced from the claim,
      and (optionally) the IRI of that record. This is observable behavior.
    * ``required_status``: the minimum status the consumer's acceptance policy
      demanded for that use. Supplied directly or taken from ``policy``.
    * ``reviewed``: whether the use passed through evaluative mediation
      (a human or a validation rule) before proceeding.

    ``enacted_status`` is derived: it is ``required_status``, the standing the
    use presupposed. Inflation is enacted (= required) above declared, without
    review. A provisional input used for a purpose the policy allows on
    provisional evidence is not inflation.
    """

    id: str = Field(default_factory=lambda: _new_id("retrieval"))
    claim_id: str
    retrieved_by: AgentRef
    retrieved_at: datetime = Field(default_factory=_now)

    observed_use: RecordKind = Field(description="kind of record the consumer produced from the claim")
    produced: Optional[str] = Field(default=None, description="IRI of the record the consumer produced")
    policy: Optional[AcceptancePolicy] = None
    required_status: Optional[EpistemicStatus] = Field(
        default=None, description="minimum status the use required; taken from policy if omitted"
    )
    reviewed: bool = Field(default=False, description="did the use pass through evaluative mediation?")

    query: Optional[str] = Field(default=None, description="the retrieval query/context")
    used_in: Optional[str] = Field(default=None, description="IRI of the consuming activity/run")
    rationale: Optional[str] = Field(default=None, description="why the consumer treated it this way")

    @model_validator(mode="after")
    def _resolve_required(self) -> "RetrievalEvent":
        if self.required_status is None:
            if self.policy is None:
                raise ValueError("required_status or policy must be given")
            self.required_status = self.policy.required_for(self.observed_use)
        return self

    @property
    def enacted_status(self) -> EpistemicStatus:
        """The standing the observed use presupposed."""
        assert self.required_status is not None
        return self.required_status

    def divergence(self, declared: EpistemicStatus, policy: StatusPolicy = DEFAULT_POLICY) -> int:
        """Positive = the use presupposed more warrant than was declared."""
        return policy.inflation(declared, self.enacted_status)

    def is_inflation(self, declared: EpistemicStatus, policy: StatusPolicy = DEFAULT_POLICY) -> bool:
        """Enacted above declared, and nothing checked it on the way."""
        return self.divergence(declared, policy) > 0 and not self.reviewed
