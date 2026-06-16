"""
Final cleanup pass on the geocoded parking dataset.

Changes:
- Drop redundant columns: full_name (= "Almaty, " + name, no extra info),
  purpose (always "car"), subtype (always "ground" — noted as a known
  limitation, not removed but kept since it IS informative: it tells us
  our dataset currently contains no multilevel/underground parkings).
- Extract zone_id from name (e.g. "Парковка №6047" -> "6047"). This makes
  explicit that rows sharing a name are entries within the same municipal
  paid-parking zone (spread across real, distinct coordinates), not
  duplicate/junk rows.
- Rename headers to clear Russian labels for the spreadsheet.
- Sort by district, then zone_id, then name for readability.

Usage:
    python clean_dataset.py [input.csv] [output.csv]
"""

import sys
import csv
import re

ZONE_PATTERN = re.compile(r"№(\d+)")

COLUMN_RENAME = {
    "id": "id_2gis",
    "name": "название",
    "lat": "широта",
    "lon": "долгота",
    "is_paid": "платная",
    "capacity_total": "мест_всего",
    "capacity_special": "спец_места",
    "subtype": "тип_парковки",
    "schedule": "часы_работы",
    "gis_url": "ссылка_2гис",
    "district": "район",
    "microdistrict": "микрорайон",
    "zone_id": "номер_зоны",
}

FINAL_COLUMN_ORDER = [
    "id", "name", "zone_id", "district", "microdistrict",
    "lat", "lon", "is_paid", "capacity_total", "capacity_special",
    "subtype", "schedule", "gis_url",
]


def main():
    in_path = sys.argv[1] if len(sys.argv) > 1 else "parkings_almaty_geocoded.csv"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "parkings_almaty_clean.csv"

    with open(in_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for r in rows:
        m = ZONE_PATTERN.search(r["name"])
        r["zone_id"] = m.group(1) if m else ""
        # is_paid as Да/Нет for readability in the sheet
        r["is_paid"] = "Да" if r["is_paid"] == "True" else "Нет"

    rows.sort(key=lambda r: (r["district"], r["zone_id"].zfill(6), r["name"]))

    fieldnames = [COLUMN_RENAME[c] for c in FINAL_COLUMN_ORDER]

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(fieldnames)
        for r in rows:
            writer.writerow([r[c] for c in FINAL_COLUMN_ORDER])

    print(f"Cleaned {len(rows)} rows.")
    print(f"Dropped columns: full_name, purpose")
    print(f"Added column: zone_id (extracted from {sum(1 for r in rows if r['zone_id'])}/{len(rows)} names)")
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
