"""Rebuild the OS lifecycle seed from the endoflife.date API (needs internet).

    python3 tools/refresh_lifecycle_seed.py                 # -> app/resources/os_lifecycle_seed.json
    python3 tools/refresh_lifecycle_seed.py lifecycle.json  # -> any file

Two uses:
- refresh the seed that ships with the app (commit the result), or
- produce a file for a server WITHOUT internet: copy it over and upload it in
  Administration -> OS Support -> Upload JSON.

Only the products in app/services/lifecycle_service.PRODUCTS are fetched.
Dev-only helper: needs `requests`, nothing else from the app.
"""
import json
import os
import sys
from datetime import datetime, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("SECRET_KEY", "x")
os.environ.setdefault("ENCRYPTION_KEY", "x")
from app.services.lifecycle_service import API_URL, PRODUCTS, SEED_PATH, rows_from_api_v1  # noqa: E402


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else SEED_PATH
    doc = {"source": "endoflife.date", "schema": 1,
           "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "note": "Built from the endoflife.date API v1 by tools/refresh_lifecycle_seed.py.",
           "products": {}}
    for product in PRODUCTS:
        r = requests.get(API_URL.format(product), timeout=20,
                         headers={"User-Agent": "vm-inventory seed refresh"})
        if r.status_code == 404:
            print(f"  {product}: not on endoflife.date - skipped")
            continue
        r.raise_for_status()
        rows = rows_from_api_v1(r.json())
        doc["products"][product] = [
            {"cycle": x["version"],
             "release_date": x["release_date"].isoformat() if x["release_date"] else None,
             "eol": x["eol_standard"].isoformat() if x["eol_standard"] else None,
             "eol_reached": x["eol_reached"],
             "eol_extended": x["eol_extended"].isoformat() if x["eol_extended"] else None}
            for x in rows]
        print(f"  {product}: {len(rows)} releases")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    print(f"written: {out_path}")


if __name__ == "__main__":
    main()
