"""Re-derive canonical values from stored raw text, without calling the LLM.

Normalization is deterministic code (Section 2.1.3), so a fix to the money
parser or to relative-threshold handling can be applied to already-extracted
documents by re-running the conversion over `*_raw` columns. Re-extracting would
cost six LLM calls per document against a free-tier quota of twenty per day, and
would risk *changing* what was extracted -- this changes only how it is read.

    python -m scripts.renormalize --dry-run
    python -m scripts.renormalize

Every column this touches has a raw counterpart, so the operation is idempotent
and can be re-run after any future parser fix.
"""

from __future__ import annotations

import argparse
import logging
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.models import (  # noqa: E402
    EligibilityCriterionRow,
    TenderNotificationRow,
    VendorPastProjectRow,
    VendorSubmissionRow,
    VendorTurnoverRow,
)
from app.db.session import session_scope  # noqa: E402
from app.extraction.convert import _bare_number, _looks_monetary, relative_share  # noqa: E402
from app.normalize.money import try_normalize_amount  # noqa: E402
from app.schemas.common import CriterionType  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("renormalize")


def _changed(label: str, before, after) -> bool:
    if before == after:
        return False
    log.info("  %-46s %s -> %s", label[:46], before, after)
    return True


def renormalize(dry_run: bool = False) -> int:
    changes = 0
    with session_scope() as session:
        for notification in session.query(TenderNotificationRow).all():
            log.info("%s", notification.tender_id[:60])

            for field in ("emd_amount", "contract_value"):
                raw = getattr(notification, f"{field}_raw")
                if raw is None:
                    continue
                new = try_normalize_amount(raw)
                if _changed(f"{field}: {raw[:30]}", getattr(notification, f"{field}_inr"), new):
                    changes += 1
                    if not dry_run:
                        setattr(notification, f"{field}_inr", new)

            estimate = notification.contract_value_inr

            for criterion in notification.eligibility_criteria:
                changes += _renormalize_criterion(criterion, estimate, dry_run)

        for submission in session.query(VendorSubmissionRow).all():
            if submission.quoted_price_raw:
                new = try_normalize_amount(submission.quoted_price_raw)
                if _changed(f"{submission.vendor_id} price", submission.quoted_price_inr, new):
                    changes += 1
                    if not dry_run:
                        submission.quoted_price_inr = new

        for turnover in session.query(VendorTurnoverRow).all():
            if turnover.amount_raw:
                new = try_normalize_amount(turnover.amount_raw)
                if _changed(f"turnover {turnover.year}", turnover.amount_inr, new):
                    changes += 1
                    if not dry_run:
                        turnover.amount_inr = new

        for project in session.query(VendorPastProjectRow).all():
            if project.value_raw:
                new = try_normalize_amount(project.value_raw)
                if _changed(f"project {(project.client or '')[:20]}", project.value_inr, new):
                    changes += 1
                    if not dry_run:
                        project.value_inr = new

        if dry_run:
            session.rollback()

    return changes


def _renormalize_criterion(criterion, estimate: Decimal | None, dry_run: bool) -> int:
    """Recompute one criterion's thresholds from its raw text."""
    if criterion.type != CriterionType.NUMERIC or not criterion.threshold_raw:
        return 0

    raw = criterion.threshold_raw
    amount = number = None

    percentage = relative_share(raw)
    if percentage is not None:
        # A share of the estimated cost. Resolvable only when the estimate is
        # known; otherwise both slots stay empty and the criterion surfaces as
        # needs-manual-check, which is honest.
        if estimate is not None:
            amount = (estimate * Decimal(str(percentage)) / Decimal(100)).quantize(
                Decimal("0.01")
            )
    elif _looks_monetary(raw, criterion.unit):
        amount = try_normalize_amount(raw)
    else:
        number = _bare_number(raw)

    changes = 0
    if _changed(f"  [{criterion.clause_ref or '-'}] {raw[:34]} inr", criterion.threshold_amount_inr, amount):
        changes += 1
        if not dry_run:
            criterion.threshold_amount_inr = amount
    if _changed(f"  [{criterion.clause_ref or '-'}] {raw[:34]} num", criterion.threshold_number, number):
        changes += 1
        if not dry_run:
            criterion.threshold_number = number
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-derive canonical values from raw text")
    parser.add_argument("--dry-run", action="store_true", help="report changes without writing")
    args = parser.parse_args()

    count = renormalize(dry_run=args.dry_run)
    verb = "would change" if args.dry_run else "changed"
    log.info("\n%s %d value(s)", verb, count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
