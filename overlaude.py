"""overlaude: two-way sync between a local folder and an Overleaf project.

Local edits go up through Overleaf's live editing channel (Socket.IO 0.9 + ShareJS ops), so
history shows them as real edits and collaborators see them typed in. Collaborators' edits
are 3-way merged into the local files.
"""

import argparse
import difflib
import getpass
import hashlib
import json
import os
import re
import sys
import time
from fnmatch import fnmatch
from pathlib import Path

import requests
import websocket
from diff_match_patch import diff_match_patch
from merge3 import Merge3

BASE = os.environ.get("OVERLEAF_URL", "https://www.overleaf.com").rstrip("/")
HOME = Path(os.environ.get("OVERLAUDE_HOME", Path.home() / ".overlaude"))
COOKIE_FILE = HOME / "cookie"
AGENT_FILES = {"CLAUDE.md", "AGENTS.md", "GEMINI.md"}
# Never uploaded as new files (tracked remote files are always synced). Extend with .olignore.
IGNORE = [".*", "*.aux", "*.log", "*.out", "*.toc", "*.lof", "*.lot", "*.bbl", "*.blg", "*.bcf",
          "*.run.xml", "*.fls", "*.fdb_latexmk", "*.synctex.gz", "*.nav", "*.snm", "*.pyc",
          "__pycache__", "*.orig", *AGENT_FILES]
CONFLICT = re.compile(r"^<<<<<<< local$", re.M)


def unsafe(rel):
    """Remote paths a collaborator could use to plant tool config (.claude/, .latexmkrc, ...) or escape the folder."""
    parts = rel.split("/")
    return "\\" in rel or any(p in ("", ".", "..") or p.startswith(".") or p in AGENT_FILES for p in parts)

dmp = diff_match_patch()
dmp.Match_Threshold = 0.0  # merge patches only onto exactly matching context, never fuzzily
dmp.Patch_DeleteThreshold = 0.0


def die(msg):
    sys.exit(f"ol: {msg}")


# -- text ------------------------------------------------------------------
def u16(s):
    return len(s.encode("utf-16-le")) // 2  # ShareJS positions are JS (UTF-16) string offsets


def to_op(old, new):
    """ShareJS op turning `old` into `new`, as a minimal character diff."""
    diffs = dmp.diff_main(old, new)
    dmp.diff_cleanupSemantic(diffs)
    op, p = [], 0
    for kind, text in diffs:
        if kind == 0:
            p += u16(text)
        elif kind < 0:
            op.append({"p": p, "d": text})
        else:
            op.append({"p": p, "i": text})
            p += u16(text)
    return op


def merge(base, local, remote):
    """3-way merge -> (text, conflicted). Character-level first, then line-level with markers."""
    if local in (base, remote):
        return remote, False
    if remote == base:
        return local, False
    if base is not None:
        text, ok = dmp.patch_apply(dmp.patch_make(base, local), remote)
        if all(ok):
            return text, False
    lines = Merge3((base or "").splitlines(True), local.splitlines(True), remote.splitlines(True))
    return "".join(lines.merge_lines("local", "overleaf")), True


def sha(path):
    return hashlib.sha1(path.read_bytes()).hexdigest()


# -- http --------------------------------------------------------------------
def session():
    raw = os.environ.get("OVERLEAF_COOKIE") or (COOKIE_FILE.read_text().strip() if COOKIE_FILE.exists() else "")
    if not raw:
        die("not logged in; run `ol login`")
    name, _, value = raw.partition("=") if "=" in raw else ("overleaf_session2", "", raw)
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (overlaude)"
    s.cookies.set(name.strip(), value.strip())
    return s


def csrf(s, path):
    r = s.get(BASE + path)
    m = re.search(r'name="ol-csrfToken"\s+content="([^"]+)"', r.text)
    if not m or "/login" in r.url:
        die("Overleaf session invalid or expired; run `ol login`")
    s.headers["X-Csrf-Token"] = m.group(1)


def ok(r):
    if r.status_code >= 400:
        die(f"{r.request.method} {r.url} failed ({r.status_code}): {r.text[:200]}")
    return r


def projects(s):
    csrf(s, "/project")
    return ok(s.post(BASE + "/api/project", json={})).json()["projects"]


def resolve_project(s, ref):
    if m := re.search(r"\b[0-9a-f]{24}\b", ref):
        return m.group(0), None
    ps = [p for p in projects(s) if not p.get("trashed")]
    hits = [p for p in ps if p["name"] == ref] or [p for p in ps if p["name"].lower() == ref.lower()]
    if len(hits) != 1:
        die(f"{len(hits)} projects named {ref!r}; pass the project id or URL")
    return hits[0]["id"], hits[0]["name"]


# -- realtime -----------------------------------------------------------------
class Realtime:
    def __init__(self, s, pid):
        r = s.get(f"{BASE}/socket.io/1/", params={"projectId": pid, "esh": 1, "ssp": 1, "t": int(time.time() * 1000)})
        if r.status_code != 200 or r.text.count(":") < 3:
            die(f"realtime handshake rejected ({r.status_code}); run `ol login`")
        sid = r.text.split(":")[0]
        cookie = "; ".join(f"{c.name}={c.value}" for c in s.cookies)  # includes the GCLB affinity cookie
        url = f"{BASE.replace('http', 'ws', 1)}/socket.io/1/websocket/{sid}?projectId={pid}&esh=1&ssp=1"
        self.ws = websocket.create_connection(url, header=[f"Cookie: {cookie}", f"User-Agent: {s.headers['User-Agent']}"], origin=BASE, timeout=60)
        self.n, self.events = 0, []
        self.project = self.wait("joinProjectResponse")[0]["project"]

    def recv(self):
        while True:
            frame = self.ws.recv()
            kind, _, rest = frame.partition(":")
            if kind == "2":
                self.ws.send("2::")
            elif kind == "5":
                ev = json.loads(rest.split(":", 2)[2])
                name, args = ev["name"], ev.get("args", [])
                if name == "serverPing":
                    self.ws.send("5:::" + json.dumps({"name": "clientPong", "args": args}))
                elif name in ("otUpdateError", "connectionRejected", "forceDisconnect"):
                    die(f"Overleaf: {name} {args}")
                else:
                    return "event", name, args
            elif kind == "6":
                ack_id, _, data = rest.split(":", 2)[2].partition("+")
                return "ack", int(ack_id), json.loads(data) if data else []
            elif kind in ("0", "7"):
                die(f"realtime connection closed: {frame}")

    def call(self, name, *args):
        self.n += 1
        self.ws.send(f"5:{self.n}+::" + json.dumps({"name": name, "args": list(args)}, ensure_ascii=False))
        while True:
            kind, a, b = self.recv()
            if kind == "event":
                self.events.append((a, b))
            elif a == self.n:
                if b and b[0]:
                    die(f"{name} failed: {b[0]}")
                return b

    def wait(self, name, match=lambda args: True):
        for i, (n, args) in enumerate(self.events):
            if n == name and match(args):
                return self.events.pop(i)[1]
        while True:
            kind, a, b = self.recv()
            if kind == "event":
                if a == name and match(b):
                    return b
                self.events.append((a, b))

    def join(self, doc_id):
        ack = self.call("joinDoc", doc_id, {"encodeRanges": True})
        # lines arrive as a byte-view (one UTF-8 byte per code unit)
        return "\n".join(line.encode("latin-1").decode("utf-8") for line in ack[1]), ack[2]

    def edit(self, doc_id, op, version):
        self.call("applyOtUpdate", doc_id, {"doc": doc_id, "op": op, "v": version})
        # the ack only means "queued"; an op-less otUpdateApplied means applied
        self.wait("otUpdateApplied", lambda a: a and a[0].get("doc") == doc_id and "op" not in a[0])


def tree(project):
    docs, files, folders = {}, {}, {}

    def walk(folder, prefix):
        folders[prefix.rstrip("/")] = folder["_id"]
        docs.update({prefix + d["name"]: d["_id"] for d in folder.get("docs", [])})
        files.update({prefix + f["name"]: f["_id"] for f in folder.get("fileRefs", [])})
        for sub in folder.get("folders", []):
            walk(sub, prefix + sub["name"] + "/")

    walk(project["rootFolder"][0], "")
    return docs, files, folders


# -- sync ---------------------------------------------------------------------
def find_root():
    for d in [Path.cwd(), *Path.cwd().parents]:
        if (d / ".ol/state.json").exists():
            return d
    die("not inside an overlaude folder; run `ol clone <project>` first")


def load(root):
    return json.loads((root / ".ol/state.json").read_text())


def save(root, st):
    tmp = root / ".ol/state.json.tmp"
    tmp.write_text(json.dumps(st, indent=1, ensure_ascii=False))
    tmp.replace(root / ".ol/state.json")


def local_files(root):
    ignore = IGNORE + [l.strip() for l in (root / ".olignore").read_text().splitlines()
                       if l.strip() and not l.startswith("#")] if (root / ".olignore").exists() else IGNORE
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not any(fnmatch(d, g) for g in ignore)]
        for f in filenames:
            rel = (Path(dirpath) / f).relative_to(root).as_posix()
            if not any(fnmatch(f, g) or fnmatch(rel, g) for g in ignore):
                out.append(rel)
    return out


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8", newline="")
    else:
        path.write_bytes(data)


def sync(root, allow_delete=False):
    st = load(root)
    pid, bdocs, bfiles = st["project"], st["docs"], st["files"]
    s = session()
    csrf(s, f"/project/{pid}")
    rt = Realtime(s, pid)
    docs, files, folders = tree(rt.project)
    first = not bdocs and not bfiles
    log = lambda tag, path: print(f"{tag:>9}  {path}")
    for table in (docs, files):
        for rel in [r for r in table if unsafe(r)]:
            del table[rel]
            log("SKIPPED", f"{rel} (dotfile, agent config, or unsafe path; never written locally)")

    def folder_id(rel):
        parent = rel.rpartition("/")[0]
        if parent not in folders:
            pparent, _, name = parent.rpartition("/")
            folder_id(parent)  # creates the grandparent first if needed
            r = ok(s.post(f"{BASE}/project/{pid}/folder", json={"name": name, "parent_folder_id": folders[pparent]}))
            folders[parent] = r.json()["_id"]
        return folders[parent]

    def upload(rel):
        p = root / rel
        r = ok(s.post(f"{BASE}/project/{pid}/upload", params={"folder_id": folder_id(rel)},
                      data={"relativePath": "null", "name": p.name}, files={"qqfile": (p.name, p.read_bytes())})).json()
        if not r.get("success"):
            die(f"upload of {rel} failed: {r}")
        if r["entity_type"] == "doc":  # Overleaf turns text files into editable docs
            bdocs[rel] = p.read_text(encoding="utf-8")
        else:
            bfiles[rel] = {"id": r["entity_id"], "sha": sha(p)}
        log("uploaded", rel)

    def remove_remote(rel, kind, eid):
        if not allow_delete:
            log("KEPT", f"{rel} (deleted locally; rerun with --delete to delete it on Overleaf)")
            return
        ok(s.delete(f"{BASE}/project/{pid}/{kind}/{eid}"))
        (bdocs if kind == "doc" else bfiles).pop(rel, None)
        log("deleted", f"{rel} (on Overleaf)")

    for rel, did in docs.items():
        p, base = root / rel, bdocs.get(rel)
        remote, version = rt.join(did)
        if not p.exists() and base is not None:
            if remote == base:
                remove_remote(rel, "doc", did)
                continue
            log("RESTORED", f"{rel} (you deleted it, but a collaborator edited it)")
        local = p.read_text(encoding="utf-8") if p.exists() else None
        if local is None:
            write(p, remote)
            bdocs[rel] = remote
            log("pulled", rel)
            continue
        if CONFLICT.search(local):
            log("CONFLICT", f"{rel} still has <<<<<<< markers; resolve them, then sync again")
            continue
        if base is not None and remote != base and not first:
            print("".join(difflib.unified_diff(base.splitlines(True), remote.splitlines(True), f"a/{rel}", f"b/{rel} (overleaf)")))
        text, conflicted = merge(base, local, remote)
        if conflicted:
            write(p, text)
            bdocs[rel] = remote  # once resolved, the file diffs against what is on Overleaf
            log("CONFLICT", f"{rel}: overlapping edits marked with <<<<<<< local / >>>>>>> overleaf")
            continue
        if text != remote:
            rt.edit(did, to_op(remote, text), version)
            log("pushed", rel)
        elif remote != base:
            log("pulled", rel)
        if text != local:
            write(p, text)
        bdocs[rel] = text

    for rel, fid in files.items():
        p, base = root / rel, bfiles.get(rel)
        if not p.exists():
            if base and base["id"] == fid:
                remove_remote(rel, "file", fid)
                continue
            write(p, ok(s.get(f"{BASE}/project/{pid}/file/{fid}")).content)
            bfiles[rel] = {"id": fid, "sha": sha(p)}
            log("pulled", rel)
            continue
        lsha = sha(p)
        if base is None:
            data = ok(s.get(f"{BASE}/project/{pid}/file/{fid}")).content
            if hashlib.sha1(data).hexdigest() == lsha:
                bfiles[rel] = {"id": fid, "sha": lsha}
            else:
                log("CONFLICT", f"{rel}: differs from Overleaf's copy; left both alone")
            continue
        mine, theirs = lsha != base["sha"], fid != base["id"]
        if mine and theirs:
            log("CONFLICT", f"{rel}: replaced both locally and on Overleaf; left both alone")
        elif mine:
            upload(rel)
        elif theirs:
            write(p, ok(s.get(f"{BASE}/project/{pid}/file/{fid}")).content)
            bfiles[rel] = {"id": fid, "sha": sha(p)}
            log("pulled", rel)

    # deleted on Overleaf
    for table, remote in ((bdocs, docs), (bfiles, files)):
        for rel in [r for r in table if r not in remote]:
            p, base = root / rel, table.pop(rel)
            unchanged = p.exists() and (p.read_text(encoding="utf-8") == base if table is bdocs else sha(p) == base["sha"])
            if unchanged:
                p.unlink()
                log("removed", f"{rel} (deleted on Overleaf)")
            elif p.exists():
                log("KEPT", f"{rel} (deleted on Overleaf, but you changed it; it will be re-uploaded)")

    for rel in local_files(root):
        if rel not in docs and rel not in files and rel not in bdocs and rel not in bfiles:
            upload(rel)

    save(root, st)
    rt.ws.close()


# -- compile --------------------------------------------------------------------
def compile_(root):
    pid = load(root)["project"]
    s = session()
    csrf(s, f"/project/{pid}")
    r = ok(s.post(f"{BASE}/project/{pid}/compile", params={"auto_compile": "true"}, timeout=300,
                  json={"rootDoc_id": None, "draft": False, "check": "silent", "incrementalCompilesEnabled": True})).json()
    for f in r.get("outputFiles", []):
        if f["path"] in ("output.pdf", "output.log"):
            data = ok(s.get(BASE + f["url"], params={"clsiserverid": r.get("clsiServerId")})).content
            write(root / ".ol" / f["path"], data)
    lines = (root / ".ol/output.log").read_text(errors="replace").splitlines() if (root / ".ol/output.log").exists() else []
    for i, line in enumerate(lines):
        if line.startswith("!"):
            where = next((l for l in lines[i + 1:i + 8] if re.match(r"l\.\d+", l)), "")
            print(f"error: {line[1:].strip()}  {where}")
        elif re.search(r"Warning: (Reference|Citation) .* undefined", line):
            print(f"warning: {line.strip()}")
    print(f"status: {r.get('status')}  pdf: .ol/output.pdf  log: .ol/output.log")


# -- cli ---------------------------------------------------------------------------
def login(cookie):
    if not cookie:
        try:
            import browser_cookie3
            host = BASE.split("//")[1]
            cookie = next(f"{c.name}={c.value}" for c in browser_cookie3.load(domain_name=host.removeprefix("www."))
                          if c.name in ("overleaf_session2", "overleaf.sid", "sharelatex.sid"))
            print("found an Overleaf session in your browser")
        except Exception:
            if not sys.stdin.isatty():
                die("no Overleaf session found in your browsers, and no terminal to paste a cookie into; "
                    "run `ol login` in a terminal")
            print(f"Open {BASE}, sign in, then DevTools > Application > Cookies > copy `overleaf_session2`.")
            cookie = getpass.getpass("cookie value: ").strip()
    os.environ["OVERLEAF_COOKIE"] = cookie
    csrf(session(), "/project")  # dies if the cookie does not work
    HOME.mkdir(mode=0o700, exist_ok=True)
    COOKIE_FILE.touch(mode=0o600)
    COOKIE_FILE.write_text(cookie)
    print(f"logged in; session saved to {COOKIE_FILE}")


def main():
    ap = argparse.ArgumentParser(prog="ol", description="Two-way sync between a local folder and an Overleaf project.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="save your Overleaf session cookie").add_argument("cookie", nargs="?")
    sub.add_parser("projects", help="list your projects")
    c = sub.add_parser("clone", help="copy a project into a new local folder")
    c.add_argument("project", help="project name, id, or URL")
    c.add_argument("dir", nargs="?")
    sub.add_parser("sync", help="merge local and Overleaf changes both ways").add_argument("--delete", action="store_true", help="also delete files on Overleaf that you deleted locally")
    sub.add_parser("compile", help="compile on Overleaf; save PDF and log to .ol/")
    a = ap.parse_args()

    if a.cmd == "login":
        login(a.cookie)
    elif a.cmd == "projects":
        for p in projects(session()):
            if not p.get("trashed"):
                print(f"{p['id']}  {p.get('lastUpdated', '')[:10]}  {p['name']}")
    elif a.cmd == "clone":
        pid, name = resolve_project(session(), a.project)
        root = Path(a.dir or re.sub(r"[^\w.-]+", "-", name or pid).strip("-"))
        if root.exists() and any(root.iterdir()):
            die(f"{root} already exists and is not empty")
        (root / ".ol").mkdir(parents=True)
        save(root, {"project": pid, "docs": {}, "files": {}})
        sync(root)
        print(f"cloned into {root}/")
    elif a.cmd == "sync":
        sync(find_root(), a.delete)
    elif a.cmd == "compile":
        compile_(find_root())


if __name__ == "__main__":
    main()
