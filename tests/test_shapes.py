"""SHACL-level rules, including the cross-claim ones pydantic cannot see."""

from rdflib import RDF, Graph, Literal, Namespace, URIRef
from rdflib.namespace import PROV

from claimprov import Asset, Claim, ClaimGraph, EpistemicStatus, RecordKind, RetrievalEvent, validate
from conftest import passed_by

CP = Namespace("https://w3id.org/claimprov#")


def _asserted(analyst, cid="urn:claimprov:claim:a"):
    return Claim(id=cid, statement="S-17 lead time is 14 days", declared_status=EpistemicStatus.ASSERTED,
                 asserted_by=analyst, confidence=0.7)


# ---- happy paths ------------------------------------------------------------

def test_asserted_claim_conforms(analyst):
    g = ClaimGraph(); g.add_claim(_asserted(analyst))
    rep = g.validate()
    assert rep.conforms, rep.text
    assert not rep.findings


def test_derived_claim_conforms(analyst):
    g = ClaimGraph()
    g.add_claim(_asserted(analyst))
    g.add_claim(Claim(id="urn:claimprov:claim:b", statement="Reorder S-17 two weeks ahead",
                      declared_status=EpistemicStatus.DERIVED, asserted_by=analyst,
                      derived_from=["urn:claimprov:claim:a"]))
    assert g.validate().conforms


def test_tool_verified_claim_conforms(analyst, sql_tool, dataset_evidence):
    g = ClaimGraph()
    g.add_claim(Claim(statement="S-17 lead time is 14 days", declared_status=EpistemicStatus.TOOL_VERIFIED,
                      asserted_by=analyst, verifications=[passed_by(sql_tool, dataset_evidence)]))
    rep = g.validate()
    assert rep.conforms, rep.text


def test_human_verified_claim_conforms(analyst, reviewer, dataset_evidence):
    g = ClaimGraph()
    g.add_claim(Claim(statement="S-17 lead time is 14 days", declared_status=EpistemicStatus.HUMAN_VERIFIED,
                      asserted_by=analyst, verifications=[passed_by(reviewer, dataset_evidence, "review")]))
    assert g.validate().conforms


def test_roundtrip_turtle(analyst, sql_tool, dataset_evidence):
    g = ClaimGraph()
    g.add_claim(Claim(statement="x", declared_status=EpistemicStatus.TOOL_VERIFIED, asserted_by=analyst,
                      verifications=[passed_by(sql_tool, dataset_evidence)]))
    ttl = g.serialize()
    g2 = Graph().parse(data=ttl, format="turtle")
    assert validate(g2).conforms
    assert "cp:ToolVerified" in ttl and "prov:wasAttributedTo" in ttl


# ---- storage-time violations (built by hand in RDF to bypass pydantic) -------

def _raw_claim(g: Graph, cid: str, status: URIRef, agent: URIRef):
    c = URIRef(cid)
    g.add((c, RDF.type, CP.Claim)); g.add((c, RDF.type, PROV.Entity))
    g.add((c, CP.statement, Literal("x")))
    g.add((c, CP.declaredStatus, status))
    g.add((c, PROV.wasAttributedTo, agent))
    return c


def test_shacl_rejects_derived_without_sources(analyst):
    g = ClaimGraph(); a = g.add_agent(analyst)
    _raw_claim(g.g, "urn:c1", CP.Derived, a)
    rep = g.validate()
    assert not rep.conforms
    assert any("Derived requires" in f.message for f in rep.violations)


def test_shacl_rejects_verified_without_verification(analyst):
    g = ClaimGraph(); a = g.add_agent(analyst)
    _raw_claim(g.g, "urn:c1", CP.ToolVerified, a)
    rep = g.validate()
    assert any("ToolVerified requires" in f.message for f in rep.violations)


def test_shacl_rejects_llm_as_verifier(analyst, planner, dataset_evidence):
    g = ClaimGraph(); a = g.add_agent(analyst)
    c = _raw_claim(g.g, "urn:c1", CP.ToolVerified, a)
    v = URIRef("urn:v1")
    g.g.add((v, RDF.type, CP.Verification)); g.g.add((v, RDF.type, PROV.Activity))
    g.g.add((v, CP.outcome, CP.Passed)); g.g.add((v, CP.method, Literal("reread")))
    g.g.add((v, PROV.wasAssociatedWith, g.add_agent(planner)))
    g.g.add((v, PROV.used, g.add_evidence(dataset_evidence)))
    g.g.add((c, CP.verifiedBy, v))
    rep = g.validate()
    msgs = " | ".join(f.message for f in rep.violations)
    assert "cannot be associated with a cp:LLMAgent" in msgs
    assert "ToolVerified requires" in msgs


def test_status_laundering_detected(analyst, planner):
    """asserted --derivedFrom--> 'tool-verified' with no verification of its own = laundering."""
    g = ClaimGraph(); a = g.add_agent(analyst); p = g.add_agent(planner)
    _raw_claim(g.g, "urn:src", CP.Asserted, a)
    child = _raw_claim(g.g, "urn:child", CP.ToolVerified, p)
    g.g.add((child, PROV.wasDerivedFrom, URIRef("urn:src")))
    rep = g.validate()
    assert not rep.conforms
    laund = [f for f in rep.violations if "laundering" in f.message]
    assert laund and laund[0].focus == "urn:child"
    assert "rank 1" in laund[0].message and "rank 0" in laund[0].message


def test_laundering_not_flagged_when_child_is_verified(analyst, sql_tool, dataset_evidence):
    """Upgrading over a weaker source is fine if the child earned it."""
    g = ClaimGraph()
    g.add_claim(_asserted(analyst, "urn:claimprov:claim:src"))
    g.add_claim(Claim(statement="x", declared_status=EpistemicStatus.TOOL_VERIFIED, asserted_by=analyst,
                      derived_from=["urn:claimprov:claim:src"],
                      verifications=[passed_by(sql_tool, dataset_evidence)]))
    rep = g.validate()
    assert rep.conforms, rep.text


def test_downgrade_is_never_laundering(analyst, reviewer, dataset_evidence):
    g = ClaimGraph()
    g.add_claim(Claim(id="urn:claimprov:claim:hv", statement="x", declared_status=EpistemicStatus.HUMAN_VERIFIED,
                      asserted_by=analyst, verifications=[passed_by(reviewer, dataset_evidence)]))
    g.add_claim(Claim(statement="y", declared_status=EpistemicStatus.DERIVED, asserted_by=analyst,
                      derived_from=["urn:claimprov:claim:hv"]))
    assert g.validate().conforms


# ---- retrieval-time divergence (warning, not violation) ----------------------

def test_status_inflation_at_retrieval_is_warning(analyst, planner):
    g = ClaimGraph()
    g.add_claim(_asserted(analyst))
    g.add_retrieval(RetrievalEvent(claim_id="urn:claimprov:claim:a", retrieved_by=planner,
                                   observed_use=RecordKind.EVENT, required_status=EpistemicStatus.HUMAN_VERIFIED,
                                   query="lead time S-17", rationale="recorded as confirmed"))
    rep = g.validate()
    assert rep.conforms  # warnings do not break conformance
    assert len(rep.warnings) == 1
    assert "inflation" in rep.warnings[0].message
    assert "rank 2" in rep.warnings[0].message and "rank 0" in rep.warnings[0].message


def test_faithful_retrieval_has_no_warning(analyst, planner):
    g = ClaimGraph()
    g.add_claim(_asserted(analyst))
    g.add_retrieval(RetrievalEvent(claim_id="urn:claimprov:claim:a", retrieved_by=planner,
                                   observed_use=RecordKind.DECISION, required_status=EpistemicStatus.ASSERTED))
    rep = g.validate()
    assert rep.conforms and not rep.findings


def test_reviewed_gap_is_info_not_warning(analyst, planner):
    g = ClaimGraph()
    g.add_claim(_asserted(analyst))
    g.add_retrieval(RetrievalEvent(claim_id="urn:claimprov:claim:a", retrieved_by=planner,
                                   observed_use=RecordKind.EVENT, required_status=EpistemicStatus.HUMAN_VERIFIED,
                                   reviewed=True))
    rep = g.validate()
    assert rep.conforms and not rep.warnings
    assert any(f.severity == "Info" and "closed by review" in f.message for f in rep.findings)


def test_enacted_must_equal_required(analyst, planner):
    """Hand-built graph where someone annotated enacted directly: rejected."""
    g = ClaimGraph()
    g.add_claim(_asserted(analyst))
    r = URIRef("urn:r1")
    g.g.add((r, RDF.type, CP.Retrieval)); g.g.add((r, RDF.type, PROV.Activity))
    g.g.add((r, PROV.used, URIRef("urn:claimprov:claim:a")))
    g.g.add((r, PROV.wasAssociatedWith, g.add_agent(planner)))
    g.g.add((r, CP.observedUse, CP.Decision))
    g.g.add((r, CP.requiredStatus, CP.Asserted))
    g.g.add((r, CP.enactedStatus, CP.HumanVerified))
    rep = g.validate()
    assert any("derived, not annotated" in f.message for f in rep.violations)


def test_asset_inheritance_warning(analyst):
    g = ClaimGraph()
    crm = Asset(id="urn:claimprov:asset:crm", name="CRM.accounts (certified)",
                default_status=EpistemicStatus.HUMAN_VERIFIED)
    g.add_asset(crm)
    g.add_claim(Claim(id="urn:claimprov:claim:churn", statement="Account A churn risk high",
                      declared_status=EpistemicStatus.ASSERTED, asserted_by=analyst, stored_in=crm.id))
    rep = g.validate()
    assert rep.conforms
    assert any("Asset inheritance" in f.message and "rank 2" in f.message for f in rep.warnings)


def test_asset_no_warning_when_claim_matches(analyst, reviewer, dataset_evidence):
    g = ClaimGraph()
    crm = Asset(id="urn:claimprov:asset:crm", name="CRM", default_status=EpistemicStatus.HUMAN_VERIFIED)
    g.add_asset(crm)
    g.add_claim(Claim(statement="x", declared_status=EpistemicStatus.HUMAN_VERIFIED, asserted_by=analyst,
                      stored_in=crm.id, verifications=[passed_by(reviewer, dataset_evidence)]))
    rep = g.validate()
    assert rep.conforms and not rep.warnings
