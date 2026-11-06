"""Serialize the pydantic model to a PROV-O graph and validate it with SHACL."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from importlib import resources
from typing import Iterable, Optional

from pyshacl import validate as _shacl_validate
from rdflib import RDF, RDFS, XSD, BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, PROV

from .model import (
    CP_NS,
    AcceptancePolicy,
    AgentKind,
    AgentRef,
    Asset,
    Claim,
    Evidence,
    EvidenceKind,
    RecordKind,
    RetrievalEvent,
    Verification,
    VerificationOutcome,
)

CP = Namespace(CP_NS)

_AGENT_CLASS = {
    AgentKind.LLM_AGENT: CP.LLMAgent,
    AgentKind.TOOL: CP.Tool,
    AgentKind.HUMAN: PROV.Person,
    AgentKind.ORGANIZATION: PROV.Organization,
}
_OUTCOME = {
    VerificationOutcome.PASSED: CP.Passed,
    VerificationOutcome.FAILED: CP.Failed,
    VerificationOutcome.INCONCLUSIVE: CP.Inconclusive,
}
_RECORD_KIND = {
    RecordKind.PREDICTION: CP.Prediction,
    RecordKind.DECISION: CP.Decision,
    RecordKind.EVENT: CP.EventRecord,
}
_EVIDENCE_KIND = {
    EvidenceKind.DATASET: CP.Dataset,
    EvidenceKind.DOCUMENT: CP.Document,
    EvidenceKind.TOOL_OUTPUT: CP.ToolOutput,
    EvidenceKind.OBSERVATION: CP.Observation,
    EvidenceKind.HUMAN_REVIEW: CP.HumanReview,
}


def _ontology_text(name: str) -> str:
    return resources.files("claimprov.ontology").joinpath(name).read_text(encoding="utf-8")


def load_ontology() -> Graph:
    return Graph().parse(data=_ontology_text("claimprov.ttl"), format="turtle")


def load_shapes() -> Graph:
    return Graph().parse(data=_ontology_text("shapes.ttl"), format="turtle")


class ClaimGraph:
    """An rdflib graph with claimprov conveniences. Backing store for v0.1."""

    def __init__(self, graph: Optional[Graph] = None):
        self.g = graph if graph is not None else Graph()
        self.g.bind("cp", CP)
        self.g.bind("prov", PROV)
        self.g.bind("dcterms", DCTERMS)

    # ---- adding --------------------------------------------------------------

    def add_agent(self, a: AgentRef) -> URIRef:
        node = URIRef(a.id)
        self.g.add((node, RDF.type, PROV.Agent))
        self.g.add((node, RDF.type, _AGENT_CLASS[a.kind]))
        self.g.add((node, RDFS.label, Literal(a.name)))
        if a.model:
            self.g.add((node, CP.modelName, Literal(a.model)))
        if a.version:
            self.g.add((node, CP.agentVersion, Literal(a.version)))
        return node

    def add_evidence(self, e: Evidence) -> URIRef:
        node = URIRef(e.id)
        self.g.add((node, RDF.type, CP.Evidence))
        self.g.add((node, RDF.type, PROV.Entity))
        self.g.add((node, CP.evidenceKind, _EVIDENCE_KIND[e.kind]))
        self.g.add((node, CP.sourceLocation, Literal(e.source, datatype=XSD.anyURI)))
        self.g.add((node, PROV.generatedAtTime, Literal(e.retrieved_at)))
        if e.content_hash:
            self.g.add((node, CP.contentHash, Literal(e.content_hash)))
        if e.excerpt:
            self.g.add((node, CP.excerpt, Literal(e.excerpt)))
        if e.license:
            self.g.add((node, DCTERMS.license, Literal(e.license)))
        return node

    def add_verification(self, v: Verification, claim_node: URIRef) -> URIRef:
        node = URIRef(v.id)
        self.g.add((node, RDF.type, CP.Verification))
        self.g.add((node, RDF.type, PROV.Activity))
        self.g.add((node, PROV.wasAssociatedWith, self.add_agent(v.verifier)))
        self.g.add((node, CP.method, Literal(v.method)))
        self.g.add((node, CP.outcome, _OUTCOME[v.outcome]))
        self.g.add((node, PROV.endedAtTime, Literal(v.performed_at)))
        if v.note:
            self.g.add((node, CP.note, Literal(v.note)))
        for e in v.evidence:
            self.g.add((node, PROV.used, self.add_evidence(e)))
        self.g.add((claim_node, CP.verifiedBy, node))
        return node

    def add_asset(self, a: Asset) -> URIRef:
        node = URIRef(a.id)
        self.g.add((node, RDF.type, CP.Asset))
        self.g.add((node, RDF.type, PROV.Entity))
        self.g.add((node, RDFS.label, Literal(a.name)))
        self.g.add((node, CP.defaultStatus, URIRef(a.default_status.iri)))
        if a.certified_by:
            self.g.add((node, PROV.wasAttributedTo, self.add_agent(a.certified_by)))
        return node

    def add_policy(self, p: AcceptancePolicy) -> URIRef:
        node = URIRef(p.id)
        self.g.add((node, RDF.type, CP.AcceptancePolicy))
        self.g.add((node, RDF.type, PROV.Plan))
        self.g.add((node, RDFS.label, Literal(p.name)))
        self.g.add((node, CP.readsStatus, Literal(p.reads_status)))
        for kind, st in p.required.items():
            req = BNode()
            self.g.add((node, CP.requires, req))
            self.g.add((req, CP.forRecordKind, _RECORD_KIND[kind]))
            self.g.add((req, CP.minimumStatus, URIRef(st.iri)))
        return node

    def add_claim(self, c: Claim) -> URIRef:
        node = URIRef(c.id)
        self.g.add((node, RDF.type, CP.Claim))
        self.g.add((node, RDF.type, PROV.Entity))
        self.g.add((node, CP.statement, Literal(c.statement)))
        self.g.add((node, CP.recordKind, _RECORD_KIND[c.record_kind]))
        self.g.add((node, CP.declaredStatus, URIRef(c.declared_status.iri)))
        if c.stored_in:
            self.g.add((node, CP.storedIn, URIRef(c.stored_in)))
        self.g.add((node, PROV.wasAttributedTo, self.add_agent(c.asserted_by)))
        self.g.add((node, PROV.generatedAtTime, Literal(c.asserted_at)))
        if c.generated_by:
            self.g.add((node, PROV.wasGeneratedBy, URIRef(c.generated_by)))
        if c.subject:
            self.g.add((node, CP.claimSubject, Literal(c.subject)))
        if c.predicate:
            self.g.add((node, CP.claimPredicate, Literal(c.predicate)))
        if c.object:
            self.g.add((node, CP.claimObject, Literal(c.object)))
        if c.confidence is not None:
            self.g.add((node, CP.confidence, Literal(Decimal(str(c.confidence)), datatype=XSD.decimal)))
        if c.valid_from:
            self.g.add((node, CP.validFrom, Literal(c.valid_from)))
        if c.valid_to:
            self.g.add((node, CP.validTo, Literal(c.valid_to)))
        for src in c.derived_from:
            self.g.add((node, PROV.wasDerivedFrom, URIRef(src)))
        for e in c.evidence:
            self.g.add((node, CP.supportedBy, self.add_evidence(e)))
        for v in c.verifications:
            self.add_verification(v, node)
        return node

    def add_retrieval(self, r: RetrievalEvent) -> URIRef:
        node = URIRef(r.id)
        self.g.add((node, RDF.type, CP.Retrieval))
        self.g.add((node, RDF.type, PROV.Activity))
        self.g.add((node, PROV.used, URIRef(r.claim_id)))
        self.g.add((node, PROV.wasAssociatedWith, self.add_agent(r.retrieved_by)))
        self.g.add((node, PROV.startedAtTime, Literal(r.retrieved_at)))
        self.g.add((node, CP.observedUse, _RECORD_KIND[r.observed_use]))
        self.g.add((node, CP.requiredStatus, URIRef(r.enacted_status.iri)))
        self.g.add((node, CP.enactedStatus, URIRef(r.enacted_status.iri)))
        self.g.add((node, CP.reviewed, Literal(r.reviewed)))
        if r.produced:
            self.g.add((node, PROV.generated, URIRef(r.produced)))
        if r.policy:
            self.g.add((node, PROV.hadPlan, self.add_policy(r.policy)))
        if r.query:
            self.g.add((node, CP.retrievalQuery, Literal(r.query)))
        if r.used_in:
            self.g.add((node, PROV.wasInformedBy, URIRef(r.used_in)))
        if r.rationale:
            self.g.add((node, CP.rationale, Literal(r.rationale)))
        return node

    def add_all(self, items: Iterable[Claim | RetrievalEvent | Asset]) -> None:
        for item in items:
            if isinstance(item, Claim):
                self.add_claim(item)
            elif isinstance(item, RetrievalEvent):
                self.add_retrieval(item)
            elif isinstance(item, Asset):
                self.add_asset(item)
            else:
                raise TypeError(type(item))

    # ---- querying ------------------------------------------------------------

    def declared_status_iri(self, claim_id: str) -> Optional[URIRef]:
        return self.g.value(URIRef(claim_id), CP.declaredStatus)

    def serialize(self, fmt: str = "turtle") -> str:
        return self.g.serialize(format=fmt)

    # ---- validation ----------------------------------------------------------

    def validate(self) -> "ValidationReport":
        return validate(self.g)


@dataclass
class Finding:
    severity: str  # "Violation" | "Warning" | "Info"
    focus: str
    message: str
    shape: Optional[str] = None


@dataclass
class ValidationReport:
    conforms: bool
    findings: list[Finding] = field(default_factory=list)
    text: str = ""

    @property
    def violations(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "Violation"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "Warning"]


SH = Namespace("http://www.w3.org/ns/shacl#")


def validate(data: Graph) -> ValidationReport:
    """Run the claimprov shapes against a data graph.

    The ontology is merged into a copy of the data graph (not passed as
    ``ont_graph``) because pyshacl does not expose ``ont_graph`` triples to
    SPARQL-based constraints, and the laundering/inflation rules need
    cp:trustRank on the status individuals.
    """
    merged = Graph()
    merged += data
    merged += load_ontology()
    conforms, report_graph, report_text = _shacl_validate(
        merged,
        shacl_graph=load_shapes(),
        advanced=True,
        inference="none",
        abort_on_first=False,
    )
    findings: list[Finding] = []
    for result in report_graph.subjects(RDF.type, SH.ValidationResult):
        sev = report_graph.value(result, SH.resultSeverity)
        findings.append(
            Finding(
                severity=str(sev).rsplit("#", 1)[-1] if sev else "Violation",
                focus=str(report_graph.value(result, SH.focusNode)),
                message=str(report_graph.value(result, SH.resultMessage) or ""),
                shape=str(report_graph.value(result, SH.sourceShape) or "") or None,
            )
        )
    # pyshacl sets conforms=False on warnings too. Here conformance means "no violations":
    # a retrieval-time inflation warning is a signal to surface, not malformed data.
    conforms = not any(f.severity == "Violation" for f in findings)
    return ValidationReport(conforms=conforms, findings=findings, text=report_text)
