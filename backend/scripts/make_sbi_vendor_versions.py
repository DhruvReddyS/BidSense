"""Generate four progressively complete synthetic bids for the SBI AMCC tender.

The progression is intentionally fixed in data/tracking_vendors.csv before these
documents are rendered.  These files are demonstration fixtures, not submissions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "output" / "pdf" / "sbi_amcc"
LOGO = ROOT / "frontend" / "public" / "bidsense-logo.png"

NAVY = colors.HexColor("#071B3D")
BLUE = colors.HexColor("#1457D9")
SKY = colors.HexColor("#EAF1FF")
INK = colors.HexColor("#172033")
MUTED = colors.HexColor("#667085")
LINE = colors.HexColor("#D9E1EC")
PAPER = colors.HexColor("#F7F9FC")
GREEN = colors.HexColor("#147D64")
AMBER = colors.HexColor("#B36B00")
RED = colors.HexColor("#B42318")


@dataclass(frozen=True)
class Version:
    number: int
    vendor_id: str
    maturity: str
    status: str
    accent: colors.Color
    summary: str


VERSIONS = (
    Version(1, "SBI_AMCC_VERSION1", "INITIAL DRAFT", "INCOMPLETE", RED,
            "Early working draft with basic bidder information and an outline response."),
    Version(2, "SBI_AMCC_VERSION2", "ELIGIBILITY PACK", "INCOMPLETE", AMBER,
            "Adds SBI empanelment evidence, EMD payment evidence, and Annexure-A."),
    Version(3, "SBI_AMCC_VERSION3", "TECHNICAL BID", "NEARLY COMPLETE", BLUE,
            "Adds the complete technical method, Annexure-B, compliance email, and ongoing-works list."),
    Version(4, "SBI_AMCC_VERSION4", "FINAL BID PACK", "COMPLETE", GREEN,
            "Complete reviewer-ready pack with every extracted mandatory enclosure and procedural evidence."),
)


def register_fonts() -> tuple[str, str]:
    regular = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
    bold = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")
    if regular.exists() and bold.exists():
        pdfmetrics.registerFont(TTFont("BidSans", str(regular)))
        pdfmetrics.registerFont(TTFont("BidSans-Bold", str(bold)))
        return "BidSans", "BidSans-Bold"
    return "Helvetica", "Helvetica-Bold"


FONT, FONT_BOLD = register_fonts()


def styles():
    base = getSampleStyleSheet()
    return {
        "body": ParagraphStyle("Body", parent=base["BodyText"], fontName=FONT,
            fontSize=9.2, leading=14, textColor=INK, spaceAfter=7),
        "small": ParagraphStyle("Small", parent=base["BodyText"], fontName=FONT,
            fontSize=7.5, leading=10.5, textColor=MUTED),
        "eyebrow": ParagraphStyle("Eyebrow", parent=base["BodyText"], fontName=FONT_BOLD,
            fontSize=7.5, leading=10, textColor=BLUE, tracking=1.3, spaceAfter=5),
        "h1": ParagraphStyle("H1", parent=base["Heading1"], fontName=FONT_BOLD,
            fontSize=23, leading=27, textColor=NAVY, spaceAfter=12),
        "h2": ParagraphStyle("H2", parent=base["Heading2"], fontName=FONT_BOLD,
            fontSize=15, leading=19, textColor=NAVY, spaceBefore=4, spaceAfter=9),
        "h3": ParagraphStyle("H3", parent=base["Heading3"], fontName=FONT_BOLD,
            fontSize=10.5, leading=14, textColor=INK, spaceBefore=7, spaceAfter=4),
        "center": ParagraphStyle("Center", parent=base["BodyText"], fontName=FONT,
            alignment=TA_CENTER, fontSize=9, leading=13, textColor=INK),
        "right": ParagraphStyle("Right", parent=base["BodyText"], fontName=FONT,
            alignment=TA_RIGHT, fontSize=8, leading=11, textColor=MUTED),
        "quote": ParagraphStyle("Quote", parent=base["BodyText"], fontName=FONT,
            fontSize=9, leading=14, textColor=NAVY, leftIndent=12, rightIndent=12,
            borderColor=BLUE, borderWidth=1.5, borderPadding=9, spaceBefore=6, spaceAfter=9),
    }


S = styles()


def P(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, S[style])


def bullet(text: str) -> Paragraph:
    return Paragraph(text, ParagraphStyle("Bullet", parent=S["body"], leftIndent=13,
        firstLineIndent=-7, bulletIndent=0, spaceAfter=4), bulletText="-")


def heading(kicker: str, title: str, intro: str | None = None):
    out = [P(kicker.upper(), "eyebrow"), P(title, "h1")]
    if intro:
        out.append(P(intro, "quote"))
    return out


def table(rows, widths=None, header=True, font_size=8.0):
    cell_style = ParagraphStyle("TableCell", parent=S["small"], fontName=FONT,
        fontSize=font_size, leading=font_size + 3, textColor=INK)
    head_style = ParagraphStyle("TableHead", parent=cell_style, fontName=FONT_BOLD,
        textColor=colors.white)
    data = []
    for row_index, row in enumerate(rows):
        style = head_style if header and row_index == 0 else cell_style
        data.append([Paragraph(str(cell), style) for cell in row])
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.45, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
    ]
    if header:
        commands += [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ]
    for row in range(1 if header else 0, len(data)):
        if row % 2 == 0:
            commands.append(("BACKGROUND", (0, row), (-1, row), PAPER))
    t.setStyle(TableStyle(commands))
    return t


class BidDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str, version: Version):
        super().__init__(filename, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
                         topMargin=22*mm, bottomMargin=18*mm,
                         title=f"SBI AMCC Bid - Version {version.number}",
                         author="Himalayan Workspace Projects Pvt. Ltd. - Synthetic Demo")
        self.version = version
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height,
                      id="main", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates(PageTemplate(id="bid", frames=[frame], onPage=self._decorate))

    def _decorate(self, canvas, doc):
        canvas.saveState()
        width, height = A4
        if doc.page == 1:
            canvas.setFillColor(NAVY)
            canvas.rect(0, height - 13*mm, width, 13*mm, fill=1, stroke=0)
            canvas.setFillColor(self.version.accent)
            canvas.rect(0, height - 15*mm, width, 2*mm, fill=1, stroke=0)
        else:
            canvas.setStrokeColor(LINE)
            canvas.line(18*mm, height - 15*mm, width - 18*mm, height - 15*mm)
            canvas.setFont(FONT_BOLD, 7)
            canvas.setFillColor(NAVY)
            canvas.drawString(18*mm, height - 11.5*mm, "HIMALAYAN WORKSPACE PROJECTS PVT. LTD.")
            canvas.setFont(FONT, 7)
            canvas.setFillColor(MUTED)
            canvas.drawRightString(width - 18*mm, height - 11.5*mm,
                f"SBI AMCC / VERSION {self.version.number}")
        canvas.setFillColor(colors.Color(0.25, 0.33, 0.45, alpha=0.08))
        canvas.setFont(FONT_BOLD, 38)
        canvas.translate(width/2, height/2)
        canvas.rotate(34)
        canvas.drawCentredString(0, 0, "SYNTHETIC DEMONSTRATION")
        canvas.rotate(-34)
        canvas.translate(-width/2, -height/2)
        canvas.setStrokeColor(LINE)
        canvas.line(18*mm, 13*mm, width - 18*mm, 13*mm)
        canvas.setFont(FONT, 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(18*mm, 8.5*mm, "Tender: DEL/AO-3/RBO-6/AMCC/IN/01")
        canvas.drawCentredString(width/2, 8.5*mm, "NOT FOR SUBMISSION")
        canvas.drawRightString(width - 18*mm, 8.5*mm, f"Page {doc.page}")
        canvas.restoreState()


def cover(v: Version):
    status_bg = v.accent
    return [
        Spacer(1, 12*mm),
        P("TECHNICAL AND PRICE BID", "eyebrow"),
        P("Interior and Allied Civil Works", "h1"),
        P("Proposed SBI AMCC Branch at New Tehri, Uttarakhand", "h2"),
        Spacer(1, 6*mm),
        table([
            ["Tender reference", "DEL/AO-3/RBO-6/AMCC/IN/01"],
            ["Issued by", "State Bank of India, RBO-6 Tehri Garhwal"],
            ["Submission deadline", "22 September 2026, 15:00 IST"],
            ["Completion period", "45 days from handover / work order"],
            ["Bidder", f"Himalayan Workspace Projects Pvt. Ltd. - Bid Version {v.number} (fictional)"],
            ["Bid identity", v.vendor_id],
        ], widths=[46*mm, 118*mm], header=False),
        Spacer(1, 8*mm),
        Table([[P(f"VERSION {v.number}", "h2"), P(v.maturity, "h2"), P(v.status, "h2")]],
              colWidths=[36*mm, 75*mm, 53*mm], style=TableStyle([
                  ("BACKGROUND", (0, 0), (-1, -1), status_bg),
                  ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                  ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                  ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                  ("TOPPADDING", (0, 0), (-1, -1), 8),
                  ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
              ])),
        Spacer(1, 7*mm),
        P(v.summary, "quote"),
        Spacer(1, 20*mm),
        P("This document is a synthetic product demonstration. The company, people, credentials, references, payment instruments, signatures, and acknowledgements are fictional and must not be used as a real tender submission.", "small"),
        PageBreak(),
    ]


def contents(v: Version, section_names: list[str]):
    story = heading("Document control", "Submission map",
        "This version is deliberately staged so that compliance improvements can be measured after each upload.")
    rows = [["No.", "Section", "Included in this version"]]
    for i, name in enumerate(section_names, 1):
        rows.append([f"{i:02d}", name, "Yes"])
    story += [table(rows, widths=[15*mm, 105*mm, 44*mm]), Spacer(1, 6*mm)]
    story += [P("Version control", "h2"), table([
        ["Version", "Purpose", "Document-control status"],
        ["1", "Initial working draft", "Core schedules not yet assembled"],
        ["2", "Eligibility and EMD pack", "Partial technical bid"],
        ["3", "Detailed technical bid", "Two procedural enclosures outstanding"],
        ["4", "Final complete pack", "All extracted enclosures present"],
    ], widths=[18*mm, 69*mm, 77*mm])]
    story += [PageBreak()]
    return story


def bidder_profile(v: Version):
    story = heading("Section 01", "Bidder profile",
        "A fictional specialist interior contractor prepared for controlled testing of the tender-compliance workflow.")
    story += [table([
        ["Field", "Declared particulars"],
        ["Legal name", f"Himalayan Workspace Projects Pvt. Ltd. - Bid Version {v.number} (fictional demonstration entity)"],
        ["Registered office", "14 Rajpur Business Enclave, Dehradun, Uttarakhand 248001"],
        ["Constitution", "Private limited company"],
        ["Year established", "2014"],
        ["GSTIN", "05AABCH0000D1ZX - synthetic placeholder"],
        ["PAN", "AABCH0000D - synthetic placeholder"],
        ["Authorized representative", "Arjun Mehta, Director - Projects (fictional)"],
        ["Bid contact", "tenders@example.invalid | +91 00000 00000"],
    ], widths=[45*mm, 119*mm])]
    story += [P("Capability statement", "h2")]
    story += [P("The bidder specializes in branch interiors, joinery, modular counters, customer-service furniture, ceilings, glass partitions, wall finishes, and allied civil works. The delivery model combines a Dehradun fabrication partner, a site engineering team, and documented material-approval gates.")]
    if v.number >= 2:
        story += [P("Eligibility declaration", "h2"), P(
            "We declare that we are empaneled with State Bank of India in the Interior and Furnishing Works category up to INR 25 lakh and above, under synthetic empanelment reference SBI/DEL/INT/2026/041, and that we received the project invitation from the Project Architect / SBI. A fictional empanelment and invitation record is reproduced in this pack for workflow testing.", "quote")]
    story += [PageBreak()]
    return story


def letter_of_bid(v: Version):
    story = heading("Section 02", "Letter of bid")
    story += [P("To<br/>The Regional Manager<br/>State Bank of India, RBO-6 Tehri Garhwal<br/>Administrative Office-3, New Delhi")]
    story += [P("Subject: Bid for interior and allied civil works for the proposed SBI AMCC Branch at New Tehri, Uttarakhand")]
    story += [P("We have examined the notice inviting tender, conditions of contract, technical specifications, approved-make requirements, drawings, and bill of quantities. We offer to execute and complete the works in conformity with those documents within 45 calendar days.")]
    story += [bullet("Offer validity: four months from the tender submission date.")]
    story += [bullet("Defects liability: 12 months from certified completion.")]
    story += [bullet("Rates include labour, materials, plant, transport, duties, and taxes other than GST.")]
    story += [bullet("Initial security deposit and total security deposit requirements are accepted.")]
    story += [bullet("Additional security / performance guarantee will be furnished within seven days if the quoted amount triggers the below-estimate condition.")]
    if v.number >= 3:
        story += [bullet("The site was inspected on 10 September 2026 and local access, working-hour, protection, and storage constraints were incorporated into the programme.")]
    story += [Spacer(1, 8*mm), table([
        ["For the bidder", "Synthetic execution"],
        ["Name", "Arjun Mehta (fictional)"],
        ["Capacity", "Authorized Signatory"],
        ["Signature", "/s/ Arjun Mehta - SYNTHETIC"],
        ["Company seal", "HWPPL - DEMONSTRATION SEAL"],
        ["Date / place", "18 September 2026 / Dehradun"],
    ], widths=[45*mm, 119*mm], header=False), PageBreak()]
    return story


def methodology(v: Version):
    detailed = v.number >= 3
    story = heading("Section 03", "Technical methodology",
        "The execution sequence is tied to the 45-day completion requirement and the material specifications in the tender.")
    phases = [
        ("1. Mobilization and validation", "Joint measurement, condition survey, protection plan, benchmark programme, shop-drawing register, and material-submittal schedule."),
        ("2. Samples and procurement", "Approve laminates, marine plywood, IS-303 commercial plywood, hardware, glass, ACP, coatings, and upholstery before bulk procurement."),
        ("3. Off-site fabrication", "Prepare cutting lists, maximize full-length members, avoid joints where practicable, label modules by room and elevation, and inspect before dispatch."),
        ("4. Site installation", "Coordinate ceilings, partitions, counters, doors, furniture, painting, and allied works through zone releases and daily quality hold points."),
        ("5. Testing and handover", "Close punch items, submit manufacturer test certificates, warranties, as-built markups, cleaning records, and a defects-liability contact protocol."),
    ]
    story += [table([["Phase", "Controlled output"]] + [list(x) for x in phases], widths=[46*mm, 118*mm])]
    if detailed:
        story += [P("Material and workmanship controls", "h2")]
        for text in [
            "Use 710 marine plywood where specified; use approved IS-303 commercial plywood elsewhere. Exposed edges receive 1 mm laminate or minimum 6 mm wood beading with the scheduled finish.",
            "Use approved IS-2046 laminate at not less than 1 mm thickness and 0.8 mm balancing laminate. Internal furniture surfaces receive 0.75 mm frosty-white phenolic laminate.",
            "Treat wood members before construction with Biflex TC in two coats at the specified 1:24 chemical-to-kerosene proportion. Hidden board, ply, and wood surfaces receive the specified antibacterial coating.",
            "Test wood moisture and knot percentage at the contractor's cost. Submit manufacturer test certificates wherever applicable before incorporation into the works.",
            "Provide the scheduled glass, hardware, foam density, door closers, hinges, locks, ACP build-up, primers, and finish-coat systems without substitution unless written approval is obtained.",
        ]:
            story.append(bullet(text))
        story += [P("Inspection hold points", "h2"), table([
            ["Hold point", "Evidence", "Release authority"],
            ["HP-01", "Existing-condition survey and joint dimensions", "SBI / Architect"],
            ["HP-02", "Material samples and approved-make register", "Architect"],
            ["HP-03", "First-off joinery module", "Architect / Site Engineer"],
            ["HP-04", "Concealed treatment before closure", "Site Engineer"],
            ["HP-05", "Snag closure and handover dossier", "SBI / Architect"],
        ], widths=[25*mm, 92*mm, 47*mm])]
    story += [PageBreak()]
    return story


def programme(v: Version):
    story = heading("Section 04", "45-day delivery programme")
    story += [table([
        ["Activity", "Days", "Planned window", "Control milestone"],
        ["Mobilization, survey, protection", "4", "Day 1-4", "Joint survey signed"],
        ["Shop drawings and material approvals", "7", "Day 2-8", "Approval register issued"],
        ["Procurement and fabrication", "19", "Day 5-23", "First-off module approved"],
        ["Site civil corrections and services", "10", "Day 6-15", "Zones released"],
        ["Partitions, ceilings, joinery", "20", "Day 14-33", "Room-wise inspection"],
        ["Finishes, furniture, signage interfaces", "9", "Day 31-39", "Finish inspection"],
        ["Testing, snag closure, handover", "6", "Day 40-45", "Completion dossier"],
    ], widths=[57*mm, 16*mm, 33*mm, 58*mm])]
    if v.number >= 3:
        story += [P("Resourcing", "h2"), table([
            ["Role / crew", "Planned deployment", "Responsibility"],
            ["Project manager", "1", "Programme, coordination, commercial control"],
            ["Site engineer", "1", "Measurements, permits, quality records"],
            ["Joinery supervisors", "2", "Factory and site installation interfaces"],
            ["Carpenters / installers", "12", "Counters, furniture, partitions, doors"],
            ["Civil and finishing crew", "8", "Repairs, ceilings, painting, snagging"],
            ["Safety and housekeeping", "2", "Toolbox talks, access, waste control"],
        ], widths=[48*mm, 38*mm, 78*mm])]
    story += [PageBreak()]
    return story


def commercial(v: Version):
    price = {1: "Not finalized", 2: "INR 2,317,500", 3: "INR 2,294,800", 4: "INR 2,288,400"}[v.number]
    story = heading("Section 05", "Commercial summary",
        "The portal item-rate schedule remains the controlling price bid. This summary does not alter BOQ descriptions or units.")
    story += [table([
        ["Commercial parameter", "Offer"],
        ["Quoted price excluding GST", price],
        ["GST", "Extra at the applicable statutory rate" if v.number >= 2 else "To be confirmed"],
        ["Completion", "45 calendar days"],
        ["Offer validity", "Four months"],
        ["Defects liability", "12 months"],
        ["Price basis", "Firm item rates; labour, materials, freight, duties, and taxes except GST included"],
    ], widths=[61*mm, 103*mm])]
    if v.number >= 3:
        story += [P("Priced work-breakdown summary", "h2"), table([
            ["Work package", "Amount (INR)", "Share"],
            ["Partitions, ceilings, and allied civil works", "434,600", "19.0%"],
            ["Counters, workstations, and storage joinery", "812,400", "35.5%"],
            ["Loose / fixed furniture and upholstery", "343,300", "15.0%"],
            ["Doors, glass, hardware, and ACP interfaces", "297,500", "13.0%"],
            ["Painting, polish, protective treatments", "217,400", "9.5%"],
            ["Mobilization, protection, testing, handover", "183,200", "8.0%"],
            ["TOTAL EXCLUDING GST", "2,288,400" if v.number == 4 else "2,294,800", "100.0%"],
        ], widths=[88*mm, 42*mm, 34*mm])]
        story += [P("Every portal BOQ line will be entered as an item rate. Descriptions, quantities, and units will not be edited. The authorized signatory has initialled and stamped each attached schedule in this synthetic pack.", "quote")]
    story += [PageBreak()]
    return story


def empanelment_and_emd(v: Version):
    story = heading("Section 06", "Eligibility and bid security evidence")
    story += [P("SBI empanelment and invitation evidence", "h2"), table([
        ["Record", "Details"],
        ["Empanelment category", "Interior and Furnishing Works - INR 25 lakh and above"],
        ["Synthetic reference", "SBI/DEL/INT/2026/041"],
        ["Validity", "01 April 2026 to 31 March 2027"],
        ["Project invitation", "Invitation email dated 31 August 2026 for DEL/AO-3/RBO-6/AMCC/IN/01"],
        ["Verification note", "Fictional record included only for local workflow demonstration"],
    ], widths=[48*mm, 116*mm])]
    story += [P("EMD", "h2"), table([
        ["Payment field", "Declared value"],
        ["Amount", "INR 23,600"],
        ["Mode", "Online bank transfer / NEFT"],
        ["Synthetic transaction", "SBIN-DEMO-18092026-23600"],
        ["Value date", "18 September 2026"],
        ["Beneficiary", "State Bank of India - as identified in tender instructions"],
        ["Evidence status", "Scanned payment acknowledgement enclosed"],
    ], widths=[48*mm, 116*mm])]
    story += [P("This page constitutes the scanned EMD evidence for extraction testing. It is not a real payment receipt and carries no negotiable value.", "quote"), PageBreak()]
    return story


def annexure_a():
    story = heading("Mandatory enclosure", "Undertaking (Annexure-A)",
        "Printed on the fictional bidder's letterhead, signed, stamped, and included with the technical bid.")
    declarations = [
        "We have carefully examined the tender documents and accept all conditions without deviation.",
        "We visited the New Tehri site and assessed access, protection, storage, working hours, and coordination constraints.",
        "We will complete the work within 45 days and keep the offer valid for four months.",
        "We have remitted EMD of INR 23,600 and included the scanned evidence in the technical bid.",
        "No conditional qualification, alternate condition, or alteration to the tender format is proposed.",
        "The list of directors and the authority of the signatory are included in the bidder information schedules.",
        "All tender pages and schedules included in this pack have been reviewed for signature and company seal.",
    ]
    story += [P("We, Himalayan Workspace Projects Pvt. Ltd. (fictional), provide the following undertaking:")]
    story += [bullet(x) for x in declarations]
    story += [Spacer(1, 6*mm), table([
        ["Authorized signatory", "Arjun Mehta (fictional)"],
        ["Signature", "/s/ Arjun Mehta - SYNTHETIC"],
        ["Company stamp", "HWPPL - DEMONSTRATION SEAL"],
        ["Place and date", "Dehradun / 18 September 2026"],
    ], widths=[48*mm, 116*mm], header=False), PageBreak()]
    return story


def annexure_b():
    story = heading("Mandatory enclosure", "Process Compliance Statement (Annexure-B)",
        "Signed and stamped process declaration for participation in the SBI e-tender event.")
    story += [P("We confirm that:")]
    for x in [
        "the e-tender procedures, event rules, and service-provider instructions have been read and understood;",
        "our authorized representative has completed the necessary process familiarization;",
        "a valid Digital Signature Certificate will be used for portal authentication and bid submission;",
        "all portal bids and item rates entered through the authorized account will be honoured;",
        "we will not disclose credentials or attempt to disrupt, manipulate, or bypass the bidding process; and",
        "we accept the Bank's right to reject a bid that does not follow the prescribed process.",
    ]:
        story.append(bullet(x))
    story += [table([
        ["Authorized representative", "Arjun Mehta (fictional)"],
        ["DSC identifier", "DEMO-DSC-HWPPL-2026-09"],
        ["DSC validity", "31 March 2027"],
        ["Signature", "/s/ Arjun Mehta - SYNTHETIC"],
        ["Company stamp", "HWPPL - DEMONSTRATION SEAL"],
    ], widths=[48*mm, 116*mm], header=False), PageBreak()]
    return story


def compliance_email_and_works():
    story = heading("Mandatory enclosures", "Compliance email and ongoing SBI works")
    story += [P("Compliance form", "h2"), table([
        ["Transmission field", "Evidence"],
        ["Form", "Prescribed e-tender compliance form"],
        ["Sent to", "Service-provider event desk - synthetic demonstration address"],
        ["Sent before event", "Yes - 17 September 2026, 11:42 IST"],
        ["Synthetic message ID", "DEMO-MSG-SBI-AMCC-17092026"],
        ["Attachment", "HWPPL_SBI_AMCC_Compliance_Form.pdf"],
        ["Status", "Email dispatch record and form enclosed"],
    ], widths=[47*mm, 117*mm])]
    story += [P("List of ongoing works in SBI Delhi Circle with scheduled completion date", "h2")]
    story += [table([
        ["Work order", "Description", "Scheduled completion", "Position"],
        ["SBI/DEL/INT/26/118", "RACPC Noida interior refresh", "30 Oct 2026", "On schedule"],
        ["SBI/DEL/INT/26/074", "Lajpat Nagar branch counters", "15 Sep 2026", "Completed 12 Sep"],
        ["SBI/DEL/INT/26/129", "RBO Ghaziabad meeting rooms", "18 Nov 2026", "On schedule"],
    ], widths=[37*mm, 63*mm, 34*mm, 30*mm])]
    story += [P("Delayed works count: 0. The bidder therefore does not exceed the tender's stated disqualification trigger of more than two delayed ongoing works.", "quote"), PageBreak()]
    return story


def site_quality_safety():
    story = heading("Section 10", "Site, quality, and safety plans")
    story += [P("Site visit record", "h2"), table([
        ["Visit", "Record"],
        ["Date / time", "10 September 2026 / 11:00-13:10"],
        ["Location", "Proposed AMCC Branch, New Tehri, Uttarakhand"],
        ["Attendees", "Fictional bidder site engineer and architect representative"],
        ["Observed controls", "Occupied-building protection, restricted storage, dust and noise control, daily debris removal"],
    ], widths=[45*mm, 119*mm])]
    story += [P("Inspection and test plan", "h2"), table([
        ["Element", "Check", "Record"],
        ["Plywood / timber", "Grade, thickness, moisture, knot percentage", "Material receipt and test sheet"],
        ["Laminates", "Make, shade, IS reference, thickness", "Approval and batch record"],
        ["Joinery", "Dimensions, squareness, edge finish, hardware", "First-off and room checklist"],
        ["Treatments", "Anti-termite ratio/coats; hidden-surface coating", "Concealed-work inspection"],
        ["Glass / doors", "Thickness, edges, hardware operation", "Installation checklist"],
        ["Finishes", "Preparation, primer, coat count, shade", "Finish inspection sheet"],
    ], widths=[38*mm, 75*mm, 51*mm])]
    story += [P("Safety and protection", "h2")]
    for x in [
        "Daily toolbox talk, induction, PPE, guarded power tools, and inspected electrical leads.",
        "Dust barriers and floor protection before demolition, drilling, or paint preparation.",
        "Hot-work and work-at-height permits where applicable; extinguishers kept at the activity location.",
        "Waste segregated and removed daily; access and fire routes maintained at all times.",
    ]:
        story.append(bullet(x))
    story += [PageBreak()]
    return story


def boq_schedule():
    story = heading("Price bid evidence", "Item-rate BOQ control schedule",
        "This schedule evidences the item-rate method. The e-tender portal remains the controlling submission channel.")
    story += [table([
        ["Control", "Bidder confirmation"],
        ["Item rates", "Entered online against each issued BOQ line"],
        ["Descriptions / units", "Not changed"],
        ["Arithmetic", "Line extensions and grand total independently checked"],
        ["Tax basis", "GST excluded; all other taxes and incidental costs included"],
        ["Alterations", "None"],
        ["Authentication", "Every price schedule page signed and stamped"],
        ["Quoted total", "INR 2,288,400 excluding GST"],
    ], widths=[49*mm, 115*mm])]
    story += [P("BOQ authentication certificate", "h2"), P(
        "I certify that the issued item descriptions, quantities, and units have not been amended; all item rates are entered; the grand total has been checked; and each page is initialled and stamped by the authorized signatory.", "quote")]
    story += [table([
        ["Signed", "/s/ Arjun Mehta - SYNTHETIC"],
        ["Stamped", "HWPPL - DEMONSTRATION SEAL"],
        ["Date", "18 September 2026"],
    ], widths=[48*mm, 116*mm], header=False), PageBreak()]
    return story


def sealed_envelope_and_annexure_ii():
    story = heading("Mandatory enclosures", "Physical delivery and service-provider statement")
    story += [P("Demand Draft of specified amount of EMD", "h2"), table([
        ["Instrument field", "Synthetic evidence"],
        ["Demand draft number", "DEMO-DD-23600-180926"],
        ["Amount", "INR 23,600"],
        ["Drawn in favour of", "State Bank of India - as specified in tender"],
        ["Instrument status", "Copy enclosed; original listed in sealed envelope"],
        ["Caution", "Fictional non-negotiable demonstration instrument"],
    ], widths=[50*mm, 114*mm])]
    story += [P("Sealed-envelope transmittal", "h2"), table([
        ["Delivery field", "Evidence"],
        ["Addressee", "Bank's Civil Engineer at the tender address"],
        ["Contents", "Original EMD instrument and duly signed process compliance form"],
        ["Dispatch", "Hand delivery scheduled before 22 September 2026, 15:00 IST"],
        ["Synthetic receipt", "SBI-RBO6-DEMO-ACK-210926-1045"],
        ["Status", "Sealed-envelope checklist and acknowledgement enclosed"],
    ], widths=[50*mm, 114*mm])]
    story += [P("Process Compliance Statement (Annexure-II)", "h2"), P(
        "We have read the e-tender event terms supplied by M/s Antares Systems Limited, understand the online bidding process, will use the authorized Digital Signature Certificate, and agree to be bound by every valid bid entered through our account. This statement is signed, stamped, and included for the service provider.", "quote")]
    story += [table([
        ["Authorized representative", "Arjun Mehta (fictional)"],
        ["Signature", "/s/ Arjun Mehta - SYNTHETIC"],
        ["Company stamp", "HWPPL - DEMONSTRATION SEAL"],
        ["Date", "18 September 2026"],
    ], widths=[50*mm, 114*mm], header=False), PageBreak()]
    return story


def authorization():
    story = heading("Supporting schedule", "Authority, DSC, and declarations")
    story += [P("Authorized signatory and power of attorney", "h2"), P(
        "The fictional board resolution HWPPL/BR/2026/19 authorizes Arjun Mehta, Director - Projects, to sign, digitally submit, clarify, and bind the company in relation to tender DEL/AO-3/RBO-6/AMCC/IN/01. The authority remains valid through the offer-validity period.")]
    story += [P("Digital Signature Certificate", "h2"), table([
        ["Certificate field", "Details"],
        ["Holder", "Arjun Mehta (fictional)"],
        ["Certificate class", "Signing and encryption certificate"],
        ["Synthetic serial", "DEMO-DSC-HWPPL-2026-09"],
        ["Valid until", "31 March 2027"],
        ["Document present", "Yes - certificate particulars enclosed"],
    ], widths=[48*mm, 116*mm])]
    story += [P("Declarations", "h2")]
    for x in [
        "The bidder is not blacklisted, debarred, insolvent, or under liquidation.",
        "No conflict of interest exists in relation to this tender.",
        "All information in this synthetic demonstration pack is internally consistent with the staged answer key.",
        "The bidder accepts verification of empanelment, ongoing works, payment evidence, and authorization records.",
    ]:
        story.append(bullet(x))
    story += [PageBreak()]
    return story


def final_checklist(v: Version):
    complete = v.number == 4
    rows = [["Mandatory requirement", "Status", "Evidence location"]]
    requirements = [
        ("Bank's empaneled Interiors & furnishing category contractors with SBI under appropriate category who are invited by the project Architect/SBI", v.number >= 2, "Eligibility and EMD section"),
        ("Undertaking (Annexure-A)", v.number >= 2, "Annexure-A section"),
        ("Process Compliance Statement (Annexure-B)", v.number >= 3, "Annexure-B section"),
        ("EMD", v.number >= 2, "Eligibility and EMD section"),
        ("list of ongoing works in SBI Delhi Circle with scheduled completion date", v.number >= 3, "Ongoing works schedule"),
        ("compliance form", v.number >= 3, "Email transmission schedule"),
        ("Demand Draft of specified amount of EMD", complete, "Physical delivery section"),
        ("Process compliance form", v.number >= 3, "Annexure-B / email schedule"),
        ("Process Compliance Statement (Annexure-II)", complete, "Service-provider statement"),
    ]
    for req, present, where in requirements:
        rows.append([req, "ENCLOSED" if present else "NOT ENCLOSED", where if present else "Outstanding in this staged version"])
    story = heading("Submission control", "Mandatory enclosure checklist",
        "The exact extracted requirement names are used here so each upload can be compared consistently.")
    story += [table(rows, widths=[87*mm, 31*mm, 46*mm])]
    if complete:
        story += [P("Final completeness certification", "h2"), P(
            "All eight deduplicated mandatory enclosure groups extracted by the application are present in Version 4. The signed-and-stamped, page-authentication, portal-entry, and sealed-envelope requirements are evidenced in this pack and remain subject to the application's human-review safeguard.", "quote")]
        story += [table([
            ["Technical upload", "Annexure-A, Annexure-B, and scanned EMD evidence included"],
            ["Hard-copy pack", "Annexure-A, Annexure-B, EMD instrument, and transmittal included"],
            ["Portal price bid", "Item rates prepared without editing issued descriptions or units"],
            ["Every page", "Reviewed for synthetic signature / demonstration stamp"],
        ], widths=[46*mm, 118*mm], header=False)]
    else:
        outstanding = sum(1 for _, present, _ in requirements if not present)
        story += [P(f"Staged completeness note: {outstanding} mandatory enclosure group(s) remain outstanding in this version. This is intentional for the progressive upload demonstration.", "quote")]
    story += [Spacer(1, 8*mm), P("END OF SYNTHETIC BID VERSION", "eyebrow")]
    return story


def build_story(v: Version):
    names = ["Bidder profile", "Letter of bid", "Technical methodology", "45-day programme", "Commercial summary"]
    if v.number >= 2:
        names += ["Eligibility and EMD evidence", "Undertaking (Annexure-A)"]
    if v.number >= 3:
        names += ["Process Compliance Statement (Annexure-B)", "Compliance form and SBI ongoing works", "Site / quality / safety", "BOQ control schedule"]
    if v.number == 4:
        names += ["Demand Draft and sealed-envelope transmittal", "Process Compliance Statement (Annexure-II)", "Authority and DSC"]
    names += ["Mandatory enclosure checklist"]

    story = []
    story += cover(v)
    story += contents(v, names)
    story += bidder_profile(v)
    story += letter_of_bid(v)
    story += methodology(v)
    story += programme(v)
    story += commercial(v)
    if v.number >= 2:
        story += empanelment_and_emd(v)
        story += annexure_a()
    if v.number >= 3:
        story += annexure_b()
        story += compliance_email_and_works()
        story += site_quality_safety()
        story += boq_schedule()
    if v.number == 4:
        story += sealed_envelope_and_annexure_ii()
        story += authorization()
    story += final_checklist(v)
    return story


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for version in VERSIONS:
        path = OUTPUT / f"version{version.number}.pdf"
        doc = BidDocTemplate(str(path), version)
        doc.build(build_story(version))
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
