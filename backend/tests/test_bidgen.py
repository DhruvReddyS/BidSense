"""Synthetic bid generation (Section 9.2).

The generator is test data, but it is test data the evaluation numbers depend
on. If a "compliant" bid does not actually enclose what the tender asks for,
Section 10's elimination precision measures the fixture, not the pipeline.
"""

from __future__ import annotations

from dataclasses import replace
import re

import pytest

from app.bidgen.render import build_pages
from app.bidgen.spec import VendorSpec
from app.bidgen.tenders import PROFILES
from app.bidgen.vendors import ALL_VENDORS, BY_NOTIFICATION


def spec_for(vendor_id: str) -> VendorSpec:
    return next(v for v in ALL_VENDORS if v.vendor_id == vendor_id)


# --------------------------------------------------------------------------- #
# Ground truth integrity (Section 9.2.1)
# --------------------------------------------------------------------------- #
def test_every_vendor_has_a_defined_outcome():
    for vendor in ALL_VENDORS:
        assert vendor.intended_status in {"pass", "eliminate"}
        if vendor.intended_status == "eliminate":
            assert vendor.intended_reason, f"{vendor.vendor_id} has no stated reason"
        else:
            assert not vendor.intended_reason


def test_vendor_ids_are_unique():
    ids = [v.vendor_id for v in ALL_VENDORS]
    assert len(ids) == len(set(ids))


def test_every_vendor_targets_a_known_tender():
    for vendor in ALL_VENDORS:
        assert vendor.notification_id in PROFILES


def test_each_tender_has_the_section_9_2_2_distribution():
    """A set that is all passes or all failures cannot distinguish a working
    rule engine from one that always says yes."""
    for notification_id, vendors in BY_NOTIFICATION.items():
        assert len(vendors) == 5, notification_id
        passes = [v for v in vendors if v.intended_status == "pass"]
        eliminations = [v for v in vendors if v.intended_status == "eliminate"]
        assert len(passes) >= 2, notification_id
        assert len(eliminations) >= 2, notification_id
        # A document-only failure, so a gap that is not financial is exercised.
        assert any(v.omitted_documents for v in vendors), notification_id
        # A threshold failure, so the numeric comparison path is exercised.
        assert any(
            v.intended_status == "eliminate" and not v.omitted_documents
            and not v.is_blacklisted
            for v in vendors
        ), notification_id
        # Both write-up qualities, for the Section 5.4 fluency-bias guard.
        assert {v.writeup_quality for v in vendors} == {"strong", "weak"}


def test_blacklisting_is_covered_across_the_corpus():
    """Section 9.2.2 makes a blacklisted vendor optional per notification, so
    this is asserted over the whole set rather than per tender -- but it must
    exist somewhere, or Section 5.8's hard fail is never exercised."""
    blacklisted = [v for v in ALL_VENDORS if v.is_blacklisted]
    assert len(blacklisted) >= 2
    assert all(v.intended_status == "eliminate" for v in blacklisted)
    # And on more than one tender, so it is not a quirk of a single profile.
    assert len({v.notification_id for v in blacklisted}) >= 2


def test_borderline_vendors_exist_and_are_expected_to_pass():
    """Section 9.2.2 asks for vendors sitting exactly on a threshold. An
    off-by-one comparison (">" instead of ">=") flips exactly these."""
    borderline = [v for v in ALL_VENDORS if v.is_borderline]
    assert len(borderline) >= 3
    assert all(v.intended_status == "pass" for v in borderline)
    # One per tender, so the check is not specific to one set of thresholds.
    assert len({v.notification_id for v in borderline}) == 3


def test_a_weak_writeup_vendor_still_passes_somewhere():
    """Section 5.4: a plain but complete bid must not be treated as weaker than
    a fluent but vague one. If every passing vendor writes well, the guard is
    untested."""
    weak_passers = [
        v for v in ALL_VENDORS
        if v.writeup_quality == "weak" and v.intended_status == "pass"
    ]
    assert weak_passers, "no weak-write-up vendor is expected to pass"


def test_blacklisted_vendors_disclose_it_in_the_document():
    """The flag has to be discoverable from the bid text, or extraction cannot
    find it and the elimination is untestable end to end."""
    for vendor in ALL_VENDORS:
        if not vendor.is_blacklisted:
            continue
        text = " ".join(build_pages(vendor, PROFILES[vendor.notification_id]))
        assert any(
            word in text.lower() for word in ("debarred", "liquidation", "banned")
        ), vendor.vendor_id


# --------------------------------------------------------------------------- #
# Document rendering
# --------------------------------------------------------------------------- #
def test_a_compliant_bid_encloses_the_supplied_requirement_list():
    """Data-driven: a compliant bid must enclose what the tender actually asks
    for. Against a hand-written list of fourteen, a bid for a tender demanding
    fifty documents is reported non-compliant -- a defect in the fixture."""
    vendor = spec_for("VENDOR_supply_01_01")
    required = [f"Annexure {i} declaration" for i in range(1, 31)]
    text = " ".join(build_pages(vendor, PROFILES[vendor.notification_id], required))

    for name in required:
        assert f"[X]  {name}" in text, f"{name} not enclosed"
    assert "NOT ENCLOSED" not in text


def test_an_omitted_document_is_listed_but_marked_absent():
    """A real bid's checklist shows an outstanding item, it does not hide it.

    Asserted on the [X]/[ ] markers and the omitted NAME rather than on the
    enclosed names: this vendor writes its checklist in its own words
    (`document_naming`), so "PAN Card" legitimately appears as "Permanent
    Account Number". The omitted document keeps the tender's wording -- renaming
    it would change what the answer key says is missing.
    """
    vendor = spec_for("VENDOR_supply_01_03")
    required = ["Manufacturers authorization form", "PAN Card", "GST registration"]
    text = " ".join(build_pages(vendor, PROFILES[vendor.notification_id], required))

    assert "NOT ENCLOSED" in text
    assert "Manufacturers authorization form" in text
    # Counted on numbered checklist entries only. The legend above the list
    # ("items marked [X] are enclosed") contains both markers too.
    entries = re.findall(r"\d+\.\s+\[([X ])\]\s+(.+)", text)
    assert [flag for flag, _ in entries] == ["X", "X", " "]
    assert entries[-1][1].startswith("Manufacturers authorization form")


@pytest.mark.parametrize(
    "vendor_id",
    ["VENDOR_civilworks_01_01", "VENDOR_civilworks_01_05"],
)
def test_iit_pass_bids_execute_the_required_annexure_v_undertaking(vendor_id):
    """A checklist tick and an unrelated Annexure V are not the signed form.

    These two bids are production-gate true negatives, so their source must
    contain the actual site-inspection undertaking required by tender page 79.
    """
    vendor = spec_for(vendor_id)
    text = " ".join(build_pages(vendor, PROFILES[vendor.notification_id]))

    assert "TENDER ANNEXURE V — SELF-CERTIFICATION/UNDERTAKING" in text
    assert re.search(r"personally\s+inspected the site", text)
    assert f"Name of firm/agency : {vendor.vendor_name}" in text


def test_iit_annexure_v_undertaking_can_be_deliberately_omitted():
    base = spec_for("VENDOR_civilworks_01_01")
    required = list(PROFILES[base.notification_id].key_documents)
    missing = "Duly filled Self-certification/undertaking in the format as per Annexure V"
    vendor = replace(base, omitted_documents=(missing,))
    text = " ".join(build_pages(vendor, PROFILES[vendor.notification_id], required))

    assert f"[ ]  {missing}   — NOT ENCLOSED" in text
    assert "TENDER ANNEXURE V — SELF-CERTIFICATION/UNDERTAKING" not in text


def test_omission_matching_is_not_exact_string_only():
    """The requirement list comes from extraction and its wording varies, so an
    omission stated in the spec must still match a longer extracted phrasing."""
    vendor = spec_for("VENDOR_supply_01_03")
    required = ["Copy of Manufacturers authorization form duly signed by the OEM"]
    text = " ".join(build_pages(vendor, PROFILES[vendor.notification_id], required))
    assert "NOT ENCLOSED" in text


def test_bids_are_long_enough_to_be_realistic():
    """Section 9.2.2 step 4: extraction must be tested against real document
    style, not a bare data dump."""
    for vendor in ALL_VENDORS:
        pages = build_pages(vendor, PROFILES[vendor.notification_id])
        assert len(pages) >= 9, vendor.vendor_id
        assert sum(len(p) for p in pages) > 8000, vendor.vendor_id


def test_financial_figures_appear_in_the_document_text():
    """The evaluation compares extracted figures to the spec, so the figures
    must actually be in the prose the extractor reads."""
    for vendor in ALL_VENDORS:
        text = " ".join(build_pages(vendor, PROFILES[vendor.notification_id]))
        for _year, amount in vendor.turnover:
            assert amount in text, f"{vendor.vendor_id}: {amount} missing"
        assert vendor.quoted_price in text
        for project in vendor.projects:
            assert project["value"] in text


@pytest.mark.parametrize("vendor", ALL_VENDORS, ids=lambda v: v.vendor_id)
def test_every_bid_names_its_tender(vendor: VendorSpec):
    tender = PROFILES[vendor.notification_id]
    text = " ".join(build_pages(vendor, tender))
    assert tender.tender_ref.split(",")[0] in text
    assert vendor.vendor_name.upper() in text.upper()
