"""Cover-art image caching.

The account API's `image` field is a protocol-relative base hash with no
extension (e.g. `//images-3.gog-statics.com/<hash>`). Appending a size
suffix makes it fetchable -- confirmed live: `_100.jpg` (~4KB), `_196.jpg`
(~9KB), `_392.jpg` (~29KB) all work; bare `.jpg` gives full-res (~250KB,
too big to fetch eagerly for the whole library); `_600.jpg` 404s (not a
valid bucket).
"""
import os

import requests

from .. import paths

COVER_SUFFIX = "_196.jpg"


def cover_url(image_url):
    if not image_url:
        return None
    if image_url.startswith("//"):
        image_url = "https:" + image_url
    return image_url + COVER_SUFFIX


def fetch_cover(product_id, image_url, session, force=False):
    url = cover_url(image_url)
    if not url:
        return None
    dest = os.path.join(paths.game_images_dir(product_id), "cover.jpg")
    if os.path.exists(dest) and not force:
        return dest
    resp = session.get(url, timeout=15)
    if resp.status_code != 200:
        return None
    with open(dest, "wb") as f:
        f.write(resp.content)
    return dest


def fetch_all_covers(entitlements, progress=None):
    fetched, skipped, failed = 0, 0, 0
    session = requests.Session()
    total = len(entitlements)
    for i, (pid, entry) in enumerate(entitlements.items(), start=1):
        dest = os.path.join(paths.game_images_dir(pid), "cover.jpg")
        already = os.path.exists(dest)
        result = fetch_cover(pid, entry.get("image_url"), session)
        if result is None:
            failed += 1
        elif already:
            skipped += 1
        else:
            fetched += 1
        if progress and (i % 100 == 0 or i == total):
            progress(i, total)
    return {"fetched": fetched, "skipped": skipped, "failed": failed}
