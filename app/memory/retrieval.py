from __future__ import annotations

import re
from datetime import datetime

from app.memory.models import MemoryRecord


def score_memory(record: MemoryRecord, query: str, now: datetime) -> float:
    query_terms = set(re.findall(r"[a-z0-9]+", query.casefold()))
    content_terms = set(re.findall(r"[a-z0-9]+", record.content.casefold()))
    key_terms = set(record.normalized_key.split("_"))
    lexical = len(query_terms.intersection(content_terms | key_terms))
    key_bonus = 3.0 if record.normalized_key.casefold() in query.casefold() else 0.0
    source = getattr(record.source, "value", record.source)
    explicit_bonus = 0.5 if source == "user_explicit" else 0.0
    age_days = max((now - record.updated_at).total_seconds() / 86400, 0.0)
    recency = 1.0 / (1.0 + age_days / 30.0)
    return lexical + key_bonus + explicit_bonus + recency
