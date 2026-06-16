"""
2GIS parking scraper for Almaty.

Strategy:
- Adaptive grid: start with coarse cells covering Almaty bounding box.
- For each cell, query items?q=parking&type=parking&point=<center>&radius=<r>
- If total > MAX_TOTAL, split the cell into 4 sub-cells and recurse.
- Otherwise, paginate (page_size=10) until all items for that cell are fetched.
- Deduplicate globally by item 'id'.
- Save results to CSV (and optionally push to Google Sheets).

Usage:
    python parking_scraper.py YOUR_API_KEY
"""

import sys
import time
import csv
import requests

API_URL = "https://catalog.api.2gis.com/3.0/items"
FIELDS = (
    "items.point,items.capacity,items.is_paid,items.level_count,"
    "items.purpose,items.schedule,items.address_name,items.full_name,"
    "items.subtype,items.links"
)

# Approx bounding box of Almaty (lon_min, lon_max, lat_min, lat_max)
LON_MIN, LON_MAX = 76.82, 77.10
LAT_MIN, LAT_MAX = 43.13, 43.32

# Monthly limit is only 1000 requests — do NOT recursively split cells.
# Accept top-N results per cell instead (N = MAX_PAGES_PER_CELL * PAGE_SIZE).
MAX_TOTAL_PER_CELL = 10**9  # effectively disables splitting
PAGE_SIZE = 10
MAX_PAGES_PER_CELL = 3  # 30 items/cell max -> ~150-200 requests for full city

# Be polite to the API
SLEEP_BETWEEN_REQUESTS = 0.3

# Minimum cell size (in degrees) to stop recursion even if total is high
MIN_CELL_SIZE = 0.003  # ~300m


REQUEST_COUNT = 0


def query(point, radius, page=1, key=None):
    global REQUEST_COUNT
    REQUEST_COUNT += 1
    params = {
        "q": "parking",
        "type": "parking",
        "point": f"{point[0]},{point[1]}",
        "radius": int(radius),
        "page": page,
        "page_size": PAGE_SIZE,
        "fields": FIELDS,
        "key": key,
    }
    for attempt in range(3):
        try:
            resp = requests.get(API_URL, params=params, timeout=15)
            data = resp.json()
            if data.get("meta", {}).get("code") == 200:
                return data["result"]
            else:
                err = data.get("meta", {}).get("error", {})
                print(f"  [API error] {err.get('message')}")
                return None
        except requests.RequestException as e:
            print(f"  [Network error, attempt {attempt+1}/3] {e}")
            time.sleep(2)
    return None


def process_cell(lon, lat, radius_m, key, seen, results, depth=0):
    """Fetch parkings in a cell centered at (lon, lat). Recurse if too dense."""
    point = (lon, lat)

    result = query(point, radius_m, page=1, key=key)
    time.sleep(SLEEP_BETWEEN_REQUESTS)
    if result is None:
        return

    total = result.get("total", 0)

    # Decide whether to split
    cell_size_deg = (radius_m / 111000) * 2  # rough conversion m -> deg
    if total > MAX_TOTAL_PER_CELL and cell_size_deg > MIN_CELL_SIZE:
        half = cell_size_deg / 4  # offset for 4 sub-cells
        sub_radius = radius_m / 2
        for dlon in (-half, half):
            for dlat in (-half, half):
                process_cell(lon + dlon, lat + dlat, sub_radius, key, seen, results, depth + 1)
        return

    # Otherwise, paginate through this cell
    pages_needed = min((total + PAGE_SIZE - 1) // PAGE_SIZE, MAX_PAGES_PER_CELL)
    all_items = result.get("items", [])

    for page in range(2, pages_needed + 1):
        r = query(point, radius_m, page=page, key=key)
        time.sleep(SLEEP_BETWEEN_REQUESTS)
        if r is None:
            break
        all_items.extend(r.get("items", []))

    new_count = 0
    for item in all_items:
        item_id = item.get("id")
        if item_id and item_id not in seen:
            seen.add(item_id)
            results.append(item)
            new_count += 1

    print(f"  Cell ({lon:.4f},{lat:.4f}) r={radius_m}m total={total} -> +{new_count} new "
          f"(depth={depth}, requests so far={REQUEST_COUNT})")

    # Checkpoint every 20 requests so we don't lose progress if interrupted
    if REQUEST_COUNT % 20 == 0:
        save_csv(results, "parkings_almaty_checkpoint.csv")


def flatten_item(item):
    """Convert a raw API item into a flat dict for CSV/Sheets."""
    point = item.get("point", {})
    capacity = item.get("capacity", {})
    schedule = item.get("schedule", {})

    if "_raw" in schedule:
        hours = schedule["_raw"]
    elif schedule.get("is_24x7"):
        hours = "24/7"
    else:
        days_hours = []
        for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
            d = schedule.get(day)
            if d and d.get("working_hours"):
                wh = d["working_hours"][0]
                days_hours.append(f"{day} {wh['from']}-{wh['to']}")
        hours = "; ".join(days_hours) if days_hours else ""

    special = capacity.get("special_spaces", [])
    special_str = "; ".join(f"{s.get('name')}: {s.get('count')}" for s in special)

    return {
        "id": item.get("id", ""),
        "name": item.get("name", ""),
        "full_name": item.get("full_name", ""),
        "lat": point.get("lat", ""),
        "lon": point.get("lon", ""),
        "is_paid": item.get("is_paid", ""),
        "capacity_total": capacity.get("total", ""),
        "capacity_special": special_str,
        "subtype": item.get("subtype", ""),
        "purpose": item.get("purpose", ""),
        "schedule": hours,
        "gis_url": f"https://2gis.kz/almaty/firm/{item.get('id', '')}",
    }


FIELDNAMES = [
    "id", "name", "full_name", "lat", "lon", "is_paid",
    "capacity_total", "capacity_special", "subtype", "purpose",
    "schedule", "gis_url",
]


def save_csv(results, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for item in results:
            writer.writerow(flatten_item(item))


REFINE_MAX_TOTAL = 30
REFINE_MIN_CELL_SIZE = 0.002  # ~200m


def process_cell_recursive(lon, lat, radius_m, key, seen, results, depth=0, max_depth=4):
    """Like process_cell, but recursively splits dense cells (used for hotspots)."""
    point = (lon, lat)
    result = query(point, radius_m, page=1, key=key)
    time.sleep(SLEEP_BETWEEN_REQUESTS)
    if result is None:
        return

    total = result.get("total", 0)
    cell_size_deg = (radius_m / 111000) * 2

    if total > REFINE_MAX_TOTAL and cell_size_deg > REFINE_MIN_CELL_SIZE and depth < max_depth:
        half = cell_size_deg / 4
        sub_radius = radius_m / 2
        for dlon in (-half, half):
            for dlat in (-half, half):
                process_cell_recursive(lon + dlon, lat + dlat, sub_radius, key, seen, results, depth + 1, max_depth)
        return

    pages_needed = min((total + PAGE_SIZE - 1) // PAGE_SIZE, MAX_PAGES_PER_CELL)
    all_items = result.get("items", [])
    for page in range(2, pages_needed + 1):
        r = query(point, radius_m, page=page, key=key)
        time.sleep(SLEEP_BETWEEN_REQUESTS)
        if r is None:
            break
        all_items.extend(r.get("items", []))

    new_count = 0
    for item in all_items:
        item_id = item.get("id")
        if item_id and item_id not in seen:
            seen.add(item_id)
            results.append(item)
            new_count += 1

    print(f"  Cell ({lon:.4f},{lat:.4f}) r={radius_m}m total={total} -> +{new_count} new "
          f"(depth={depth}, requests so far={REQUEST_COUNT})")


def load_existing_csv(path, seen, results):
    """Load previously saved CSV so refine pass dedupes against it."""
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                item_id = row.get("id")
                if item_id and item_id not in seen:
                    seen.add(item_id)
                    # Reconstruct a minimal "item"-like dict so flatten_item works later
                    results.append({
                        "id": row["id"],
                        "name": row["name"],
                        "full_name": row["full_name"],
                        "point": {"lat": row["lat"], "lon": row["lon"]},
                        "is_paid": row["is_paid"] == "True",
                        "capacity": {"total": row["capacity_total"]},
                        "subtype": row["subtype"],
                        "purpose": row["purpose"],
                        "schedule": {"_raw": row["schedule"]},  # placeholder, see flatten note
                    })
        print(f"Loaded {len(results)} existing items from {path}")
    except FileNotFoundError:
        print(f"No existing file {path} found, starting fresh.")


# Hotspot cells from the first full run that hit the 30-item cap
HOTSPOT_CELLS = [
    (76.9010, 43.2380, 1500),
    (76.9280, 43.2380, 1500),
    (76.9280, 43.2650, 1500),
    (76.9550, 43.2380, 1500),
    (76.9550, 43.2650, 1500),
]


def main():
    if len(sys.argv) < 2:
        print("Usage: python parking_scraper.py YOUR_API_KEY [--test]")
        sys.exit(1)

    api_key = sys.argv[1]
    test_mode = "--test" in sys.argv

    seen = set()
    results = []

    refine_mode = "--refine" in sys.argv

    if refine_mode:
        load_existing_csv("parkings_almaty.csv", seen, results)
        print(f"Refining {len(HOTSPOT_CELLS)} hotspot cells (recursive split)...")
        for lon, lat, radius_m in HOTSPOT_CELLS:
            process_cell_recursive(lon, lat, radius_m, api_key, seen, results)
        print(f"\nTotal unique parkings after refine: {len(results)}")
        print(f"Total API requests made: {REQUEST_COUNT}")
        save_csv(results, "parkings_almaty_refined.csv")
        print("Saved to parkings_almaty_refined.csv")
        return

    if test_mode:
        # Quick test: just a few cells in the center
        print("TEST MODE: scanning a small area near the city center")
        centers = [
            (76.945, 43.238),
            (76.95, 43.24),
            (76.94, 43.235),
        ]
        for lon, lat in centers:
            process_cell(lon, lat, 1000, api_key, seen, results)
    else:
        # Full coverage: grid with ~1.5km initial radius (~3km cells)
        step_deg = 0.027  # ~3km
        radius_m = 1500
        lon = LON_MIN
        cell_num = 0
        total_cells = int((LON_MAX - LON_MIN) / step_deg + 1) * int((LAT_MAX - LAT_MIN) / step_deg + 1)
        print(f"Starting full scan: ~{total_cells} top-level cells")
        try:
            while lon < LON_MAX:
                lat = LAT_MIN
                while lat < LAT_MAX:
                    cell_num += 1
                    print(f"[{cell_num}/{total_cells}] cell at ({lon:.4f}, {lat:.4f})")
                    process_cell(lon, lat, radius_m, api_key, seen, results)
                    lat += step_deg
                lon += step_deg
        except KeyboardInterrupt:
            print("\nInterrupted! Saving partial results...")
            save_csv(results, "parkings_almaty_partial.csv")
            print(f"Saved {len(results)} parkings to parkings_almaty_partial.csv "
                  f"({REQUEST_COUNT} API requests used)")
            sys.exit(0)

    print(f"\nTotal unique parkings found: {len(results)}")
    print(f"Total API requests made: {REQUEST_COUNT}")

    out_path = "parkings_almaty.csv"
    save_csv(results, out_path)
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
