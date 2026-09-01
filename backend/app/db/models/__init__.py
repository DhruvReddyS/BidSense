"""ORM models. Importing this package registers every table on Base.metadata,
which is what Alembic autogenerate and create_all rely on."""

from app.db.base import Base
from app.db.models.corrigendum import ChangedFieldRow, CorrigendumRow
from app.db.models.notification import (
    EligibilityCriterionRow,
    MandatoryDocumentRow,
    TenderNotificationRow,
)
from app.db.models.submission import (
    VendorCertificationRow,
    VendorDocumentRow,
    VendorPastProjectRow,
    VendorSubmissionRow,
    VendorTurnoverRow,
)
from app.db.models.user import User

__all__ = [
    "Base",
    "ChangedFieldRow",
    "CorrigendumRow",
    "EligibilityCriterionRow",
    "MandatoryDocumentRow",
    "TenderNotificationRow",
    "User",
    "VendorCertificationRow",
    "VendorDocumentRow",
    "VendorPastProjectRow",
    "VendorSubmissionRow",
    "VendorTurnoverRow",
]
