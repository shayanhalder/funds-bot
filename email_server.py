"""
Flask REST API for processing Venmo emails from the pickleball club.
Receives batches of email data from a Google Apps Script webhook and adds
pickleball-related Venmo transactions to the spreadsheet.

"""

import logging
import os
import re
from datetime import datetime

from flask import Flask, request, jsonify
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import actions
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv(".env")

# Send all logs to email-log.txt
_file_handler = logging.FileHandler("email-log.txt", encoding="utf-8")
_file_handler.setLevel(logging.INFO)
_file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
logging.getLogger().setLevel(logging.INFO)
logging.getLogger().addHandler(_file_handler)

app = Flask(__name__)

PICKLEBALL_KEYWORDS = [
    "pickleball", "pickle", "pball", "tryouts", "competition", "comp",
    "tournament", "tourney", "reimbursement", "winter classic", "doubles",
    "mixed", "uci", "uc irvine",
]

# Venmo subject patterns
# "[First Last] paid you $25.00" -> Income
RE_PAID_YOU = re.compile(r"^(.+?)\s+paid you\s+\$([\d,]+(?:\.\d{2})?)\s*$", re.IGNORECASE)
# "You paid [First Last] $25.00" -> Expense
RE_YOU_PAID = re.compile(r"^You paid\s+(.+?)\s+\$([\d,]+(?:\.\d{2})?)\s*$", re.IGNORECASE)


def _is_from_venmo(from_header: str) -> bool:
    """Return True if the email is from Venmo."""
    if not from_header:
        return False
    return "venmo" in from_header.lower()


def _is_pickleball_related(body: str) -> bool:
    """Return True if the email body contains any pickleball club keyword."""
    if not body:
        return False
    body_lower = body.lower()
    return any(kw.lower() in body_lower for kw in PICKLEBALL_KEYWORDS)


def _parse_venmo_subject(subject: str) -> tuple[str, float, str] | None:
    """
    Parse Venmo subject line. Returns (person_name, amount, category) or None.
    category is "Income" or "Expense".
    """
    if not subject or not subject.strip():
        return None
    subject = subject.strip()

    # Someone paid you
    m = RE_PAID_YOU.match(subject)
    if m:
        person = m.group(1).strip()
        amount_str = m.group(2).replace(",", "")
        try:
            amount = float(amount_str)
            return (person, amount, "Income")
        except ValueError:
            return None

    # You paid someone
    m = RE_YOU_PAID.match(subject)
    if m:
        person = m.group(1).strip()
        amount_str = m.group(2).replace(",", "")
        try:
            amount = -1 * float(amount_str)
            return (person, amount, "Expense")
        except ValueError:
            return None

    return None


def _format_date(email_date) -> str:
    """Convert email date to YYYY-MM-DD for the spreadsheet."""
    if isinstance(email_date, str):
        try:
            # ISO format from JS Date
            dt = datetime.fromisoformat(email_date.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return datetime.utcnow().strftime("%Y-%m-%d")
    return datetime.utcnow().strftime("%Y-%m-%d")


def _get_sheet_client():
    """Build Google Sheets API client using service account from env."""
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    service_account_file = os.getenv("SERVICE_ACCOUNT_FILE")
    if not service_account_file:
        raise RuntimeError("SERVICE_ACCOUNT_FILE not set in environment")
    credentials = Credentials.from_service_account_file(
        service_account_file, scopes=scopes
    )
    service = build("sheets", "v4", credentials=credentials)
    return service.spreadsheets(), service


@app.route("/process-emails", methods=["POST"])
def webhook():
    """
    Receive a batch of emails from the Google Apps Script trigger.
    Body: JSON { "emails": [ { "id", "threadId", "subject", "from", "date", "body", "link" }, ... ] }
    """
    payload = request.get_json(silent=True)
    if not payload or "emails" not in payload:
        return jsonify({"error": "Missing 'emails' in JSON body"}), 400

    emails = payload["emails"]
    if not isinstance(emails, list):
        return jsonify({"error": "'emails' must be an array"}), 400

    try:
        sheet, service = _get_sheet_client()
    except Exception as e:
        return jsonify({"error": f"Google Sheets setup failed: {e}"}), 500

    added = []
    skipped = []

    for email in emails:
        email_id = email.get("id", "?")
        from_header = email.get("from", "")
        subject = email.get("subject", "")
        body = email.get("body", "") or ""
        date = email.get("date")
        link = email.get("link", "")
        logger.info(
            "Email: subject=%r body=%r",
            subject, body
        )

        if not _is_from_venmo(from_header):
            skipped.append({"id": email_id, "reason": "not_from_venmo"})
            continue

        if not _is_pickleball_related(body):
            skipped.append({"id": email_id, "reason": "not_pickleball_related"})
            continue

        parsed = _parse_venmo_subject(subject)
        if not parsed:
            skipped.append({"id": email_id, "reason": "could_not_parse_subject"})
            continue

        person, amount, category = parsed
        date_str = _format_date(date)
        match = re.search(r'\n00\n\n(.*?)\n\nSee transaction \n', body, re.DOTALL)
        notes = match.group(1).strip() if match else ""
        account = "Venmo"

        success = actions.add_transaction(
            sheet, service,
            date=date_str,
            category=category,
            amount=amount,
            notes=notes,
            person=person,
            account=account,
        )
        if success:
            added.append({
                "id": email_id,
                "person": person,
                "amount": amount,
                "category": category,
            })
        else:
            skipped.append({"id": email_id, "reason": "add_transaction_failed"})

    return jsonify({
        "processed": len(emails),
        "added": len(added),
        "skipped": len(skipped),
        "added_details": added,
        "skipped_details": skipped,
    }), 200


@app.route("/health", methods=["GET"])
def health():
    """Health check for deployment."""
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
