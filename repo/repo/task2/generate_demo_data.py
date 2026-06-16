"""
Generates a synthetic input CSV for the WhatsApp dry-run demo.

IMPORTANT: phone numbers here are NOT real. They are sequential
placeholders (+7700000001, +7700000002, ...) used only to demonstrate
that the sender can process a full-volume table (572 rows from the
parking dataset of task 1) without ever attempting a real send.

Usage:
    python generate_demo_data.py [parking_csv] [output_csv]

Defaults: parking_csv = parkings_almaty_clean.csv
          output_csv  = demo_input.csv
"""

import sys
import csv

PHONE_PREFIX = "+7700000"  # + sequential index, clearly synthetic


def main():
    in_path = sys.argv[1] if len(sys.argv) > 1 else "parkings_almaty_clean.csv"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "demo_input.csv"

    with open(in_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    out_rows = []
    for i, r in enumerate(rows, 1):
        phone = f"{PHONE_PREFIX}{i:03d}"  # +7700000001, +7700000002, ...
        message = (
            f"{r['название']}, {r['район']}, "
            f"{'платная' if r['платная'] == 'Да' else 'бесплатная'}, "
            f"мест: {r['мест_всего']}. {r['ссылка_2гис']}"
        )
        out_rows.append({"phone": phone, "message": message})

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["phone", "message"])
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"Generated {len(out_rows)} synthetic rows -> {out_path}")
    print("NOTE: phone numbers are sequential placeholders, NOT real numbers.")


if __name__ == "__main__":
    main()
