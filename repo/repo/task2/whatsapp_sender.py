"""
WhatsApp bulk-table sender — demonstration of principle, NOT a real
bulk-messaging tool.

SAFETY DESIGN (read before touching this file):
- Default mode is dry-run: no network/automation call to WhatsApp is ever
  made. Each row is validated and logged to a CSV report.
- live mode requires the --live flag AND a separate whitelist file
  (live_whitelist.csv) containing at most LIVE_MAX_RECIPIENTS phone
  numbers. The main input table (which may have hundreds of rows) is
  NEVER used as the source of recipients in live mode — this is enforced
  in code, not just by convention, so a mistake in the input file cannot
  cause a mass send.
- live mode sends through WhatsApp Web automation (pywhatkit), which
  requires the operator to be logged into WhatsApp Web on this machine
  and to manually confirm the browser opens correctly. It is meant for
  demonstrating that the underlying technical capability works, not for
  any real outreach.

Usage:
    Dry-run (default):
        python whatsapp_sender.py --input demo_input.csv

    Live (sends to numbers in live_whitelist.csv ONLY, max 2):
        python whatsapp_sender.py --input demo_input.csv --live --whitelist live_whitelist.csv
"""

import argparse
import csv
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

LIVE_MAX_RECIPIENTS = 2

# E.164-ish phone validation: + followed by 8-15 digits.
PHONE_RE = re.compile(r"^\+\d{8,15}$")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("whatsapp_sender.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("whatsapp_sender")


@dataclass
class Result:
    phone: str
    message_preview: str
    status: str  # "ok", "invalid_number", "send_error", "skipped"
    detail: str = ""


def validate_phone(phone: str) -> bool:
    return bool(PHONE_RE.match(phone.strip()))


def load_table(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows:
        raise ValueError(f"Input file {path} is empty")
    missing = {"phone", "message"} - set(rows[0].keys())
    if missing:
        raise ValueError(f"Input file is missing required columns: {missing}")
    return rows


def run_dry_run(rows: list[dict], report_path: str) -> list[Result]:
    results = []
    for row in rows:
        phone = row.get("phone", "").strip()
        message = row.get("message", "").strip()
        preview = message[:60] + ("..." if len(message) > 60 else "")

        if not phone:
            results.append(Result(phone, preview, "invalid_number", "empty phone field"))
            log.warning("Skipped row: empty phone field")
            continue

        if not validate_phone(phone):
            results.append(Result(phone, preview, "invalid_number", "does not match +<countrycode><number>"))
            log.warning(f"Invalid phone format: {phone}")
            continue

        if not message:
            results.append(Result(phone, preview, "invalid_number", "empty message"))
            log.warning(f"Empty message for {phone}")
            continue

        # DRY RUN: no network call. Just record what *would* be sent.
        results.append(Result(phone, preview, "ok", "would send (dry-run, not sent)"))
        log.info(f"[DRY-RUN] Would send to {phone}: {preview}")

    write_report(results, report_path)
    return results


def write_report(results: list[Result], path: str):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["phone", "message_preview", "status", "detail"])
        for r in results:
            writer.writerow([r.phone, r.message_preview, r.status, r.detail])
    ok = sum(1 for r in results if r.status == "ok")
    bad = len(results) - ok
    log.info(f"Report saved to {path}: {ok} would-send, {bad} invalid/skipped")


def load_whitelist(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Whitelist file {path} not found. live mode requires an explicit "
            f"whitelist of your own/test numbers (max {LIVE_MAX_RECIPIENTS})."
        )
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if len(rows) == 0:
        raise ValueError("Whitelist file is empty.")
    if len(rows) > LIVE_MAX_RECIPIENTS:
        raise ValueError(
            f"Whitelist has {len(rows)} entries, but live mode allows at most "
            f"{LIVE_MAX_RECIPIENTS}. Refusing to proceed (mass-send protection)."
        )
    return rows


def run_live(whitelist_rows: list[dict], report_path: str) -> list[Result]:
    """
    Sends real messages via WhatsApp Web automation, ONLY to numbers found
    in the whitelist file (never the main input table).
    """
    try:
        import pywhatkit as kit
    except ImportError:
        log.error(
            "pywhatkit is not installed. Run: pip install pywhatkit --break-system-packages"
        )
        sys.exit(1)

    results = []
    for row in whitelist_rows:
        phone = row.get("phone", "").strip()
        message = row.get("message", "").strip()
        preview = message[:60] + ("..." if len(message) > 60 else "")

        if not validate_phone(phone):
            results.append(Result(phone, preview, "invalid_number", "bad format"))
            log.warning(f"Invalid phone in whitelist: {phone}")
            continue

        try:
            log.info(f"[LIVE] Sending to {phone}: {preview}")
            # sendwhatmsg_instantly opens WhatsApp Web, waits, sends, closes tab.
            kit.sendwhatmsg_instantly(
                phone_no=phone,
                message=message,
                wait_time=20,
                tab_close=True,
            )
            results.append(Result(phone, preview, "ok", "sent (live)"))
            log.info(f"Sent to {phone}")
        except Exception as e:
            # Catch-all: WhatsApp Web automation can fail for many reasons
            # (not logged in, network drop, UI changed, browser not found).
            results.append(Result(phone, preview, "send_error", str(e)))
            log.error(f"Failed to send to {phone}: {e}")

        time.sleep(2)

    write_report(results, report_path)
    return results


def main():
    parser = argparse.ArgumentParser(description="WhatsApp table sender (dry-run by default)")
    parser.add_argument("--input", required=True, help="CSV with columns: phone, message")
    parser.add_argument("--live", action="store_true", help="Enable LIVE sending (max 2 recipients, from --whitelist)")
    parser.add_argument("--whitelist", default="live_whitelist.csv", help="CSV with your own/test numbers for live mode")
    parser.add_argument("--report", default=None, help="Output report CSV path")
    args = parser.parse_args()

    if args.live:
        report_path = args.report or "live_report.csv"
        log.info("=" * 60)
        log.info("LIVE MODE — real messages will be sent.")
        log.info(f"Recipients are restricted to whitelist file: {args.whitelist}")
        log.info("=" * 60)
        try:
            whitelist_rows = load_whitelist(args.whitelist)
        except (FileNotFoundError, ValueError) as e:
            log.error(str(e))
            sys.exit(1)
        log.info(f"Whitelist loaded: {len(whitelist_rows)} recipient(s)")
        run_live(whitelist_rows, report_path)
    else:
        report_path = args.report or "dry_run_report.csv"
        log.info("DRY-RUN mode (default). No messages will be sent.")
        try:
            rows = load_table(args.input)
        except (FileNotFoundError, ValueError) as e:
            log.error(str(e))
            sys.exit(1)
        log.info(f"Loaded {len(rows)} rows from {args.input}")
        run_dry_run(rows, report_path)


if __name__ == "__main__":
    main()
