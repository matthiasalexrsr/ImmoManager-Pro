"""Deterministic plain-text letters using the existing ReportLab print theme."""

import hashlib
import re
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from mietvertrag_wizard_fastapi_reportlab_pro.mietvertrag_wizard.pdf_theme import contract_styles

PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def render_text(body: str, context: dict[str, str]) -> str:
    def replace(match):
        name = match.group(1)
        if name not in context:
            raise ValueError("Unbekannter Vorlagenplatzhalter. Vorlage vor der Freigabe prüfen.")
        return context[name]
    rendered = PLACEHOLDER.sub(replace, body)
    if "{{" in rendered or "}}" in rendered:
        raise ValueError("Ungültiger Vorlagenplatzhalter.")
    return rendered


def render_pdf(review: dict) -> bytes:
    # Deliberately no current timestamp, random identifier or automatic wording.
    # SHA remains identical when the same approved review is reopened later.
    output = BytesIO()
    styles = contract_styles()
    document = SimpleDocTemplate(output, pagesize=A4, title=review["data"]["subject"], invariant=1,
        author="ImmoManager", leftMargin=50, rightMargin=50, topMargin=50, bottomMargin=50)
    data = review["data"]
    blocks = [Paragraph(escape(data["recipient_name"]), styles["base"]),
        Paragraph(escape(data["recipient_address"]).replace("\n", "<br/>"), styles["base"]),
        Spacer(1, 20), Paragraph(escape(data["letter_date"]), styles["small"]),
        Paragraph(escape(data["subject"]), styles["label"]), Spacer(1, 12)]
    blocks.extend(Paragraph(escape(line).replace("\n", "<br/>"), styles["base"])
                  if line else Spacer(1, 10) for line in review["rendered_body"].split("\n\n"))
    document.build(blocks)
    return output.getvalue()


def pdf_hash(review: dict) -> str:
    return hashlib.sha256(render_pdf(review)).hexdigest()
