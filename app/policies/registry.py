from app.policies.models import PolicyAuditEvent


class InMemoryPolicyAuditLog:
    def __init__(self) -> None:
        self.events: list[PolicyAuditEvent] = []

    def append(self, event: PolicyAuditEvent) -> None:
        self.events.append(event)
