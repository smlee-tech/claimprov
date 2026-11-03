import pytest

from claimprov import AgentKind, AgentRef, Evidence, EvidenceKind, Verification, VerificationOutcome


@pytest.fixture
def analyst() -> AgentRef:
    return AgentRef(id="urn:claimprov:agent:analyst", kind=AgentKind.LLM_AGENT,
                    name="analysis-agent", model="claude-sonnet-4-5")


@pytest.fixture
def planner() -> AgentRef:
    return AgentRef(id="urn:claimprov:agent:planner", kind=AgentKind.LLM_AGENT,
                    name="planning-agent", model="claude-sonnet-4-5")


@pytest.fixture
def sql_tool() -> AgentRef:
    return AgentRef(id="urn:claimprov:agent:duckdb", kind=AgentKind.TOOL, name="duckdb-recount", version="1.1")


@pytest.fixture
def reviewer() -> AgentRef:
    return AgentRef(id="urn:claimprov:agent:jane", kind=AgentKind.HUMAN, name="J. Doe (supply planner)")


@pytest.fixture
def dataset_evidence() -> Evidence:
    return Evidence(kind=EvidenceKind.DATASET, source="kaggle:dataco-supply-chain/orders.csv",
                    content_hash="sha256:abc", license="CC0-1.0", excerpt="rows 1-12,430")


def passed_by(agent: AgentRef, evidence: Evidence, method: str = "recount") -> Verification:
    return Verification(verifier=agent, method=method, outcome=VerificationOutcome.PASSED, evidence=[evidence])
