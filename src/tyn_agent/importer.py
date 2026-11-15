"""Repeatable, idempotent importer: dataset.json -> dedicated Jira project.

Preserves for every record: source id (summary prefix "[REC-1234]", label src-<id>, first description line),
kind (label rr-<kind>), release (label rel-<release>), recorded status (transition + description line),
all comments VERBATIM and in file order (scenario actor/role/timestamp stay in the text), and links.
Re-running skips records that already exist (matched by label src-<id>), and only adds missing comments/links.
"""
from __future__ import annotations
import argparse, json, sys
from .jira_client import Jira, JiraError, adf_from_text, SRC_RE

KIND_TYPE = {"requirement": "Task", "evidence": "Task", "work": "Task", "manifest": "Task"}


def jql_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def existing_map(jira: Jira, project: str, label: str) -> dict[str, str]:
    issues = jira.search(f"project = {jql_str(project)} AND labels = {jql_str(label)} ORDER BY key ASC",
                         ["summary"], limit=5000)
    m = {}
    for i in issues:
        mm = SRC_RE.match(i["fields"]["summary"])
        if mm:
            m[mm.group(1)] = i["key"]
    return m


def run_import(jira: Jira, dataset: dict, project: str, issue_type: str = "Task", log=print) -> dict:
    label = dataset["dataset_label"]
    recs = dataset["records"]
    ids = {r["source_id"] for r in recs}
    keys = existing_map(jira, project, label)
    stats = dict(created=0, skipped=0, comments=0, links=0, status_failed=[], dangling_links=[])

    for r in recs:
        sid = r["source_id"]
        if sid in keys:
            stats["skipped"] += 1
            continue
        desc = (f"Source ID: {sid}\nSource kind: {r['kind']}\nSource release: {r['release']}\n"
                f"Recorded status: {r['recorded_status']}\n\n{r['description']}")
        fields = {
            "project": {"key": project},
            "issuetype": {"name": issue_type},
            "summary": f"[{sid}] {r['summary']}"[:250],
            "description": adf_from_text(desc),
            "labels": [label, f"src-{sid}", f"rr-{r['kind']}", f"rel-{r['release']}"],
        }
        keys[sid] = jira.create_issue(fields)
        stats["created"] += 1
        # Comments are written only for freshly created issues (keeps re-runs duplicate-free).
        for c in r["comments"]:
            jira.add_comment(keys[sid], c)
            stats["comments"] += 1
        if r["recorded_status"] != "To Do" and not jira.transition_to(keys[sid], r["recorded_status"]):
            stats["status_failed"].append((sid, r["recorded_status"]))
        if stats["created"] % 25 == 0:
            log(f"  imported {stats['created']}/{len(recs)}")

    # Links last, once every issue exists. Skip ones already present.
    for r in recs:
        src = keys[r["source_id"]]
        have = {l.get("outwardIssue", {}).get("key") for l in
                jira.get_issue(src, "issuelinks")["fields"].get("issuelinks", [])}
        for tgt in r["links"]:
            if tgt not in ids:
                stats["dangling_links"].append((r["source_id"], tgt))
                continue
            if keys[tgt] in have:
                continue
            jira.link(src, keys[tgt])
            stats["links"] += 1
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description="Import the TYN dataset into a Jira Cloud project")
    ap.add_argument("--dataset", default="inputs/dataset.json")
    ap.add_argument("--project", required=True, help="Jira project key (dedicated project)")
    ap.add_argument("--issue-type", default="Task")
    a = ap.parse_args(argv)
    with open(a.dataset, encoding="utf-8") as f:
        ds = json.load(f)
    try:
        st = run_import(Jira.from_env(), ds, a.project, a.issue_type)
    except JiraError as e:
        print(f"IMPORT FAILED: {e}\nRe-run the same command to resume; it is idempotent.", file=sys.stderr)
        return 1
    print(json.dumps(st, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
