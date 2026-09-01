"""Tender profiles, taken from the three real notifications in data/.

Requirements here mirror what the extraction pipeline actually pulled out of
each document, so a generated bid answers the clauses it will be checked
against rather than a plausible-sounding invention.
"""

from __future__ import annotations

from app.bidgen.spec import TenderProfile

GHMC = TenderProfile(
    notification_id="NOTIF_supply_01",
    tender_ref="TENDER No.01/SE(Electrical)/GHMC/2024-25, Dated: 13.09.2024",
    authority="Greater Hyderabad Municipal Corporation",
    authority_address="Office of the Superintending Engineer (Electrical),\nGHMC Head Office, Tank Bund Road, Hyderabad - 500 063",
    work_title=(
        "Procurement of 15500 Nos. New LED Street lights of various wattages "
        "for use in GHMC Jurisdiction"
    ),
    sector="supply",
    estimated_cost="Rs. 29,87,20,000/-",
    emd="Rs. 2,98,720/- (1% of ECV)",
    bid_due="04.10.2024",
    turnover_requirement="Rs. 3,00,00,000/- (Rupees Three Crore only)",
    experience_requirement=(
        "One order of similar supply for Rs. 2.39 Crore or two orders of "
        "Rs. 1.49 Crore each within the last seven years"
    ),
    key_documents=(
        "Permanent Account Number (PAN)",
        "Copy of GST registration",
        "Proof of Payment of EMD",
        "Manufacturers authorization form",
        "Technical Specification for Item 35W, 70W & 110W LED Street Light Fittings",
        "Certificate of Chartered Accountant showing calculation of Net Worth",
        "Audited Balance Sheets",
        "Work orders of works cited in support of eligibility",
        "Completion and satisfactory performance certificates",
        "Self-Declaration by Bidder: No Blacklisting",
        "Certificate of Conformity / No Deviation",
        "Power of Attorney",
        "Bid-Securing Declaration",
        "Test report",
    ),
    technical_context="LED street lighting supply, delivery and installation",
)

IITISM = TenderProfile(
    notification_id="NOTIF_civilworks_01",
    tender_ref="eTender Notice No. CMU-12011/17/2026-CMU",
    authority="Indian Institute of Technology (Indian School of Mines) Dhanbad",
    authority_address="Office of the Campus Maintenance Unit,\nIIT (ISM) Dhanbad, Jharkhand - 826 004",
    work_title=(
        "Construction of boundary wall of approximate length 300 metre at "
        "Part of IIT (ISM) Campus, Dhanbad"
    ),
    sector="civil works",
    estimated_cost="Rs. 12,56,561/-",
    emd="Rs. 31,500/-",
    bid_due="22.08.2026",
    # 30% of the estimated cost -- the tender states the requirement as a share,
    # which the pipeline resolves to Rs. 3,76,968.
    turnover_requirement=(
        "Average annual financial turnover of not less than 30% of the "
        "estimated cost, i.e. Rs. 3,76,968/-, during the last three financial years"
    ),
    experience_requirement=(
        "One similar completed work costing not less than 80% of the estimated "
        "cost, i.e. Rs. 10,05,249/-, during the last seven years"
    ),
    key_documents=(
        "Photocopy of PAN card",
        "Photocopy of GST registration with latest monthly Return filed",
        "Certificate of annual turnover from Chartered Accountant",
        "Experience of having successfully completed similar type of works",
        "Scan copy of EMD amount",
        "Registration in ESIC and EPFO",
        "Financial status, Balance sheet, Profit and Loss Account for last 3 years",
        "Bid capacity as per format in Annexure IV",
        "Duly filled and signed copy of Annexure I, Annexure II and Annexure III",
        "Compliance sheet",
        "Proforma for earnest money deposit declaration",
        "Possession of Valid Class II/III Digital Signature Certificate",
    ),
    technical_context="reinforced cement concrete boundary wall construction",
)

HGCL = TenderProfile(
    notification_id="NOTIF_civilworks_02",
    tender_ref=(
        "BID NOTICE No.178/CGM(T)/HGCL/DGM(Elec)/Cycle Track/2022-23/"
        "second call/Dated: 24.04.2023"
    ),
    authority="Hyderabad Growth Corridor Limited",
    authority_address="HGCL Office Building, 2nd Floor, Khajaguda Road,\nAdjacent to ORR, Nanakramguda, Hyderabad - 500 104",
    work_title=(
        "Design, Engineering, Supply, Construction, Erection, Testing & "
        "Commissioning of cumulative 13 MW (AC) Solar PV Power Plant on "
        "rooftop of Cycle Track"
    ),
    sector="civil works",
    estimated_cost="Rs. 99,71,00,000/-",
    emd="1% of the ECV",
    bid_due="03.05.2023",
    turnover_requirement=(
        "Liquid assets and/or credit facilities of not less than "
        "Rs. 49.855 Crores"
    ),
    experience_requirement=(
        "Satisfactorily completed similar works of cumulative 13 MW capacity, "
        "including SITC of 166 nos. inverters and 33KV substation works of "
        "Rs. 10.0 Cr"
    ),
    key_documents=(
        "'Covering Letter' on Bidder's 'Letterhead' (in Original)",
        "EMD, in original",
        "Power of Attorney for authorized signatory",
        "Board Resolution",
        "Certificate of Incorporation",
        "Bidder's General Information, as per Form F-1",
        "No Deviation Confirmation, as per Form F-6",
        "Bidder's Declaration regarding Banning, Liquidation etc.",
        "Declaration on restriction on procurement from certain countries",
        "Declaration regarding the procurement of Solar Inverters & Solar Modules",
        "Bidder's Experience as per Form F-13",
        "Audited financial statements",
        "Bid Form for first Part",
    ),
    technical_context="rooftop solar photovoltaic EPC",
)

PROFILES = {p.notification_id: p for p in (GHMC, IITISM, HGCL)}
