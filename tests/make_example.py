"""Regenerates examples/ from a SCRIPTED (no-model) replay against the offline mock Jira."""
import json, os, sys
sys.path.insert(0, "src"); sys.path.insert(0, "tests")
from tyn_agent import mock_jira
from tyn_agent.jira_client import Jira
from tyn_agent.importer import run_import
from tyn_agent.tools import JiraTools
from tyn_agent.agent import run_agent
from tyn_agent.report import write_outputs
from scripted_model import FakeClient, build_script

ds = json.load(open("inputs/dataset.json"))
srv, st, url = mock_jira.start("TYN"); j = Jira(url, "a", "b")
run_import(j, ds, "TYN", log=lambda *_: None)
t = JiraTools(j, "TYN", ds["dataset_label"], "R2.4")
run = run_agent(FakeClient(build_script(ds)), t, "SCRIPTED-REPLAY (no model)", "R2.4", max_turns=400, max_tool_calls=400)
md = write_outputs("examples/scripted_replay", t, run, "https://YOUR-SITE.atlassian.net", ds["target"])
banner = ("> **SAMPLE ONLY - NOT AGENT OUTPUT.** Produced by a scripted replay of the tool layer against an offline mock "
          "Jira, using an analyst-traced answer key. It shows the report format and verifies the pipeline. The "
          "deliverable report/trace/timings come from `python -m tyn_agent.cli` with a real model (see README). "
          "Token and time figures below are placeholders from the replay.\n\n")
p = "examples/scripted_replay/report.md"
body = open(p).read()
open(p, "w").write(banner + body)
