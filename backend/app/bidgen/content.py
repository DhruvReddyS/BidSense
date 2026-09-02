"""Domain vocabulary for generating long, realistic bid documents.

Real technical bids reach fifty to two hundred pages through a handful of
sections that legitimately repeat: clause-by-clause specification compliance,
personnel CVs, per-activity method statements, item-wise price schedules and
reproduced annexures. Padding with filler would defeat the purpose -- extraction
has to meet the shape of a real document, including the long stretches of
boilerplate that a real bid contains and that a naive extractor drowns in.

Everything here is structured data expanded by `sections.py`, so a 200-page bid
is generated from a few hundred lines rather than written out.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Specification compliance rows, by sector.
#
# A real supply bid answers the technical specification clause by clause. This
# is the single largest section in most bids and the one that most reliably
# buries an eligibility failure in the middle of a document.
# --------------------------------------------------------------------------- #
LED_SPECS: list[tuple[str, str, str]] = [
    ("Luminaire wattage — 35W variant", "35W ± 5%", "Complied. Measured 34.6W at 230V AC."),
    ("Luminaire wattage — 70W variant", "70W ± 5%", "Complied. Measured 69.2W at 230V AC."),
    ("Luminaire wattage — 110W variant", "110W ± 5%", "Complied. Measured 108.8W at 230V AC."),
    ("System luminous efficacy", "Not less than 130 lm/W", "Complied. 138 lm/W as per LM-79 report."),
    ("LED chip make", "Nichia / Osram / Cree / Lumileds", "Complied. Osram Duris S5 deployed."),
    ("Colour temperature", "5700K ± 300K", "Complied. Measured 5680K."),
    ("Colour rendering index", "CRI > 70", "Complied. CRI 74 measured."),
    ("Driver make", "Meanwell / Philips / Osram", "Complied. Meanwell HLG series."),
    ("Driver efficiency", "> 90% at full load", "Complied. 93.1% measured."),
    ("Power factor", "> 0.95 at full load", "Complied. 0.98 measured."),
    ("Total harmonic distortion", "THD < 10%", "Complied. 6.4% measured."),
    ("Surge protection", "10kV / 10kA as per IEC 61000-4-5", "Complied. External SPD provided."),
    ("Ingress protection — luminaire", "IP66 minimum", "Complied. IP66 certified."),
    ("Ingress protection — driver compartment", "IP66 minimum", "Complied."),
    ("Impact protection", "IK08 minimum", "Complied. IK09 achieved."),
    ("Housing material", "Die-cast aluminium, powder coated", "Complied. LM6 grade alloy."),
    ("Housing thickness", "Not less than 2.5 mm", "Complied. 3.0 mm."),
    ("Lens material", "Toughened glass / PMMA", "Complied. Toughened glass 4 mm."),
    ("Operating voltage range", "140V to 280V AC", "Complied. 120V-300V achieved."),
    ("Operating temperature", "-10°C to +55°C ambient", "Complied."),
    ("Lumen maintenance", "L70 at 50,000 hours", "Complied. LM-80 report enclosed."),
    ("Warranty", "5 years comprehensive on-site", "Complied. 5 years offered."),
    ("BIS registration", "Mandatory under CRO", "Complied. Registration enclosed."),
    ("Photobiological safety", "Risk Group 1 or exempt per IEC 62471", "Complied. RG1."),
    ("EMI / EMC compliance", "As per CISPR 15", "Complied. Test report enclosed."),
    ("Mounting arrangement", "Suitable for 40-60 mm dia bracket", "Complied. Adjustable."),
    ("Tilt adjustment", "0° to 15° at site", "Complied. Toolless adjustment."),
    ("Cable entry", "Through gland, IP66 rated", "Complied. PG-13.5 gland."),
    ("Earthing terminal", "Provided on housing", "Complied. M6 stud."),
    ("Marking", "Make, wattage, month/year of manufacture", "Complied. Laser etched."),
    ("Heat sink design", "Integral fin type, no forced cooling", "Complied."),
    ("Junction temperature", "Tj less than 85°C at rated ambient", "Complied. 78°C measured."),
    ("Optical distribution", "Type II / Type III as per site", "Complied. Both offered."),
    ("Glare rating", "Unified Glare Rating within limits of IS 1944", "Complied."),
    ("Photometric file", "IES file to be furnished", "Complied. Enclosed on media."),
    ("Third party inspection", "By agency nominated by Employer", "Accepted."),
    ("Sample approval", "Prior to bulk manufacture", "Accepted."),
    ("Packing", "Individual carton with foam cushioning", "Complied."),
    ("Delivery schedule", "As per Employer's phased programme", "Accepted."),
    ("Spares", "2% of supplied quantity as free spares", "Complied."),
]

SOLAR_SPECS: list[tuple[str, str, str]] = [
    ("Module technology", "Mono-crystalline PERC or better", "Complied. Mono PERC bifacial."),
    ("Module wattage", "Not less than 540 Wp", "Complied. 550 Wp modules offered."),
    ("Module efficiency", "Not less than 20.5%", "Complied. 21.3%."),
    ("Module make", "ALMM listed manufacturer", "Complied. ALMM List-I enclosed."),
    ("Module certification", "IEC 61215 / IEC 61730", "Complied. Certificates enclosed."),
    ("Module warranty — product", "12 years minimum", "Complied. 12 years."),
    ("Module warranty — performance", "25 years at 84.8% output", "Complied."),
    ("PID resistance", "As per IEC 62804", "Complied. Test report enclosed."),
    ("Inverter type", "String inverter, transformerless", "Complied."),
    ("Inverter capacity", "100 kW to 125 kW per unit", "Complied. 110 kW units."),
    ("Inverter quantity", "166 nos. minimum", "Complied. 168 nos. offered."),
    ("Inverter efficiency", "Euro efficiency > 98%", "Complied. 98.6%."),
    ("Inverter make", "SMA / Sungrow / TMEIC / Delta", "Complied. Sungrow SG110CX."),
    ("MPPT channels", "Minimum 6 per inverter", "Complied. 9 MPPT."),
    ("Inverter protection", "IP65 minimum", "Complied. IP66."),
    ("Anti-islanding protection", "As per IEEE 1547 / CEA regulations", "Complied."),
    ("Grid frequency range", "47.5 Hz to 52 Hz", "Complied."),
    ("Reactive power capability", "0.8 lagging to 0.8 leading", "Complied."),
    ("Module mounting structure", "Hot dip galvanised, 80 micron", "Complied. 85 micron."),
    ("Structure design wind speed", "As per IS 875 Part 3 for the zone", "Complied. 47 m/s."),
    ("Structure warranty", "10 years against corrosion", "Complied."),
    ("DC cable", "1500V DC rated, XLPE, UV resistant", "Complied. TUV certified."),
    ("AC cable", "1.1kV grade, XLPE armoured aluminium", "Complied."),
    ("Cable sizing", "Voltage drop within 2% DC, 1% AC", "Complied. Calculations enclosed."),
    ("String combiner box", "IP65 with fuse and SPD protection", "Complied."),
    ("Earthing system", "As per IS 3043 with chemical earthing", "Complied."),
    ("Lightning protection", "As per IS/IEC 62305", "Complied. Rolling sphere design."),
    ("Transformer rating", "Suitable for 33kV evacuation", "Complied. 2.5 MVA units."),
    ("Transformer type", "Cast resin dry type / oil filled ONAN", "Complied. ONAN."),
    ("33kV switchgear", "Vacuum circuit breaker, indoor type", "Complied."),
    ("Protection relays", "Numerical, IEC 61850 compliant", "Complied. ABB REF615."),
    ("SCADA system", "Plant level monitoring with remote access", "Complied."),
    ("Weather monitoring station", "Irradiance, module and ambient temperature", "Complied."),
    ("Energy meter", "0.2S class, ABT compliant", "Complied."),
    ("Performance ratio guarantee", "Not less than 78%", "Complied. 80.2% guaranteed."),
    ("Plant availability guarantee", "Not less than 97% annually", "Complied. 98%."),
    ("O&M period", "5 years comprehensive", "Complied."),
    ("Module cleaning frequency", "Minimum once per fortnight", "Complied. Weekly offered."),
    ("Spares holding", "As per O&M schedule", "Complied. List enclosed."),
    ("Grid synchronisation", "As per DISCOM requirements", "Accepted."),
    ("Fire detection", "As per NBC 2016 for rooftop installations", "Complied."),
    ("Walkways and safety rails", "As per site safety plan", "Complied."),
    ("Structural load certification", "By registered structural engineer", "Complied."),
    ("Roof waterproofing", "Non-penetrative ballasted where required", "Complied."),
]

CIVIL_SPECS: list[tuple[str, str, str]] = [
    ("Cement grade", "43 grade OPC conforming to IS 8112", "Complied. Ultratech / ACC."),
    ("Cement testing", "Every 50 MT or part thereof", "Accepted."),
    ("Fine aggregate", "Zone II river sand conforming to IS 383", "Complied."),
    ("Coarse aggregate", "20 mm and 10 mm graded, IS 383", "Complied."),
    ("Reinforcement steel", "Fe 500D conforming to IS 1786", "Complied. SAIL / TATA."),
    ("Steel testing", "One sample per 20 MT per diameter", "Accepted."),
    ("Concrete grade — footing", "M20 as per IS 456", "Complied."),
    ("Concrete grade — columns", "M20 as per IS 456", "Complied."),
    ("Concrete grade — plinth beam", "M20 as per IS 456", "Complied."),
    ("Concrete mix design", "By approved laboratory before commencement", "Accepted."),
    ("Cube testing frequency", "As per Table 11 of IS 456", "Accepted."),
    ("Slump range", "75 mm to 100 mm at placement", "Complied."),
    ("Curing period", "Minimum 14 days for all RCC", "Complied."),
    ("Formwork", "Steel or approved shuttering ply", "Complied. Steel forms."),
    ("Cover to reinforcement", "As per IS 456 exposure condition", "Complied. Cover blocks."),
    ("Brick class", "First class, minimum 75 kg/cm² strength", "Complied."),
    ("Brick masonry mortar", "Cement mortar 1:6", "Complied."),
    ("Plaster thickness", "12 mm on both faces", "Complied."),
    ("Plaster mortar", "Cement mortar 1:6 with waterproofing compound", "Complied."),
    ("Painting — primer", "One coat cement primer", "Complied."),
    ("Painting — finish", "Two coats exterior emulsion", "Complied. Asian Paints Apex."),
    ("Excavation", "To the lines and levels shown on drawings", "Accepted."),
    ("Anti-termite treatment", "As per IS 6313 where specified", "Complied."),
    ("Backfilling", "In 200 mm layers, compacted", "Complied."),
    ("Surplus earth disposal", "Outside campus at approved location", "Accepted."),
    ("Coping", "RCC coping of specified section", "Complied."),
    ("Weep holes", "As shown on drawings", "Complied."),
    ("Gate and grill work", "MS section as per drawing, painted", "Complied."),
    ("Levelling instrument", "Auto level with staff at site", "Complied."),
    ("Site cleanliness", "Daily removal of debris", "Accepted."),
]

SPECS_BY_SECTOR = {
    "supply": LED_SPECS,
    "civil works": CIVIL_SPECS,
}

# --------------------------------------------------------------------------- #
# Key personnel. Real bids reproduce a CV per named person.
# --------------------------------------------------------------------------- #
PERSONNEL_ROLES: list[tuple[str, str, str, str]] = [
    ("Project Manager", "B.E. (Civil), M.Tech (Construction Management)", "18",
     "Overall responsibility for delivery, client interface, and contractual correspondence."),
    ("Deputy Project Manager", "B.E. (Electrical)", "13",
     "Day to day site control, sub-contractor coordination and progress reporting."),
    ("Site Engineer — Civil", "B.E. (Civil)", "9",
     "Setting out, execution supervision, measurement books and quality records."),
    ("Site Engineer — Electrical", "B.E. (Electrical)", "8",
     "Cabling, terminations, earthing and pre-commissioning checks."),
    ("Quality Assurance Engineer", "B.E. (Mechanical), ISO 9001 Lead Auditor", "11",
     "Inspection and test plans, material clearance, non-conformance closure."),
    ("Safety Officer", "B.Sc., Advanced Diploma in Industrial Safety", "10",
     "Toolbox talks, permit to work, incident investigation and statutory registers."),
    ("Planning Engineer", "B.E. (Civil), Primavera certified", "7",
     "Baseline programme, weekly look-ahead and delay analysis."),
    ("Billing Engineer", "Diploma (Civil)", "12",
     "Measurement, running account bills and reconciliation of materials."),
    ("Store Keeper", "B.Com.", "14",
     "Material receipt, issue registers, and preservation of stores."),
    ("Design Engineer", "B.E. (Electrical), M.Tech (Power Systems)", "10",
     "Detailed engineering, drawings, and vendor document review."),
    ("Commissioning Engineer", "B.E. (Electrical)", "9",
     "Testing, grid synchronisation and performance demonstration."),
    ("O&M Manager", "B.E. (Electrical)", "11",
     "Operations and maintenance during the defect liability and O&M period."),
    ("Surveyor", "Diploma (Civil), Total Station certified", "8",
     "Survey, setting out and as-built documentation."),
    ("Electrical Supervisor", "ITI with State wireman licence", "15",
     "Supervision of licensed electrical work at site."),
    ("Document Controller", "B.A., PGDCA", "6",
     "Drawing register, transmittal control and correspondence filing."),
]

FIRST_NAMES = [
    "Ramesh", "Suresh", "Anil", "Vijay", "Prakash", "Srinivas", "Mahesh", "Rajesh",
    "Venkat", "Naresh", "Ganesh", "Kiran", "Sandeep", "Praveen", "Manoj", "Deepak",
    "Ashok", "Satish", "Ravi", "Sunil",
]
LAST_NAMES = [
    "Kumar", "Reddy", "Rao", "Sharma", "Naidu", "Verma", "Patel", "Singh",
    "Gupta", "Yadav", "Mishra", "Prasad", "Choudhary", "Nair", "Menon", "Joshi",
]

# --------------------------------------------------------------------------- #
# Plant and machinery, by sector.
# --------------------------------------------------------------------------- #
PLANT_BY_SECTOR: dict[str, list[tuple[str, str, str]]] = {
    "supply": [
        ("Hydraulic boom lift, 14 m reach", "4", "Owned"),
        ("Light commercial vehicle for material shifting", "6", "Owned"),
        ("Cable laying winch", "2", "Owned"),
        ("Insulation resistance tester, 1000V", "8", "Owned"),
        ("Earth resistance tester", "6", "Owned"),
        ("Digital lux meter, calibrated", "10", "Owned"),
        ("Clamp meter, true RMS", "12", "Owned"),
        ("Portable generator, 5 kVA", "4", "Owned"),
        ("Hydraulic crimping tool set", "10", "Owned"),
        ("Torque wrench set", "8", "Owned"),
        ("Retro-reflective barricading, 500 m", "1 lot", "Owned"),
        ("Night work illumination towers", "6", "Hired"),
    ],
    "civil works": [
        ("Concrete mixer, 10/7 capacity", "3", "Owned"),
        ("Needle vibrator with petrol engine", "6", "Owned"),
        ("Plate compactor", "2", "Owned"),
        ("Total station with prism set", "1", "Owned"),
        ("Auto level with staff", "2", "Owned"),
        ("Bar bending machine", "2", "Owned"),
        ("Bar cutting machine", "2", "Owned"),
        ("Water tanker, 5000 litre", "1", "Hired"),
        ("Tractor with trolley", "2", "Owned"),
        ("Steel shuttering plates", "800 sqm", "Owned"),
        ("Scaffolding pipes and couplers", "1 lot", "Owned"),
        ("Dewatering pump, 5 HP", "3", "Owned"),
        ("Excavator, JCB 3DX", "1", "Hired"),
        ("Concrete cube moulds", "12 sets", "Owned"),
    ],
}

# --------------------------------------------------------------------------- #
# Method statement activities, by sector. Each becomes a full sub-section.
# --------------------------------------------------------------------------- #
METHOD_ACTIVITIES: dict[str, list[tuple[str, str]]] = {
    "supply": [
        ("Mobilisation and site establishment",
         "Establishment of the site office, secure stores for luminaires, and the "
         "material staging yard at the location allotted by the Engineer-in-Charge. "
         "Statutory notices will be displayed and the labour licence obtained before "
         "any workman is deployed."),
        ("Joint survey and asset register preparation",
         "A pole-by-pole joint survey with the Employer's representative recording "
         "pole identity, height, arm length, existing fitting wattage, feeder pillar "
         "mapping and GPS coordinates. The register is the basis for despatch "
         "planning and is frozen only after joint signature."),
        ("Design and photometric validation",
         "Preparation of lighting layouts using DIALux for a representative sample of "
         "road cross sections, demonstrating compliance with the illumination levels "
         "of IS 1944 for the applicable road category, submitted for approval before "
         "bulk despatch."),
        ("Sample submission and approval",
         "Submission of one sample of each wattage together with type test reports "
         "for approval. Bulk manufacture commences only against written approval of "
         "the sample."),
        ("Manufacture and in-process inspection",
         "Manufacture at the approved works with in-process inspection at defined "
         "hold points. The Employer's inspector shall have free access during "
         "working hours."),
        ("Pre-despatch inspection and testing",
         "Routine tests on every luminaire and acceptance tests on samples drawn per "
         "lot, witnessed by the Employer's nominated agency. Material is released "
         "only against an inspection release note."),
        ("Packing, transport and receipt at site",
         "Individual cartons with foam cushioning, transported in covered vehicles. "
         "Joint physical verification of quantity and condition on receipt, recorded "
         "in the material receipt register."),
        ("Removal of existing fittings",
         "Careful dismantling of existing fittings after shutdown permit, with the "
         "removed material handed over to the Employer's stores against a signed "
         "receipt on the same day."),
        ("Installation of luminaires",
         "Mounting on the existing bracket, alignment and tilt setting, gland entry "
         "and termination with the specified lugs. Torque applied per the "
         "manufacturer's schedule and recorded."),
        ("Cabling and terminations",
         "Replacement of deteriorated tail-end cable where directed, with proper "
         "ferruling and continuity of the earth conductor throughout."),
        ("Earthing and bonding verification",
         "Measurement of earth resistance at each feeder pillar and recording of "
         "values, with improvement where readings exceed the specified limit."),
        ("Testing and illumination measurement",
         "Insulation resistance and earth continuity tests on each circuit, followed "
         "by night-time lux measurement at sample points jointly recorded and signed."),
        ("Commissioning and handover",
         "Energisation circuit by circuit with the Employer's representative present, "
         "followed by a seven-day observation period before the section is taken over."),
        ("Documentation and as-built submission",
         "Submission of the completed asset register, test records, warranty "
         "certificates and as-built feeder drawings in hard and soft copy."),
        ("Warranty support and defect rectification",
         "A dedicated helpdesk with a 24-hour acknowledgement and 72-hour "
         "rectification commitment, with a monthly report of complaints and closures."),
    ],
    "civil works": [
        ("Mobilisation and site establishment",
         "Establishment of the site office, labour accommodation as required, secure "
         "cement godown on a raised plinth, steel stacking yard and a curing water "
         "point within the area allotted by the Engineer-in-Charge."),
        ("Survey and setting out",
         "Setting out of the centre line using a total station, referenced to at "
         "least three permanent benchmarks established outside the working width so "
         "that the alignment can be re-established after excavation."),
        ("Site clearance and dismantling",
         "Clearance of vegetation, removal of obstructions and careful dismantling of "
         "any existing structure, with serviceable material stacked as directed."),
        ("Excavation for foundation",
         "Excavation to the depth and width shown on the drawings, sides kept "
         "vertical and shored where the depth exceeds 1.5 metre. Dewatering "
         "arranged where groundwater is met."),
        ("Foundation inspection and approval",
         "The founding stratum is offered for inspection and no concrete is placed "
         "until written approval is recorded in the site order book."),
        ("Levelling course and PCC",
         "A levelling course of M10 concrete, 100 mm thick, laid over the approved "
         "formation and cured before reinforcement is placed."),
        ("Reinforcement fabrication and placement",
         "Cutting and bending strictly to the bar bending schedule, placement with "
         "cover blocks of the same grade as the surrounding concrete, and binding at "
         "every intersection at corners."),
        ("Formwork erection",
         "Steel shuttering erected true to line and level, adequately braced and "
         "treated with approved release agent, checked for verticality before the "
         "pour is permitted."),
        ("Concreting of footings and columns",
         "Concrete batched by weight, placed in layers not exceeding 450 mm and "
         "compacted with needle vibrators. Construction joints only at locations "
         "approved by the Engineer-in-Charge."),
        ("Cube casting and testing",
         "Cubes cast at the frequency laid down in IS 456, cured in the site "
         "laboratory and tested at an approved laboratory, with results submitted "
         "alongside each running account bill."),
        ("Curing regime",
         "Continuous curing for not less than fourteen days using gunny bags kept "
         "moist, with a curing register maintained and available for inspection."),
        ("Plinth beam and masonry",
         "Casting of the plinth beam followed by first-class brick masonry in cement "
         "mortar 1:6, courses kept truly plumb with horizontal joints raked for "
         "plaster key."),
        ("Plastering and finishing",
         "Twelve millimetre cement plaster in 1:6 mortar on both faces, finished "
         "smooth and cured, followed by one coat of primer and two coats of exterior "
         "emulsion of an approved shade."),
        ("Coping and gate works",
         "RCC coping cast to the specified section, and fabrication and fixing of MS "
         "gate and grill work as detailed on the drawings, painted with one coat "
         "primer and two coats synthetic enamel."),
        ("Site restoration and handover",
         "Removal of all debris and temporary works, restoration of the disturbed "
         "ground, and handover with as-built drawings and the complete quality "
         "dossier."),
    ],
}

# --------------------------------------------------------------------------- #
# Declarations reproduced in full. Real bids run one per page.
# --------------------------------------------------------------------------- #
DECLARATIONS: list[tuple[str, str]] = [
    ("Declaration of Non-Blacklisting",
     "We declare that our firm, its partners and directors, and its associate "
     "concerns have not been blacklisted, debarred or banned from participating in "
     "tenders by any Central or State Government department, public sector "
     "undertaking, municipal body or autonomous institution, and that no proceedings "
     "for such action are pending against us as on the date of submission."),
    ("Declaration on Code of Integrity",
     "We declare that we have not offered, and shall not offer, any inducement or "
     "reward to any officer or employee of the Employer in connection with this "
     "procurement, and that we have not entered into any agreement with any other "
     "bidder with a view to restricting competition or influencing the outcome."),
    ("No Deviation Confirmation",
     "We confirm that our bid conforms in full to the terms, conditions, "
     "specifications, drawings and schedules of the bid document and that we have "
     "taken no deviation or exception. We understand that any deviation not "
     "expressly accepted in writing by the Employer shall be treated as withdrawn."),
    ("Declaration on Restriction on Procurement from Certain Countries",
     "We confirm that we are not from a country which shares a land border with "
     "India, or where we are, that we stand registered with the Competent Authority "
     "constituted under the Order of the Ministry of Finance dated 23.07.2020, and "
     "the registration certificate is enclosed."),
    ("Declaration Regarding Litigation History",
     "We declare that no arbitration or litigation arising out of any contract "
     "executed by us in the last five years has resulted in an award against us "
     "exceeding ten percent of the contract value, and that no contract awarded to "
     "us has been terminated for default."),
    ("Undertaking on Statutory Compliance",
     "We undertake to comply with the Contract Labour (Regulation and Abolition) "
     "Act 1970, the Building and Other Construction Workers Act 1996, the Minimum "
     "Wages Act 1948, the Employees' Provident Funds and Miscellaneous Provisions "
     "Act 1952 and the Employees' State Insurance Act 1948, and to maintain the "
     "registers prescribed thereunder."),
    ("Undertaking on Deployment of Key Personnel",
     "We undertake to deploy the key personnel named in this bid for the duration "
     "of the contract, and not to replace any of them without the prior written "
     "approval of the Engineer-in-Charge, and then only by a person of equal or "
     "better qualification and experience."),
    ("Declaration on Correctness of Information",
     "We declare that the particulars furnished in this bid and in the documents "
     "accompanying it are true and correct to the best of our knowledge and belief "
     "and that nothing material has been concealed. We understand that if any "
     "information is found to be false at any stage, our bid shall be liable to "
     "summary rejection and our earnest money forfeited."),
    ("Undertaking on Site Inspection",
     "We confirm that we have visited and examined the site, satisfied ourselves as "
     "to the nature of the ground, the access, the availability of materials, water "
     "and power, and all other circumstances affecting the execution of the work, "
     "and that our rates take account of the same."),
    ("Declaration on Bid Validity",
     "We confirm that this bid shall remain valid and binding upon us for a period "
     "of one hundred and eighty days from the date fixed for opening of bids, and "
     "may be accepted at any time before the expiry of that period."),
    ("Undertaking on Performance Security",
     "We undertake, if our bid is accepted, to furnish the Performance Security in "
     "the form and within the period stipulated in the conditions of contract, "
     "failing which we accept that the earnest money shall stand forfeited."),
    ("Declaration on Related Party Participation",
     "We declare that no other bid has been submitted for this work by any concern "
     "in which any of our partners or directors has a substantial interest, and that "
     "we are not participating in this tender in more than one capacity."),
]

# --------------------------------------------------------------------------- #
# Risk register rows.
# --------------------------------------------------------------------------- #
RISKS: list[tuple[str, str, str, str]] = [
    ("Delay in receipt of Employer's approval of samples", "Medium", "High",
     "Submission of samples within seven days of award, with weekly follow-up and "
     "escalation to the Engineer-in-Charge after fourteen days."),
    ("Component lead time from overseas suppliers", "Medium", "High",
     "Buffer stock equivalent to three weeks of installation demand held at site, "
     "and a second approved source qualified for critical components."),
    ("Monsoon restricting site access", "High", "Medium",
     "Low-lying sections sequenced ahead of the monsoon window so that weather "
     "delay does not sit on the critical path."),
    ("Traffic restrictions on arterial roads", "High", "Medium",
     "Night working with police permission obtained in advance, and barricading "
     "and flagmen deployed at both approaches."),
    ("Shortage of skilled manpower during festival season", "Medium", "Medium",
     "Advance planning of leave rosters and a standing arrangement with two "
     "labour contractors for surge capacity."),
    ("Price escalation of raw material", "Medium", "Low",
     "Rates quoted are firm; procurement of principal materials committed with "
     "suppliers at the time of bidding."),
    ("Damage to existing services during excavation", "Low", "High",
     "Trial pits and service drawings obtained before mechanical excavation, and "
     "hand excavation within one metre of any known service."),
    ("Non-conformance detected at pre-despatch inspection", "Low", "Medium",
     "In-process inspection at defined hold points so that a non-conformance is "
     "caught at the works rather than at site."),
    ("Industrial dispute or local agitation", "Low", "Medium",
     "Engagement of local labour where practicable and liaison with the local "
     "administration maintained throughout."),
    ("Grid unavailability delaying commissioning", "Medium", "High",
     "Early application for the shutdown, and sequencing of testable sections so "
     "that work continues while approvals are pending."),
]

# --------------------------------------------------------------------------- #
# Bill of quantities line items, by sector.
# --------------------------------------------------------------------------- #
BOQ_BY_SECTOR: dict[str, list[tuple[str, str, str]]] = {
    "supply": [
        ("Supply of 35W LED street light luminaire complete with driver, "
         "surge protection and mounting accessories", "Nos.", "6200"),
        ("Supply of 70W LED street light luminaire complete with driver, "
         "surge protection and mounting accessories", "Nos.", "6100"),
        ("Supply of 110W LED street light luminaire complete with driver, "
         "surge protection and mounting accessories", "Nos.", "3200"),
        ("Dismantling of existing conventional fitting including safe handover "
         "of removed material to Employer's stores", "Nos.", "15500"),
        ("Installation, testing and commissioning of LED luminaire on existing "
         "bracket including alignment and tilt setting", "Nos.", "15500"),
        ("Supply and laying of 2 core 2.5 sqmm copper tail-end cable", "Metre", "46500"),
        ("Supply and fixing of MCB in feeder pillar, 6A to 32A", "Nos.", "1240"),
        ("Chemical earthing with 3 metre electrode and earth enhancing compound",
         "Nos.", "310"),
        ("Supply and fixing of surge protection device at feeder pillar", "Nos.", "310"),
        ("Night-time illumination measurement and joint recording", "Point", "3100"),
        ("Retro-reflective barricading and traffic management during night work",
         "Day", "180"),
        ("Comprehensive warranty and helpdesk support for 5 years", "Year", "5"),
    ],
    "civil works": [
        ("Earthwork in excavation in foundation trenches in all kinds of soil "
         "including shoring and dewatering", "Cum", "142.00"),
        ("Providing and laying plain cement concrete M10 as levelling course",
         "Cum", "18.50"),
        ("Providing and laying reinforced cement concrete M20 in footings",
         "Cum", "36.20"),
        ("Providing and laying reinforced cement concrete M20 in columns",
         "Cum", "22.40"),
        ("Providing and laying reinforced cement concrete M20 in plinth beam",
         "Cum", "19.80"),
        ("Supply, cutting, bending and placing of Fe 500D reinforcement", "MT", "6.85"),
        ("Steel shuttering for footings, columns and beams including "
         "erection, propping and removal", "Sqm", "412.00"),
        ("First class brick masonry in cement mortar 1:6 in superstructure",
         "Cum", "88.40"),
        ("Twelve millimetre cement plaster in cement mortar 1:6 on both faces",
         "Sqm", "1180.00"),
        ("Providing and applying one coat primer and two coats exterior emulsion",
         "Sqm", "1180.00"),
        ("Providing and laying RCC coping of specified section", "Rm", "300.00"),
        ("Fabrication and fixing of MS gate including hinges and locking arrangement",
         "Kg", "480.00"),
        ("Backfilling in layers of 200 mm including watering and compaction",
         "Cum", "96.00"),
        ("Disposal of surplus earth outside campus at approved location",
         "Cum", "46.00"),
    ],
}
