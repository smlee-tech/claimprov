import pytest
from pydantic import ValidationError

from claimprov import (TOOL_FIRST_POLICY, AcceptancePolicy, AgentKind, AgentRef, Claim, EpistemicStatus,
                       RecordKind, RetrievalEvent, StatusPolicy, Verification, VerificationOutcome)
from conftest import passed_by


def test_trust_lattice():
    s = EpistemicStatus
    assert s.ASSERTED.trust_rank == s.DERIVED.trust_rank == 0
    assert s.TOOL_VERIFIED.trust_rank == 1
    assert s.HUMAN_VERIFIED.trust_rank == 2
    assert s.ASSERTED < s.TOOL_VERIFIED < s.HUMAN_VERIFIED
    assert s.TOOL_VERIFIED.iri.endswith("#ToolVerified")


def test_asserted_needs_only_attribution(analyst):
    c = Claim(statement="S-17 lead time is 14 days", declared_status=EpistemicStatus.ASSERTED, asserted_by=analyst)
    assert c.trust_rank == 0
    assert c.highest_conferred() is EpistemicStatus.ASSERTED


def test_derived_requires_sources(analyst):
    with pytest.raises(ValidationError, match="derived_from"):
        Claim(statement="x", declared_status=EpistemicStatus.DERIVED, asserted_by=analyst)
    c = Claim(statement="x", declared_status=EpistemicStatus.DERIVED, asserted_by=analyst,
              derived_from=["urn:claimprov:claim:a"])
    assert c.highest_conferred() is EpistemicStatus.DERIVED


def test_self_derivation_rejected(analyst):
    with pytest.raises(ValidationError, match="itself"):
        Claim(id="urn:c", statement="x", declared_status=EpistemicStatus.DERIVED,
              asserted_by=analyst, derived_from=["urn:c"])


def test_tool_verified_requires_passed_tool_verification(analyst, sql_tool, dataset_evidence):
    with pytest.raises(ValidationError, match="requires a passed verification"):
        Claim(statement="x", declared_status=EpistemicStatus.TOOL_VERIFIED, asserted_by=analyst)

    failed = Verification(verifier=sql_tool, method="recount", outcome=VerificationOutcome.FAILED,
                          evidence=[dataset_evidence])
    with pytest.raises(ValidationError, match="requires a passed verification"):
        Claim(statement="x", declared_status=EpistemicStatus.TOOL_VERIFIED, asserted_by=analyst,
              verifications=[failed])

    ok = Claim(statement="x", declared_status=EpistemicStatus.TOOL_VERIFIED, asserted_by=analyst,
               verifications=[passed_by(sql_tool, dataset_evidence)])
    assert ok.highest_conferred() is EpistemicStatus.TOOL_VERIFIED


def test_verification_must_cite_evidence(analyst, sql_tool):
    bare = Verification(verifier=sql_tool, method="recount", outcome=VerificationOutcome.PASSED)
    with pytest.raises(ValidationError, match="cite evidence"):
        Claim(statement="x", declared_status=EpistemicStatus.TOOL_VERIFIED, asserted_by=analyst, verifications=[bare])


def test_llm_cannot_verify(analyst, planner, dataset_evidence):
    """An LLM 'checking' a claim confers nothing."""
    llm_check = Verification(verifier=planner, method="reread", outcome=VerificationOutcome.PASSED,
                             evidence=[dataset_evidence])
    assert llm_check.confers is None
    with pytest.raises(ValidationError):
        Claim(statement="x", declared_status=EpistemicStatus.TOOL_VERIFIED, asserted_by=analyst,
              verifications=[llm_check])


def test_human_verified_needs_human_not_tool(analyst, sql_tool, reviewer, dataset_evidence):
    with pytest.raises(ValidationError, match="human"):
        Claim(statement="x", declared_status=EpistemicStatus.HUMAN_VERIFIED, asserted_by=analyst,
              verifications=[passed_by(sql_tool, dataset_evidence)])
    ok = Claim(statement="x", declared_status=EpistemicStatus.HUMAN_VERIFIED, asserted_by=analyst,
               verifications=[passed_by(reviewer, dataset_evidence, "analyst-review")])
    assert ok.trust_rank == 2


def test_human_verification_satisfies_tool_verified(analyst, reviewer, dataset_evidence):
    """Declaring *lower* than what the evidence supports is always allowed."""
    c = Claim(statement="x", declared_status=EpistemicStatus.TOOL_VERIFIED, asserted_by=analyst,
              verifications=[passed_by(reviewer, dataset_evidence)])
    assert c.highest_conferred() is EpistemicStatus.HUMAN_VERIFIED


def test_retrieval_divergence(planner):
    r = RetrievalEvent(claim_id="urn:c", retrieved_by=planner, observed_use=RecordKind.DECISION,
                       required_status=EpistemicStatus.HUMAN_VERIFIED)
    assert r.enacted_status is EpistemicStatus.HUMAN_VERIFIED
    assert r.divergence(EpistemicStatus.ASSERTED) == 2
    assert r.divergence(EpistemicStatus.HUMAN_VERIFIED) == 0
    r2 = RetrievalEvent(claim_id="urn:c", retrieved_by=planner, observed_use=RecordKind.DECISION,
                        required_status=EpistemicStatus.ASSERTED)
    assert r2.divergence(EpistemicStatus.TOOL_VERIFIED) == -1


def test_retrieval_requires_policy_or_required(planner):
    with pytest.raises(ValidationError, match="required_status or policy"):
        RetrievalEvent(claim_id="urn:c", retrieved_by=planner, observed_use=RecordKind.DECISION)


def test_required_status_taken_from_policy(planner):
    pol = AcceptancePolicy(name="ops", required={
        RecordKind.PREDICTION: EpistemicStatus.ASSERTED,
        RecordKind.DECISION: EpistemicStatus.ASSERTED,
        RecordKind.EVENT: EpistemicStatus.TOOL_VERIFIED,
    })
    r = RetrievalEvent(claim_id="urn:c", retrieved_by=planner, observed_use=RecordKind.EVENT, policy=pol)
    assert r.required_status is EpistemicStatus.TOOL_VERIFIED


def test_inflation_needs_gap_and_no_review(planner):
    r = RetrievalEvent(claim_id="urn:c", retrieved_by=planner, observed_use=RecordKind.DECISION,
                       required_status=EpistemicStatus.TOOL_VERIFIED)
    assert r.is_inflation(EpistemicStatus.ASSERTED)
    assert not r.is_inflation(EpistemicStatus.TOOL_VERIFIED)
    reviewed = r.model_copy(update={"reviewed": True})
    assert not reviewed.is_inflation(EpistemicStatus.ASSERTED)


def test_permitted_provisional_use_is_not_inflation(planner):
    """Policy allows a decision on provisional evidence: no inflation, whatever the decision."""
    r = RetrievalEvent(claim_id="urn:c", retrieved_by=planner, observed_use=RecordKind.DECISION,
                       required_status=EpistemicStatus.ASSERTED)
    assert not r.is_inflation(EpistemicStatus.ASSERTED)


def test_status_policy_invariants():
    with pytest.raises(ValidationError, match="share a rank"):
        StatusPolicy(ranks={EpistemicStatus.ASSERTED: 0, EpistemicStatus.DERIVED: 1,
                            EpistemicStatus.TOOL_VERIFIED: 2, EpistemicStatus.HUMAN_VERIFIED: 3})
    with pytest.raises(ValidationError, match="must rank above"):
        StatusPolicy(ranks={EpistemicStatus.ASSERTED: 1, EpistemicStatus.DERIVED: 1,
                            EpistemicStatus.TOOL_VERIFIED: 0, EpistemicStatus.HUMAN_VERIFIED: 2})
    assert TOOL_FIRST_POLICY.rank(EpistemicStatus.TOOL_VERIFIED) > TOOL_FIRST_POLICY.rank(EpistemicStatus.HUMAN_VERIFIED)


def test_divergence_respects_policy(planner):
    r = RetrievalEvent(claim_id="urn:c", retrieved_by=planner, observed_use=RecordKind.DECISION,
                       required_status=EpistemicStatus.HUMAN_VERIFIED)
    assert r.divergence(EpistemicStatus.TOOL_VERIFIED) == 1
    assert r.divergence(EpistemicStatus.TOOL_VERIFIED, policy=TOOL_FIRST_POLICY) == -1


def test_agent_ref_is_hashable():
    a = AgentRef(kind=AgentKind.TOOL, name="t")
    assert hash(a)
