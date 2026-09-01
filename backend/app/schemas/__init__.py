"""Section 6 shared extraction schema -- the architectural backbone of both parts."""

from app.schemas.common import (
    ChunkSection,
    CriterionType,
    DocumentKind,
    MoneyAmount,
    Provenance,
    Provenanced,
    SchemaModel,
    UserRole,
    VendorStatus,
    YearlyTurnover,
)
from app.schemas.corrigendum import ChangedField, Corrigendum
from app.schemas.notification import (
    EligibilityCriterion,
    EvaluationCriterion,
    MandatoryDocument,
    SubmissionFormatRule,
    TechnicalRequirement,
    TenderNotification,
)
from app.schemas.submission import (
    Certification,
    PastProject,
    SubmittedDocument,
    VendorSubmission,
)

__all__ = [
    "Certification",
    "ChangedField",
    "ChunkSection",
    "Corrigendum",
    "CriterionType",
    "DocumentKind",
    "EligibilityCriterion",
    "EvaluationCriterion",
    "MandatoryDocument",
    "MoneyAmount",
    "PastProject",
    "Provenance",
    "Provenanced",
    "SchemaModel",
    "SubmissionFormatRule",
    "SubmittedDocument",
    "TechnicalRequirement",
    "TenderNotification",
    "UserRole",
    "VendorStatus",
    "VendorSubmission",
    "YearlyTurnover",
]
