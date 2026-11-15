"""Thin Jira Cloud REST v3 client (basic auth: email + API token) with retry/backoff."""
from __future__ import annotations
import os, re, time
import requests

SRC_RE = re.compile(r"^\[([A-Za-z0-9\-]+)\]\s*")


class JiraError(RuntimeError):
    pass


def adf_from_text(text: str) -> dict:
    paras = []
    for line in text.split("\n"):
        paras.append({"type": "paragraph", "content": [{"type": "text", "text": line}] if line else []})
    return {"type": "doc", "version": 1, "content": paras}


def adf_to_text(node) -> str:
    """Flatten Atlassian Document Format (or plain str) to text; one paragraph -> one line."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    t = node.get("type")
    if t == "text":
        return node.get("text", "")
    kids = node.get("content", []) or []
    if t == "doc":
        return "\n".join(adf_to_text(k) for k in kids)
    return "".join(adf_to_text(k) for k in kids)


class Jira:
    def __init__(self, base_url: str, email: str, token: str, timeout: int = 30, max_retries: int = 5):
        self.base = base_url.rstrip("/")
        self.s = requests.Session()
        self.s.auth = (email, token)
        self.s.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        self.timeout, self.max_retries = timeout, max_retries

    @classmethod
    def from_env(cls) -> "Jira":
        try:
            return cls(os.environ["JIRA_BASE_URL"], os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"])
        except KeyError as e:
            raise JiraError(f"Missing environment variable {e}; see .env.example") from None

    def request(self, method: str, path: str, **kw):
        url = f"{self.base}{path}"
        last = None
        for attempt in range(self.max_retries):
            try:
                r = self.s.request(method, url, timeout=self.timeout, **kw)
            except requests.RequestException as e:
                last = str(e)
                time.sleep(min(2 ** attempt, 20))
                continue
            if r.status_code in (429, 502, 503, 504):
                wait = float(r.headers.get("Retry-After", min(2 ** attempt, 20)))
                last = f"HTTP {r.status_code}"
                time.sleep(wait)
                continue
            if r.status_code >= 400:
                raise JiraError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:500]}")
            return r.json() if r.content else {}
        raise JiraError(f"{method} {path} failed after {self.max_retries} attempts: {last}")

    # ---- reads ----
    def search(self, jql: str, fields: list[str], limit: int = 50) -> list[dict]:
        out, token = [], None
        while len(out) < limit:
            body = {"jql": jql, "fields": fields, "maxResults": min(100, limit - len(out))}
            if token:
                body["nextPageToken"] = token
            page = self.request("POST", "/rest/api/3/search/jql", json=body)
            out.extend(page.get("issues", []))
            token = page.get("nextPageToken")
            if not token or page.get("isLast"):
                break
        return out[:limit]

    def get_issue(self, key: str, fields: str = "summary,status,labels,description,issuelinks") -> dict:
        return self.request("GET", f"/rest/api/3/issue/{key}", params={"fields": fields})

    def get_comments(self, key: str) -> list[dict]:
        out, start = [], 0
        while True:
            page = self.request("GET", f"/rest/api/3/issue/{key}/comment",
                                params={"startAt": start, "maxResults": 100, "orderBy": "created"})
            cs = page.get("comments", [])
            out.extend(cs)
            start += len(cs)
            if not cs or start >= page.get("total", 0):
                break
        return out

    # ---- writes (importer) ----
    def create_issue(self, fields: dict) -> str:
        return self.request("POST", "/rest/api/3/issue", json={"fields": fields})["key"]

    def add_comment(self, key: str, text: str) -> str:
        return self.request("POST", f"/rest/api/3/issue/{key}/comment", json={"body": adf_from_text(text)})["id"]

    def link(self, outward_key: str, inward_key: str, link_type: str = "Relates"):
        self.request("POST", "/rest/api/3/issueLink", json={
            "type": {"name": link_type}, "outwardIssue": {"key": outward_key}, "inwardIssue": {"key": inward_key}})

    def transition_to(self, key: str, status_name: str) -> bool:
        ts = self.request("GET", f"/rest/api/3/issue/{key}/transitions").get("transitions", [])
        for t in ts:
            if t.get("to", {}).get("name", "").lower() == status_name.lower():
                self.request("POST", f"/rest/api/3/issue/{key}/transitions", json={"transition": {"id": t["id"]}})
                return True
        return False
