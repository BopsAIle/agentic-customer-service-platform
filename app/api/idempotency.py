from typing import Annotated

from fastapi import Header


def get_idempotency_key(
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=200,
            description="Stable identifier for retries of this business request.",
        ),
    ],
) -> str:
    return idempotency_key
