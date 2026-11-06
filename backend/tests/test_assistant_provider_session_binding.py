"""Local synthetic Claude streams must remain in the initialized session."""

import json

import pytest

from backend.services import assistant_provider_claude as claude
from backend.services.assistant_provider_protocol import ProviderError
from backend.tests.test_assistant_provider_claude import final, frame, init
from backend.tests.test_assistant_provider_claude import transport as transport


def replaced(event, **changes):
    value = json.loads(event[1])
    value.update(changes)
    return frame(**value)


@pytest.mark.parametrize("events", [
    [init(), replaced(final(), session_id="stale-session")],
    [init(), replaced(final(), session_id=None)],
    [init(), replaced(final(), session_id=7)],
    [replaced(init(), session_id=None), final()],
    [init(), init(), final()],
    [init(), final(), final()],
    [final(), init()],
    [init(), frame(type="stream_event", session_id="stale-session",
                   event={"delta": {"type": "text_delta", "text": "UNTRUSTED-CONTENT"}}), final()],
])
def test_inconsistent_session_or_duplicate_envelope_is_rejected(transport, events):
    transport.scripts.append({"events": events})
    emitted: list[dict] = []
    with pytest.raises(ProviderError) as rejected:
        claude.execute(transport.profile, transport.executable, {}, emitted.append, lambda: False)
    assert rejected.value.code == "provider_protocol_error"
    assert rejected.value.uncertain
    assert "UNTRUSTED-CONTENT" not in str(emitted) + str(rejected.value)
    assert transport.children[0].closed
