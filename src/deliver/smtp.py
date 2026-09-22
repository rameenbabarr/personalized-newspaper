from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from src.config import load_paper
from src.models import Edition


def send_pdf(edition: Edition, pdf_path: Path) -> None:
    paper = load_paper()
    send = paper["send"]
    # GMAIL_APP_PASSWORD is the documented name; RAMEEN_APP_PASSWORD is the
    # original one, still read so an existing .env keeps sending.
    password = os.environ.get("GMAIL_APP_PASSWORD") or os.environ.get("RAMEEN_APP_PASSWORD")
    if not password:
        raise RuntimeError("GMAIL_APP_PASSWORD is not set")
    lead = next((a for a in edition.articles if a.role == "lead"), None)
    headline = lead.headline if lead else "Today's edition"
    filename = f"The-Rameen-Times-{edition.date}.pdf"

    message = EmailMessage()
    message["From"] = f'{paper["paper_name"]} <{send["from"]}>'
    message["To"] = send["to"]
    message["Subject"] = f'{paper["paper_name"]}, {edition.date}'
    message.set_content(f"{edition.date}\n{headline}\n\npaper attached")
    message.add_attachment(
        pdf_path.read_bytes(),
        maintype="application",
        subtype="pdf",
        filename=filename,
    )

    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.starttls()
        smtp.login(send["from"], password.replace(" ", ""))
        smtp.send_message(message)
