from app.tools.base import OperationType, RiskLevel, ToolMetadata

TOOL_REGISTRY: dict[str, ToolMetadata] = {
    "get_customer": ToolMetadata(
        "get_customer", "Retrieve a customer by ID.", OperationType.READ, RiskLevel.READ_ONLY
    ),
    "get_customer_orders": ToolMetadata(
        "get_customer_orders",
        "List orders for a customer.",
        OperationType.READ,
        RiskLevel.READ_ONLY,
    ),
    "get_order": ToolMetadata(
        "get_order", "Retrieve an order by ID.", OperationType.READ, RiskLevel.READ_ONLY
    ),
    "get_customer_tickets": ToolMetadata(
        "get_customer_tickets",
        "List support tickets for a customer.",
        OperationType.READ,
        RiskLevel.READ_ONLY,
    ),
    "get_ticket": ToolMetadata(
        "get_ticket", "Retrieve a support ticket by ID.", OperationType.READ, RiskLevel.READ_ONLY
    ),
    "create_support_ticket": ToolMetadata(
        "create_support_ticket", "Create a support ticket.", OperationType.WRITE, RiskLevel.LOW
    ),
    "cancel_order": ToolMetadata(
        "cancel_order",
        "Cancel an eligible customer order.",
        OperationType.WRITE,
        RiskLevel.CONFIRMATION_REQUIRED,
    ),
    "request_refund": ToolMetadata(
        "request_refund",
        "Request a refund for a delivered order.",
        OperationType.WRITE,
        RiskLevel.CONFIRMATION_REQUIRED,
    ),
    "escalate_to_human": ToolMetadata(
        "escalate_to_human",
        "Queue a case for human handling.",
        OperationType.WRITE,
        RiskLevel.HUMAN_HANDLING,
    ),
}


def list_tools() -> list[ToolMetadata]:
    return list(TOOL_REGISTRY.values())


def get_tool(name: str) -> ToolMetadata:
    return TOOL_REGISTRY[name]
