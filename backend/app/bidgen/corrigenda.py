"""Synthetic corrigenda, written the way Indian tender amendments actually read.

Section 9.2's argument applies here too: the outcome is fixed before the prose.
Each `CorrigendumSpec` states exactly which parent fields it amends and to what,
so the diff the pipeline produces can be compared against a key rather than eyeballed.

The prose is deliberately awkward in the ways real corrigenda are -- the change
is stated once in a table and again in a paragraph, dates are written DD.MM.YYYY,
the tender reference is repeated with different spacing, and there is a page of
boilerplate about all other terms remaining unchanged. An amendment printed as a
tidy JSON-shaped list would not test the extractor against anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["CorrigendumSpec", "build_pages", "render_pdf"]


@dataclass(frozen=True)
class CorrigendumSpec:
    """One amendment, with its answer key."""

    corrigendum_id: str
    parent_tender_ref: str
    authority: str
    authority_address: str
    work_title: str
    issued_date: str                      # as printed, DD.MM.YYYY
    issued_date_iso: str
    #: field_path -> (old as printed, new as printed). The answer key.
    amendments: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: Changes stated in prose that map to no notification field we hold.
    unmapped_notes: tuple[str, ...] = ()
    reason: str = "administrative reasons and requests received from prospective bidders"


_SUBJECT_LINES = {
    "submission_deadline": "Last date and time for submission of bids",
    "pre_bid_query_deadline": "Last date for receipt of pre-bid queries",
    "emd_amount": "Earnest Money Deposit (EMD)",
    "contract_value_estimate": "Estimated cost put to tender",
}


def build_pages(spec: CorrigendumSpec) -> list[str]:
    """The corrigendum, page by page."""
    rows = [
        (
            f"{index}",
            _SUBJECT_LINES.get(path, path),
            old,
            new,
        )
        for index, (path, (old, new)) in enumerate(spec.amendments.items(), start=1)
    ]

    width_subject = max([28] + [len(r[1]) for r in rows]) + 2
    width_old = max([18] + [len(r[2]) for r in rows]) + 2
    table = "\n".join(
        [
            f"{'Sl.':<5}{'Description':<{width_subject}}{'As per original':<{width_old}}As amended",
            "-" * (5 + width_subject + width_old + 24),
        ]
        + [
            f"{r[0]:<5}{r[1]:<{width_subject}}{r[2]:<{width_old}}{r[3]}"
            for r in rows
        ]
    )

    cover = f"""{spec.authority.upper()}
{spec.authority_address}




{spec.corrigendum_id}




Sub : {spec.work_title} — Corrigendum

Ref : Tender Notice No. {spec.parent_tender_ref}


Dated : {spec.issued_date}




In partial modification of the tender notice cited under reference above, and
consequent upon {spec.reason}, the following amendments are hereby notified to
all prospective bidders.

This corrigendum shall form an integral part of the tender document. All other
terms, conditions and specifications of the original tender notice shall remain
unchanged."""

    amendments_page = f"""AMENDMENTS

The following amendments are made to Tender Notice No. {spec.parent_tender_ref}:

{table}


{_prose(spec)}"""

    closing = f"""GENERAL

1. This corrigendum shall be read in conjunction with the original tender notice
   No. {spec.parent_tender_ref} and forms an integral part thereof.

2. Save as expressly amended herein, all other terms, conditions, specifications
   and annexures of the original tender document remain unaltered and in full
   force.

3. Bidders who have already submitted their bids may withdraw and resubmit them
   in accordance with the revised schedule notified above. No claim on account of
   the extension shall lie against this office.

4. This corrigendum is being hosted on the e-procurement portal and on the
   official website of this office. Bidders are advised to check both regularly
   for further corrigenda, if any.




                                                    Sd/-
                                        Superintending Engineer
                                        {spec.authority}"""

    return [cover, amendments_page, closing]


def _prose(spec: CorrigendumSpec) -> str:
    """The same changes restated in paragraphs, as real corrigenda do."""
    lines = []
    for index, (path, (old, new)) in enumerate(spec.amendments.items(), start=1):
        subject = _SUBJECT_LINES.get(path, path)
        if "deadline" in path:
            lines.append(
                f"{index}. The {subject.lower()}, which was earlier notified as "
                f"{old}, is hereby extended to {new}. Bids received after the "
                "revised date and time shall not be entertained under any "
                "circumstances."
            )
        else:
            lines.append(
                f"{index}. In Clause relating to {subject.lower()}, for the "
                f"figure “{old}” appearing in the tender notice, the "
                f"figure “{new}” shall be read and substituted in its "
                "place."
            )
    for note in spec.unmapped_notes:
        lines.append(f"{len(lines) + 1}. {note}")
    return "\n\n".join(lines)


def render_pdf(spec: CorrigendumSpec, out_dir: Path) -> Path:
    """Render to a real PDF, so extraction meets real pagination and a text layer."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = spec.corrigendum_id.replace("/", "_").replace(" ", "_")
    path = out_dir / f"{safe}.pdf"

    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        leftMargin=20 * mm,
        rightMargin=18 * mm,
        title=f"{spec.corrigendum_id} — {spec.parent_tender_ref}",
        author=spec.authority,
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9.5, leading=13)
    # Monospaced for the amendment table so column alignment survives into the
    # PDF text layer, which is what the parser reads back.
    mono = ParagraphStyle("mono", parent=body, fontName="Courier", fontSize=8.5, leading=11)

    story = []
    pages = build_pages(spec)
    for index, page in enumerate(pages):
        for block in page.strip().split("\n\n"):
            tabular = "----" in block or "Sl." in block
            story.append(Paragraph(block.replace("\n", "<br/>"), mono if tabular else body))
            story.append(Spacer(1, 5))
        if index < len(pages) - 1:
            story.append(PageBreak())
    doc.build(story)
    return path
