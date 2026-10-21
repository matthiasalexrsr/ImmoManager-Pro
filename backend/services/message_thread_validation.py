"""Validate newly written thread references without making legacy history unreadable."""
from ..storage import NotFoundError, ValidationError


def validate_message_thread(data, resolve, previous=None):
    if not isinstance(data.subject, str) or not data.subject.strip():
        raise ValidationError('Bitte einen Betreff für die Konversation angeben.')

    def available(kind, identifier, label):
        if not identifier:
            return None
        try:
            return resolve(kind, identifier)
        except NotFoundError as exc:
            raise ValidationError(label + ' ist nicht verfügbar.') from exc

    location_fields = ('property_id', 'unit_id', 'contract_id')
    if previous is None or any(getattr(previous, key) != getattr(data, key) for key in location_fields):
        available('property', data.property_id, 'Die Immobilie')
        unit = available('unit', data.unit_id, 'Die Einheit')
        contract = available('contract', data.contract_id, 'Der Mietvertrag')
        if unit is not None and data.property_id and unit.property_id != data.property_id:
            raise ValidationError('Die Einheit gehört nicht zur gewählten Immobilie.')
        if contract is not None and (data.property_id and contract.property_id != data.property_id
                                     or data.unit_id and contract.unit_id != data.unit_id):
            raise ValidationError('Der Mietvertrag gehört nicht zur gewählten Immobilie oder Einheit.')
    if previous is None or previous.participant_ids != data.participant_ids:
        for identifier in dict.fromkeys(value.strip() for value in (data.participant_ids or '').split(',') if value.strip()):
            available('contact', identifier, 'Ein gewählter Kontakt')
