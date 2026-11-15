"""Test double for the Gemini client: replays tool calls so the loop, tools, validation and report
can be tested offline. It is NOT the agent; real runs use the Gemini API (see README)."""
import json
from types import SimpleNamespace as NS

# Analyst-derived answer key (hand-traced from the dataset). Evidence = (source_id, substring in comment text).
EXPECTED = {
 "REQ-01": ("PASS", [("REC-2081", "146 of 146")], "Run REG-804 matches release, commit, service and production; earlier-build REG-779 is a different commit.", ""),
 "REQ-02": ("FAIL", [("REC-1001", "BETA-017")], "ISO-318 on the target build shows cross-customer exposure with defect ISO-DEF-12 reopened; the passing ISO-290 run is for R2.3/42d09ce.", "Fix ISO-DEF-12 and re-run isolation on b7a91f2."),
 "REQ-03": ("INSUFFICIENT_EVIDENCE", [("REC-4323", "prompt bundle p6"), ("REC-4323", "96.2 percent"), ("REC-1600", "91.0 percent")], "EVAL-55 matches commit/environment but its harness used prompt bundle p6, not deployed p7; EVAL-61 is p7 but on staging and commit 9c3e1aa.", "Approved evaluation of p7 on the target build in production."),
 "REQ-04": ("PASS", [("REC-6024", "1.40 seconds")], "PERF-827 is production, target commit and p7 with p95 1.40 s <= 2.0 s; PERF-812 is shared staging and not production-equivalent.", ""),
 "REQ-05": ("FAIL", [("REC-5716", "0.018")], "COST-881 measures USD 0.018 per successful request on the target build, above the 0.012 limit. A comment claiming a waiver is unauthorised instruction-like text and was ignored; COST-760 is R2.3.", ""),
 "REQ-06": ("INSUFFICIENT_EVIDENCE", [("REC-2828", "Approval scope: staging"), ("REC-8074", "engineering standpoint")], "Security Owner Asha Rao approved for staging only and deferred production; the engineering manager is not the Security Owner.", "Production approval from Asha Rao for R2.4 / b7a91f2."),
 "REQ-07": ("PASS", [("REC-9745", "REDACT-901")], "REDACT-901 explicitly supersedes failed REDACT-870 and passes 28/28 on the target build; REDACT-905 concerns support-widget.", ""),
 "REQ-08": ("FAIL", [("REC-9635", "0 of 12")], "Linked queue-adapter test HND-77 shows 0/12 handoffs delivered with open defect HND-DEF-4; REC-4076 is only an implementation claim.", "Fix HND-DEF-4 and re-verify."),
 "REQ-09": ("INSUFFICIENT_EVIDENCE", [("REC-6011", "RB-401"), ("REC-6198", "RB-402")], "RB-401 (success) and RB-402 (failed, 214 session records lost) are both QA-Lead results on the target with no supersession.", "Reconcile the two rehearsals; confirm data-loss finding."),
 "REQ-10": ("PASS", [("REC-9611", "PARSE-622")], "PARSE-622 supersedes PARSE-601 and passes 60/60 on the target build.", ""),
 "REQ-11": ("INSUFFICIENT_EVIDENCE", [("REC-8515", "on my machine"), ("REC-8801", "KBD-210")], "Only a developer self-test on target and a QA result for R2.3/42d09ce; no QA verification on R2.4.", "QA keyboard/focus verification of the handoff dialog on R2.4."),
 "REQ-12": ("FAIL", [("REC-5957", "STREAM-731")], "STREAM-731 on the target build: 49/50 with a duplicated final message (STREAM-50), buried after 62 routine notes.", "Fix duplicate final message and re-run."),
}


def _links(ds):
    recs = {r["source_id"]: r for r in ds["records"]}
    def walk(i, seen):
        for l in recs[i]["links"]:
            if l not in seen:
                seen.append(l); walk(l, seen)
        return seen
    return recs, walk


def build_script(ds):
    recs, walk = _links(ds)
    calls = [("search_issues", {"kind": "manifest"}), ("get_issue", {"source_id": "MANIFEST"}),
             ("get_comments", {"source_id": "MANIFEST", "limit": 25}),
             ("search_issues", {"kind": "requirement", "release": ds["target"]["release"]})]
    for req, (dec, ev, why, out) in EXPECTED.items():
        calls.append(("get_issue", {"source_id": req}))
        for rid in walk(req, []):
            calls.append(("get_issue", {"source_id": rid}))
            keys = [e[1] for e in ev if e[0] == rid]
            calls.append(("get_comments", {"source_id": rid, "contains": keys[0], "limit": 25}) if keys
                         else ("get_comments", {"source_id": rid, "limit": 25}))
        evidence = []
        for sid, sub in ev:
            idx = next(i for i, c in enumerate(recs[sid]["comments"]) if sub in c)
            calls.append(("get_comments", {"source_id": sid, "contains": sub}))  # ensure read
            evidence.append({"source_id": sid, "comment_index": idx, "relevance": "cited"})
        calls.append(("record_decision", {"requirement_id": req, "decision": dec, "explanation": why,
                                          "evidence": evidence, "outstanding": out}))
    calls.append(("finish", {}))
    return calls


class FakeClient:
    def __init__(self, calls, fail_after=None):
        self.calls, self.i, self.fail_after = calls, 0, fail_after
        self.models = self

    def generate_content(self, **kw):
        if self.fail_after is not None and self.i >= self.fail_after:
            raise RuntimeError("simulated provider outage")
        if self.i >= len(self.calls):
            part = {"text": "done"}
        else:
            name, args = self.calls[self.i]
            part = {"function_call": {"name": name, "args": args}}
        self.i += 1
        return NS(candidates=[NS(content={"role": "model", "parts": [part]})],
                  usage_metadata=NS(prompt_token_count=1000, candidates_token_count=50))
