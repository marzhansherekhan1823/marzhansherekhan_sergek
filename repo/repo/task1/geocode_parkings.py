"""
Reverse-geocode each parking record using the 2GIS Geocoder endpoint
(items/geocode), extracting administrative context: district and
microdistrict (living_area). A true street-level address is not
available for these standalone "parking" type objects in 2GIS, so we
fall back to the nearest admin divisions, which still gives useful
location context for the spreadsheet.

Usage:
    python geocode_parkings.py YOUR_API_KEY [input.csv] [output.csv]

Defaults: input.csv = parkings_almaty_refined.csv
          output.csv = parkings_almaty_geocoded.csv
"""

import sys
import time
import csv
import requests

GEOCODE_URL = "https://catalog.api.2gis.com/3.0/items/geocode"
SLEEP_BETWEEN_REQUESTS = 0.3

REQUEST_COUNT = 0


def reverse_geocode(lat, lon, key):
    global REQUEST_COUNT
    REQUEST_COUNT += 1
    params = {
        "lat": lat,
        "lon": lon,
        "fields": "items.adm_div",
        "key": key,
    }
    for attempt in range(3):
        try:
            resp = requests.get(GEOCODE_URL, params=params, timeout=15)
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


def extract_admin_context(result):
    """Pull district and microdistrict (living_area) names from a geocode result."""
    district = ""
    microdistrict = ""
    if not result:
        return district, microdistrict

    for item in result.get("items", []):
        if item.get("type") == "adm_div":
            subtype = item.get("subtype")
            if subtype == "district" and not district:
                district = item.get("name", "")
            elif subtype == "living_area" and not microdistrict:
                microdistrict = item.get("name", "")

    # Some items embed adm_div as a list directly on themselves too
    if not district or not microdistrict:
        for item in result.get("items", []):
            for adm in item.get("adm_div", []) or []:
                subtype = adm.get("type") or adm.get("subtype")
                if subtype == "district" and not district:
                    district = adm.get("name", "")
                elif subtype == "living_area" and not microdistrict:
                    microdistrict = adm.get("name", "")

    return district, microdistrict


def main():
    if len(sys.argv) < 2:
        print("Usage: python geocode_parkings.py YOUR_API_KEY [input.csv] [output.csv]")
        sys.exit(1)

    api_key = sys.argv[1]
    in_path = sys.argv[2] if len(sys.argv) > 2 else "parkings_almaty_refined.csv"
    out_path = sys.argv[3] if len(sys.argv) > 3 else "parkings_almaty_geocoded.csv"

    with open(in_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames + ["district", "microdistrict"]

    print(f"Loaded {len(rows)} rows from {in_path}")

    try:
        for i, row in enumerate(rows, 1):
            lat, lon = row["lat"], row["lon"]
            result = reverse_geocode(lat, lon, api_key)
            district, microdistrict = extract_admin_context(result)
            row["district"] = district
            row["microdistrict"] = microdistrict

            if i % 20 == 0 or i == len(rows):
                print(f"[{i}/{len(rows)}] requests so far={REQUEST_COUNT} "
                      f"-> district='{district}', microdistrict='{microdistrict}'")
                # checkpoint
                with open(out_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows[:i])

            time.sleep(SLEEP_BETWEEN_REQUESTS)
    except KeyboardInterrupt:
        print("\nInterrupted! Saving partial results...")

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone. Total geocode requests: {REQUEST_COUNT}")
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
