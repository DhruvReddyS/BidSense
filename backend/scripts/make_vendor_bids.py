"""Generate synthetic vendor bids with known ground truth (Section 9.2).

Section 9.2.1 is the important part: **the compliance outcome is decided before
the document is written**, so afterwards the pipeline's verdict can be compared
against an answer key. Generating documents first and labelling them afterwards
gives you files with nothing to measure against.

Each entry below therefore carries `intended_status` and `intended_reason`, and
those are written to `data/tracking_vendors.csv` (Section 9.4, Tab 2) alongside
the rendered documents.

    python -m scripts.make_vendor_bids --out ../data/vendors
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@dataclass
class VendorSpec:
    """A planned bid: the intended outcome first, the content second."""

    vendor_id: str
    notification_id: str
    vendor_name: str
    intended_status: str            # 'pass' | 'eliminate'
    intended_reason: str            # '' when passing
    intended_failed_clause: str     # '' when passing
    writeup_quality: str            # 'strong' | 'weak' -- for the 5.4 fluency guard
    turnover: list[tuple[str, str]]
    years_in_business: str
    net_worth: str
    similar_order_value: str
    similar_order_client: str
    quoted_price: str
    certifications: list[tuple[str, str]] = field(default_factory=list)
    documents: list[tuple[str, bool]] = field(default_factory=list)
    is_blacklisted: bool = False
    technical_approach: str = ""


# --------------------------------------------------------------------------- #
# GHMC LED street lighting — TENDER No.01/SE(Electrical)/GHMC/2024-25
# Extracted requirements: turnover >= Rs. 3,00,00,000; one similar supply order
# >= Rs. 2.39 Cr; positive net worth; not debarred; PAN, GST, EMD proof,
# manufacturer's authorisation, technical specification sheet.
# --------------------------------------------------------------------------- #
STANDARD_DOCS = [
    ("Permanent Account Number (PAN)", True),
    ("Copy of GST registration certificate", True),
    ("Proof of Payment of EMD", True),
    ("Manufacturers authorization form", True),
    ("Technical Specification for Item 35W, 70W & 110W LED Fittings", True),
    ("Power of Attorney", True),
    ("Audited Balance Sheets", True),
]

STRONG_APPROACH = """Our delivery methodology for this contract is organised in \
four phases, each with a named owner and a defined exit criterion.

Phase 1 - Survey and validation (weeks 1-3). We will conduct a pole-by-pole \
survey across all GHMC circles, recording existing fitting wattage, pole height, \
arm length and feeder pillar mapping into a GIS-tagged asset register. No \
fitting is despatched until its location record is validated, which is how we \
avoid the wattage mismatches that commonly cause re-work on street lighting \
contracts.

Phase 2 - Supply and pre-dispatch inspection (weeks 2-14). LED fittings will be \
manufactured against the technical specification for 35W, 70W and 110W items. \
Every batch undergoes photometric testing at an NABL-accredited laboratory, and \
we will submit LM-79 and LM-80 test reports to the Engineer-in-Charge before \
despatch. Batches are released only after written clearance.

Phase 3 - Installation (weeks 4-22, overlapping supply). Installation proceeds \
circle by circle using four crews working night shifts to avoid daytime traffic \
disruption on arterial roads. Each crew carries a supervisor certified under the \
Telangana Electrical Licensing Board.

Phase 4 - Commissioning and handover (weeks 20-26). Illumination levels will be \
measured against IS 1944 at sample points in each circle, with lux readings \
recorded and jointly signed. We will hand over the complete asset register, \
warranty certificates and a defect-reporting protocol with a 24-hour response \
commitment for the full warranty period."""

WEAK_APPROACH = """We are a reputed and well established firm in the field of \
electrical works with many years of experience. We have executed several \
prestigious projects to the entire satisfaction of our clients.

We will supply the LED street light fittings as per the specifications given in \
the tender document. All materials will be of best quality and of reputed make. \
Installation will be carried out by our experienced and skilled technicians in a \
workmanlike manner.

We assure the department of our best services at all times and shall complete \
the work within the stipulated time period. Quality is our motto and customer \
satisfaction is our aim. We hope our offer will be found suitable and look \
forward to receiving your valued order."""


GHMC = "NOTIF_supply_01"

VENDORS: list[VendorSpec] = [
    VendorSpec(
        vendor_id="VENDOR_supply_01_01",
        notification_id=GHMC,
        vendor_name="Lumina Electricals Private Limited",
        intended_status="pass",
        intended_reason="",
        intended_failed_clause="",
        writeup_quality="strong",
        turnover=[("2021-22", "Rs. 3,85,00,000"), ("2022-23", "Rs. 4,20,00,000"),
                  ("2023-24", "Rs. 4,65,00,000")],
        years_in_business="12",
        net_worth="Rs. 1,95,00,000 (positive)",
        similar_order_value="Rs. 2,84,00,000",
        similar_order_client="Nizamabad Municipal Corporation",
        quoted_price="Rs. 28,74,50,000",
        certifications=[("ISO 9001:2015", "2027-11-30"), ("BIS Registration", "2026-12-31")],
        documents=STANDARD_DOCS,
        technical_approach=STRONG_APPROACH,
    ),
    VendorSpec(
        vendor_id="VENDOR_supply_01_02",
        notification_id=GHMC,
        vendor_name="Bright Path Infra LLP",
        intended_status="eliminate",
        # Below the Rs. 3,00,00,000 turnover floor -- the elimination the rule
        # engine must catch, and must attribute to this clause specifically.
        intended_reason="Average annual turnover Rs. 1.8 Cr is below the required Rs. 3 Cr",
        intended_failed_clause="5",
        writeup_quality="weak",
        turnover=[("2021-22", "Rs. 1,42,00,000"), ("2022-23", "Rs. 1,68,00,000"),
                  ("2023-24", "Rs. 1,80,00,000")],
        years_in_business="6",
        net_worth="Rs. 42,00,000 (positive)",
        similar_order_value="Rs. 2,45,00,000",
        similar_order_client="Karimnagar Municipal Corporation",
        quoted_price="Rs. 27,90,00,000",
        certifications=[("ISO 9001:2015", "2026-08-31")],
        documents=STANDARD_DOCS,
        technical_approach=WEAK_APPROACH,
    ),
    VendorSpec(
        vendor_id="VENDOR_supply_01_03",
        notification_id=GHMC,
        vendor_name="Deccan Lighting Solutions Pvt Ltd",
        intended_status="eliminate",
        # Turnover clears comfortably; the manufacturer's authorisation is
        # missing. Tests that a document gap eliminates on its own, and that the
        # reason cites the document rather than the (passing) financials.
        intended_reason="Manufacturers authorization form not enclosed",
        intended_failed_clause="7",
        writeup_quality="strong",
        turnover=[("2021-22", "Rs. 5,10,00,000"), ("2022-23", "Rs. 5,60,00,000"),
                  ("2023-24", "Rs. 6,05,00,000")],
        years_in_business="15",
        net_worth="Rs. 2,60,00,000 (positive)",
        similar_order_value="Rs. 3,15,00,000",
        similar_order_client="Warangal Municipal Corporation",
        quoted_price="Rs. 29,10,00,000",
        certifications=[("ISO 9001:2015", "2028-02-28"), ("ISO 14001:2015", "2027-05-31")],
        documents=[(name, name != "Manufacturers authorization form")
                   for name, _ in STANDARD_DOCS],
        technical_approach=STRONG_APPROACH,
    ),
    VendorSpec(
        vendor_id="VENDOR_supply_01_04",
        notification_id=GHMC,
        vendor_name="Sunrise Power Systems Limited",
        intended_status="eliminate",
        intended_reason="Bidder is debarred; declared blacklisted",
        intended_failed_clause="4",
        writeup_quality="weak",
        turnover=[("2021-22", "Rs. 4,05,00,000"), ("2022-23", "Rs. 4,40,00,000"),
                  ("2023-24", "Rs. 4,72,00,000")],
        years_in_business="9",
        net_worth="Rs. 1,10,00,000 (positive)",
        similar_order_value="Rs. 2,66,00,000",
        similar_order_client="Adilabad Municipality",
        quoted_price="Rs. 27,45,00,000",
        certifications=[("ISO 9001:2015", "2027-01-31")],
        documents=STANDARD_DOCS,
        is_blacklisted=True,
        technical_approach=WEAK_APPROACH,
    ),
    VendorSpec(
        vendor_id="VENDOR_supply_01_05",
        notification_id=GHMC,
        vendor_name="Godavari Illumination Works",
        intended_status="pass",
        intended_reason="",
        intended_failed_clause="",
        writeup_quality="strong",
        # Borderline on purpose (Section 9.2.2): turnover sits exactly on the
        # Rs. 3,00,00,000 floor. ">= threshold" must pass; "> threshold" fails.
        turnover=[("2021-22", "Rs. 2,95,00,000"), ("2022-23", "Rs. 3,00,00,000"),
                  ("2023-24", "Rs. 3,00,00,000")],
        years_in_business="8",
        net_worth="Rs. 78,00,000 (positive)",
        similar_order_value="Rs. 2,39,00,000",   # exactly the required minimum
        similar_order_client="Ramagundam Municipal Corporation",
        quoted_price="Rs. 28,20,00,000",
        certifications=[("ISO 9001:2015", "2026-10-31")],
        documents=STANDARD_DOCS,
        technical_approach=STRONG_APPROACH,
    ),
]


def bid_text(spec: VendorSpec) -> list[str]:
    """Realistic bid prose, page by page.

    Written as a covering letter and annexures rather than a data dump --
    Section 9.2.2 step 4 is explicit that extraction must be tested against real
    document style, not clean lists.
    """
    turnover_rows = "\n".join(
        f"{year}                    {amount}" for year, amount in spec.turnover
    )
    certs = "\n".join(
        f"  - {name}, valid until {valid}" for name, valid in spec.certifications
    )
    docs = "\n".join(
        f"  {'[X]' if present else '[ ]'} {name}"
        + ("" if present else "   -- NOT ENCLOSED")
        for name, present in spec.documents
    )
    blacklist = (
        "We declare that our firm has been debarred by a State Government "
        "department and the matter is presently under appeal."
        if spec.is_blacklisted
        else "We declare that our firm has not been blacklisted or debarred by "
        "any Central or State Government department, public sector undertaking "
        "or autonomous body as on the date of this bid."
    )

    page1 = f"""{spec.vendor_name.upper()}
Hyderabad, Telangana

To
The Superintending Engineer (Electrical)
Greater Hyderabad Municipal Corporation

Sub: Bid for Procurement of 15500 Nos. New LED Street lights of various
wattages for use in GHMC Jurisdiction
Ref: TENDER No.01/SE(Electrical)/GHMC/2024-25, Dated: 13.09.2024

Sir,

1. Covering Letter

1.1 With reference to the above tender, we submit herewith our technical and
financial bid for the supply, delivery and installation of LED street light
fittings.

1.2 {spec.vendor_name} has been engaged in the manufacture and supply of
electrical and lighting equipment for {spec.years_in_business} years and is
registered under the Companies Act.

1.3 {blacklist}

1.4 Our total quoted price for the entire scope of work is
{spec.quoted_price} inclusive of all applicable taxes and duties.

1.5 We confirm that our bid remains valid for 180 days from the date of opening.
"""

    page2 = f"""2. Financial Capacity

2.1 Annual Turnover

Our audited annual turnover for the last three financial years is as under.
Audited balance sheets certified by our statutory auditor are enclosed at
Annexure III.

Financial Year          Turnover
{turnover_rows}

2.2 Net Worth

Our net worth as on 31 March 2024 as certified by our Chartered Accountant is
{spec.net_worth}. The Chartered Accountant's certificate is enclosed.

3. Experience of Similar Works

3.1 We have successfully executed the following order of similar nature within
the preceding period:

Client            : {spec.similar_order_client}
Order value       : {spec.similar_order_value}
Scope             : Supply, delivery and installation of LED street light
                    fittings of 35W, 70W and 110W ratings
Year of completion: 2023

The work order copy and the satisfactory completion certificate issued by the
client are enclosed at Annexure IV.

4. Certifications Held

{certs or "  - Nil"}
"""

    page3 = f"""5. Technical Approach and Methodology

{spec.technical_approach}
"""

    page4 = f"""6. Checklist of Documents Enclosed

{docs}

7. Declaration

We hereby declare that the information furnished above is true and correct to
the best of our knowledge and belief. We understand that any misrepresentation
shall render our bid liable for rejection.

For {spec.vendor_name}

Authorised Signatory
Date: {date(2024, 10, 8).strftime('%d.%m.%Y')}
Place: Hyderabad
"""
    return [page1, page2, page3, page4]


def render_pdf(spec: VendorSpec, out_dir: Path) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    path = out_dir / f"{spec.vendor_id}.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    styles = getSampleStyleSheet()
    # Preformatted-ish style so the turnover table keeps its column alignment.
    mono = ParagraphStyle("mono", parent=styles["BodyText"], fontName="Courier", fontSize=9)

    story = []
    for index, page in enumerate(bid_text(spec)):
        for block in page.strip().split("\n\n"):
            tabular = "Turnover" in block or "[X]" in block or "[ ]" in block
            style = mono if tabular else styles["BodyText"]
            story.append(Paragraph(block.replace("\n", "<br/>"), style))
            story.append(Spacer(1, 6))
        if index < 3:
            story.append(PageBreak())
    doc.build(story)
    return path


def write_tracking(specs: list[VendorSpec], path: Path) -> None:
    """Section 9.4, Tab 2 -- the answer key every Section 10 number traces to."""
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "vendor_id", "notification_id", "intended_status", "intended_reason",
            "intended_failed_clause", "is_blacklisted", "technical_writeup_quality",
            "file_name", "generated_by", "date", "notes",
        ])
        for spec in specs:
            writer.writerow([
                spec.vendor_id, spec.notification_id, spec.intended_status,
                spec.intended_reason, spec.intended_failed_clause,
                str(spec.is_blacklisted).lower(), spec.writeup_quality,
                f"{spec.vendor_id}.pdf", "scripts.make_vendor_bids",
                date.today().isoformat(), "",
            ])


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic vendor bids")
    parser.add_argument("--out", default="../data/vendors")
    parser.add_argument("--tracking", default="../data/tracking_vendors.csv")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for spec in VENDORS:
        path = render_pdf(spec, out_dir)
        print(f"  {spec.vendor_id:24} {spec.intended_status:9} {path.name}")

    write_tracking(VENDORS, Path(args.tracking))
    print(f"\nGround truth written to {args.tracking} ({len(VENDORS)} vendors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
