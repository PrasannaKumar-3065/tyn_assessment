from __future__ import annotations
import argparse, os, sys, time, re
from .jira_client import Jira, JiraError
from .tools import JiraTools
from .agent import run_agent
from .report import write_outputs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Jira release-evidence agent")
    ap.add_argument("--project", required=True)
    ap.add_argument("--label", default="tyn-release-assessment-v2", help="dataset scope label")
    ap.add_argument("--release", required=True)
    ap.add_argument("--model", default=os.environ.get("TYN_MODEL", "gemini-3.8-flash"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-turns", type=int, default=80)
    ap.add_argument("--max-tool-calls", type=int, default=200)
    ap.add_argument("--max-seconds", type=int, default=900)
    a = ap.parse_args(argv)
    out = a.out or f"runs/{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        from google import genai
        client = genai.Client()                  # reads GEMINI_API_KEY or GOOGLE_API_KEY
        jira = Jira.from_env()
    except Exception as e:
        print(f"SETUP FAILED: {e}", file=sys.stderr); return 2
    tools = JiraTools(jira, a.project, a.label, a.release)
    run = run_agent(client, tools, a.model, a.release, a.max_turns, a.max_tool_calls, a.max_seconds)
    target = None
    mf = tools.key_by_sid.get("MANIFEST")
    if mf:
        try:
            d = tools.get_issue("MANIFEST")["description"]
            m = re.search(r"Target: (\{.*?\})", d)
            if m:
                import json; target = json.loads(m.group(1))
        except Exception:
            pass
    md = write_outputs(out, tools, run, jira.base, target)
    print(md.split("\n\n")[1] if "\n\n" in md else md)
    print(f"Report, JSON and trace written to {out}/ ({run['status']})")
    return 0 if run["status"] == "completed" else 3


if __name__ == "__main__":
    sys.exit(main())
