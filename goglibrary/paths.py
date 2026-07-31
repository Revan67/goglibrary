import os

DATA_DIR = os.path.join(os.environ["LOCALAPPDATA"], "GOGLibrary")
IMAGES_DIR = os.path.join(DATA_DIR, "images")
ENTITLEMENTS_FILE = os.path.join(DATA_DIR, "entitlements.json")
CATALOG_CACHE_FILE = os.path.join(DATA_DIR, "catalog_cache.json")
TOKEN_FILE = os.path.join(DATA_DIR, "gog-token.dat")


def ensure_data_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(IMAGES_DIR, exist_ok=True)


def game_images_dir(product_id):
    path = os.path.join(IMAGES_DIR, str(product_id))
    os.makedirs(path, exist_ok=True)
    return path
