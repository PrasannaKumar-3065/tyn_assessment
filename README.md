# Jira Release Evidence Agent

A tool-using agent that decides whether the requirements of a release (here `atlas-assistant` R2.4) are satisfied by
evidence recorded in Jira, and writes one evidence-backed report. Python 3.12, Gemini API, Jira Cloud REST v3.

## Status of this submission (read first)
* Importer, tools, agent loop and report renderer are implemented and tested offline (`pytest`: 6 tests) against a
  mock Jira that mirrors the endpoints used. Import counts match the dataset: 400 issues, 2,059 comments, 76 links.
* **The agent has not been run against a live Jira site or a live model by the author of this code**, because that needs
  your Jira Cloud site and API keys. So there is no real agent report, trace, timing or token figure yet. Run step 3 to
  produce them; the files land in `runs/<timestamp>/`.
* `examples/scripted_replay/` shows the report format. It is a scripted replay of the tool layer using a hand-traced answer
  key and is labelled as such. Do not submit it as agent output.

## Setup
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in, then: set -a; source .env; set +a
```
Set `GEMINI_API_KEY` in `.env` to a Google AI Studio API key. The default model is `gemini-3.8-flash`;
override it with `TYN_MODEL` or `--model`.
1. Create a dedicated Jira Cloud project (e.g. key `TYN`; Task issue type; Relates link type; To Do / In Progress / Done
   workflow, the default Scrum/Kanban template works).
2. Import (idempotent; re-run to resume after a failure):
   `PYTHONPATH=src python -m tyn_agent.importer --project TYN --dataset inputs/dataset.json`
3. Assess:
   `PYTHONPATH=src python -m tyn_agent.cli --project TYN --label tyn-release-assessment-v2 --release R2.4`
   Outputs: `report.md`, `report.json`, `trace.jsonl` (every tool call, args, result size/preview, timings),
   plus tokens, model calls and wall time inside the report's *Run metrics* section.
4. Tests (offline): `python -m pytest tests -q`

## What the importer preserves
Source id (summary prefix `[REC-1234]`, label `src-REC-1234`, first description line), kind (`rr-<kind>`; the manifest
says requirements are labelled `rr-requirement`), release (`rel-R2.4`), dataset scope label (applied to every issue),
recorded status (transition + description line), links, and every comment **verbatim in file order**, so scenario
actor, role and recorded timestamps remain in the text. Native Jira authors and timestamps are the importer's and the
agent never uses them as evidence.

## Design
* **Model chooses actions.** Tools: `search_issues`, `get_issue`, `get_comments` (paginated, `contains` filter),
  `record_decision`, `finish`. No dataset JSON is ever sent to the model; it reads Jira only through these tools.
* **Policy lives in Jira.** The prompt gives method only; target (commit, prompt, environment, service) and decision
  rules are read from the manifest ticket by the model.
* **Guarantees enforced in code, not prompt:** all queries are forced into project + dataset label; source ids are
  validated against JQL injection; a decision may only cite comments that were actually fetched; PASS/FAIL need
  evidence; the overall BLOCKED / NEEDS_REVIEW / READY verdict is computed in code from the decisions; requirements
  left undecided are reported as not assessed, never silently passed.
* **Context management:** tool output is capped (8 KB, 1.5 KB per comment), comments paginate and filter (one ticket
  has 64 mostly-routine comments), and old tool results are pruned to stubs after 10 tool-result turns.
* **Untrusted data:** ticket text is data. A heuristic flags instruction-like text aimed at reviewers; the model is told
  to ignore it, and flagged comments are listed under *Integrity notes* in the report. In the supplied dataset, REC-5716
  contains such a note (claiming a cost waiver and asking not to be mentioned); it is reported, not obeyed.
* **Bounds and failures:** turn, tool-call and wall-clock budgets; Jira calls retry with backoff on 429/5xx; any
  model/tool failure ends in a report that states the failure, lists undecided requirements and cannot yield READY.

## Known limits
* Injection detection is a regex heuristic; the real defence is the prompt plus code-enforced evidence rules.
* Evidence validation proves a cited comment was read, not that it supports the claim; correctness of the reasoning
  rests on the model. A second-pass verifier model would be the next step.
* One requirement set per run; target release is an argument, other target fields come from the manifest.
* The mock Jira is minimal (not full JQL). Status transitions assume workflow names To Do / In Progress / Done;
  failures are returned in the importer summary (`status_failed`).
* Run-to-run variation is possible even at temperature 0; compare `report.json` across runs.

## AI assistance
The runtime agent uses Gemini for its tool-enabled Jira assessment loop. The offline tests use a scripted model and
require no model API key.
