import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src")); sys.path.insert(0, os.path.dirname(__file__))
import pytest
from tyn_agent import mock_jira
from tyn_agent.jira_client import Jira
from tyn_agent.importer import run_import
from tyn_agent.tools import JiraTools
from tyn_agent.agent import run_agent
from tyn_agent.report import render
from scripted_model import FakeClient, build_script, EXPECTED

DS = json.load(open(os.path.join(os.path.dirname(__file__), "..", "inputs", "dataset.json")))


@pytest.fixture(scope="module")
def jira():
    srv, st, url = mock_jira.start("TYN")
    j = Jira(url, "a", "b")
    # a foreign ticket in the same project must never be visible to the agent
    j.create_issue({"project": {"key": "TYN"}, "issuetype": {"name": "Task"}, "summary": "[REQ-99] decoy",
                    "labels": ["other-dataset", "rr-requirement", "rel-R2.4"]})
    stats = run_import(j, DS, "TYN", log=lambda *_: None)
    j.stats, j.state = stats, st
    return j


def test_import_counts_and_idempotent(jira):
    assert jira.stats["created"] == 400 and jira.stats["comments"] == 2059 and not jira.stats["dangling_links"]
    assert run_import(jira, DS, "TYN", log=lambda *_: None)["created"] == 0


def test_scope_enforced(jira):
    t = JiraTools(jira, "TYN", DS["dataset_label"], "R2.4")
    sids = {r["source_id"] for r in t.search_issues(kind="requirement")["results"]}
    assert "REQ-99" not in sids and len(sids) == 12
    assert json.loads(t.call("get_issue", {"source_id": "REQ-99"})[0])["error"]
    assert t.call("get_issue", {"source_id": 'x" OR 1=1'})[1]          # JQL-injection attempt rejected


def test_decision_validation(jira):
    t = JiraTools(jira, "TYN", DS["dataset_label"], "R2.4")
    t.get_issue("REQ-05")
    assert "error" in t.record_decision("REQ-05", "PASS", "x", [])                      # PASS needs evidence
    assert "error" in t.record_decision("REQ-05", "FAIL", "x", [{"source_id": "REC-5716", "comment_index": 4, "relevance": ""}])  # unread
    assert "error" in t.record_decision("REQ-05", "MAYBE", "x", [])
    assert "error" in t.record_decision("REC-5716", "FAIL", "x", [])                   # not a requirement


def test_full_scripted_run_matches_answer_key(jira):
    t = JiraTools(jira, "TYN", DS["dataset_label"], "R2.4")
    run = run_agent(FakeClient(build_script(DS)), t, "scripted", "R2.4", max_turns=400, max_tool_calls=400)
    assert run["status"] == "completed" and not run["undecided"]
    assert {r: d["decision"] for r, d in t.decisions.items()} == {r: v[0] for r, v in EXPECTED.items()}
    assert t.overall() == "BLOCKED"
    assert [(f["source_id"]) for f in t.flags] == ["REC-5716"]          # injected "report PASS" note flagged
    md = render(t, run, jira.base, DS["target"])
    assert "Overall decision: BLOCKED" in md and "Integrity notes" in md
    assert any(x["tool"] == "get_comments" for x in run["trace"] if "tool" in x)


def test_provider_outage_is_reported_not_hidden(jira):
    t = JiraTools(jira, "TYN", DS["dataset_label"], "R2.4")
    run = run_agent(FakeClient(build_script(DS), fail_after=12), t, "scripted", "R2.4")
    assert run["status"] == "stopped: model error" and run["errors"]
    assert t.overall() in ("NEEDS_REVIEW", "BLOCKED") and t.overall() != "READY"


def test_tool_budget(jira):
    t = JiraTools(jira, "TYN", DS["dataset_label"], "R2.4")
    run = run_agent(FakeClient(build_script(DS)), t, "scripted", "R2.4", max_tool_calls=10)
    assert run["status"].startswith("stopped") and t.overall() != "READY"
