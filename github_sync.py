#!/usr/bin/env python3
import json, base64, urllib.request, urllib.error

API_BASE = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"

def _request(url, method="GET", token=None, data=None):
    headers = {"User-Agent": "AIOS-WishBridge"}
    if token: headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        data = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return res.read().decode()
    except urllib.error.HTTPError as e: return e.read().decode()
    except Exception as e: return json.dumps({"error": str(e)})

def push_file(token, repo, filepath, content, message="update via AIOS"):
    owner, name = repo.split("/")
    url = f"{API_BASE}/repos/{owner}/{name}/contents/{filepath}"
    sha = None
    try: sha = json.loads(_request(url, token=token)).get("sha")
    except: pass
    payload = {"message": message, "content": base64.b64encode(content.encode()).decode()}
    if sha: payload["sha"] = sha
    return json.loads(_request(url, method="PUT", token=token, data=payload))

def pull_latest(repo, filename, branch="main"):
    owner, name = repo.split("/")
    try:
        with urllib.request.urlopen(f"{RAW_BASE}/{owner}/{name}/{branch}/{filename}", timeout=15) as r:
            return r.read().decode()
    except Exception as e: return f"ERROR: {e}"

def get_latest_commit(repo):
    owner, name = repo.split("/")
    try:
        data = json.loads(_request(f"{API_BASE}/repos/{owner}/{name}/commits"))
        return data[0].get("sha") if isinstance(data, list) else None
    except Exception as e: return f"ERROR: {e}"
