class ObservabilityConfig:
    """Small typed view of observability settings used by bootstrap code."""

    def __init__(
        self,
        *,
        enabled: bool,
        endpoint: str,
        service_name: str,
    ) -> None:
        self.enabled = enabled
        self.endpoint = endpoint
        self.service_name = service_name
