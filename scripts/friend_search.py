#!/usr/bin/env python3
"""Take the game creator from result.json, walk their friends list breadth-first
up to MAX_DEPTH hops, and flag target usernames / keyword matches."""
import json, os, sys, time, urllib.request, urllib.error
from collections import deque
from roblox_favorites_lookup import get

TARGETS = {t.strip().lower() for t in os.environ.get("TARGET_USERNAMES", "mr_bolde2,justaprogamer8").split(",") if t.strip()}
KEYWORD = os.environ.get("KEYWORD", "adf").lower()
MAX_DEPTH = int(os.environ.get("MAX_DEPTH", "2"))
MAX_USERS = int(os.environ.get("MAX_USERS", "3000"))  # cap on friend lists fetched
DELAY = float(os.environ.get("REQUEST_DELAY", "0.4"))


def creator_user_id(creator):
    if creator["type"] == "User":
        return creator["id"]
    owner = (get(f"https://groups.roblox.com/v1/groups/{creator['id']}").get("owner") or {})
    if not owner.get("userId"):
        sys.exit(f"Group {creator['id']} has no owner to start from")
    print(f"Creator is a group; using owner user {owner['userId']}")
    return owner["userId"]


def classify(u):
    """Return 'target', 'keyword' or None for a {id,name,displayName} dict."""
    name, disp = (u.get("name") or "").lower(), (u.get("displayName") or "").lower()
    if name in TARGETS or disp in TARGETS:
        return "target"
    if KEYWORD and (KEYWORD in name or KEYWORD in disp):
        return "keyword"
    return None


def search(start, friends_of, max_depth=MAX_DEPTH, max_users=MAX_USERS):
    """BFS. friends_of(id) -> list of {id,name,displayName}. Returns (hits, seen, fetched)."""
    seen = {start["id"]: None}  # id -> parent id
    fof = []  # friends of friends (depth 2)
    info = {start["id"]: start}
    queue, hits, fetched = deque([(start["id"], 0)]), [], 0
    h = classify(start)
    if h:
        hits.append((h, start, 0))
    while queue:
        uid, depth = queue.popleft()
        if depth >= max_depth or fetched >= max_users:
            continue
        try:
            friends = friends_of(uid)
        except Exception as e:
            print(f"  skip {uid}: {e}")
            continue
        fetched += 1
        if fetched % 50 == 0:
            print(f"  fetched {fetched} friend lists, {len(seen)} users seen, depth {depth}")
        for f in friends:
            if f["id"] in seen:
                continue
            seen[f["id"]] = uid
            info[f["id"]] = f
            if depth + 1 == 2:
                fof.append({"id": f["id"], "username": f.get("name"), "displayName": f.get("displayName"), "friend_of": info[uid].get("name")})
            h = classify(f)
            if h:
                hits.append((h, f, depth + 1))
            queue.append((f["id"], depth + 1))
    def path(i):
        p = []
        while i is not None:
            p.append(info[i].get("name") or str(i))
            i = seen[i]
        return " <- ".join(p)
    out = [{"type": t, "id": u["id"], "username": u.get("name"), "displayName": u.get("displayName"),
            "depth": d, "path": path(u["id"])} for t, u, d in hits]
    return out, len(seen), fetched, fof


NAMES = {}  # id -> {id, name, displayName}


def post_json(url, payload, retries=6):
    for i in range(retries):
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Accept": "application/json",
                                              "User-Agent": "kaiju-online-workflow"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(2 * (i + 1))
                continue
            raise RuntimeError(f"HTTP {e.code} for {url}: {e.read().decode('utf-8', 'replace')[:300]}")
        except urllib.error.URLError:
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"Failed after retries: {url}")


def resolve_names(ids):
    """The friends endpoint only returns ids now; look up username/displayName in batches of 100."""
    todo = [i for i in ids if i not in NAMES]
    for k in range(0, len(todo), 100):
        time.sleep(DELAY)
        chunk = todo[k:k + 100]
        data = post_json("https://users.roblox.com/v1/users", {"userIds": chunk, "excludeBannedUsers": False}).get("data", [])
        for u in data:
            NAMES[u["id"]] = {"id": u["id"], "name": u.get("name"), "displayName": u.get("displayName")}
        for i in chunk:  # ids Roblox didn't return (deleted etc.)
            NAMES.setdefault(i, {"id": i, "name": "", "displayName": ""})
    return [NAMES[i] for i in ids]


def live_friends(uid):
    time.sleep(DELAY)
    data = get(f"https://friends.roblox.com/v1/users/{uid}/friends", retries=8).get("data", [])
    return resolve_names([d["id"] for d in data])


def main():
    res = json.load(open("result.json"))
    creator = res["matches"][0]["creator"]
    start_id = creator_user_id(creator)
    start = get(f"https://users.roblox.com/v1/users/{start_id}")
    print(f"Start: {start['name']} ({start_id}); targets={sorted(TARGETS)} keyword={KEYWORD!r} depth={MAX_DEPTH} cap={MAX_USERS}")
    hits, seen, fetched, fof = search(start, live_friends)
    json.dump({"start": {"id": start["id"], "name": start["name"], "displayName": start.get("displayName")}, "max_depth": MAX_DEPTH,
               "users_seen": seen, "friend_lists_fetched": fetched, "hits": hits, "friends_of_friends": fof},
              open("friend_search_result.json", "w"), indent=2)
    print(f"Done: {seen} users seen, {fetched} friend lists fetched, {len(hits)} hits")
    targets = [h for h in hits if h["type"] == "target"]
    keywords = [h for h in hits if h["type"] == "keyword"]
    for h in targets:
        print(f"::error title=TARGET FOUND::{h['username']} ({h['id']}) at depth {h['depth']}: {h['path']}")
    for h in keywords[:50]:
        print(f"::warning title=Keyword '{KEYWORD}'::{h['username']} / {h['displayName']} ({h['id']}) depth {h['depth']}: {h['path']}")
    if len(keywords) > 50:
        print(f"::notice::{len(keywords) - 50} more keyword hits in friend_search_result.json")
    if fetched >= MAX_USERS:
        print(f"::notice::Stopped at the {MAX_USERS} friend-list cap; raise max_users to go further")
    sys.exit(2 if targets else 0)


if __name__ == "__main__":
    main()
