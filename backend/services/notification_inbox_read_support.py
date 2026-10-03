"""Pure candidate hints; never credentials, authority or a release switch."""

from collections.abc import Mapping

SELECTED_SUBJECT_TABLES = frozenset({"portfolios", "properties", "units"})


def notification_read_subject_hint(
    *, status: str, unrestricted: bool, entity_type: str | None,
    entity_id: str | None, resource_aliases: Mapping[str, str],
) -> bool:
    """Use only after actual read eligibility; a True value issues no proof.

    Root must supply the actual verified principal and central alias mapping.
    Selected unlinked rows still need their actual positive resource grant.
    All-scope read eligibility does not depend on the polymorphic parent graph.
    """
    if type(unrestricted) is not bool or status not in {"unread", "read"}:
        return False
    if unrestricted:
        return True
    if entity_type is None and entity_id is None:
        return True
    if not isinstance(entity_type, str) or not isinstance(entity_id, str) or not entity_id.strip():
        return False
    return resource_aliases.get(entity_type) in SELECTED_SUBJECT_TABLES
