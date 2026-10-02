"""Business write capabilities of the five installation roles.

Account security/display preferences are checked separately against the actor.
Portfolio membership is a separate resource boundary, not inferred from a role.
"""
ALL_CAPABILITIES = frozenset({"administration", "portfolio", "rental", "finance", "billing", "operations", "documents", "marketing", "communication"})
ROLE_CAPABILITIES = {
    "eigentuemer": ALL_CAPABILITIES,
    "verwalter": ALL_CAPABILITIES,
    "buchhaltung": frozenset({"finance", "billing", "documents", "communication"}),
    "techniker": frozenset({"operations", "documents", "communication"}),
    "readonly": frozenset(),
}
RESOURCE_CAPABILITY = {
    **dict.fromkeys(("portfolios", "properties", "units"), "portfolio"),
    **dict.fromkeys(("tenants", "contracts", "contract-wizard"), "rental"),
    **dict.fromkeys(("accounts", "bookings", "receivables", "invoices", "deposits", "budgets", "tax-rates", "reports", "rent-charges", "rent-adjustments", "categories", "insurances"), "finance"),
    "billing": "billing",
    **dict.fromkeys(("maintenance", "tasks", "calendar", "escalation", "meters", "handover-protocols", "tasks-status", "tenancy-changes"), "operations"),
    **dict.fromkeys(("documents", "files", "photos"), "documents"),
    **dict.fromkeys(("listings", "leads", "viewings"), "marketing"),
    **dict.fromkeys(("messages", "contacts", "notifications", "notification-templates"), "communication"),
}


def write_capabilities(role: str) -> list[str]:
    return sorted(ROLE_CAPABILITIES.get(role, frozenset()))


def may_write_resource(role: str, resource: str) -> bool:
    capability = RESOURCE_CAPABILITY.get(resource, "administration")
    return capability in ROLE_CAPABILITIES.get(role, frozenset())
