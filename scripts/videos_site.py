"""The owners' videos (the promo and the how-tos) at https://nexgen-bbpro.web.app/videos/.

They are files of the Firebase Hosting site, which Firebase serves itself before its ``**`` rule sends every other
address to Cloud Run, so the API never carries them. They live outside the repo (made in C:\\dev\\video\\nexgen;
``sitefiles.py`` there writes the folder this script uploads: the films, their posters, durations.json and a plain
index page). The same layout as FBSim's videos (asked 2026-11-07).

  python scripts/videos_site.py DIR              what would be sent
  python scripts/videos_site.py DIR --preview    a test address of its own for a day: these files alone, no rule,
                                                 so nothing of the league can be reached through it
  python scripts/videos_site.py DIR --go         released on nexgen-bbpro.web.app
  python scripts/videos_site.py --keep           put /videos/ back after a ``firebase deploy --only hosting``

Why ``--keep``: ``firebase deploy`` releases a version holding only desktop/dist, so it drops /videos/. firebase.json
runs ``--keep`` after every hosting deploy: it finds the newest earlier release that served /videos/, and makes a
new version as a copy of the one just released plus those files, by their hashes. Firebase already holds the
bytes, so nothing is uploaded and the deploying machine needs no video files.

``--go`` and ``--keep`` both make the new version as a copy of the released one (Firebase's versions:clone), so its
files, redirects and rule stay exactly as they are. Firebase wants every file gzipped for the upload and serves it
as it was. Credentials: gcloud's (``gcloud auth print-access-token``), as for the rest of the deploy.
"""

from __future__ import annotations

import concurrent.futures
import gzip
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

PROJECT = "nexgen-bbpro"
SITE = "nexgen-bbpro"
FOLDER = "videos"
KINDS = (".mp4", ".jpg", ".json", ".html", ".css")
CHANNEL = "videos-check"
V1 = "https://firebasehosting.googleapis.com/v1beta1"
API = f"{V1}/projects/{PROJECT}"


def token() -> str:
    return subprocess.run(
        "gcloud auth print-access-token", shell=True, capture_output=True, text=True, check=True
    ).stdout.strip()


def call(method: str, url: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token()}", "x-goog-user-project": PROJECT,
        "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def upload(url: str, data: bytes, bearer: str):
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {bearer}", "x-goog-user-project": PROJECT,
        "Content-Type": "application/octet-stream"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except OSError as e:
        return 0, str(e)


def releases(n: int = 10) -> list:
    status, got = call("GET", f"{API}/sites/{SITE}/releases?pageSize={n}")
    if status != 200:
        raise SystemExit(f"releases: {status} {got}")
    return got.get("releases") or []


def version_files(version_name: str) -> dict:
    """{path: hash} of every file a version serves."""
    out, page = {}, ""
    while True:
        status, got = call("GET", f"{V1}/{version_name}/files?pageSize=1000"
                           + (f"&pageToken={page}" if page else ""))
        if status != 200:
            raise SystemExit(f"files: {status} {got}")
        out.update({f["path"]: f["hash"] for f in got.get("files", [])})
        page = got.get("nextPageToken")
        if not page:
            return out


def files(folder: str) -> dict:
    """{"/videos/<name>": the file's bytes} for the files of the kinds the pages use."""
    return {f"/{FOLDER}/{n}": open(os.path.join(folder, n), "rb").read()
            for n in sorted(os.listdir(folder)) if n.lower().endswith(KINDS)}


def clone_released() -> str:
    """A new version, not yet finalized, holding every file, redirect and the rule of the version served now."""
    now = (releases(1) or [{}])[0].get("version", {})
    if not now.get("name"):
        raise SystemExit("the site serves no version: nothing to add the videos to")
    status, op = call("POST", f"{API}/sites/{SITE}/versions:clone",
                      {"sourceVersion": now["name"], "finalize": False})
    while status == 200 and not op.get("done"):
        time.sleep(3)
        status, op = call("GET", f"{V1}/{op['name']}")
    if status != 200 or "error" in op:
        raise SystemExit(f"clone: {status} {op}")
    print(f"version {op['response']['name'].rsplit('/', 1)[-1]}: a copy of "
          f"{now['name'].rsplit('/', 1)[-1]} ({now.get('fileCount', '?')} files)")
    return op["response"]["name"]


def fill(name: str, hashes: dict, by_hash: dict | None = None) -> None:
    """Put the files ({path: hash of the gzipped bytes}) into the version, send what Firebase lacks, finalize."""
    status, got = call("POST", f"{V1}/{name}:populateFiles", {"files": hashes})
    if status != 200:
        raise SystemExit(f"populate: {status} {got}")
    need, url = got.get("uploadRequiredHashes", []), got.get("uploadUrl")
    if need and not by_hash:
        raise SystemExit(f"Firebase no longer holds {len(need)} of the files; upload them with DIR --go")
    print(f"{len(need)} of {len(hashes)} files to upload "
          f"({sum(len(by_hash[h]) for h in need) / 1e6 if need else 0:.0f} MB)")
    bearer = token()

    def send(h):
        for attempt in range(5):
            status, body = upload(f"{url}/{h}", by_hash[h], bearer)
            if status == 200:
                return True
            time.sleep(2 + 2 * attempt)
        print("upload failed:", h, status, body)
        return False

    with concurrent.futures.ThreadPoolExecutor(6) as ex:
        if not all(ex.map(send, need)):
            raise SystemExit("an upload failed: nothing released")
    status, got = call("PATCH", f"{V1}/{name}?update_mask=status", {"status": "FINALIZED"})
    if status != 200:
        raise SystemExit(f"finalize: {status} {got}")


def release(name: str) -> int:
    status, got = call("POST", f"{API}/sites/{SITE}/releases?versionName={name}", {})
    print("released:", status, got.get("releaseTime", got))
    return 0 if status == 200 else 1


def preview(hashes: dict, by_hash: dict) -> str:
    """These files alone, no rule, on a channel of their own that ends in a day; returns its address."""
    status, got = call("POST", f"{API}/sites/{SITE}/versions", {"config": {}})
    if status != 200:
        raise SystemExit(f"version: {status} {got}")
    fill(got["name"], hashes, by_hash)
    status, chan = call("GET", f"{API}/sites/{SITE}/channels/{CHANNEL}")
    if status == 404:
        status, chan = call("POST", f"{API}/sites/{SITE}/channels?channelId={CHANNEL}", {"ttl": "86400s"})
    else:
        status, chan = call("PATCH", f"{API}/sites/{SITE}/channels/{CHANNEL}?update_mask=ttl", {"ttl": "86400s"})
    if status != 200:
        raise SystemExit(f"channel: {status} {chan}")
    status, rel = call("POST", f"{API}/sites/{SITE}/channels/{CHANNEL}/releases?versionName={got['name']}", {})
    if status != 200:
        raise SystemExit(f"release: {status} {rel}")
    return chan.get("url", "")


def keep() -> int:
    """After a CLI deploy: carry /videos/ over from the newest earlier release that had them."""
    prefix = f"/{FOLDER}/"
    history = releases(10)
    if not history:
        print("no releases: nothing to keep")
        return 0
    current = history[0].get("version", {})
    if any(p.startswith(prefix) for p in version_files(current["name"])):
        print("the released version already serves /videos/")
        return 0
    for rel in history[1:]:
        version = rel.get("version", {})
        if not version.get("name"):
            continue
        carried = {p: h for p, h in version_files(version["name"]).items() if p.startswith(prefix)}
        if carried:
            print(f"/videos/: {len(carried)} files from {version['name'].rsplit('/', 1)[-1]}")
            break
    else:
        print("no earlier release served /videos/: nothing to keep")
        return 0
    name = clone_released()
    fill(name, carried)
    return release(name)


def main(argv) -> int:
    if "--keep" in argv:
        return keep()
    if not argv or argv[0].startswith("--"):
        print(__doc__)
        return 2
    have = files(argv[0])
    print(f"{len(have)} files, {sum(map(len, have.values())) / 1e6:.0f} MB, under /{FOLDER}/:")
    for p, data in have.items():
        print(f"  {p}  {len(data) / 1e6:.1f} MB")
    if "--go" not in argv and "--preview" not in argv:
        return 0
    packed = {p: gzip.compress(d, 1, mtime=0) for p, d in have.items()}
    hashes = {p: hashlib.sha256(gz).hexdigest() for p, gz in packed.items()}
    by_hash = {hashes[p]: packed[p] for p in packed}
    if "--preview" in argv:
        print("preview at:", preview(hashes, by_hash), "(for a day)")
        return 0
    name = clone_released()
    fill(name, hashes, by_hash)
    return release(name)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
