"""Milestone 1a: sync owned games+movies from GOG's account API into entitlements.json.

Reuses gogrepoc_backend.py's login/session/request handling as-is for now
(plaintext token, eval-based storage) -- Milestone 4 replaces the token
storage with DPAPI encryption. This module does not touch download URLs or
per-game details; that's out of scope until the downloader milestone.
"""
import getpass
import json
import os
import sys
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import gogrepoc_backend as gog  # noqa: E402

from .. import paths  # noqa: E402
from . import images  # noqa: E402

MEDIA_TYPES = {
    "game": gog.GOG_MEDIA_TYPE_GAME,
    "movie": gog.GOG_MEDIA_TYPE_MOVIE,
}


def ensure_logged_in():
    """Reuses gog's existing token file if valid; otherwise runs the
    interactive login flow. Must be run in a real terminal -- prompts for
    username/password (and 2FA, if enabled) via input()/getpass().
    """
    os.chdir(paths.DATA_DIR)
    token = gog.load_token()
    if token.get("access_token"):
        print("Existing token found, reusing it.")
        return
    print("No valid token found -- logging in.")
    print("You must use a GOG or GOG Galaxy account (Google/Discord sign-in isn't supported).")
    user = input("GOG username/email: ")
    passwd = getpass.getpass("GOG password: ")
    gog.cmd_login(user, passwd)


def fetch_entitlements(media_type_label, media_type_value, session):
    api_url = gog.GOG_ACCOUNT_URL + "/getFilteredProducts"
    entries = {}
    page = 1
    total_pages = 1
    while page <= total_pages:
        response = gog.request(
            session, api_url,
            args={"mediaType": media_type_value, "sortBy": "title", "page": str(page)},
        )
        data = response.json()
        total_pages = data.get("totalPages", 1)
        for product in data.get("products", []):
            pid = str(product["id"])
            entries[pid] = {
                "id": product["id"],
                "slug": product["slug"],
                "title": product["title"],
                "media_type": media_type_label,
                "image_url": product.get("image"),
                "store_url": product.get("url"),
                "is_hidden": bool(product.get("isHidden", False)),
            }
        print(f"  page {page}/{total_pages}: {len(data.get('products', []))} products")
        page += 1
    return entries


def sync():
    paths.ensure_data_dirs()
    ensure_logged_in()
    session = gog.makeGOGSession(False)

    all_entries = {}
    for label, value in MEDIA_TYPES.items():
        print(f"Fetching {label} entitlements...")
        entries = fetch_entitlements(label, value, session)
        print(f"  -> {len(entries)} {label}(s)")
        all_entries.update(entries)

    out = {
        "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "games": all_entries,
    }
    with open(paths.ENTITLEMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {len(all_entries)} total entries to {paths.ENTITLEMENTS_FILE}")

    print("Fetching cover images...")

    def report(done, total):
        print(f"  {done}/{total}")

    result = images.fetch_all_covers(all_entries, progress=report)
    print(f"Covers: {result['fetched']} fetched, {result['skipped']} already cached, {result['failed']} failed")

    return out


if __name__ == "__main__":
    sync()
