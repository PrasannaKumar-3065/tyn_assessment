"""Minimal in-memory Jira Cloud v3 look-alike (only the endpoints this project uses).
Lets the importer, tools and agent loop be tested offline and deterministically. Not a Jira replacement."""
from __future__ import annotations
import json, re, threading, itertools
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _adf_text(n):
    if isinstance(n, str): return n
    if not n: return ""
    if n.get("type") == "text": return n.get("text", "")
    k = n.get("content", []) or []
    return ("\n" if n.get("type") == "doc" else "").join(_adf_text(x) for x in k) if n.get("type") == "doc" else "".join(_adf_text(x) for x in k)


class State:
    def __init__(self, project="TYN"):
        self.project, self.issues, self.n, self.cid = project, {}, itertools.count(1), itertools.count(10000)
        self.lock = threading.Lock()


def make_handler(st: State):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _send(self, code, obj=None):
            b = json.dumps(obj).encode() if obj is not None else b""
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

        def _body(self):
            n = int(self.headers.get("Content-Length", 0)); return json.loads(self.rfile.read(n)) if n else {}

        def _issue_json(self, i, fields=None):
            links = []
            for l in i["links"]:
                o = st.issues[l["other"]]
                links.append({("outwardIssue" if l["dir"] == "out" else "inwardIssue"):
                              {"key": o["key"], "fields": {"summary": o["summary"]}}})
            return {"key": i["key"], "fields": {"summary": i["summary"], "labels": i["labels"],
                    "status": {"name": i["status"]}, "description": i["description"], "issuelinks": links}}

        def _match(self, i, jql):
            for m in re.finditer(r'labels = "((?:[^"\\]|\\.)*)"', jql):
                if m.group(1).replace('\\"', '"') not in i["labels"]: return False
            m = re.search(r'project = "([^"]+)"', jql)
            if m and not i["key"].startswith(m.group(1) + "-"): return False
            m = re.search(r'text ~ "((?:[^"\\]|\\.)*)"', jql)
            if m:
                t = m.group(1).lower()
                hay = (i["summary"] + _adf_text(i["description"]) + " ".join(_adf_text(c["body"]) for c in i["comments"])).lower()
                if t not in hay: return False
            return True

        def do_POST(self):
            p, b = self.path, self._body()
            with st.lock:
                if p == "/rest/api/3/issue":
                    f = b["fields"]; key = f"{f['project']['key']}-{next(st.n)}"
                    st.issues[key] = {"key": key, "summary": f["summary"], "labels": f.get("labels", []),
                                      "description": f.get("description"), "status": "To Do", "comments": [], "links": []}
                    return self._send(201, {"key": key})
                if p == "/rest/api/3/search/jql":
                    hits = [i for k, i in sorted(st.issues.items(), key=lambda kv: int(kv[0].split('-')[1])) if self._match(i, b["jql"])]
                    start = int(b.get("nextPageToken") or 0); size = b.get("maxResults", 50)
                    page = hits[start:start + size]; last = start + size >= len(hits)
                    r = {"issues": [self._issue_json(i) for i in page], "isLast": last}
                    if not last: r["nextPageToken"] = str(start + size)
                    return self._send(200, r)
                m = re.match(r"/rest/api/3/issue/([A-Z]+-\d+)/comment$", p)
                if m:
                    c = {"id": str(next(st.cid)), "body": b["body"]}; st.issues[m.group(1)]["comments"].append(c)
                    return self._send(201, {"id": c["id"]})
                if p == "/rest/api/3/issueLink":
                    o, i = b["outwardIssue"]["key"], b["inwardIssue"]["key"]
                    st.issues[o]["links"].append({"other": i, "dir": "out"}); st.issues[i]["links"].append({"other": o, "dir": "in"})
                    return self._send(201)
                m = re.match(r"/rest/api/3/issue/([A-Z]+-\d+)/transitions$", p)
                if m:
                    st.issues[m.group(1)]["status"] = {"11": "To Do", "21": "In Progress", "31": "Done"}[b["transition"]["id"]]
                    return self._send(204)
            self._send(404, {"error": p})

        def do_GET(self):
            path = self.path.split("?")[0]; q = dict(re.findall(r"([^=&]+)=([^&]*)", self.path.split("?", 1)[1])) if "?" in self.path else {}
            with st.lock:
                m = re.match(r"/rest/api/3/issue/([A-Z]+-\d+)$", path)
                if m and m.group(1) in st.issues: return self._send(200, self._issue_json(st.issues[m.group(1)]))
                m = re.match(r"/rest/api/3/issue/([A-Z]+-\d+)/comment$", path)
                if m:
                    cs = st.issues[m.group(1)]["comments"]; s, n = int(q.get("startAt", 0)), int(q.get("maxResults", 50))
                    return self._send(200, {"comments": cs[s:s + n], "total": len(cs), "startAt": s})
                m = re.match(r"/rest/api/3/issue/([A-Z]+-\d+)/transitions$", path)
                if m:
                    return self._send(200, {"transitions": [{"id": "11", "to": {"name": "To Do"}}, {"id": "21", "to": {"name": "In Progress"}}, {"id": "31", "to": {"name": "Done"}}]})
            self._send(404, {"error": path})
    return H


def start(project="TYN"):
    st = State(project)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(st))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, st, f"http://127.0.0.1:{srv.server_address[1]}"
