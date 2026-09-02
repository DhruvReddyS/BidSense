"""Assemble a bid document from content blocks, at a configurable size.

Real technical bids are long for structural reasons, not padding. A 200-page
EPC bid is mostly: clause-by-clause specification compliance, a CV per named
person, a method statement per activity, a case study per cited project, a
declaration per page, an item-wise price schedule, and reproduced annexures.

Generating those properly matters for the pipeline under test. Page selection
(`app.extraction.selection`) exists precisely because a real document buries
three relevant clauses in hundreds of pages of boilerplate; a bid that is nine
tidy pages never exercises it. These documents do.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.bidgen import content
from app.bidgen.spec import TenderProfile, VendorSpec


@dataclass(frozen=True)
class BidScale:
    """How much of each section to emit.

    Sized to the tender rather than chosen arbitrarily: a Rs. 12 lakh boundary
    wall does not attract a 200-page bid, and pretending otherwise would make
    the test set less realistic, not more.
    """

    name: str
    personnel: int
    projects: int
    method_activities: int
    spec_rows: int
    declarations: int
    boq_expansion: int          # sub-items generated per BOQ line
    annexure_packets: int       # reproduced annexure sets
    itp_activities: int         # inspection & test plan entries
    site_packets: int           # per-site/zone annexures (EPC style)


COMPACT = BidScale(
    name="compact", personnel=6, projects=2, method_activities=8, spec_rows=18,
    declarations=8, boq_expansion=0, annexure_packets=1, itp_activities=6,
    site_packets=0,
)
STANDARD = BidScale(
    name="standard", personnel=10, projects=3, method_activities=15, spec_rows=40,
    declarations=12, boq_expansion=2, annexure_packets=2, itp_activities=12,
    site_packets=4,
)
COMPREHENSIVE = BidScale(
    name="comprehensive", personnel=15, projects=4, method_activities=15,
    spec_rows=45, declarations=12, boq_expansion=4, annexure_packets=3,
    itp_activities=18,
    # A 13 MW rooftop plant spans dozens of roof blocks, and a real EPC bid
    # carries a survey and interface sheet for each one. This is the section
    # that legitimately takes a large bid past two hundred pages.
    site_packets=48,
)

SCALES = {s.name: s for s in (COMPACT, STANDARD, COMPREHENSIVE)}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _person(index: int) -> tuple[str, str, str, str, str]:
    """Deterministic name for a role, so regenerating a bid is reproducible."""
    role, qualification, years, responsibility = content.PERSONNEL_ROLES[
        index % len(content.PERSONNEL_ROLES)
    ]
    first = content.FIRST_NAMES[index % len(content.FIRST_NAMES)]
    last = content.LAST_NAMES[(index * 7) % len(content.LAST_NAMES)]
    return f"{first} {last}", role, qualification, years, responsibility


def _table(rows: list[tuple[str, ...]], headers: tuple[str, ...], widths: tuple[int, ...]) -> str:
    """Fixed-width table. Monospaced in the PDF so columns survive to the text
    layer, which is what the parser reads back."""
    line = "  ".join(h[:w].ljust(w) for h, w in zip(headers, widths))
    rule = "-" * len(line)
    body = [
        "  ".join(str(c)[:w].ljust(w) for c, w in zip(row, widths))
        for row in rows
    ]
    return "\n".join([line, rule, *body])


def _wrapped_rows(rows: list[tuple[str, ...]], widths: tuple[int, ...]) -> list[tuple[str, ...]]:
    """Split over-long first cells across continuation rows, as a real printed
    schedule does, rather than truncating the description."""
    out: list[tuple[str, ...]] = []
    for row in rows:
        head = str(row[0])
        width = widths[0]
        if len(head) <= width:
            out.append(row)
            continue
        words, line, chunks = head.split(), "", []
        for word in words:
            if len(line) + len(word) + 1 > width:
                chunks.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            chunks.append(line)
        out.append((chunks[0], *row[1:]))
        for extra in chunks[1:]:
            out.append((f"  {extra}", *("" for _ in row[1:])))
    return out


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #
def section_personnel(spec: VendorSpec, tender: TenderProfile, scale: BidScale) -> list[str]:
    """One CV per named person. Real bids reproduce these in full."""
    pages = [
        """SECTION 7 — ORGANISATION AND KEY PERSONNEL

7.1 Project Organisation

The work will be executed under a dedicated project organisation reporting to
our Chief Operating Officer. The organisation chart submitted at Annexure VII
shows the reporting lines and the interfaces with the Employer's
Engineer-in-Charge.

7.2 Commitment on Deployment

The personnel named in this section will be deployed for the duration of the
contract. None of them will be replaced without the prior written approval of
the Engineer-in-Charge, and then only by a person of equal or better
qualification and experience. Curricula vitae, attested copies of degree
certificates and experience certificates for each are enclosed.

7.3 Summary of Key Personnel
"""
    ]

    summary_rows = []
    for index in range(scale.personnel):
        name, role, qualification, years, _ = _person(index)
        summary_rows.append((role, name, qualification, f"{years} yrs"))
    pages[0] += "\n" + _table(
        summary_rows, ("Position", "Name", "Qualification", "Experience"),
        (30, 20, 40, 10),
    )

    for index in range(scale.personnel):
        name, role, qualification, years, responsibility = _person(index)
        pages.append(f"""7.{index + 4} Curriculum Vitae — {role}

Name                     : {name}
Position proposed        : {role}
Date of birth            : {1968 + (index * 3) % 28}
Nationality              : Indian
Qualification            : {qualification}
Total experience         : {years} years
Years with this firm     : {min(int(years), 4 + index % 9)} years
Languages                : English, Hindi, Telugu

Responsibilities on this contract

{responsibility} The postholder will be present at site for the periods
required by the contract and will attend all progress review meetings convened
by the Engineer-in-Charge.

Employment record

{2025 - int(years)} to {2025 - int(years) + 4}   Site Engineer, regional
                        infrastructure contracts. Responsible for execution
                        supervision, measurement and quality records on works of
                        similar nature and magnitude.

{2025 - int(years) + 4} to {2025 - int(years) + 9}   Senior Engineer, with
                        additional responsibility for sub-contractor
                        coordination, material planning and interface with
                        statutory authorities.

{2025 - int(years) + 9} to date   {role} with {spec.vendor_name}, discharging
                        the responsibilities set out above on contracts
                        comparable to the present work.

Relevant project experience

Deployed on the {spec.projects[index % len(spec.projects)]['client']} contract
of value {spec.projects[index % len(spec.projects)]['value']}, where the
postholder was responsible for the corresponding function through execution and
handover, including the preparation of the quality dossier and the as-built
documentation.

Certifications and training

Holder of the qualifications listed above. Trained in the firm's safety
induction programme and, where applicable to the role, in the operation of the
project planning and quality management systems in use on this contract.

Declaration

I confirm that the particulars given above are correct and that I am available
to be deployed on this contract for the period stated.


(Signature)                                    ({name})
""")
    return pages


def section_experience(spec: VendorSpec, tender: TenderProfile, scale: BidScale) -> list[str]:
    """A case study per cited project, at the length a real bid gives them."""
    pages = [f"""SECTION 5 — EXPERIENCE OF SIMILAR WORKS (Form F-13)

5.1 Eligibility Requirement

The requirement stipulated in the bid document is {tender.experience_requirement}.

5.2 Works Cited in Support

In support of the above we cite the works listed below. Copies of the work
orders and of the completion and satisfactory performance certificates issued by
the respective clients, each signed by an officer not below the rank of
Executive Engineer or equivalent, are enclosed at Annexure IV.

5.3 Summary of Cited Works
"""]

    rows = [
        (p["client"], p["value"], str(p["year"]), p["order_no"])
        for p in spec.projects
    ]
    pages[0] += "\n" + _table(
        _wrapped_rows(rows, (38, 20, 6, 24)),
        ("Client", "Value", "Year", "Work order no."),
        (38, 20, 6, 24),
    )
    pages[0] += """

5.4 Declaration on Cited Works

We confirm that each of the works cited above was executed by us in our own name
and not through any joint venture, consortium or sub-contract arrangement, and
that none of the contracts was terminated for default or foreclosed on account of
any act or omission on our part.
"""

    for index in range(min(scale.projects, len(spec.projects))):
        project = spec.projects[index]
        pages.append(f"""5.{index + 5} Case Study — {project['client']}

Contract particulars

Client                : {project['client']}
Work order number     : {project['order_no']}
Contract value        : {project['value']}
Year of completion    : {project['year']}
Contract duration     : {10 + (index * 3) % 14} months
Present status        : Completed and taken over

Scope of work

{project['scope']}. The contract was executed under the client's general
conditions with a defect liability period of twelve months following the taking
over certificate.

Approach adopted

The work was mobilised within fifteen days of the letter of award. A joint
survey with the client's representative established the baseline against which
all subsequent measurement was made. Execution proceeded in phases so that the
client's operations were not interrupted, with each phase handed over on
completion rather than the whole work being retained until the end.

Quality control

A project-specific quality assurance plan was approved before commencement,
identifying inspection and test plans, hold and witness points and acceptance
criteria for each activity. All test records were maintained at site and
submitted with each running account bill. No non-conformance remained open at
the time of taking over.

Safety performance

The contract was completed without a lost-time injury. Daily toolbox talks were
conducted, a permit-to-work system operated for all work at height and all live
electrical work, and personal protective equipment was issued to and enforced
for every worker on site.

Interfaces managed

Coordination was required with the local municipal authority for road cutting
permissions, with the electricity utility for shutdowns, and with the client's
own operations staff for access. All approvals were obtained in advance of the
programmed dates and no time extension was sought on account of interface delay.

Outcome and client feedback

The work was completed within the stipulated period and taken over without
deduction on account of delay. The completion certificate issued by the client
records that the work was executed to the entire satisfaction of the department,
and is enclosed at Annexure IV.

Relevance to the present work

The cited work is of similar nature and magnitude to the present work in that it
comprised {tender.technical_context} executed for a public authority under
comparable conditions of contract, and it demonstrates our capacity to mobilise,
execute and hand over work of this character within the time allowed.
""")
    return pages


def section_specification_compliance(tender: TenderProfile, scale: BidScale) -> list[str]:
    """Clause-by-clause compliance. The largest section of a real supply bid."""
    specs = content.SPECS_BY_SECTOR.get(tender.sector, content.CIVIL_SPECS)
    if tender.sector == "civil works" and "Solar" in tender.work_title:
        specs = content.SOLAR_SPECS
    specs = specs[: scale.spec_rows]

    pages = ["""SECTION 8 — COMPLIANCE WITH TECHNICAL SPECIFICATIONS

8.1 Statement of Compliance

We confirm that the goods and works offered comply in full with the technical
specifications of the bid document. Our clause-by-clause compliance is set out
below. Where the offered parameter exceeds the specified requirement, the
achieved value is stated; no clause is answered with a bare confirmation where a
measured value is available.

8.2 Basis of the Values Stated

The values recorded in the compliance column are drawn from type test reports
issued by NABL-accredited laboratories, from the manufacturer's published
technical datasheets, or from measurements taken on production samples. The
supporting reports are enclosed at Annexure VIII and are cross-referenced by
clause number.
"""]

    chunk = 14
    for start in range(0, len(specs), chunk):
        block = specs[start : start + chunk]
        rows = [
            (f"8.{start + i + 3}", parameter, requirement, response)
            for i, (parameter, requirement, response) in enumerate(block)
        ]
        page = f"8.{start // chunk + 3} Compliance Statement (continued)\n\n" if start else ""
        page += _table(
            _wrapped_rows(rows, (7, 34, 32, 34)),
            ("Clause", "Parameter", "Specified requirement", "Our compliance"),
            (7, 34, 32, 34),
        )
        pages.append(page)
    return pages


def section_method_statement(tender: TenderProfile, scale: BidScale) -> list[str]:
    """A sub-section per activity, as a real method statement is written."""
    activities = content.METHOD_ACTIVITIES.get(tender.sector, content.METHOD_ACTIVITIES["civil works"])
    activities = activities[: scale.method_activities]

    pages = [f"""SECTION 6 — METHOD STATEMENT

6.1 General

This method statement sets out how each activity comprised in the work will be
carried out, the sequence in which the activities will be undertaken, the
resources to be deployed and the controls to be applied. It has been prepared
against the site conditions recorded during our pre-bid site visit and against
the specifications forming part of the bid document.

6.2 Sequence of Operations

The activities are described below in the order in which they will be
undertaken. Activities which can proceed in parallel are identified as such in
the programme at Section 9. No activity carrying a hold point will proceed
until the Engineer-in-Charge has released it in writing.

6.3 Resources

The plant, machinery and manpower to be deployed against each activity are set
out in Section 10. Resources will be mobilised in advance of the programmed
start of each activity so that no activity waits on mobilisation.
"""]

    for index, (title, description) in enumerate(activities):
        pages.append(f"""6.{index + 4} {title}

Description of the activity

{description}

Method of execution

The activity will be carried out by a dedicated crew under the supervision of
the site engineer responsible for the discipline. Work will proceed only against
approved drawings and an approved inspection and test plan, and the supervisor
will satisfy himself before commencement that the preceding activity has been
released and that the working area is safe.

Resources deployed

One supervisor, the crew appropriate to the activity, and the plant listed in
Section 10 against this activity. Materials will be drawn from site stores
against an issue voucher and reconciled at the end of each week.

Quality controls

Inspection and test requirements applicable to this activity are set out in the
inspection and test plan at Section 11. Records will be raised on the day the
work is done, signed by the supervisor and countersigned by the quality
assurance engineer, and filed in the project quality dossier.

Safety controls

A job safety analysis has been prepared for this activity and will be briefed to
the crew before work starts. Personal protective equipment appropriate to the
activity will be issued and its use enforced. Where the activity involves work
at height, live electrical work or excavation, a permit to work will be raised
and closed on completion.

Interfaces and hold points

The Engineer-in-Charge will be given not less than twenty-four hours notice of
any hold point. Work will not proceed past a hold point without written release
recorded in the site order book.

Completion criteria

The activity is complete when the work has been executed to the specified
tolerance, the associated test records have been accepted, and the working area
has been cleared of surplus material and debris.
""")
    return pages


def section_quality_plan(tender: TenderProfile, scale: BidScale) -> list[str]:
    activities = content.METHOD_ACTIVITIES.get(tender.sector, content.METHOD_ACTIVITIES["civil works"])
    rows = [
        (
            f"{i + 1}",
            title[:34],
            "Visual / measurement" if i % 3 else "Documented test",
            "H" if i % 4 == 0 else ("W" if i % 4 == 1 else "R"),
            "Engineer-in-Charge" if i % 2 else "QA Engineer",
        )
        for i, (title, _) in enumerate(activities[: scale.itp_activities])
    ]

    return [
        """SECTION 11 — QUALITY ASSURANCE PLAN

11.1 Quality Policy

Our quality management system is certified to ISO 9001:2015 and the certificate
is enclosed. The system is applied to this contract through the project-specific
quality assurance plan described in this section, which will be submitted for the
approval of the Engineer-in-Charge within fifteen days of the award of work.

11.2 Responsibility and Authority

The Quality Assurance Engineer named in Section 7 reports functionally to our
corporate quality head and not to the project manager, so that acceptance
decisions are not subordinated to programme pressure. He holds the authority to
stop work where a non-conformance is detected and to refuse release of a hold
point.

11.3 Control of Materials

All materials brought to site will be accompanied by the manufacturer's test
certificate for the relevant lot. Samples will be submitted for approval before
bulk procurement, and material rejected by the Engineer-in-Charge will be removed
from site within forty-eight hours and recorded in the rejection register.

11.4 Inspection and Test Plan

The inspection and test plan below identifies, for each activity, the nature of
the inspection, whether it constitutes a hold point (H), a witness point (W) or a
review of records (R), and the party responsible.
""" + "\n" + _table(
            rows,
            ("Sl.", "Activity", "Nature of inspection", "Type", "Responsibility"),
            (4, 34, 24, 6, 22),
        ) + """

11.5 Control of Non-Conformance

A non-conformance report will be raised for any work that does not meet the
specified requirement. The report will record the nature of the non-conformance,
the disposition proposed, and the corrective action to prevent recurrence. No
non-conformance will be closed without the written acceptance of the
Engineer-in-Charge.

11.6 Records

The project quality dossier will be maintained at site and will be available for
inspection at all times. It will comprise material test certificates, inspection
records, test results, non-conformance reports and their closure, and calibration
certificates for all measuring equipment used on the contract.

11.7 Calibration

All measuring and test equipment used for acceptance will be calibrated by an
NABL-accredited laboratory, and the calibration certificates will be produced
before the equipment is used. Equipment found out of calibration will be
withdrawn and the affected measurements repeated.
"""
    ]


def section_hse(spec: VendorSpec, tender: TenderProfile) -> list[str]:
    return [
        """SECTION 12 — HEALTH, SAFETY AND ENVIRONMENT

12.1 Policy

We operate a written health and safety policy signed by our managing director
and displayed at every workplace. The policy commits the firm to providing a
workplace free from foreseeable hazard, to the provision of personal protective
equipment at our cost, and to the training of every person deployed.

12.2 Organisation

A qualified safety officer holding an Advanced Diploma in Industrial Safety will
be deployed for the duration of the contract. He reports to the corporate safety
head and has the authority to stop any activity he considers unsafe, without
reference to the project manager.

12.3 Induction and Training

No person will be permitted to work on site until he has undergone the site
safety induction covering the hazards present, the emergency assembly point, the
permit-to-work system and the reporting of incidents and near misses. A record of
induction will be maintained and the induction sticker affixed to the helmet.

12.4 Personal Protective Equipment

Helmet, safety shoes and high-visibility jacket will be issued to every person on
site. Full body harness with double lanyard will be issued for all work above two
metres, and electrical gloves and insulated tools for all live electrical work.
Use will be enforced and non-compliance treated as a disciplinary matter.

12.5 Permit to Work

A permit to work will be raised for work at height, live electrical work,
excavation deeper than 1.5 metre, confined space entry and hot work. The permit
will identify the hazards, the controls, the persons authorised and the validity
period, and will be closed on completion of the work.
""",
        """12.6 Toolbox Talks and Safety Meetings

A toolbox talk will be conducted at the start of each shift covering the
activities planned and their specific hazards. A weekly safety meeting chaired by
the project manager will review incidents, near misses and observations, and a
monthly safety report will be submitted to the Engineer-in-Charge.

12.7 Traffic and Public Safety

Where work affects a public road, retro-reflective barricading will be erected
for the full working length and trained flagmen deployed at both approaches.
Advance warning signage will be placed at the distance required by the local
traffic authority. Work on arterial roads will be carried out at night wherever
the Engineer-in-Charge so directs.

12.8 Emergency Preparedness

An emergency response plan will be prepared identifying the assembly point, the
nearest hospital, the emergency contact numbers and the route to be taken. A
first aid box and a trained first aider will be present at site whenever work is
in progress, and an emergency vehicle will be available on call.

12.9 Incident Reporting and Investigation

Every incident and near miss will be reported to the Engineer-in-Charge within
twenty-four hours and investigated to root cause. The investigation report and
the corrective action will be submitted within seven days.

12.10 Environmental Management

Debris and construction waste will be removed to a disposal site approved by the
local authority and the disposal challans retained. Water sprinkling will be
carried out to suppress dust. No burning of waste will be permitted on site. Used
oil and other hazardous waste will be handed to an authorised recycler and the
manifest retained.

12.11 Statutory Compliance

We will comply with the Building and Other Construction Workers Act 1996, the
Contract Labour (Regulation and Abolition) Act 1970, and the rules made
thereunder, and will maintain the registers prescribed. The labour licence will
be obtained before any workman is deployed and a copy furnished to the
Engineer-in-Charge.
""",
    ]


def section_programme(tender: TenderProfile) -> list[str]:
    return [
        f"""SECTION 9 — PROGRAMME AND SEQUENCE OF WORK

9.1 Overall Programme

The work will be completed within the period stipulated in the bid document. A
detailed bar chart prepared in Primavera P6, showing the activities, their
durations, their logical relationships and the critical path, is enclosed at
Annexure IX. The programme will be updated fortnightly and the updated programme
submitted with the monthly progress report.

9.2 Mobilisation

Mobilisation will commence within seven days of the letter of award and will be
complete within twenty-one days. Mobilisation comprises establishment of the site
office and stores, deployment of the key personnel named in Section 7,
mobilisation of the plant listed in Section 10, and obtaining the labour licence
and any permissions required from the local authority.

9.3 Critical Path

The critical path runs through approval of samples, manufacture and delivery of
the principal materials, and the sequential execution of the main activity. Our
programme allows a float of three weeks against the delivery of principal
materials, held deliberately because that is the activity least within our
control.

9.4 Sequencing Against Site Constraints

The sequence has been set against the constraints recorded during the site visit,
including access restrictions, the working window permitted by the Employer, and
the monsoon period. Activities sensitive to weather are programmed outside the
monsoon window so that a weather delay does not sit on the critical path.

9.5 Progress Monitoring and Reporting

Progress will be measured against the approved baseline and reported weekly in a
look-ahead format covering the three weeks ahead. A monthly progress report will
be submitted covering physical and financial progress, manpower and plant
deployed, quality and safety statistics, and any matters requiring the
Engineer-in-Charge's decision.

9.6 Recovery of Delay

Where progress falls behind the approved programme by more than five percent, a
recovery plan will be submitted within seven days identifying the additional
resources to be deployed and the revised sequence, at no additional cost to the
Employer where the delay is attributable to us.
"""
    ]


def section_plant(tender: TenderProfile) -> list[str]:
    plant = content.PLANT_BY_SECTOR.get(tender.sector, content.PLANT_BY_SECTOR["civil works"])
    rows = [(item, qty, ownership, "Available") for item, qty, ownership in plant]
    return [
        """SECTION 10 — PLANT, MACHINERY AND EQUIPMENT

10.1 Statement of Resources

The plant and machinery to be deployed on this contract is listed below. Items
shown as owned are in our possession and available for immediate deployment;
items shown as hired are covered by a standing arrangement with the equipment
supplier and will be mobilised in advance of the programmed start of the
activity for which they are required.
""" + "\n" + _table(
            _wrapped_rows(rows, (52, 10, 12, 12)),
            ("Description", "Quantity", "Ownership", "Status"),
            (52, 10, 12, 12),
        ) + """

10.2 Maintenance of Plant

All plant will be maintained in accordance with the manufacturer's schedule and
the maintenance records will be available at site. Plant found unserviceable will
be replaced within seventy-two hours so that no activity waits on plant failure.

10.3 Calibration of Measuring Equipment

All measuring and test equipment used for acceptance purposes will be calibrated
by an NABL-accredited laboratory before deployment, and the calibration
certificates will be produced to the Engineer-in-Charge on demand.
"""
    ]


def section_risk() -> list[str]:
    rows = [
        (risk, likelihood, impact, mitigation)
        for risk, likelihood, impact, mitigation in content.RISKS
    ]
    return [
        """SECTION 13 — RISK REGISTER

13.1 Approach to Risk

The risks identified below were assessed during our pre-bid review against the
site conditions, the programme and the conditions of contract. Each risk is
assigned an owner within our project organisation, and the register will be
reviewed at the monthly progress meeting and updated as risks are closed or new
risks emerge.
""" + "\n" + _table(
            _wrapped_rows(rows, (40, 10, 8, 52)),
            ("Risk", "Likelihood", "Impact", "Mitigation"),
            (40, 10, 8, 52),
        )
    ]


def section_boq(spec: VendorSpec, tender: TenderProfile, scale: BidScale) -> list[str]:
    items = content.BOQ_BY_SECTOR.get(tender.sector, content.BOQ_BY_SECTOR["civil works"])
    pages = [f"""SECTION 14 — PRICE SCHEDULE

14.1 Summary of Price

Our total price for the whole of the work, inclusive of all taxes, duties,
levies, cess, insurance, transportation, loading and unloading and all incidental
charges, is:

        {spec.quoted_price}
        ({spec.quoted_words})

14.2 Basis of Rates

The rates quoted are firm and are not subject to escalation during the currency
of the contract, save to the extent expressly provided in the conditions of
contract. The rates are inclusive of Goods and Services Tax at the applicable
rate and we shall raise invoices in accordance with the GST Act and the rules
made thereunder.

14.3 Item-wise Schedule
"""]

    rows: list[tuple[str, ...]] = []
    for index, (description, unit, quantity) in enumerate(items, start=1):
        rows.append((f"{index}", description, unit, quantity))
        for sub in range(scale.boq_expansion):
            rows.append((
                f"{index}.{sub + 1}",
                f"Sub-item: {['supply', 'installation', 'testing', 'documentation'][sub % 4]} "
                f"component of item {index}",
                unit, "As above",
            ))

    chunk = 16
    for start in range(0, len(rows), chunk):
        block = rows[start : start + chunk]
        page = "14.3 Item-wise Schedule (continued)\n\n" if start else ""
        page += _table(
            _wrapped_rows(block, (7, 58, 8, 12)),
            ("Item", "Description", "Unit", "Quantity"),
            (7, 58, 8, 12),
        )
        pages.append(page)

    pages.append("""14.4 Notes to the Price Schedule

(a) The quantities shown are those given in the bid document and are for the
    purpose of comparison of bids only. Payment will be made against the
    quantities actually executed and measured.

(b) The rates are deemed to include all costs of compliance with the conditions
    of contract, including the provision of the quality and safety arrangements
    described in Sections 11 and 12 of this bid.

(c) No claim will be made on account of any matter which a careful examination of
    the site and the bid document would have disclosed.

(d) Where an item is not separately priced, its cost is deemed to be distributed
    across the other items in this schedule.
""")
    return pages


def section_declarations(spec: VendorSpec, tender: TenderProfile, scale: BidScale) -> list[str]:
    """One declaration per page, reproduced in full, as a real bid does."""
    declarations = list(content.DECLARATIONS[: scale.declarations])
    pages = ["""SECTION 15 — DECLARATIONS AND UNDERTAKINGS

The declarations required by the bid document are reproduced in full on the
following pages, each signed by our authorised signatory and bearing the seal of
the firm. Where the bid document prescribes a format, the declaration has been
made in that format.
"""]

    for index, (title, body) in enumerate(declarations):
        # The blacklisting declaration is where a debarred bidder must disclose,
        # so the disclosure is placed exactly where a reader would look for it.
        if "Non-Blacklisting" in title and spec.is_blacklisted and spec.extra_declarations:
            body = "\n\n".join(spec.extra_declarations)

        pages.append(f"""15.{index + 1} {title}

To
The {tender.authority}

Ref: {tender.tender_ref}
Work: {tender.work_title}

Sir,

{body}

This declaration is made in the knowledge that the Employer will rely upon it in
evaluating our bid, and that any statement found to be false will render our bid
liable to rejection and our earnest money to forfeiture.

For {spec.vendor_name}


(Authorised Signatory)
Date  : {tender.bid_due}
Place : {spec.city}
Seal  :
""")
    return pages


def section_annexures(spec: VendorSpec, tender: TenderProfile, scale: BidScale) -> list[str]:
    """Reproduced annexures. Real bids run to dozens of these."""
    pages = ["""ANNEXURES

The documents listed in the checklist at Section 16 are reproduced in the
annexures that follow. Each annexure is separately tabbed and page numbered, and
the annexure number is cross-referenced against the checklist entry.
"""]

    annexure_titles = [
        ("I", "Statutory registrations — PAN, GST, EPFO, ESIC"),
        ("II", "Power of Attorney and Board Resolution"),
        ("III", "Audited financial statements and Chartered Accountant certificates"),
        ("IV", "Work orders and completion certificates for cited works"),
        ("V", "Certifications and accreditations held"),
        ("VI", "Bankers' solvency certificate and credit availability letter"),
        ("VII", "Project organisation chart"),
        ("VIII", "Type test reports and technical datasheets"),
        ("IX", "Detailed programme (bar chart)"),
        ("X", "Earnest money deposit — proof of remittance"),
    ]

    for packet in range(max(1, scale.annexure_packets)):
        for numeral, title in annexure_titles:
            pages.append(f"""ANNEXURE {numeral}{'' if packet == 0 else f'-{packet + 1}'} — {title.upper()}

Bidder     : {spec.vendor_name}
Tender ref : {tender.tender_ref}
Work       : {tender.work_title}

Contents of this annexure

The documents comprised in this annexure are listed below. Each is a true copy
of the original, self-attested by our authorised signatory. The originals will be
produced for verification at any time on the demand of the Employer.

  1.  {title} — principal document
  2.  {title} — supporting correspondence
  3.  {title} — attestation by authorised signatory

Certification

We certify that the documents reproduced in this annexure are true copies of the
originals in our possession, that none of them has been altered in any respect,
and that all of them are valid and subsisting as on the date of submission of
this bid.

For {spec.vendor_name}


(Authorised Signatory)
Date : {tender.bid_due}
""")

    # Per-site annexures, which is how a large EPC bid genuinely reaches length.
    for site in range(scale.site_packets):
        pages.append(f"""ANNEXURE XI-{site + 1} — SITE PARTICULARS, LOCATION {site + 1}

Bidder     : {spec.vendor_name}
Tender ref : {tender.tender_ref}

Site identification

Location reference   : L-{site + 1:03d}
Nature of the site   : As inspected during the pre-bid site visit
Access               : By metalled road, suitable for the plant to be deployed
Working window       : As permitted by the Employer for this location
Storage area         : Within the location, at the point to be allotted

Survey observations

The location was inspected and the existing conditions recorded. The dimensions
and levels taken during the survey are reflected in the quantities against which
our rates have been quoted. No condition was observed at this location which
would prevent execution by the method described in Section 6.

Sequence proposed for this location

Work at this location is programmed in the phase shown in the bar chart at
Annexure IX. Execution will follow the sequence set out in the method statement,
adapted at this location only in respect of the access and working window stated
above.

Interfaces at this location

Coordination will be required with the Employer's operations staff for access
and, where the work affects a public road, with the local traffic authority for
the necessary permission. Both will be sought in advance of the programmed start.

Declaration for this location

We confirm that we have inspected this location, that our rates take account of
the conditions found, and that we shall make no claim on account of any condition
which a careful inspection would have disclosed.

For {spec.vendor_name}


(Authorised Signatory)
""")
    return pages


def section_design_basis(spec: VendorSpec, tender: TenderProfile, scale: BidScale) -> list[str]:
    """Design basis report. A design-build contract cannot be bid without one,
    and it is a substantial document in its own right."""
    topics = [
        ("Scope and Design Life",
         "The design life of the plant is twenty-five years for the modules and the "
         "mounting structure, and ten years for the power conversion equipment with "
         "provision for mid-life replacement. All design calculations are prepared "
         "on that basis and are submitted for the approval of the Employer's "
         "engineer before procurement."),
        ("Codes and Standards",
         "The design follows the Indian Standards applicable to each discipline, the "
         "Central Electricity Authority (Measures relating to Safety and Electric "
         "Supply) Regulations, the Grid Code, and the technical standards for "
         "connectivity to the distribution system. Where an Indian Standard does not "
         "cover a matter the corresponding IEC standard is applied and the reference "
         "recorded."),
        ("Site and Meteorological Data",
         "Global horizontal irradiance, diffuse fraction, ambient temperature and "
         "wind speed have been taken from a commercial meteorological dataset for "
         "the location, cross-checked against the nearest ground station. The data "
         "used in the yield assessment is tabulated with its source and the period "
         "covered."),
        ("Structural Design Basis",
         "Wind loading is computed in accordance with IS 875 Part 3 for the basic "
         "wind speed applicable to the zone, with terrain category and topography "
         "factors as found on site. Seismic loading follows IS 1893. The roof is "
         "assessed for the imposed load of the array by a registered structural "
         "engineer, whose certificate is enclosed."),
        ("Array Layout and Shading",
         "Row spacing has been set from a shadow analysis on the winter solstice so "
         "that no row shades the next between nine in the morning and three in the "
         "afternoon. Near shading from parapets, service structures and existing "
         "installations has been modelled and the resulting loss is reflected in the "
         "yield assessment."),
        ("Electrical Design — DC",
         "String sizing has been carried out for the extremes of module temperature "
         "so that the open circuit voltage at the lowest expected temperature "
         "remains within the inverter's maximum input voltage, and the maximum power "
         "point voltage at the highest expected temperature remains within the MPPT "
         "window. DC cable sizing limits the voltage drop to two percent at full "
         "output."),
        ("Electrical Design — AC",
         "AC cable sizing limits the voltage drop to one percent from the inverter "
         "to the point of interconnection. Short circuit withstand has been verified "
         "against the fault level advised by the utility. The protection scheme, its "
         "settings and the coordination study are submitted for approval before "
         "energisation."),
        ("Earthing and Lightning Protection",
         "The earthing system is designed to IS 3043 with chemical earthing "
         "electrodes and a buried conductor grid interconnecting all metallic "
         "structures. Lightning protection is designed to IS/IEC 62305 using the "
         "rolling sphere method, with air terminations positioned so that the array "
         "falls within the zone of protection."),
        ("Energy Yield Assessment",
         "The yield assessment has been prepared using industry standard software "
         "with the loss factors tabulated individually: soiling, shading, mismatch, "
         "DC and AC ohmic losses, inverter conversion, transformer losses, auxiliary "
         "consumption and availability. The performance ratio resulting from the "
         "assessment supports the guarantee offered."),
        ("Evacuation and Grid Interface",
         "Power is evacuated at 33 kV through the substation described in the scope. "
         "The interface with the utility, including metering, protection and "
         "communication, is designed to the utility's published requirements, and "
         "the connectivity application will be filed immediately on award."),
        ("Fire Safety",
         "Fire safety follows the National Building Code 2016 for rooftop "
         "installations, with segregation distances, access ways for firefighting, "
         "and DC isolation accessible at ground level. Portable extinguishers of the "
         "class appropriate to electrical fire are provided at each inverter "
         "station."),
        ("Monitoring and Control",
         "A plant level SCADA system records inverter level generation, string level "
         "current where combiner monitoring is provided, irradiance from a "
         "calibrated pyranometer, and module and ambient temperature. Data is "
         "retained for the full term of the O&M period and made available to the "
         "Employer through a web interface."),
    ]

    pages = ["""SECTION 17 — DESIGN BASIS REPORT

17.1 Purpose

This design basis report records the criteria against which the plant will be
designed, the codes and standards applied, and the assumptions made. It is
submitted with the bid so that the Employer's engineer can satisfy himself that
the offered design meets the requirements of the specification. The detailed
design will be developed against this basis after award and submitted for
approval before procurement.

17.2 Design Responsibility

Design is carried out by our in-house engineering group under the Design Engineer
named in Section 7, and is independently checked before issue. Structural
calculations affecting the existing roof are certified by a registered structural
engineer whose certificate is enclosed.
"""]

    for index, (title, body) in enumerate(topics):
        pages.append(f"""17.{index + 3} {title}

{body}

Documents to be submitted

The calculations, drawings and datasheets supporting this element of the design
will be submitted for the approval of the Employer's engineer in accordance with
the document submission schedule, and procurement of the affected items will not
commence until that approval is received.

Verification

The design will be verified against the criteria stated above by our independent
checker before issue, and the check record will be available for audit by the
Employer at any time.
""")
    return pages


def section_om_plan(spec: VendorSpec, tender: TenderProfile) -> list[str]:
    return [
        """SECTION 18 — OPERATION AND MAINTENANCE PLAN

18.1 Scope of the O&M Obligation

The comprehensive operation and maintenance obligation runs for five years from
the date of taking over. It covers preventive maintenance, breakdown
rectification, the supply of all spares and consumables, module cleaning, and the
performance reporting described below, at no additional cost to the Employer.

18.2 O&M Organisation

A resident O&M team will be stationed at site under the O&M Manager named in
Section 7. The team will comprise the technicians and support staff necessary to
meet the response times committed below, and will be supported by our regional
service centre for specialist intervention.

18.3 Preventive Maintenance Schedule

Preventive maintenance is carried out to a published schedule with daily, weekly,
monthly, quarterly and annual tasks. Daily tasks comprise generation review and
alarm inspection. Weekly tasks comprise module cleaning and visual inspection of
the array. Monthly tasks comprise inverter filter cleaning, torque checks on
electrical connections and earthing continuity verification. Quarterly tasks add
thermographic inspection of terminations and testing of protection relays. Annual
tasks add insulation resistance testing, earth resistance measurement and a full
calibration of the metering and monitoring instruments.
""",
        """18.4 Breakdown Response

Faults are classified by their effect on generation. A fault affecting more than
ten percent of plant output will be attended within four hours of detection and
rectified within twenty-four hours. Any other fault will be attended within
twenty-four hours and rectified within seventy-two hours. Response times are
measured from the raising of the alarm by the monitoring system, not from a
report by the Employer.

18.5 Spares Holding

A spares inventory sized against the failure rates published by the equipment
manufacturers will be held at site from the date of taking over. The inventory
includes inverter power modules, fuses, surge protection devices, string cables,
connectors and monitoring components. Consumption is replenished within thirty
days so that the holding does not deplete over the term.

18.6 Module Cleaning

Modules will be cleaned not less than once per week using demineralised water and
soft brushes, and more frequently during periods of high soiling. Cleaning is
recorded and the effect on generation is reported so that the frequency can be
adjusted against measured soiling loss rather than assumption.

18.7 Performance Reporting

A monthly performance report will be submitted covering generation against
budget, performance ratio, plant availability, faults raised and closed with
their durations, preventive maintenance completed, and spares consumed. An annual
report will additionally cover degradation measured against the previous year and
any recommendations for the year ahead.

18.8 Performance Guarantees

We guarantee a performance ratio of not less than that stated in our compliance
statement, and plant availability of not less than ninety-seven percent measured
annually excluding grid unavailability and force majeure. Liquidated damages for
shortfall will apply on the basis set out in the conditions of contract.

18.9 Handback Condition

At the end of the O&M period the plant will be handed back in a condition
consistent with normal wear, with the spares inventory replenished to the agreed
level, the monitoring records transferred in full, and a joint inspection carried
out to record the condition of each major item.
""",
        """SECTION 19 — TRAINING PLAN

19.1 Objective

The Employer's personnel will be trained so that they are able to operate the
plant, interpret the monitoring system, respond to routine alarms and supervise
our O&M team effectively.

19.2 Programme

Training is delivered in three modules. The first, of two days, covers the plant
description, the single line diagram and the safety rules. The second, of three
days, covers the monitoring system, alarm interpretation and first-line response.
The third, of two days, covers routine maintenance, record keeping and the
handover arrangements at the end of the O&M period.

19.3 Delivery

Training is delivered at site by the Commissioning Engineer and the O&M Manager,
with classroom sessions supported by supervised practical work on the installed
equipment. Training material in English is issued to each participant and a
master copy is handed to the Employer.

19.4 Refresher Training

Refresher training of one day will be delivered annually during the O&M period,
and additional sessions will be delivered whenever the Employer deploys new
personnel, at no additional cost.

19.5 Records

Attendance records and an assessment for each participant will be maintained and
submitted to the Employer at the conclusion of each module.
""",
    ]
