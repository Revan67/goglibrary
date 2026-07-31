"""Primary catalog enrichment source: GOGDB's daily bulk archive.

GOGDB (gogdb.org, github.com/Yepoleb/gogdb) is a community-run mirror of
GOG's full catalog -- not official GOG infrastructure. Their own docs
recommend downloading the daily bulk archive rather than hitting the live
site per-product, which is what this module does: one ~60MB .tar.xz
containing every product's product.json (14,920+ products as of the
initial discovery run), parsed entirely in memory.

This becomes the primary enrichment source (richer than GOG's own v2
catalog API -- adds store_state/delisting, build/price history, and often
more screenshots/videos). goglibrary.sync.catalog (GOG's live v2 API) is
kept as the fallback for any product ID missing here or if GOGDB is ever
unreachable -- see docs/DESIGN_PLAN.md for the reasoning. Ownership itself
always comes from entitlements.json (GOG's account API), never from here.
"""
import json
import os
import sys
import tarfile
import time
from urllib.parse import urljoin

import requests

sys.stdout.reconfigure(errors="replace")

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from .. import paths  # noqa: E402

GOGDB_CACHE_FILE = os.path.join(paths.DATA_DIR, "gogdb_cache.json")
BACKUPS_INDEX_URL = "https://www.gogdb.org/backups_v3/products/"
IMAGE_BASE = "https://images.gog-statics.com/"


def _latest_archive_url():
    """Finds the most recent monthly folder, then the most recent .tar.xz in it."""
    resp = requests.get(BACKUPS_INDEX_URL, timeout=15)
    resp.raise_for_status()
    months = sorted(
        part.split('"')[1] for part in resp.text.split("href=") if '"20' in part[:6]
    )
    if not months:
        raise RuntimeError("Could not find any monthly backup folders on GOGDB.")
    month_url = urljoin(BACKUPS_INDEX_URL, months[-1])

    resp = requests.get(month_url, timeout=15)
    resp.raise_for_status()
    archives = sorted(
        part.split('"')[1] for part in resp.text.split("href=") if ".tar.xz" in part[:60]
    )
    if not archives:
        raise RuntimeError(f"No .tar.xz archives found in {month_url}")
    return urljoin(month_url, archives[-1])


def download_archive(url, dest_path, progress=None):
    print(f"Downloading {url}")
    resp = requests.get(url, timeout=120, stream=True)
    resp.raise_for_status()
    total = int(resp.headers.get("Content-Length", 0))
    written = 0
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
            written += len(chunk)
            if progress:
                progress(written, total)
    return dest_path


def image_url(image_hash, suffix=".jpg"):
    if not image_hash:
        return None
    return f"{IMAGE_BASE}{image_hash}{suffix}"


def _extract(data):
    return {
        "status": "ok",
        "title": data.get("title"),
        "slug": data.get("slug"),
        "type": data.get("type"),
        "store_state": data.get("store_state"),
        "description": data.get("description"),
        "tags": data.get("tags", []),
        "properties": data.get("properties", []),
        "series": data.get("series"),
        "age_rating": data.get("age_rating"),
        "dlcs": data.get("dlcs", []),
        "screenshot_hashes": data.get("screenshots", []),
        "videos": data.get("videos", []),
        "images": {
            "icon": data.get("image_icon"),
            "logo": data.get("image_logo"),
            "box_art": data.get("image_boxart"),
            "background": data.get("image_background"),
            "galaxy_background": data.get("image_galaxy_background"),
        },
    }


def parse_archive(archive_path, progress=None):
    """Returns {product_id: extracted_entry} for every product.json in the archive."""
    results = {}
    with tarfile.open(archive_path, "r:xz") as tf:
        members = [m for m in tf.getmembers() if m.name.endswith("/product.json")]
        total = len(members)
        for i, member in enumerate(members, start=1):
            product_id = member.name.split("/")[1]
            try:
                raw = tf.extractfile(member).read()
                data = json.loads(raw)
                results[product_id] = _extract(data)
            except (ValueError, KeyError, AttributeError) as e:
                results[product_id] = {"status": "error", "error": str(e)}
            if progress and (i % 1000 == 0 or i == total):
                progress(i, total)
    return results


def _last_synced_archive_url():
    if not os.path.exists(GOGDB_CACHE_FILE):
        return None
    with open(GOGDB_CACHE_FILE, encoding="utf-8") as f:
        return json.load(f).get("source_archive_url")


def check_for_update():
    """Cheap check (a couple small HTML page fetches, not the 60MB archive):
    is there a newer archive than the one we last synced from?
    Returns (has_update: bool, latest_url: str).
    """
    latest_url = _latest_archive_url()
    return latest_url != _last_synced_archive_url(), latest_url


def sync(archive_path=None, force=False):
    paths.ensure_data_dirs()

    source_url = None
    if archive_path:
        tmp_archive = archive_path
    else:
        latest_url = _latest_archive_url()
        if not force and latest_url == _last_synced_archive_url():
            print(f"Already up to date with {latest_url} -- nothing to do.")
            with open(GOGDB_CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
        print(f"New archive available: {latest_url}")
        source_url = latest_url
        tmp_archive = os.path.join(paths.DATA_DIR, "gogdb_archive.tar.xz")

        def dl_progress(written, total):
            if total:
                print(f"  {written / 1_000_000:.1f}MB / {total / 1_000_000:.1f}MB", end="\r")
        download_archive(source_url, tmp_archive, progress=dl_progress)
        print()

    print("Parsing archive...")

    def parse_progress(done, total):
        print(f"  {done}/{total}")

    results = parse_archive(tmp_archive, progress=parse_progress)

    entitlements_path = paths.ENTITLEMENTS_FILE
    owned_ids = set()
    if os.path.exists(entitlements_path):
        with open(entitlements_path, encoding="utf-8") as f:
            owned_ids = set(json.load(f)["games"].keys())
    for pid, entry in results.items():
        entry["is_owned"] = pid in owned_ids

    out = {
        "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_archive_url": source_url or _last_synced_archive_url(),
        "products": results,
    }
    with open(GOGDB_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    owned_count = sum(1 for e in results.values() if e["is_owned"])
    print(f"\nWrote {len(results)} total products ({owned_count} owned) to {GOGDB_CACHE_FILE}")
    return out


if __name__ == "__main__":
    sync()
