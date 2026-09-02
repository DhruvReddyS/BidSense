"""Vendor specifications: 5 per tender, outcome decided before the prose.

Distribution follows Section 9.2.2 for each tender:
  1 fully compliant · 1 missing one mandatory document · 1 below a numeric
  threshold · 1 borderline (exactly at a threshold) · 1 blacklisted
with strong/weak technical write-ups mixed across them so the Section 5.4
fluency-bias guard has both to work with.
"""

from __future__ import annotations

from app.bidgen.spec import VendorSpec

# --------------------------------------------------------------------------- #
# GHMC — LED street lights. Turnover floor Rs. 3,00,00,000; similar order
# Rs. 2.39 Cr.
# --------------------------------------------------------------------------- #
GHMC_VENDORS = [
    VendorSpec(
        vendor_id="VENDOR_supply_01_01",
        document_naming="alias",
        notification_id="NOTIF_supply_01",
        vendor_name="Lumina Electricals Private Limited",
        constitution="Private Limited Company registered under the Companies Act, 2013",
        city="Hyderabad",
        established=2013,
        intended_status="pass",
        intended_reason="",
        intended_failed_clause="",
        writeup_quality="strong",
        turnover=[("2021-22", "Rs. 3,85,00,000"), ("2022-23", "Rs. 4,20,00,000"),
                  ("2023-24", "Rs. 4,65,00,000")],
        net_worth="Rs. 1,95,40,000",
        bank_credit="Rs. 3,50,00,000",
        projects=[
            dict(client="Nizamabad Municipal Corporation", value="Rs. 2,84,00,000",
                 year=2023, scope="Supply, delivery and installation of 4,200 nos. LED "
                 "street light fittings of 35W, 70W and 110W ratings across 14 wards",
                 order_no="NMC/ELE/2022-23/117"),
            dict(client="Telangana State Southern Power Distribution Company",
                 value="Rs. 1,96,00,000", year=2022,
                 scope="Supply of 3,100 nos. LED luminaires with 5-year warranty",
                 order_no="TSSPDCL/PROC/2021-22/443"),
            dict(client="Siddipet Municipality", value="Rs. 88,00,000", year=2021,
                 scope="Retrofitting of 1,450 conventional fittings with LED luminaires",
                 order_no="SDP/MUN/2020-21/62"),
        ],
        certifications=[("ISO 9001:2015", "30.11.2027"), ("ISO 14001:2015", "31.03.2027"),
                        ("BIS Registration (IS 10322)", "31.12.2026")],
        quoted_price="Rs. 28,74,50,000",
        quoted_words="Rupees Twenty Eight Crore Seventy Four Lakh Fifty Thousand only",
        notes="Fully compliant on every criterion. Baseline true-negative for elimination.",
    ),
    VendorSpec(
        vendor_id="VENDOR_supply_01_02",
        notification_id="NOTIF_supply_01",
        vendor_name="Bright Path Infra LLP",
        constitution="Limited Liability Partnership registered under the LLP Act, 2008",
        city="Warangal",
        established=2019,
        intended_status="eliminate",
        intended_reason="Average annual turnover Rs. 1.80 Cr is below the required Rs. 3.00 Cr",
        intended_failed_clause="5",
        writeup_quality="weak",
        turnover=[("2021-22", "Rs. 1,42,00,000"), ("2022-23", "Rs. 1,68,00,000"),
                  ("2023-24", "Rs. 1,80,00,000")],
        net_worth="Rs. 42,60,000",
        bank_credit="Rs. 75,00,000",
        projects=[
            dict(client="Karimnagar Municipal Corporation", value="Rs. 2,45,00,000",
                 year=2023, scope="Supply and installation of LED street lighting in "
                 "Zone III", order_no="KMC/E/2022-23/89"),
        ],
        certifications=[("ISO 9001:2015", "31.08.2026")],
        quoted_price="Rs. 27,90,00,000",
        quoted_words="Rupees Twenty Seven Crore Ninety Lakh only",
        notes="Experience clears; turnover fails. Tests that elimination cites the "
              "right clause rather than the first failing one.",
    ),
    VendorSpec(
        vendor_id="VENDOR_supply_01_03",
        document_naming="reworded",
        notification_id="NOTIF_supply_01",
        vendor_name="Deccan Lighting Solutions Private Limited",
        constitution="Private Limited Company registered under the Companies Act, 2013",
        city="Secunderabad",
        established=2010,
        intended_status="eliminate",
        intended_reason="Manufacturers authorization form not enclosed",
        intended_failed_clause="7",
        writeup_quality="strong",
        turnover=[("2021-22", "Rs. 5,10,00,000"), ("2022-23", "Rs. 5,60,00,000"),
                  ("2023-24", "Rs. 6,05,00,000")],
        net_worth="Rs. 2,60,00,000",
        bank_credit="Rs. 4,25,00,000",
        projects=[
            dict(client="Warangal Municipal Corporation", value="Rs. 3,15,00,000",
                 year=2023, scope="Supply and installation of 5,600 LED street lights",
                 order_no="GWMC/ELE/2022-23/204"),
            dict(client="Khammam Municipal Corporation", value="Rs. 2,10,00,000",
                 year=2022, scope="Supply of 3,400 LED luminaires with smart controllers",
                 order_no="KMC/ELE/2021-22/76"),
        ],
        certifications=[("ISO 9001:2015", "28.02.2028"), ("ISO 14001:2015", "31.05.2027")],
        quoted_price="Rs. 29,10,00,000",
        quoted_words="Rupees Twenty Nine Crore Ten Lakh only",
        omitted_documents=("Manufacturers authorization form",),
        notes="Financially strong, one document missing. Tests that a document gap "
              "eliminates on its own and is not masked by good financials.",
    ),
    VendorSpec(
        vendor_id="VENDOR_supply_01_04",
        notification_id="NOTIF_supply_01",
        vendor_name="Sunrise Power Systems Limited",
        constitution="Public Limited Company registered under the Companies Act, 2013",
        city="Hyderabad",
        established=2016,
        intended_status="eliminate",
        intended_reason="Bidder is debarred by a State Government department",
        intended_failed_clause="4",
        writeup_quality="weak",
        turnover=[("2021-22", "Rs. 4,05,00,000"), ("2022-23", "Rs. 4,40,00,000"),
                  ("2023-24", "Rs. 4,72,00,000")],
        net_worth="Rs. 1,10,00,000",
        bank_credit="Rs. 2,00,00,000",
        projects=[
            dict(client="Adilabad Municipality", value="Rs. 2,66,00,000", year=2023,
                 scope="Supply and erection of LED street light fittings",
                 order_no="ADB/MUN/2022-23/31"),
        ],
        certifications=[("ISO 9001:2015", "31.01.2027")],
        quoted_price="Rs. 27,45,00,000",
        quoted_words="Rupees Twenty Seven Crore Forty Five Lakh only",
        is_blacklisted=True,
        notes="Lowest price and adequate financials -- eliminated only on debarment. "
              "Tests that a hard disqualifier is not traded off against price.",
        extra_declarations=[
            "We disclose that our firm was debarred by the Public Health Engineering "
            "Department, Government of Chhattisgarh vide order dated 11.07.2023 for a "
            "period of two years. An appeal against the said order is pending."
        ],
    ),
    VendorSpec(
        vendor_id="VENDOR_supply_01_05",
        notification_id="NOTIF_supply_01",
        vendor_name="Godavari Illumination Works",
        constitution="Partnership Firm registered under the Indian Partnership Act, 1932",
        city="Nizamabad",
        established=2017,
        intended_status="pass",
        intended_reason="",
        intended_failed_clause="",
        writeup_quality="strong",
        # Exactly at both floors. ">= threshold" must pass; "> threshold" fails.
        turnover=[("2021-22", "Rs. 2,95,00,000"), ("2022-23", "Rs. 3,00,00,000"),
                  ("2023-24", "Rs. 3,00,00,000")],
        net_worth="Rs. 78,00,000",
        bank_credit="Rs. 1,25,00,000",
        projects=[
            dict(client="Ramagundam Municipal Corporation", value="Rs. 2,39,00,000",
                 year=2023, scope="Supply and installation of 3,900 LED street lights "
                 "across 8 divisions", order_no="RMC/ELE/2022-23/58"),
        ],
        certifications=[("ISO 9001:2015", "31.10.2026")],
        quoted_price="Rs. 28,20,00,000",
        quoted_words="Rupees Twenty Eight Crore Twenty Lakh only",
        is_borderline=True,
        notes="Borderline: turnover and experience sit exactly on the thresholds. "
              "An off-by-one comparison flips this vendor's outcome.",
    ),
]

# --------------------------------------------------------------------------- #
# IIT (ISM) Dhanbad — boundary wall. Turnover floor Rs. 3,76,968 (30% of
# estimate); similar work Rs. 10,05,249 (80% of estimate).
# --------------------------------------------------------------------------- #
IITISM_VENDORS = [
    VendorSpec(
        vendor_id="VENDOR_civilworks_01_01",
        document_naming="reworded",
        notification_id="NOTIF_civilworks_01",
        vendor_name="Jharkhand构 Constructions",   # replaced below
        constitution="Proprietorship Firm",
        city="Dhanbad",
        established=2011,
        intended_status="pass", intended_reason="", intended_failed_clause="",
        writeup_quality="strong",
        turnover=[("2022-23", "Rs. 68,40,000"), ("2023-24", "Rs. 82,10,000"),
                  ("2024-25", "Rs. 91,50,000")],
        net_worth="Rs. 24,80,000",
        bank_credit="Rs. 35,00,000",
        projects=[
            dict(client="Dhanbad Municipal Corporation", value="Rs. 18,60,000", year=2024,
                 scope="Construction of RCC boundary wall of 420 metre length with "
                 "gate and pillars at municipal storage yard", order_no="DMC/CIV/2023-24/94"),
            dict(client="Bharat Coking Coal Limited", value="Rs. 14,20,000", year=2023,
                 scope="Compound wall and drain works at colliery office complex",
                 order_no="BCCL/CE/2022-23/311"),
        ],
        certifications=[("Class-B Contractor Registration, Govt. of Jharkhand", "31.03.2027"),
                        ("EPFO Registration", "—"), ("ESIC Registration", "—")],
        quoted_price="Rs. 12,18,500",
        quoted_words="Rupees Twelve Lakh Eighteen Thousand Five Hundred only",
        notes="Comfortably clears both the 30% turnover and 80% similar-work floors.",
    ),
    VendorSpec(
        vendor_id="VENDOR_civilworks_01_02",
        document_naming="alias",
        notification_id="NOTIF_civilworks_01",
        vendor_name="Sahu Brothers Engineering Works",
        constitution="Partnership Firm registered under the Indian Partnership Act, 1932",
        city="Bokaro",
        established=2020,
        intended_status="eliminate",
        intended_reason="Largest similar completed work Rs. 6.4 Lakh is below the "
                        "required Rs. 10,05,249 (80% of estimated cost)",
        intended_failed_clause="1.1(4)",
        writeup_quality="weak",
        turnover=[("2022-23", "Rs. 41,00,000"), ("2023-24", "Rs. 47,50,000"),
                  ("2024-25", "Rs. 52,20,000")],
        net_worth="Rs. 11,40,000",
        bank_credit="Rs. 15,00,000",
        projects=[
            dict(client="Bokaro Steel City Notified Area Committee", value="Rs. 6,40,000",
                 year=2024, scope="Construction of compound wall at community hall",
                 order_no="BSC/NAC/2023-24/48"),
        ],
        certifications=[("Class-C Contractor Registration, Govt. of Jharkhand", "31.03.2026"),
                        ("EPFO Registration", "—")],
        quoted_price="Rs. 11,94,000",
        quoted_words="Rupees Eleven Lakh Ninety Four Thousand only",
        notes="Turnover clears the 30% floor; the similar-work value does not. Tests "
              "that the two relative thresholds are evaluated independently.",
    ),
    VendorSpec(
        vendor_id="VENDOR_civilworks_01_03",
        notification_id="NOTIF_civilworks_01",
        vendor_name="Koyla Infrastructure Private Limited",
        constitution="Private Limited Company registered under the Companies Act, 2013",
        city="Ranchi",
        established=2009,
        intended_status="eliminate",
        intended_reason="Valid Class II/III Digital Signature Certificate not enclosed",
        intended_failed_clause="2.6(b)",
        writeup_quality="strong",
        turnover=[("2022-23", "Rs. 2,40,00,000"), ("2023-24", "Rs. 2,85,00,000"),
                  ("2024-25", "Rs. 3,10,00,000")],
        net_worth="Rs. 96,00,000",
        bank_credit="Rs. 1,50,00,000",
        projects=[
            dict(client="Jharkhand Urban Infrastructure Development Company",
                 value="Rs. 42,00,000", year=2024,
                 scope="Boundary wall, gate and internal road at water treatment plant",
                 order_no="JUIDCO/CIV/2023-24/207"),
            dict(client="Central Coalfields Limited", value="Rs. 28,50,000", year=2023,
                 scope="RCC compound wall of 640 metre at regional stores",
                 order_no="CCL/CE/2022-23/158"),
        ],
        certifications=[("ISO 9001:2015", "30.09.2027"),
                        ("Class-A Contractor Registration, Govt. of Jharkhand", "31.03.2028")],
        quoted_price="Rs. 12,45,000",
        quoted_words="Rupees Twelve Lakh Forty Five Thousand only",
        omitted_documents=("Possession of Valid Class II/III Digital Signature Certificate",),
        notes="Strongest bidder on paper, eliminated on a single procedural document.",
    ),
    VendorSpec(
        vendor_id="VENDOR_civilworks_01_04",
        notification_id="NOTIF_civilworks_01",
        vendor_name="Damodar Valley Builders",
        constitution="Proprietorship Firm",
        city="Dhanbad",
        established=2015,
        intended_status="eliminate",
        intended_reason="Average annual turnover Rs. 3,20,000 is below the required "
                        "Rs. 3,76,968 (30% of estimated cost)",
        intended_failed_clause="1",
        writeup_quality="weak",
        turnover=[("2022-23", "Rs. 2,80,000"), ("2023-24", "Rs. 3,35,000"),
                  ("2024-25", "Rs. 3,45,000")],
        net_worth="Rs. 2,10,000",
        bank_credit="Rs. 5,00,000",
        projects=[
            dict(client="Jharia Nagar Parishad", value="Rs. 10,40,000", year=2024,
                 scope="Construction of boundary wall at municipal park",
                 order_no="JNP/2023-24/22"),
        ],
        certifications=[("Class-D Contractor Registration, Govt. of Jharkhand", "31.03.2026")],
        quoted_price="Rs. 11,70,000",
        quoted_words="Rupees Eleven Lakh Seventy Thousand only",
        notes="Similar-work value clears; turnover does not. The mirror image of "
              "vendor 02, so a rule that conflates the two thresholds fails one of them.",
    ),
    VendorSpec(
        vendor_id="VENDOR_civilworks_01_05",
        notification_id="NOTIF_civilworks_01",
        vendor_name="Maithon Civil Contractors",
        constitution="Partnership Firm registered under the Indian Partnership Act, 1932",
        city="Dhanbad",
        established=2014,
        intended_status="pass", intended_reason="", intended_failed_clause="",
        writeup_quality="weak",
        # Turnover exactly on the 30% floor; similar work exactly on the 80% floor.
        turnover=[("2022-23", "Rs. 3,76,968"), ("2023-24", "Rs. 4,10,000"),
                  ("2024-25", "Rs. 3,90,000")],
        net_worth="Rs. 8,50,000",
        bank_credit="Rs. 12,00,000",
        projects=[
            dict(client="Maithon Power Limited", value="Rs. 10,05,249", year=2024,
                 scope="Construction of RCC boundary wall of 285 metre at township",
                 order_no="MPL/CIV/2023-24/71"),
        ],
        certifications=[("Class-C Contractor Registration, Govt. of Jharkhand", "31.03.2027"),
                        ("EPFO Registration", "—"), ("ESIC Registration", "—")],
        quoted_price="Rs. 12,30,000",
        quoted_words="Rupees Twelve Lakh Thirty Thousand only",
        is_borderline=True,
        notes="Borderline on BOTH relative thresholds simultaneously, and a weak "
              "write-up: must still pass. Guards against fluency bias (Section 5.4).",
    ),
]

# --------------------------------------------------------------------------- #
# HGCL — 13 MW rooftop solar EPC. Liquid assets/credit Rs. 49.855 Cr;
# similar works of 13 MW cumulative capacity.
# --------------------------------------------------------------------------- #
HGCL_VENDORS = [
    VendorSpec(
        vendor_id="VENDOR_civilworks_02_01",
        document_naming="alias",
        notification_id="NOTIF_civilworks_02",
        vendor_name="Suryodaya Renewables Limited",
        constitution="Public Limited Company registered under the Companies Act, 2013",
        city="Hyderabad",
        established=2008,
        intended_status="pass", intended_reason="", intended_failed_clause="",
        writeup_quality="strong",
        turnover=[("2020-21", "Rs. 218,40,00,000"), ("2021-22", "Rs. 264,10,00,000"),
                  ("2022-23", "Rs. 311,75,00,000")],
        net_worth="Rs. 96,20,00,000",
        bank_credit="Rs. 62,00,00,000",
        projects=[
            dict(client="NTPC Renewable Energy Limited", value="Rs. 128,00,00,000",
                 year=2022, scope="Design, supply and EPC of 18 MW (AC) rooftop solar "
                 "PV plants across 22 sites, including 210 nos. string inverters and "
                 "33KV evacuation", order_no="NTPC-REL/EPC/2021-22/044"),
            dict(client="Andhra Pradesh Solar Power Corporation", value="Rs. 74,50,00,000",
                 year=2021, scope="EPC of 11 MW (AC) ground-mounted solar plant with "
                 "33/11KV substation", order_no="APSPCL/EPC/2020-21/019"),
        ],
        certifications=[("ISO 9001:2015", "31.07.2027"), ("ISO 14001:2015", "31.07.2027"),
                        ("ISO 45001:2018", "30.06.2026"), ("MNRE Channel Partner", "31.03.2027")],
        quoted_price="Rs. 96,84,00,000",
        quoted_words="Rupees Ninety Six Crore Eighty Four Lakh only",
        notes="Clears capacity, credit and substation requirements.",
    ),
    VendorSpec(
        vendor_id="VENDOR_civilworks_02_02",
        notification_id="NOTIF_civilworks_02",
        vendor_name="Kakatiya Green Energy Private Limited",
        constitution="Private Limited Company registered under the Companies Act, 2013",
        city="Warangal",
        established=2017,
        intended_status="eliminate",
        intended_reason="Liquid assets and credit facilities of Rs. 18.40 Crores are "
                        "below the required Rs. 49.855 Crores",
        intended_failed_clause="28.1 vi)",
        writeup_quality="weak",
        turnover=[("2020-21", "Rs. 44,20,00,000"), ("2021-22", "Rs. 58,90,00,000"),
                  ("2022-23", "Rs. 66,30,00,000")],
        net_worth="Rs. 21,50,00,000",
        bank_credit="Rs. 18,40,00,000",
        projects=[
            dict(client="Telangana State Renewable Energy Development Corporation",
                 value="Rs. 38,00,00,000", year=2022,
                 scope="EPC of 6 MW rooftop solar across government buildings",
                 order_no="TSREDCO/EPC/2021-22/077"),
        ],
        certifications=[("ISO 9001:2015", "31.12.2026")],
        quoted_price="Rs. 92,15,00,000",
        quoted_words="Rupees Ninety Two Crore Fifteen Lakh only",
        notes="Lowest price, insufficient liquidity. Tests that a financial-capacity "
              "floor is enforced against an attractive quote.",
    ),
    VendorSpec(
        vendor_id="VENDOR_civilworks_02_03",
        notification_id="NOTIF_civilworks_02",
        vendor_name="Bharat Solar Infrastructure Limited",
        constitution="Public Limited Company registered under the Companies Act, 2013",
        city="Pune",
        established=2006,
        intended_status="eliminate",
        intended_reason="Declaration regarding the procurement of Solar Inverters & "
                        "Solar Modules not enclosed",
        intended_failed_clause="—",
        writeup_quality="strong",
        turnover=[("2020-21", "Rs. 402,00,00,000"), ("2021-22", "Rs. 468,50,00,000"),
                  ("2022-23", "Rs. 521,00,00,000")],
        net_worth="Rs. 174,00,00,000",
        bank_credit="Rs. 110,00,00,000",
        projects=[
            dict(client="Solar Energy Corporation of India", value="Rs. 240,00,00,000",
                 year=2022, scope="EPC of 42 MW rooftop solar with 380 nos. inverters "
                 "and 33KV substation works", order_no="SECI/EPC/2021-22/106"),
            dict(client="Maharashtra State Electricity Distribution Company",
                 value="Rs. 156,00,00,000", year=2021,
                 scope="Design and EPC of 25 MW distributed solar",
                 order_no="MSEDCL/RE/2020-21/058"),
        ],
        certifications=[("ISO 9001:2015", "31.05.2028"), ("ISO 14001:2015", "31.05.2028"),
                        ("ISO 45001:2018", "31.05.2027")],
        quoted_price="Rs. 98,40,00,000",
        quoted_words="Rupees Ninety Eight Crore Forty Lakh only",
        omitted_documents=(
            "Declaration regarding the procurement of Solar Inverters & Solar Modules",
        ),
        notes="Largest and most experienced bidder, eliminated on one missing "
              "declaration. Demo-friendly demonstration that the rule engine does not "
              "weigh reputation.",
    ),
    VendorSpec(
        vendor_id="VENDOR_civilworks_02_04",
        notification_id="NOTIF_civilworks_02",
        vendor_name="Charminar EPC Services Private Limited",
        constitution="Private Limited Company registered under the Companies Act, 2013",
        city="Hyderabad",
        established=2015,
        intended_status="eliminate",
        intended_reason="Bidder is under liquidation proceedings and is debarred",
        intended_failed_clause="2.3",
        writeup_quality="weak",
        turnover=[("2020-21", "Rs. 132,00,00,000"), ("2021-22", "Rs. 118,40,00,000"),
                  ("2022-23", "Rs. 87,60,00,000")],
        net_worth="Rs. 34,00,00,000",
        bank_credit="Rs. 51,00,00,000",
        projects=[
            dict(client="Karnataka Renewable Energy Development Limited",
                 value="Rs. 88,00,00,000", year=2021,
                 scope="EPC of 14 MW rooftop solar with inverter SITC",
                 order_no="KREDL/EPC/2020-21/033"),
        ],
        certifications=[("ISO 9001:2015", "30.04.2026")],
        quoted_price="Rs. 90,70,00,000",
        quoted_words="Rupees Ninety Crore Seventy Lakh only",
        is_blacklisted=True,
        notes="Meets the credit floor and the capacity requirement; disqualified on "
              "liquidation and debarment.",
        extra_declarations=[
            "We disclose that a petition under Section 7 of the Insolvency and "
            "Bankruptcy Code, 2016 has been admitted against the Company before the "
            "NCLT, Hyderabad Bench, and that the Company stands debarred by the "
            "Karnataka Renewable Energy Development Limited vide order dated 02.02.2023."
        ],
    ),
    VendorSpec(
        vendor_id="VENDOR_civilworks_02_05",
        document_naming="reworded",
        notification_id="NOTIF_civilworks_02",
        vendor_name="Godavari Solar Ventures LLP",
        constitution="Limited Liability Partnership registered under the LLP Act, 2008",
        city="Vijayawada",
        established=2013,
        intended_status="pass", intended_reason="", intended_failed_clause="",
        writeup_quality="weak",
        turnover=[("2020-21", "Rs. 141,00,00,000"), ("2021-22", "Rs. 168,20,00,000"),
                  ("2022-23", "Rs. 187,40,00,000")],
        net_worth="Rs. 58,90,00,000",
        # Exactly on the liquidity floor.
        bank_credit="Rs. 49,85,50,000",
        projects=[
            dict(client="Andhra Pradesh Power Generation Corporation",
                 value="Rs. 104,00,00,000", year=2022,
                 scope="EPC of 13 MW rooftop solar including SITC of 170 nos. inverters "
                 "and 33KV substation works valued at Rs. 10.4 Cr",
                 order_no="APGENCO/RE/2021-22/091"),
        ],
        certifications=[("ISO 9001:2015", "31.08.2026"), ("ISO 45001:2018", "31.08.2026")],
        quoted_price="Rs. 95,60,00,000",
        quoted_words="Rupees Ninety Five Crore Sixty Lakh only",
        is_borderline=True,
        notes="Liquidity exactly at Rs. 49.855 Cr and capacity exactly at 13 MW, with "
              "a weak write-up. Must pass on both counts.",
    ),
]

# The stray non-ASCII in the first IIT vendor's name was a typo; fix it here so
# the specs stay the single source of truth.
IITISM_VENDORS[0].vendor_name = "Jharkhand Constructions"

ALL_VENDORS = GHMC_VENDORS + IITISM_VENDORS + HGCL_VENDORS

BY_NOTIFICATION = {}
for _vendor in ALL_VENDORS:
    BY_NOTIFICATION.setdefault(_vendor.notification_id, []).append(_vendor)
