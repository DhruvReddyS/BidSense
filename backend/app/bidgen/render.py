"""Render a VendorSpec into a realistic multi-page bid document.

Section 9.2.2 step 4 asks for "realistic tender-bid prose (not a bare data
dump)" and step 5 for PDF/DOCX rather than text, "with page breaks, headers,
tables" -- because extraction must be tested against the document style it will
actually meet, not against clean lists.

The structure below mirrors a real Indian technical bid: covering letter, letter
of bid, bidder information, financial capacity with a turnover table, experience
statements, a methodology narrative, QA and safety, programme, statutory
declarations, and a checklist of enclosures.
"""

from __future__ import annotations

from pathlib import Path

from app.bidgen import sections
from app.bidgen.sections import SCALES, BidScale
from app.bidgen.spec import TenderProfile, VendorSpec

# --------------------------------------------------------------------------- #
# Technical narratives, by sector and quality.
#
# The strong/weak split is deliberate and is not about correctness: both
# describe a competent bidder. The weak ones are vague and self-congratulatory,
# the strong ones specific and verifiable. Section 5.4's fluency-bias guard
# requires that a plain-but-complete bid is not summarised as weaker than a
# fluent-but-vague one, and that cannot be tested without both.
# --------------------------------------------------------------------------- #

STRONG = {
    "supply": """Our execution plan is organised in four phases, each with a named
owner, a defined deliverable and an exit criterion that must be signed off before
the next phase begins.

Phase 1 — Survey and asset validation (weeks 1 to 3). We will carry out a
pole-by-pole survey of every location in the scope, recording existing fitting
wattage, pole height, arm length, feeder pillar mapping and GPS coordinates into a
GIS-tagged asset register. The register will be shared with the Engineer-in-Charge
in editable form before any despatch. No fitting leaves our works until its
destination record has been validated against the survey, which is how we avoid
the wattage and mounting mismatches that are the most common cause of re-work on
street lighting contracts.

Phase 2 — Manufacture and pre-despatch inspection (weeks 2 to 14). LED fittings
of 35W, 70W and 110W ratings will be manufactured strictly to the technical
specification annexed to the tender. Every production batch will be subjected to
photometric testing at an NABL-accredited laboratory, and LM-79 and LM-80 test
reports together with surge immunity certificates to IEC 61000-4-5 will be
submitted to the Engineer-in-Charge before despatch. Batches will be released for
despatch only after written clearance is received.

Phase 3 — Installation (weeks 4 to 22, overlapping supply). Installation will
proceed division by division using four independent crews. Work on arterial roads
will be carried out on night shifts between 23:00 and 05:00 to avoid traffic
disruption, with retro-reflective barricading and trained flagmen at both
approaches. Each crew will be led by a supervisor holding a valid wireman licence
issued by the State Electrical Licensing Board.

Phase 4 — Testing, commissioning and handover (weeks 20 to 26). Illumination
levels will be measured against IS 1944 at sample points in each division, with
lux readings recorded on site and jointly signed by our engineer and the
department's representative. On completion we will hand over the complete asset
register, warranty certificates, spares inventory and a defect-reporting protocol
with a committed 24-hour response and 72-hour rectification window for the full
warranty period.

Risk management. The two risks we consider material are component lead time and
monsoon access. We hold buffer stock equivalent to three weeks of installation
demand, and we sequence low-lying divisions ahead of the monsoon window so that a
weather delay does not sit on the critical path.""",

    "civil works": """Our method statement for this work follows the sequence set out
below, and is written against the site conditions we recorded during the
pre-bid site visit.

Site establishment and setting out. We will establish a site office, material
stacking yard and a curing water point within the area allotted by the
Engineer-in-Charge. The centre line of the wall will be set out using a total
station and referenced to at least three permanent benchmarks outside the working
width so that the alignment can be re-established after excavation.

Excavation and foundation. Excavation for the foundation trench will be carried
out to the depth and width shown on the drawings, with sides kept vertical and
shored where the depth exceeds 1.5 metre. The founding stratum will be inspected
and approved by the Engineer-in-Charge before any concrete is placed. A levelling
course of M10 concrete of 100 mm thickness will be laid over the approved
formation.

Reinforced concrete works. Footings, columns and the plinth beam will be cast in
M20 grade concrete using 43 grade Ordinary Portland Cement conforming to IS 8112,
batched by weight at site. Reinforcement will be Fe 500D conforming to IS 1786,
cut and bent to the bar bending schedule and placed with cover blocks of the same
grade as the surrounding concrete. Cubes will be cast at the frequency laid down
in IS 456 and tested at an approved laboratory, and results will be submitted
with each running account bill.

Masonry, plaster and finishing. Panel walls will be built in first-class brick
masonry in cement mortar 1:6, with courses kept truly plumb and horizontal joints
raked for plaster key. Both faces will receive 12 mm cement plaster in 1:6 mortar
finished smooth, followed by one coat of primer and two coats of exterior
emulsion of an approved shade.

Curing, quality and safety. All concrete and masonry will be cured for the
periods specified in IS 456 using gunny bags kept continuously moist. Every
worker on site will be issued with helmet, safety shoes and high-visibility
jacket, and a trained safety steward will be present whenever excavation or
lifting is in progress. The work area will be barricaded and signage displayed in
Hindi and English.

Programme. The work will be completed within the stipulated period. Our bar chart
sequences foundation works ahead of the monsoon, with masonry and finishing
scheduled for the drier months so that curing quality is not compromised.""",
}

WEAK = {
    "supply": """We are a reputed and well established firm engaged in the field of
electrical works and LED lighting for many years. We have executed several
prestigious projects for various government departments and municipal bodies to
the entire satisfaction of our esteemed clients.

We will supply the LED street light fittings strictly as per the specifications
given in the tender document. All the materials used will be of the best quality
and of reputed make, and will conform to the relevant Indian Standards.
Installation will be carried out by our experienced and skilled technicians in a
proper workmanlike manner under the supervision of qualified engineers.

We have adequate manpower, machinery and financial resources at our disposal to
execute the work within the stipulated time period. Our team is well versed with
the requirements of municipal street lighting works and has handled similar
assignments in the past without any complaint.

Quality is our motto and customer satisfaction is our aim. We assure the
department of our best services at all times and shall complete the work to the
full satisfaction of the Engineer-in-Charge. We hope that our offer will be found
suitable and look forward to receiving your valued work order.""",

    "civil works": """We are an experienced firm of civil contractors having undertaken
numerous construction works including boundary walls, compound walls, buildings
and allied civil works for government and private clients over the years.

The work will be carried out strictly as per the drawings, specifications and
directions of the Engineer-in-Charge. All materials such as cement, sand,
aggregate, bricks and steel will be of the best quality available and of approved
make, and samples will be got approved before use.

We have our own machinery, shuttering material and a team of skilled masons,
bar benders and helpers. Our supervisors have long experience in such works and
will ensure that the work proceeds smoothly and is completed within the time
allowed.

Proper care will be taken regarding safety of workmen and cleanliness of the
site. We assure that the work will be executed in a workmanlike manner to the
entire satisfaction of the department. We request that our tender may kindly be
considered favourably.""",
}


def _fmt_table(rows: list[tuple[str, str]], headers: tuple[str, str]) -> str:
    width = max([len(headers[0])] + [len(r[0]) for r in rows]) + 4
    lines = [f"{headers[0]:<{width}}{headers[1]}", "-" * (width + len(headers[1]) + 8)]
    lines += [f"{a:<{width}}{b}" for a, b in rows]
    return "\n".join(lines)


def build_pages(
    spec: VendorSpec,
    tender: TenderProfile,
    required_documents: list[str] | None = None,
    scale: BidScale | None = None,
) -> list[str]:
    """The complete bid, page by page.

    `required_documents`, when supplied, is the deduplicated requirement list the
    pipeline actually extracted from this notification. A compliant bid must
    enclose what the tender asks for, and these tenders ask for fifty-odd
    documents -- a hand-written list of fourteen makes a compliant vendor look
    non-compliant, which is a defect in the test data rather than in the system.
    Deliberate omissions are still removed, so the answer key stays exact.

    `scale` sets how long the document runs. It is chosen from the tender's
    value rather than picked arbitrarily: a Rs. 12 lakh boundary wall does not
    attract a 200-page bid, and pretending otherwise would make the test set
    less realistic rather than more.
    """
    scale = scale or SCALES[tender.bid_scale]
    catalogue = list(required_documents or tender.key_documents)
    omitted_norm = {d.strip().lower() for d in spec.omitted_documents}

    enclosed = [
        d for d in catalogue
        if d.strip().lower() not in omitted_norm
        and not any(o in d.strip().lower() for o in omitted_norm)
    ]
    omitted = [
        d for d in catalogue
        if d.strip().lower() in omitted_norm
        or any(o in d.strip().lower() for o in omitted_norm)
    ] or list(spec.omitted_documents)

    turnover_rows = [(year, amount) for year, amount in spec.turnover]
    certs = "\n".join(
        f"  - {name}" + (f", valid until {valid}" if valid != "\u2014" else "")
        for name, valid in spec.certifications
    ) or "  - Nil"

    cover = f"""{spec.vendor_name.upper()}
{spec.constitution}
{spec.city}




TECHNICAL AND FINANCIAL BID




Submitted to

{tender.authority}
{tender.authority_address}




Tender reference : {tender.tender_ref}

Name of work     : {tender.work_title}

Estimated cost   : {tender.estimated_cost}

Earnest money    : {tender.emd}

Due date         : {tender.bid_due}




Submitted by

{spec.vendor_name}
{spec.city}

Date : {tender.bid_due}
"""

    index_page = """INDEX

Section                                                          Page
------------------------------------------------------------------------
1    Covering Letter
2    Letter of Bid and Price
3    Bidder's General Information (Form F-1)
4    Financial Capacity
5    Experience of Similar Works (Form F-13)
6    Method Statement
7    Organisation and Key Personnel
8    Compliance with Technical Specifications
9    Programme and Sequence of Work
10   Plant, Machinery and Equipment
11   Quality Assurance Plan
12   Health, Safety and Environment
13   Risk Register
14   Price Schedule
15   Declarations and Undertakings
16   Checklist of Documents Enclosed
     Annexures I to XI
"""

    covering = f"""SECTION 1 — COVERING LETTER

Ref: {spec.vendor_id}/BID/2024                          Date: {tender.bid_due}

To
The Superintending Engineer
{tender.authority}
{tender.authority_address}

Sub: Submission of bid for "{tender.work_title}"
Ref: {tender.tender_ref}

Sir,

1.1 With reference to the above tender notice, we submit herewith our bid for
the captioned work. We have examined the bid document in its entirety, including
the notice inviting tender, the instructions to bidders, the general and special
conditions of contract, the technical specifications, the drawings, the schedules
and all addenda and corrigenda issued thereto, and we accept them without
reservation.

1.2 {spec.vendor_name} is a {spec.constitution.lower()} established in the year
{spec.established} and has been continuously engaged in
{tender.technical_context} for {spec.years_in_business} years. Our registered
office is situated at {spec.city}.

1.3 We confirm that we satisfy the qualification requirements stipulated in the
bid document and have furnished documentary evidence in support thereof at the
annexures listed in the checklist at Section 16 of this bid.

1.4 We have deposited the Earnest Money Deposit of {tender.emd} as required, and
the proof of remittance is enclosed at Annexure X.

1.5 Our bid shall remain valid for acceptance for a period of 180 days from the
date fixed for opening of bids, and it shall remain binding upon us and may be
accepted at any time before the expiry of that period.

1.6 We undertake, if our bid is accepted, to commence the work within the period
stipulated and to complete the whole of the work within the time for completion
specified in the contract data.

1.7 We confirm that we have visited and inspected the site and satisfied
ourselves as to the conditions under which the work is to be executed.

1.8 We understand that you are not bound to accept the lowest or any bid you may
receive, and that no claim shall lie against you on that account.
"""

    letter_of_bid = f"""SECTION 2 — LETTER OF BID AND PRICE

2.1 Price

The total price of our bid for the execution of the whole of the work described
above, inclusive of all taxes, duties, levies, cess, insurance, transportation,
loading and unloading, and all incidental charges, is:

        {spec.quoted_price}
        ({spec.quoted_words})

2.2 Firmness of Price

The above price is firm and is not subject to any escalation whatsoever during
the currency of the contract, save to the extent expressly provided in the
conditions of contract.

2.3 Taxes

We confirm that the rates quoted are inclusive of Goods and Services Tax at the
applicable rate, and that we shall raise invoices in accordance with the GST Act
and the rules made thereunder. Our GST registration certificate is enclosed at
Annexure I.

2.4 Validity

We confirm that our bid remains valid for 180 days from the date fixed for
opening of bids.

2.5 Earnest Money Deposit

The Earnest Money Deposit of {tender.emd} has been remitted as required by the
bid document and the proof of remittance is enclosed at Annexure X. We accept
that the Earnest Money shall stand forfeited in the circumstances set out in the
conditions of contract.

2.6 Performance Security

We undertake, if our bid is accepted, to furnish the Performance Security in the
form and within the period stipulated in the conditions of contract.
"""

    bidder_info = f"""SECTION 3 — BIDDER'S GENERAL INFORMATION (Form F-1)

3.1  Name of bidder                : {spec.vendor_name}
3.2  Constitution                  : {spec.constitution}
3.3  Year of establishment         : {spec.established}
3.4  Years in the line of business : {spec.years_in_business}
3.5  Registered office             : {spec.city}
3.6  Permanent Account Number      : Enclosed at Annexure I
3.7  GST Registration Number       : Enclosed at Annexure I
3.8  EPFO registration             : Enclosed at Annexure I
3.9  ESIC registration             : Enclosed at Annexure I
3.10 Bankers                       : State Bank of India, {spec.city} Main Branch
3.11 Authorised signatory          : As per Power of Attorney at Annexure II
3.12 Class of registration         : {spec.certifications[0][0] if spec.certifications else 'Not applicable'}

3.13 Constitution Documents

The certificate of incorporation or registration of the firm, together with the
memorandum and articles of association or the partnership deed as applicable, is
enclosed at Annexure II. There has been no change in the constitution of the firm
in the three years preceding the date of this bid.

3.14 Litigation History

No arbitration or litigation arising out of any contract executed by us in the
last five years has resulted in an award against us exceeding ten percent of the
contract value, and no contract awarded to us has been terminated for default.

3.15 Certifications and Registrations Held

{certs}

Copies of each of the above are enclosed at Annexure V.
"""

    financial = f"""SECTION 4 — FINANCIAL CAPACITY

4.1 Annual Turnover

The audited annual turnover of the firm for the last three financial years is set
out below. Audited balance sheets together with the profit and loss account for
each of these years, duly certified by our statutory auditor, are enclosed at
Annexure III.

{_fmt_table(turnover_rows, ("Financial Year", "Turnover"))}

4.2 Certification of the Figures

We confirm that the figures stated above are extracted from the audited financial
statements and that no part of the turnover shown relates to work executed as a
sub-contractor to another bidder for this tender. The certificate of our
Chartered Accountant showing the computation is enclosed.

4.3 Net Worth

The net worth of the firm as certified by our Chartered Accountant is
{spec.net_worth}, and is positive as on the last day of the immediately preceding
financial year.

4.4 Liquid Assets and Credit Facilities

We have available liquid assets and unutilised credit facilities amounting to
{spec.bank_credit}. A solvency certificate and a letter of credit availability
issued by our bankers are enclosed at Annexure VI.

4.5 Requirement Stated in the Bid Document

The requirement stipulated in the bid document in this regard is
{tender.turnover_requirement}. The figures furnished above are to be read against
that requirement.

4.6 Bid Capacity

Our available bid capacity, computed by the formula prescribed in the bid
document, exceeds the estimated cost of this work. The computation is set out at
Annexure IV together with a statement of works in hand and their anticipated
completion dates.
"""

    checklist_lines = "\n".join(
        f"  {index:>3}. [X]  {name}" for index, name in enumerate(enclosed, start=1)
    )
    if omitted:
        checklist_lines += "\n" + "\n".join(
            f"  {len(enclosed) + index:>3}. [ ]  {name}   — NOT ENCLOSED"
            for index, name in enumerate(omitted, start=1)
        )

    checklist_pages: list[str] = []
    all_lines = checklist_lines.split("\n")
    per_page = 34
    for start_index in range(0, len(all_lines), per_page):
        block = "\n".join(all_lines[start_index : start_index + per_page])
        header = (
            """SECTION 16 — CHECKLIST OF DOCUMENTS ENCLOSED

The documents listed below are enclosed with this bid in the order shown. Items
marked [X] are enclosed; any item marked [ ] is not enclosed and the reason is
stated against it.

"""
            if start_index == 0
            else "SECTION 16 — CHECKLIST OF DOCUMENTS ENCLOSED (continued)\n\n"
        )
        checklist_pages.append(header + block)

    signature = f"""UNDERTAKING AND SIGNATURE

We have read and understood the entire bid document and we agree to abide by all
its terms and conditions without any reservation. We understand that the Employer
reserves the right to reject any or all bids without assigning any reason
whatsoever, and that no claim shall lie against the Employer on that account.

We confirm that this bid is submitted by a person duly authorised to do so, and
that the Power of Attorney in his favour is enclosed at Annexure II.

We declare that the particulars and information furnished in this bid and in the
documents accompanying it are true and correct to the best of our knowledge and
belief, and that nothing material has been concealed.

Thanking you,

Yours faithfully,

For {spec.vendor_name}



(Authorised Signatory)
Name        : {"".join(w[0] for w in spec.vendor_name.split()[:3]).upper()} Signatory
Designation : Authorised Signatory
Date        : {tender.bid_due}
Place       : {spec.city}

Seal of the firm
"""

    return [
        cover,
        index_page,
        covering,
        letter_of_bid,
        bidder_info,
        financial,
        *sections.section_experience(spec, tender, scale),
        *sections.section_method_statement(tender, scale),
        *sections.section_personnel(spec, tender, scale),
        *sections.section_specification_compliance(tender, scale),
        *sections.section_programme(tender),
        *sections.section_plant(tender),
        *sections.section_quality_plan(tender, scale),
        *sections.section_hse(spec, tender),
        *sections.section_risk(),
        *(sections.section_design_basis(spec, tender, scale)
          if scale.name == "comprehensive" else []),
        *(sections.section_om_plan(spec, tender)
          if scale.name == "comprehensive" else []),
        *sections.section_boq(spec, tender, scale),
        *sections.section_declarations(spec, tender, scale),
        *checklist_pages,
        signature,
        *sections.section_annexures(spec, tender, scale),
    ]


def render_pdf(
    spec: VendorSpec,
    tender: TenderProfile,
    out_dir: Path,
    required_documents: list[str] | None = None,
    scale: BidScale | None = None,
) -> Path:
    """Render to PDF with real page breaks, so extraction meets real pagination."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    path = out_dir / f"{spec.vendor_id}.pdf"
    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        topMargin=18 * mm, bottomMargin=18 * mm,
        leftMargin=20 * mm, rightMargin=18 * mm,
        title=f"{spec.vendor_name} — bid for {tender.tender_ref}",
        author=spec.vendor_name,
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9.5, leading=13)
    # Monospaced for tables and checklists so column alignment survives to the
    # PDF text layer, which is what the parser reads back.
    mono = ParagraphStyle("mono", parent=body, fontName="Courier", fontSize=8.5, leading=11)

    story = []
    pages = build_pages(spec, tender, required_documents, scale)
    for index, page in enumerate(pages):
        for block in page.strip().split("\n\n"):
            tabular = any(
                marker in block
                for marker in ("[X]", "[ ]", "Financial Year", "Client", "  : ", "----")
            )
            story.append(Paragraph(block.replace("\n", "<br/>"), mono if tabular else body))
            story.append(Spacer(1, 5))
        if index < len(pages) - 1:
            story.append(PageBreak())

    doc.build(story)
    return path
