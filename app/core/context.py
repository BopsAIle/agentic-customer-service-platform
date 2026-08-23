from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.auth.models import ActorType, Principal


class ExecutionContext(BaseModel):
    """Server-owned identity and customer scope for one agent request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str = Field(min_length=1, max_length=200)
    conversation_id: str = Field(min_length=1, max_length=200)
    principal: Principal
    tenant_id: str = Field(default="default", min_length=1, max_length=200)
    effective_customer_id: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_customer_actor_scope(self) -> "ExecutionContext":
        if self.principal.tenant_id is not None and self.tenant_id == "default":
            object.__setattr__(self, "tenant_id", self.principal.tenant_id)
        if self.principal.tenant_id is not None and self.principal.tenant_id != self.tenant_id:
            raise ValueError("Principal does not match tenant scope.")
        if (
            self.principal.actor_type == ActorType.CUSTOMER
            and self.principal.customer_id != self.effective_customer_id
        ):
            raise ValueError("Customer principal does not match effective customer scope.")
        return self

    def safe_metadata(self) -> dict[str, str | int | list[str] | list[int]]:
        return {
            "request_id": self.request_id,
            "conversation_id": self.conversation_id,
            "actor_id": self.principal.actor_id,
            "actor_type": self.principal.actor_type.value,
            "principal_type": self.principal.principal_type.value,
            "tenant_id": self.tenant_id,
            "roles": list(self.principal.roles),
            "effective_customer_id": self.effective_customer_id,
        }

    @field_serializer("principal")
    def serialize_principal(self, principal: Principal) -> dict[str, object]:
        return {
            "actor_id": principal.actor_id,
            "actor_type": principal.actor_type.value,
            "principal_type": principal.principal_type.value,
            "roles": list(principal.roles),
            "groups": list(principal.groups),
            "tenant_id": principal.tenant_id,
            "customer_id": principal.customer_id,
            "customer_ids": list(principal.customer_ids),
        }

    def __repr_args__(self) -> Iterator[tuple[str | None, Any]]:
        return iter(self.safe_metadata().items())
