"""One quality assessment shared by the report, Q&A, and both export formats."""
from app.api.schemas import DataQualityOut, ValidationFindingOut
from app.extraction.validate import validate_notification, validate_submission


def quality_for(notification_row, notification, submission_row=None, submission=None):
    findings = []
    providers = {}
    records = [('notification', notification_row, validate_notification(notification))]
    if submission_row is not None:
        records.append(('bid', submission_row, validate_submission(submission)))
    for source, row, current in records:
        metadata = getattr(row, 'extraction_metadata', None) or {}
        providers[source] = metadata.get('provider')
        raw = [dict(field=f.field, severity=f.severity.value, message=f.message,
                    value=f.value, affects_confidence=f.affects_confidence) for f in current]
        raw += metadata.get('findings', [])
        for field in ('extraction_errors', 'parse_warnings'):
            raw += [dict(field=field, severity='warning', message=message,
                         value=None, affects_confidence=True) for message in metadata.get(field, [])]
        if not metadata:
            raw.append(dict(field='extraction_audit', severity='warning',
                            message='Original extraction audit was not recorded. Provider and extraction errors are unknown; re-extract to verify.',
                            value=None, affects_confidence=True))
        seen = set()
        for item in raw:
            key = (item['field'], item['message'])
            if key not in seen:
                findings.append(ValidationFindingOut(source=source, **item))
                seen.add(key)
    affecting = [f for f in findings if f.affects_confidence]
    banner = ' '.join(f'{f.source}: {f.message}' for f in affecting) or None
    return DataQualityOut(ok=not affecting, banner=banner, findings=findings, providers=providers)


def provider_label(quality):
    return '; '.join(f'{source}: {provider or "not recorded"}' for source, provider in quality.providers.items())
