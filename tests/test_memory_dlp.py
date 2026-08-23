from datetime import datetime

from sqlalchemy.orm import Session

from app.auth.models import ActorType, Principal
from app.memory.dlp import SensitiveDataType, classify_candidate, detected_types
from app.memory.models import MemoryRecord
from app.memory.schemas import (
    MemoryCandidate,
    MemoryRedactionState,
    MemoryRetentionPolicy,
    MemorySensitivityLevel,
    MemorySource,
    MemoryStatus,
    MemoryStorageEligibility,
    MemoryType,
)
from app.memory.service import MemoryService


def candidate(content: str) -> MemoryCandidate:
    return MemoryCandidate(
        memory_type=MemoryType.PREFERENCE,
        normalized_key="contact_channel",
        content=content,
        explicit_user_request=True,
    )


def test_credit_card_is_restricted_without_logging_or_storing_the_value() -> None:
    item = candidate("The card is 4111 1111 1111 1111.")
    classified = classify_candidate(item)

    assert SensitiveDataType.CREDIT_CARD in detected_types(item)
    assert classified.sensitivity_level == MemorySensitivityLevel.RESTRICTED
    assert classified.storage_eligibility == MemoryStorageEligibility.REJECT
    assert classified.redaction_state == MemoryRedactionState.REJECTED


def test_api_token_and_iban_are_restricted() -> None:
    token = candidate("Use sk-abcdefghijklmnop for the integration.")
    iban = candidate("Payment account: TR330006100519786457841326")

    assert SensitiveDataType.API_TOKEN in detected_types(token)
    assert SensitiveDataType.IBAN in detected_types(iban)
    assert classify_candidate(token).storage_eligibility == MemoryStorageEligibility.REJECT
    assert classify_candidate(iban).storage_eligibility == MemoryStorageEligibility.REJECT


def test_email_and_phone_are_redacted_before_persistence(db_session: Session) -> None:
    service = MemoryService(support_context_ttl_days=2)
    result = service.remember(
        db_session,
        1,
        candidate("Contact alice@example.com or +90 555 123 4567."),
    )

    assert result.status == "persisted"
    assert result.record is not None
    assert result.record.redaction_state == MemoryRedactionState.REDACTED
    assert result.record.sensitivity_level == MemorySensitivityLevel.SENSITIVE
    assert result.record.retention_policy == MemoryRetentionPolicy.SHORT
    assert "alice@example.com" not in result.record.content
    assert "+90 555 123 4567" not in result.record.content
    assert "[REDACTED_EMAIL]" in result.record.content
    assert "[REDACTED_PHONE]" in result.record.content


def test_multilingual_healthcare_content_is_restricted() -> None:
    item = candidate("Hastane teşhis ve reçete bilgilerimi hatırla.")

    classified = classify_candidate(item)

    assert SensitiveDataType.HEALTHCARE in detected_types(item)
    assert classified.sensitivity_level == MemorySensitivityLevel.RESTRICTED
    assert classified.storage_eligibility == MemoryStorageEligibility.REJECT


def test_password_and_national_identifier_are_restricted() -> None:
    password = candidate("parola: ÇokGizli123!")
    national_id = candidate("TCKN: 12345678901")

    assert SensitiveDataType.PASSWORD in detected_types(password)
    assert SensitiveDataType.NATIONAL_IDENTIFIER in detected_types(national_id)
    assert classify_candidate(password).redaction_state == MemoryRedactionState.REJECTED
    assert classify_candidate(national_id).redaction_state == MemoryRedactionState.REJECTED


def test_no_store_retention_rejects_candidate(db_session: Session) -> None:
    service = MemoryService()
    result = service.remember(
        db_session,
        1,
        candidate("Do not retain this preference."),
        retention_policy=MemoryRetentionPolicy.NO_STORE,
    )

    assert result.status == "reject"
    assert result.reason == "retention_policy_no_store"
    assert db_session.query(MemoryRecord).count() == 0


def test_retrieval_requires_customer_scope_and_sensitivity_policy(db_session: Session) -> None:
    service = MemoryService()
    service.remember(db_session, 1, candidate("The customer prefers email."))
    db_session.add(
        MemoryRecord(
            customer_id=1,
            memory_type=MemoryType.PREFERENCE,
            content="[REDACTED_RESTRICTED]",
            normalized_key="legacy_restricted",
            source=MemorySource.USER_EXPLICIT,
            confidence=1.0,
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
            status=MemoryStatus.ACTIVE,
            sensitivity_level=MemorySensitivityLevel.RESTRICTED,
            retention_policy=MemoryRetentionPolicy.NO_STORE,
            redaction_state=MemoryRedactionState.REJECTED,
        )
    )
    db_session.commit()

    customer_one = Principal(
        actor_id="customer-one",
        actor_type=ActorType.CUSTOMER,
        roles=["customer"],
        customer_id=1,
    )
    customer_two = Principal(
        actor_id="customer-two",
        actor_type=ActorType.CUSTOMER,
        roles=["customer"],
        customer_id=2,
    )

    assert len(service.retrieve(db_session, 1, "preference", principal=customer_one)) == 1
    assert service.retrieve(db_session, 1, "preference", principal=customer_two) == []
