"""Milestone 1b: catalog enrichment sync.

Fetches description/tags/screenshots/videos/series/ratings from GOG's
public v2 catalog API (no auth) for every product ID in entitlements.json.
See docs/gog_catalog_api.md for the confirmed response shape.

Resumable and interruption-safe: results are cached to disk per product ID
as they're fetched, so re-running only fetches what's missing. Matches the
pattern from the prior tag-enrichment project (discover once, cache
per-ID, never re-fetch what's already known).
"""
import json
import os
import sys
import time

import requests

# Some real GOG titles contain characters this console's encoding can't
# represent at all (not just render oddly, like the cp1252-representable
# em-dash case -- an outright encode error). Progress output must never
# crash the sync over a display-only issue.
sys.stdout.reconfigure(errors="replace")

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from .. import paths  # noqa: E402

CATALOG_URL = "https://api.gog.com/v2/games/{id}?locale=en-US"
THROTTLE_SECONDS = 0.4
SAVE_EVERY = 50


def load_cache():
    if os.path.exists(paths.CATALOG_CACHE_FILE):
        with open(paths.CATALOG_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache):
    tmp = paths.CATALOG_CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp, paths.CATALOG_CACHE_FILE)


def _extract(data):
    embedded = data.get("_embedded", {})
    links = data.get("_links", {})

    screenshots = []
    for shot in embedded.get("screenshots", []):
        href_data = shot.get("_links", {}).get("self", {})
        if href_data.get("href"):
            screenshots.append({
                "url_template": href_data["href"],
                "formatters": href_data.get("formatters", []),
            })

    videos = []
    for vid in embedded.get("videos", []):
        vid_links = vid.get("_links", {})
        videos.append({
            "provider": vid.get("provider"),
            "video_id": vid.get("videoId"),
            "embed_url": vid_links.get("self", {}).get("href"),
            "thumbnail_url": vid_links.get("thumbnail", {}).get("href"),
        })

    return {
        "status": "ok",
        "description": data.get("description"),
        "overview": data.get("overview"),
        "tags": embedded.get("tags", []),
        "properties": embedded.get("properties", []),
        "series": embedded.get("series"),
        "pegi_rating": embedded.get("pegiRating"),
        "usk_rating": embedded.get("uskRating"),
        "screenshots": screenshots,
        "videos": videos,
        "links": {
            "icon": links.get("icon", {}).get("href"),
            "logo": links.get("logo", {}).get("href"),
            "box_art": links.get("boxArtImage", {}).get("href"),
            "background": links.get("backgroundImage", {}).get("href"),
            "galaxy_background": links.get("galaxyBackgroundImage", {}).get("href"),
        },
    }


def fetch_one(product_id, session):
    url = CATALOG_URL.format(id=product_id)
    try:
        resp = session.get(url, timeout=15)
    except requests.RequestException as e:
        return {"status": "error", "error": str(e)}

    if resp.status_code == 404:
        return {"status": "not_found"}
    if resp.status_code != 200:
        return {"status": "error", "error": f"HTTP {resp.status_code}"}

    try:
        return _extract(resp.json())
    except (ValueError, KeyError) as e:
        return {"status": "error", "error": f"parse failure: {e}"}


def sync(force=False):
    with open(paths.ENTITLEMENTS_FILE, encoding="utf-8") as f:
        entitlements = json.load(f)["games"]

    cache = load_cache()
    to_fetch = list(entitlements.keys()) if force else [
        pid for pid in entitlements if pid not in cache
    ]
    print(f"{len(entitlements)} entitlements total, {len(cache)} already cached, {len(to_fetch)} to fetch.")

    session = requests.Session()
    fetched_since_save = 0
    try:
        for i, pid in enumerate(to_fetch, start=1):
            result = fetch_one(pid, session)
            result["fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            cache[pid] = result
            fetched_since_save += 1

            title = entitlements[pid]["title"]
            print(f"  [{i}/{len(to_fetch)}] {result['status']:10s} {title}")

            if fetched_since_save >= SAVE_EVERY:
                save_cache(cache)
                fetched_since_save = 0

            time.sleep(THROTTLE_SECONDS)
    finally:
        save_cache(cache)

    statuses = {}
    for entry in cache.values():
        statuses[entry["status"]] = statuses.get(entry["status"], 0) + 1
    print(f"\nCache now has {len(cache)} entries: {statuses}")
    return cache


if __name__ == "__main__":
    sync(force="--force" in sys.argv)
