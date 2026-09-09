import uuid
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.api.main import app
from app.auth import hash_password, verify_password, create_token, verify_token
from app.api.deps import ensure_submission_access
from app.schemas.common import UserRole


def test_password_hash_is_salted_and_verifiable():
    first=hash_password("long-enough-password"); second=hash_password("long-enough-password")
    assert first != second
    assert verify_password("long-enough-password", first)
    assert not verify_password("wrong-password", first)


def test_signed_token_rejects_tampering():
    token=create_token(str(uuid.uuid4()), "vendor")
    assert verify_token(token)["role"] == "vendor"
    assert verify_token(token + "x") is None


def test_anonymous_and_vendor_cannot_use_reviewer_endpoint():
    client=TestClient(app)
    assert client.post("/api/review/level1",json={"tender_id":"T"}).status_code == 401
    email=f"vendor-{uuid.uuid4()}@example.com"
    registered=client.post("/api/auth/register",json={"email":email,"password":"long-enough-password","role":"vendor"})
    token=registered.json()["access_token"]
    assert client.post("/api/review/level1",json={"tender_id":"T"},headers={"Authorization":f"Bearer {token}"}).status_code == 403

def test_vendor_ownership_is_independent_of_role_check():
    owner=uuid.uuid4();vendor=SimpleNamespace(id=owner,role=UserRole.VENDOR)
    ensure_submission_access(vendor,SimpleNamespace(owner_user_id=owner))
    with pytest.raises(HTTPException) as hidden:
        ensure_submission_access(vendor,SimpleNamespace(owner_user_id=uuid.uuid4()))
    assert hidden.value.status_code==404
