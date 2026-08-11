from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class ActorType(StrEnum):
    CUSTOMER = "customer"
    SUPPORT_OPERATOR = "support_operator"
    SERVICE = "service"


class CredentialScheme(StrEnum):
    BEARER = "bearer"


class AuthenticationCredentials(BaseModel):
    """Secret-bearing input passed only across the authentication boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scheme: CredentialScheme
    secret: SecretStr


class Principal(BaseModel):
    """Authenticated actor identity safe to pass through application layers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_id: str = Field(min_length=1, max_length=200)
    actor_type: ActorType
    roles: list[str] = Field(default_factory=list)
    customer_id: int | None = Field(default=None, gt=0)
    credential_id: str | None = Field(default=None, min_length=1, max_length=200)


class CustomerScope(BaseModel):
    """Server-resolved customer boundary for a single request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    customer_id: int = Field(gt=0)
    principal: Principal
