"""Gap report as a document a vendor can hand to their own team (Section 4.6).

A compliance report read on a screen and then quoted from memory is how a
requirement gets missed. The people who actually attach the documents -- the
accounts clerk who produces the audited balance sheet, the director who signs
the power of attorney -- are usually not the person who ran the check, so the
report has to leave the tool.

Both formats render the SAME content from the same `GapReport`, so a vendor
choosing DOCX over PDF does not get a different answer. The renderers share
`_sections()`, which is where the content decisions live; the format modules
below only decide how it looks.

What deliberately survives the export:

  * every clause reference. A to-do without the clause it comes from cannot be
    checked against the tender by whoever receives it.
  * the four-way verdict, including `needs_review` and `not_checked`. Flattening
    those to pass/fail on the way out would undo the whole point of having them.
  * the completion count with its "this is not a score" caveat attached. The
    number travels; so does the sentence that stops it being read as a grade.
  * the data-quality banner, if any. A report built on a thin extraction says so
    on the page, not only in the app.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from app.compliance.models import ActionGroup, CheckStatus, GapReport, Severity

__all__ = ["export_pdf", "export_docx", "ExportContext"]


@dataclass
class ExportContext:
    """Everything on the report that does not live on the GapReport itself."""

    tender_title: str | None = None
    issuing_authority: str | None = None
    submission_deadline: date | None = None
    data_quality_banner: str | None = None
    staleness_banner: str | None = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    extracted_by: str | None = None


# ReportLab's built-in Type 1 fonts are Latin-1: they have no glyph for the
# rupee sign, and render it as a filled box. Registering a Unicode TTF would fix
# it on this machine and silently reintroduce the boxes on a Linux deploy with a
# different font set, so the export substitutes instead.
#
# "Rs." is not a compromise here. Indian tenders print it far more often than
# the symbol, and this document is going to an Indian procurement team.
_PDF_SUBSTITUTIONS = (
    ("\u20b9", "Rs. "),   # rupee sign
    ("\u2014", "-"),      # em dash
    ("\u2013", "-"),      # en dash
    ("\u201c", '"'), ("\u201d", '"'),
    ("\u2018", "'"), ("\u2019", "'"),
    ("\u26a0", "!"),      # warning sign
    ("\u00b7", "-"),      # middle dot
    ("\u202f", " "),      # narrow no-break space, which some models emit
)


def _pdf_text(value) -> str:
    """Make a string safe for ReportLab's Latin-1 core fonts.

    Applied at every point where extracted text reaches the PDF, because the
    text comes from tender documents and from model output -- neither of which
    is under our control, and both of which contain the rupee sign constantly.
    """
    text = "" if value is None else str(value)
    for source, target in _PDF_SUBSTITUTIONS:
        text = text.replace(source, target)
    # Anything else outside Latin-1 becomes a box too. Dropped rather than
    # guessed at: a box in a compliance report reads as corruption.
    return text.encode("latin-1", "replace").decode("latin-1").replace("?", "?")


_STATUS_LABEL = {
    CheckStatus.MATCH: "Met",
    CheckStatus.PARTIAL: "Confirm",
    CheckStatus.MISSING: "Missing",
    CheckStatus.MANUAL_CHECK: "Check yourself",
    CheckStatus.NOT_ASSESSABLE: "Could not read",
}

_VERDICT_LABEL = {
    "compliant": "No blocking issues found",
    "needs_review": "No blocking issues, but items need your review",
    "not_compliant": "Blocking issues found — this bid would be rejected as it stands",
    "not_checked": "Nothing could be checked — see data quality below",
}

_GROUP_HEADING = {
    ActionGroup.HARD_FAIL: "Cannot be fixed by attaching a document",
    ActionGroup.UPLOAD: "Documents to attach",
    ActionGroup.CLARIFY: "Values to state clearly in your bid",
    ActionGroup.VERIFY: "To check yourself",
}


def _sections(report: GapReport, context: ExportContext) -> dict:
    """The content, decided once and rendered twice."""
    completion = report.completion
    by_group: dict[ActionGroup, list] = {}
    for action in report.action_list:
        by_group.setdefault(action.group, []).append(action)

    return {
        "title": "Tender compliance check",
        "subtitle": context.tender_title or report.tender_id,
        "meta": [
            ("Tender reference", report.tender_id),
            ("Issuing authority", context.issuing_authority or "not stated"),
            ("Bidder", report.vendor_name or report.vendor_id),
            (
                "Submission deadline",
                context.submission_deadline.strftime("%d %B %Y")
                if context.submission_deadline
                else "not stated",
            ),
            ("Report generated", context.generated_at.strftime("%d %B %Y, %H:%M UTC")),
        ],
        "verdict": _VERDICT_LABEL.get(report.verdict, report.verdict),
        "verdict_key": report.verdict,
        "completion": completion,
        "banners": [b for b in (context.staleness_banner, context.data_quality_banner) if b],
        "groups": [
            (_GROUP_HEADING[group], by_group[group])
            for group in (
                ActionGroup.HARD_FAIL, ActionGroup.UPLOAD,
                ActionGroup.CLARIFY, ActionGroup.VERIFY,
            )
            if by_group.get(group)
        ],
        "items": report.items,
        "counts": report.counts,
    }


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #
def export_pdf(report: GapReport, context: ExportContext | None = None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
        Spacer, Table, TableStyle,
    )

    context = context or ExportContext()
    data = _sections(report, context)

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=18 * mm, bottomMargin=18 * mm,
        leftMargin=18 * mm, rightMargin=18 * mm,
        title=f"Compliance check — {report.tender_id}",
        author="BidSense",
    )
    sheet = getSampleStyleSheet()
    ink = colors.HexColor("#12161f")
    muted = colors.HexColor("#5b6472")

    h1 = ParagraphStyle("h1", parent=sheet["Title"], fontSize=17, leading=21,
                        alignment=TA_LEFT, textColor=ink, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=sheet["BodyText"], fontSize=10.5,
                         textColor=muted, spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=sheet["Heading2"], fontSize=12, leading=15,
                        textColor=ink, spaceBefore=14, spaceAfter=6)
    body = ParagraphStyle("body", parent=sheet["BodyText"], fontSize=9.5, leading=13.5)
    small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=11.5, textColor=muted)

    story: list = [Paragraph(_pdf_text(data["title"]), h1),
                   Paragraph(_pdf_text(data["subtitle"]), sub)]

    meta = Table(
        [[Paragraph(f"<b>{_pdf_text(k)}</b>", small), Paragraph(_pdf_text(v), small)]
         for k, v in data["meta"]],
        colWidths=[42 * mm, None], hAlign="LEFT",
    )
    meta.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    story += [meta, Spacer(1, 10),
              HRFlowable(width="100%", color=colors.HexColor("#dfe3ea")), Spacer(1, 10)]

    # Verdict, coloured by outcome rather than uniformly green.
    tone = {
        "not_compliant": colors.HexColor("#b4232a"),
        "needs_review": colors.HexColor("#8a6100"),
        "compliant": colors.HexColor("#1c6b45"),
        "not_checked": colors.HexColor("#5b6472"),
    }.get(data["verdict_key"], ink)
    story.append(Paragraph(f'<font color="{tone}"><b>{_pdf_text(data["verdict"])}</b></font>',
                           ParagraphStyle("v", parent=body, fontSize=12, leading=16)))

    completion = data["completion"]
    story += [
        Spacer(1, 4),
        Paragraph(_pdf_text(f"<b>{completion.label}</b>"
                  + (f" - {completion.undetermined} not established either way"
                     if completion.undetermined else "")), body),
        Paragraph(_pdf_text(completion.caveat), small),
    ]

    for banner in data["banners"]:
        story += [Spacer(1, 6),
                  Paragraph(f'<font color="#8a6100">{_pdf_text("! " + banner)}</font>', small)]

    # The to-do list first: it is what the reader has to act on.
    for heading, actions in data["groups"]:
        rows = [[Paragraph(f"<b>{_pdf_text(heading)}</b>", body), ""]]
        for action in actions:
            clause = f"clause {action.clause_ref}" if action.clause_ref else "—"
            rows.append([Paragraph(_pdf_text(action.action), body), Paragraph(_pdf_text(clause), small)])
        table = Table(rows, colWidths=[None, 28 * mm], hAlign="LEFT")
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("SPAN", (0, 0), (1, 0)),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#e6e9ef")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4f6f9")),
        ]))
        story += [Spacer(1, 12), KeepTogether([table])]

    story += [PageBreak(), Paragraph("Every requirement checked", h2)]
    rows = [[Paragraph(f"<b>{h}</b>", small) for h in
             ("Requirement", "Status", "Required", "Found", "Clause")]]
    for item in data["items"]:
        provenance = item.notification_provenance
        rows.append([
            Paragraph(_pdf_text(item.requirement), small),
            Paragraph(_STATUS_LABEL.get(item.status, item.status.value), small),
            Paragraph(_pdf_text(item.required_value or "-"), small),
            Paragraph(_pdf_text(item.found_value or "-"), small),
            Paragraph(
                _pdf_text((f"{provenance.clause_ref or '-'}"
                 + (f" p{provenance.source_page}" if provenance.source_page else ""))
                if provenance else "-"), small),
        ])
    table = Table(rows, colWidths=[58 * mm, 20 * mm, 32 * mm, 34 * mm, 20 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4f6f9")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.35, colors.HexColor("#e6e9ef")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)

    story += [
        Spacer(1, 12),
        Paragraph(
            _pdf_text(
                "Generated by BidSense"
                + (f" using {context.extracted_by}" if context.extracted_by else "")
                + ". Format and signing rules are always left to a human reviewer, "
                  "so no bid is ever reported as fully clear."), small),
    ]
    document.build(story)
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# DOCX
# --------------------------------------------------------------------------- #
def export_docx(report: GapReport, context: ExportContext | None = None) -> bytes:
    from docx import Document
    from docx.shared import Pt, RGBColor

    context = context or ExportContext()
    data = _sections(report, context)

    document = Document()
    document.core_properties.title = f"Compliance check — {report.tender_id}"
    document.core_properties.author = "BidSense"

    document.add_heading(data["title"], level=0)
    document.add_paragraph(data["subtitle"])

    table = document.add_table(rows=0, cols=2)
    table.style = "Light List Accent 1"
    for key, value in data["meta"]:
        cells = table.add_row().cells
        cells[0].text = key
        cells[1].text = str(value)

    document.add_paragraph()
    verdict = document.add_paragraph()
    run = verdict.add_run(data["verdict"])
    run.bold = True
    run.font.size = Pt(13)
    run.font.color.rgb = {
        "not_compliant": RGBColor(0xB4, 0x23, 0x2A),
        "needs_review": RGBColor(0x8A, 0x61, 0x00),
        "compliant": RGBColor(0x1C, 0x6B, 0x45),
    }.get(data["verdict_key"], RGBColor(0x33, 0x33, 0x33))

    completion = data["completion"]
    document.add_paragraph(completion.label).runs[0].bold = True
    caveat = document.add_paragraph(completion.caveat)
    caveat.runs[0].italic = True
    caveat.runs[0].font.size = Pt(8.5)

    for banner in data["banners"]:
        paragraph = document.add_paragraph(f"⚠ {banner}")
        paragraph.runs[0].font.color.rgb = RGBColor(0x8A, 0x61, 0x00)
        paragraph.runs[0].font.size = Pt(9)

    for heading, actions in data["groups"]:
        document.add_heading(heading, level=2)
        for action in actions:
            bullet = document.add_paragraph(action.action, style="List Bullet")
            if action.clause_ref:
                reference = bullet.add_run(f"  (clause {action.clause_ref})")
                reference.italic = True
                reference.font.size = Pt(8.5)

    document.add_page_break()
    document.add_heading("Every requirement checked", level=1)
    grid = document.add_table(rows=1, cols=5)
    grid.style = "Light Grid Accent 1"
    for index, label in enumerate(("Requirement", "Status", "Required", "Found", "Clause")):
        grid.rows[0].cells[index].text = label
    for item in data["items"]:
        provenance = item.notification_provenance
        cells = grid.add_row().cells
        cells[0].text = item.requirement
        cells[1].text = _STATUS_LABEL.get(item.status, item.status.value)
        cells[2].text = str(item.required_value or "—")
        cells[3].text = str(item.found_value or "—")
        cells[4].text = (
            (f"{provenance.clause_ref or '—'}"
             + (f" p{provenance.source_page}" if provenance.source_page else ""))
            if provenance else "—"
        )

    footer = document.add_paragraph(
        "Generated by BidSense"
        + (f" using {context.extracted_by}" if context.extracted_by else "")
        + ". Format and signing rules are always left to a human reviewer, so no "
          "bid is ever reported as fully clear."
    )
    footer.runs[0].font.size = Pt(8.5)
    footer.runs[0].italic = True

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
