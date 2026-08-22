"""Immutable image identities used by source-bound D2d execution."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class D2dImageIdentity(BaseModel):
    """A locally resolvable image reference bound to one immutable digest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: str = Field(min_length=1)
    image_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: str = Field(min_length=1)
    resolution_method: str = Field(min_length=1)
    immutable: Literal[True] = True

    @model_validator(mode="after")
    def validate_reference_digest(self) -> D2dImageIdentity:
        expected_suffix = f"@sha256:{self.image_digest}"
        if not self.reference.endswith(expected_suffix):
            raise ValueError("D2D_IMAGE_REFERENCE_NOT_DIGEST_PINNED")
        return self


FrozenImageValue = str | D2dImageIdentity


def structured_image_identity(value: FrozenImageValue) -> D2dImageIdentity:
    """Return a structured identity, rejecting legacy mutable strings."""

    if isinstance(value, D2dImageIdentity):
        return value
    raise ValueError("D2D_ENVIRONMENT_IMAGE_MISMATCH:legacy_or_mutable_image_binding")


def image_reference(value: FrozenImageValue) -> str:
    return structured_image_identity(value).reference
