#!/usr/bin/env python3
"""Favorites -> place ids -> find game by title -> creator -> creator public info.

Inaccessible/private games are hidden from favorites unless accessFilter is set,
and they don't show up in games.roblox.com/v1/games, so we use the data the
favorites endpoint itself returns (name, creator, rootPlace) as the source of truth.
"""
import json, os, sys, time, urllib.request, urllib.error

USER_ID = os.environ.get("ROBLOX_USER_ID", "3882403525")
SEARCH = os.environ.get("TITLE_SEARCH", "kaiju reborn").lower()


def get(url, retries=4):
    for i in range(retries):
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "kaiju-online-workflow"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(2 * (i + 1))
                continue
            body = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"HTTP {e.code} for {url}: {body}")
        except urllib.error.URLError:
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"Failed after retries: {url}")


def fetch_favorites(uid):
    """Try every access filter so non-public (inaccessible) games are included. Dedupe by universe id."""
    found = {}
    for access in ("2", "1", None):
        label = f"accessFilter={access}" if access else "default"
        cursor, count = "", 0
        try:
            while True:
                url = f"https://games.roblox.com/v2/users/{uid}/favorite/games?limit=50&sortOrder=Desc"
                if access:
                    url += f"&accessFilter={access}"
                if cursor:
                    url += f"&cursor={cursor}"
                data = get(url)
                for g in data.get("data", []):
                    found.setdefault(g["id"], g)
                    count += 1
                cursor = data.get("nextPageCursor")
                if not cursor:
                    break
        except Exception as e:
            print(f"  [{label}] error: {e}")
            continue
        print(f"  [{label}] returned {count} favorites")
    return list(found.values())


def main():
    # 1. favorites
    favs = fetch_favorites(USER_ID)
    print(f"Favorites found (unique): {len(favs)}")
    for g in favs:
        print(f"  - {g.get('name')!r} universe={g['id']} place={(g.get('rootPlace') or {}).get('id')}")

    # 2. place ids
    place_ids = [g["rootPlace"]["id"] for g in favs if g.get("rootPlace")]
    print(f"Place ids: {place_ids}")

    # 3/4. title match (case-insensitive) on the favorites data itself
    matches = [g for g in favs if SEARCH in (g.get("name") or "").lower()]
    print(f"Games matching '{SEARCH}': {len(matches)}")
    if not matches:
        print("No matching game in favorites.")
        json.dump({"user_id": USER_ID, "search": SEARCH, "favorites_found": len(favs), "matches": []}, open("result.json", "w"), indent=2)
        sys.exit(1)

    results = []
    for g in matches:
        creator = g.get("creator")
        if not creator:  # fall back to game details if favorites entry lacks creator
            creator = get(f"https://games.roblox.com/v1/games?universeIds={g['id']}")["data"][0]["creator"]
        # 5. creator public info
        if creator["type"] == "Group":
            info = get(f"https://groups.roblox.com/v1/groups/{creator['id']}")
        else:
            info = get(f"https://users.roblox.com/v1/users/{creator['id']}")
        results.append({
            "game": {"name": g["name"], "universeId": g["id"], "rootPlaceId": (g.get("rootPlace") or {}).get("id")},
            "creator": creator,
            "creator_public_info": info,
        })

    out = {"user_id": USER_ID, "search": SEARCH, "matches": results}
    json.dump(out, open("result.json", "w"), indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
