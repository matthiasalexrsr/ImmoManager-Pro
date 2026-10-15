"""The authorized path is authoritative; a conflicting body must never write."""
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from backend.models import MessageCreate
from backend.routers import messages
from backend.storage import NotFoundError


def test_path_a_body_b_writes_nothing(monkeypatch):
    store = MagicMock()
    monkeypatch.setattr(messages, "store", store)
    with pytest.raises(HTTPException) as failure:
        messages.create_message("thread-a", MessageCreate(thread_id="thread-b", sender_name="Test", body="Private body"))
    assert failure.value.status_code == 422
    store.create_message.assert_not_called()


def test_inaccessible_path_stays_not_found_before_payload_validation(monkeypatch):
    store = MagicMock()
    store.get_message_thread.side_effect = NotFoundError("Thread nicht gefunden")
    monkeypatch.setattr(messages, "store", store)
    with pytest.raises(HTTPException) as failure:
        messages.create_message("hidden", MessageCreate(thread_id="thread-b", sender_name="Test", body="Private body"))
    assert failure.value.status_code == 404
    store.create_message.assert_not_called()


def test_matching_thread_keeps_existing_api_contract(monkeypatch):
    store = MagicMock()
    monkeypatch.setattr(messages, "store", store)
    payload = MessageCreate(thread_id="thread-a", sender_name="Test", body="Authorized body")
    messages.create_message("thread-a", payload)
    store.get_message_thread.assert_called_once_with("thread-a")
    store.create_message.assert_called_once_with(payload)
