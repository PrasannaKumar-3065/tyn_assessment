from __future__ import annotations
import json, datetime
from .tools import JiraTools


def _evidence_lines(tools: JiraTools, base_url: str, ev: list[dict]) -> list[str]:
    lines = []
    for e in ev:
        sid, idx = e["source_id"], e["comment_index"]
        c = tools.comments[sid][idx]
        key = tools.key_by_sid[sid]
        url = f"{base_url}/browse/{key}?focusedCommentId={c['comment_id']}" if base_url else key
        who = f"{c['actor']} ({c['role']}), {c['event_time']}" if c["actor"] else "unparsed"
        excerpt = c["text"].split("\n", 1)[-1].replace("\n", " ")
        lines.append(f"- **{sid}** → Jira [{key}]({url}), comment #{idx} (id {c['comment_id']}), recorded by {who}: "
                     f"\"{excerpt[:300]}\"  \n  _Relevance:_ {e.get('relevance', '')}")
    return lines


def render(tools: JiraTools, run: dict, base_url: str, target: dict | None) -> str:
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    reqs = sorted(tools.target_reqs)
    counts = {d: sum(1 for r in reqs if tools.decisions.get(r, {}).get("decision") == d)
              for d in ("PASS", "FAIL", "INSUFFICIENT_EVIDENCE")}
    not_assessed = [r for r in reqs if r not in tools.decisions]
    out = [f"# Release readiness report: {tools.release}", "",
           f"**Overall decision: {tools.overall()}**  ", f"Generated {now} · Jira project `{tools.project}` · "
           f"dataset scope `{tools.label}` · run status: {run['status']}", ""]
    if target:
        out += ["Target: " + ", ".join(f"{k} `{v}`" for k, v in target.items()), ""]
    out += [f"PASS {counts['PASS']} · FAIL {counts['FAIL']} · INSUFFICIENT_EVIDENCE {counts['INSUFFICIENT_EVIDENCE']}"
            + (f" · not assessed {len(not_assessed)}" if not_assessed else ""), "",
            "Rule applied (computed in code): any FAIL → BLOCKED; else any INSUFFICIENT or unassessed → NEEDS_REVIEW; "
            "only all PASS → READY.", "", "| Requirement | Title | Decision |", "|---|---|---|"]
    for r in reqs:
        title = tools.titles.get(r, "") if hasattr(tools, "titles") else ""
        out.append(f"| {r} | {title} | {tools.decisions.get(r, {}).get('decision', 'NOT ASSESSED')} |")
    out.append("")
    for r in reqs:
        d = tools.decisions.get(r)
        out += [f"## {r}: {d['decision'] if d else 'NOT ASSESSED'}", ""]
        if not d:
            out += ["The agent did not reach a decision (see run status). Treated as unresolved.", ""]
            continue
        out += [d["explanation"], ""]
        if d["evidence"]:
            out += ["**Evidence**"] + _evidence_lines(tools, base_url, d["evidence"]) + [""]
        if d["outstanding"]:
            out += [f"**Outstanding verification / clarification:** {d['outstanding']}", ""]
    if tools.flags:
        out += ["## Integrity notes", "",
                "Instruction-like text aimed at reviewers was found inside ticket comments. It was treated as untrusted "
                "data and did not affect any decision:", ""]
        for f in tools.flags:
            out.append(f"- {f['source_id']} comment #{f['comment_index']} (written as {f['actor']}): \"{f['excerpt']}\"")
        out.append("")
    u = run["usage"]
    out += ["## Run metrics", "",
            f"- Model: `{run['model']}` · model calls {u['calls']} · tool calls {run['tool_calls']}",
            f"- Tokens: {u['input_tokens']:,} input / {u['output_tokens']:,} output",
            f"- Wall time: {run['seconds']} s"]
    for e in run["errors"]:
        out.append(f"- ERROR: {e}")
    out.append("")
    return "\n".join(out)


def write_outputs(out_dir: str, tools: JiraTools, run: dict, base_url: str, target: dict | None):
    import os
    os.makedirs(out_dir, exist_ok=True)
    md = render(tools, run, base_url, target)
    open(f"{out_dir}/report.md", "w", encoding="utf-8").write(md)
    json.dump({"overall": tools.overall(), "decisions": tools.decisions, "revised_decisions": tools.decision_history,
               "integrity_flags": tools.flags, "run": {k: v for k, v in run.items() if k != "trace"}},
              open(f"{out_dir}/report.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    with open(f"{out_dir}/trace.jsonl", "w", encoding="utf-8") as f:
        for t in run["trace"]:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    return md
