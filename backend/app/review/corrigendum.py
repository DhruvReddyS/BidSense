"""Apply typed amendments and propagate them through stored Level 1 decisions."""
from __future__ import annotations
from app.extraction.convert import parse_date
from app.normalize.money import try_normalize_amount
from app.db.repository import to_notification_schema,to_submission_schema
from app.compliance.gap import build_gap_report
from app.compliance.elimination import decide
from app.vector.qdrant import retag_status

def apply_and_reevaluate(session, notification_row, corrigendum_row) -> bool:
    applied=0
    for change in corrigendum_row.changed_fields:
        value=change.new_value
        if change.field_path in {"submission_deadline","pre_bid_query_deadline"}:
            parsed=parse_date(value)
            if parsed is not None: setattr(notification_row,change.field_path,parsed);applied+=1
        elif change.field_path in {"emd_amount","contract_value_estimate"}:
            amount=try_normalize_amount(value)
            if amount is not None:
                prefix="emd_amount" if change.field_path=="emd_amount" else "contract_value"
                setattr(notification_row,f"{prefix}_raw",value);setattr(notification_row,f"{prefix}_inr",amount);applied+=1
    unsupported=any(c.field_path.startswith(("unmapped:","eligibility_criteria","mandatory_documents")) for c in corrigendum_row.changed_fields)
    session.flush()
    if applied:
        notification=to_notification_schema(notification_row)
        for row in notification_row.submissions:
            decision=decide(build_gap_report(notification,to_submission_schema(row)))
            row.status=decision.status;row.elimination_reason=decision.reason;row.elimination_clause_ref=decision.clause_ref;row.elimination_source_page=decision.source_page;row.elimination_source_snippet=decision.source_snippet
            session.flush();retag_status(str(row.id),row.status)
    corrigendum_row.applied=bool(applied) and not unsupported
    session.flush()
    return corrigendum_row.applied
