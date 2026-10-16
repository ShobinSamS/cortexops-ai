import asyncio
from app.agents import workflow
from app.schemas.contracts import Diagnosis


def finding(evidence_id="real-source"):
    return {"statement": "A possible explanation to validate.", "evidence_ids": [evidence_id], "classification": "hypothesis", "confidence": "medium", "contradictory_evidence_ids": []}


def test_unknown_citations_request_repair_then_are_discarded():
    state = {"evidence": [{"id": "real-source", "source": "knowledge", "title": "Evidence", "content": "Recorded information"}],
             "diagnosis": {"summary": "Unsupported model explanation", "findings": [finding("invented-source")], "recommendations": ["Validate the deployment."], "limitations": []},
             "validation_round": 0, "errors": [], "observations": 1}
    first = asyncio.run(workflow.evidence_validation(state))
    assert first["needs_repair"] is True
    assert "real-source" in first["validation_feedback"]
    second = asyncio.run(workflow.evidence_validation({**state, **first}))
    assert second["needs_repair"] is False
    assert second["diagnosis"]["findings"] == []
    assert "no model-authored hypothesis passed" in second["diagnosis"]["summary"]
    assert any("Discarded" in x for x in second["diagnosis"]["limitations"])


def test_foreign_contradictory_citations_are_not_accepted():
    item = finding()
    item["contradictory_evidence_ids"] = ["foreign-source"]
    state = {"evidence": [{"id": "real-source"}], "diagnosis": {"summary": "Explanation", "findings": [item], "recommendations": [], "limitations": []}, "validation_round": 1}
    assert asyncio.run(workflow.evidence_validation(state))["diagnosis"]["findings"] == []


def test_model_cannot_promote_its_explanation_to_verified(monkeypatch):
    async def local_output(*args, **kwargs):
        item = finding()
        item["classification"] = "verified"
        return Diagnosis(summary="A tentative interpretation", findings=[item], recommendations=["Test the explanation."], limitations=[])
    monkeypatch.setattr(workflow, "structured", local_output)
    result = asyncio.run(workflow.diagnosis({"question": "What changed?", "evidence": [{"id": "real-source", "source": "knowledge", "title": "Evidence", "content": "Untrusted text"}],
                                           "execution_id": "unit-test", "investigation_id": "unit-test", "observations": 1}))
    assert result["diagnosis"]["findings"][0]["classification"] == "hypothesis"


def test_empty_sources_produce_explicit_insufficiency_not_a_cause():
    result = asyncio.run(workflow.diagnosis({"evidence": [], "observations": 0, "errors": []}))
    assert result["diagnosis"]["findings"] == []
    assert "Insufficient evidence" in result["diagnosis"]["summary"]


def test_change_description_uses_the_models_choice_not_a_hardcoded_first_item(monkeypatch):
    async def select_second(schema, *args, **kwargs):
        return schema(primary_change_id="C2", confidence="medium", alternative_change_ids=[], recommendations=["Reproduce with the original setting."], limitations=[])
    monkeypatch.setattr(workflow, "structured", select_second)
    state = {"question": "Which observed change merits validation?", "observations": 2,
             "evidence": [{"id": "source-a", "source": "get_recent_commits", "title": "A", "content": "change A"}, {"id": "source-b", "source": "get_recent_commits", "title": "B", "content": "change B"}],
             "code_changes": [{"id": "C1", "commit": "a", "files": ["alpha.py"], "removed_lines": ["alpha_before"], "added_lines": ["alpha_after"], "evidence_id": "source-a"},
                              {"id": "C2", "commit": "b", "files": ["beta.py"], "removed_lines": ["beta_before"], "added_lines": ["beta_after"], "evidence_id": "source-b"}],
             "execution_id": "unit-test", "investigation_id": "unit-test"}
    result = asyncio.run(workflow.diagnosis(state))["diagnosis"]
    assert "beta_before" in result["summary"] and "beta_after" in result["summary"]
    assert "alpha_before" not in result["summary"]
    assert result["findings"][0]["evidence_ids"] == ["source-b"]
