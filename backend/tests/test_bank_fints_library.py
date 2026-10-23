"""Required coordinator prerequisite gate against the real library, entirely offline.

Unlike the state-machine regression this does not substitute a library. Missing
fints==5.0.1 is a failed prerequisite, never a successful mock or a silent skip.
"""
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest


def test_real_fints_library_wire_tan_and_opaque_state_roundtrip(monkeypatch):
    try:
        installed = version('fints')
    except PackageNotFoundError:
        pytest.fail('Prerequisite missing: coordinator must install requirements-bank.txt in an isolated environment; no live bank is required')
    assert installed == '5.0.1'
    import socket

    from fints.client import FinTS3PinTanClient, FinTSClientMode, NeedRetryResponse, NeedTANResponse
    from fints.dialog import FinTSDialog
    from fints.message import FinTSInstituteMessage

    def forbidden(*args, **kwargs):
        raise AssertionError('This fixture must never open a network connection')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    raw = (Path(__file__).parent / 'fixtures/bank/fints_tan.hbci').read_bytes()
    message = FinTSInstituteMessage(segments=raw)
    assert message.find_segment_first('HNHBK').message_size == len(raw)
    tan_request = message.find_segment_first('HITAN')
    assert tan_request.task_reference == 'SYNTHETIC-TASK'
    challenge = NeedTANResponse(None, tan_request, '_continue_dialog_initialization')
    assert challenge.challenge == 'Bitte Test-TAN eingeben'
    restored_challenge = NeedRetryResponse.from_data(challenge.get_data())
    assert restored_challenge.challenge == challenge.challenge
    client = FinTS3PinTanClient('12030000', 'synthetic', 'synthetic-pin', 'https://bank.example.test/fints',
        product_id='SYNTHETIC', mode=FinTSClientMode.OFFLINE)
    with FinTSDialog(client=client, lazy_init=True) as dialog:
        dialog_data = dialog.pause()
    client_data = client.deconstruct(including_private=True)
    resumed = FinTS3PinTanClient('12030000', 'synthetic', 'synthetic-pin', 'https://bank.example.test/fints',
        product_id='SYNTHETIC', mode=FinTSClientMode.OFFLINE, from_data=client_data)
    with resumed.resume_dialog(dialog_data):
        assert resumed.pause_dialog()
