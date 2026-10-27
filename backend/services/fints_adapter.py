"""Versioned read-only python-fints adapter. No transfer/payment method is exposed.

Opaque library blobs are accepted only from our authenticated encrypted database.
Raw booked CAMT streams go to the ordinary bank staging contract without reserialization.
"""
from __future__ import annotations

import base64
from contextlib import closing
from datetime import date
from importlib.metadata import version

from fastapi import HTTPException


def encode(raw):
    return base64.b64encode(raw).decode('ascii')


def decode(value):
    return base64.b64decode(value, validate=True) if value else None


class PythonFinTSAdapter:
    version = 'python-fints-5.0.1/read-camt-v1'

    def __init__(self):
        try:
            if version('fints') != '5.0.1':
                raise ImportError
            from fints.client import FinTS3PinTanClient, FinTSUnsupportedOperation, NeedRetryResponse, NeedTANResponse
            from fints.models import SEPAAccount
        except (ImportError, ModuleNotFoundError):
            raise HTTPException(503, 'Für den Bankabruf muss der Administrator fints==5.0.1 installieren') from None
        self.client_type, self.retry_type, self.tan_type, self.account_type = FinTS3PinTanClient, NeedRetryResponse, NeedTANResponse, SEPAAccount
        self.unsupported = FinTSUnsupportedOperation

    def step(self, config: dict, state: dict, *, tan: str | None = None, selected: int | None = None):
        result = self._execute(config, state, tan=tan, selected=selected)
        client = result.pop('_client', None)
        if client is not None:
            result['client'] = encode(client.deconstruct(including_private=True))
        return result

    def _execute(self, config: dict, state: dict, *, tan: str | None = None, selected: int | None = None):
        state = {**state, 'mt940_streams': list(state.get('mt940_streams', []))}
        client = self.client_type(config['bank_code'], config['user_id'], config['pin'], config['server'],
            customer_id=config.get('customer_id'), tan_medium=config.get('tan_medium'), product_id=config['product_id'], product_version='1.0',
            from_data=decode(state.get('client')))
        # The observed upstream connection uses requests.Session without a timeout.
        # Keep TLS verification and bound each request; redirects must not forward PINs.
        transport = client.connection.session
        class BoundedSession:
            def post(self, *args, **kwargs):
                kwargs.update(timeout=(10, 45), allow_redirects=False)
                return transport.post(*args, **kwargs)
        client.connection.session = BoundedSession()
        upstream = client.connection
        class CaptureStatements:
            def __getattr__(self, name):
                return getattr(upstream, name)

            def send(self, message):
                response = upstream.send(message)
                for segment in response.find_segments('HIKAZ'):
                    if segment.statement_booked:
                        state['mt940_streams'].append(encode(segment.statement_booked))
                return response
        client.connection = CaptureStatements()
        if config.get('tan_mechanism'):
            client.set_tan_mechanism(config['tan_mechanism'])
        phase = state.get('phase', 'init')
        context = client.resume_dialog(decode(state['dialog'])) if state.get('dialog') else client
        with closing(transport), context:
            if state.get('challenge'):
                challenge = self.retry_type.from_data(decode(state['challenge']))
                result = client.send_tan(challenge, tan or '')
            elif phase == 'init':
                result = client.init_tan_response
            else:
                result = None
            if isinstance(result, self.tan_type):
                return self._pause(client, state, phase, result)
            if phase == 'init':
                phase, result = 'accounts', client.get_sepa_accounts()
            if isinstance(result, self.tan_type):
                return self._pause(client, state, phase, result)
            if phase == 'accounts':
                accounts = [list(account) for account in result]
                paused = self._pause(client, {**state, 'accounts': accounts}, 'select')
                paused['state'] = 'select_account'
                return paused
            if phase == 'select':
                accounts = state['accounts']
                if selected is None or not 0 <= selected < len(accounts):
                    raise ValueError('Account selection missing')
                account = self.account_type(*accounts[selected])
                phase = 'transactions'
                try:
                    result = client.get_transactions_xml(account, start_date=date.fromisoformat(config['date_from']),
                        end_date=date.fromisoformat(config['date_to']))
                except self.unsupported:
                    phase = 'transactions_mt940'
                    result = client.get_transactions(account, start_date=date.fromisoformat(config['date_from']),
                        end_date=date.fromisoformat(config['date_to']), include_pending=False)
            if isinstance(result, self.tan_type):
                return self._pause(client, state, phase, result)
            if phase == 'transactions':
                booked, pending = result
                return {'state': 'received', 'phase': 'done', 'originals': [encode(raw) for raw in booked],
                        'formats': ['camt'] * len(booked), 'pending_count': len(pending)}
            if phase == 'transactions_mt940':
                if result and not state['mt940_streams']:
                    raise ValueError('Bank movements arrived without original MT940 streams')
                return {'state': 'received', 'phase': 'done', 'originals': state['mt940_streams'],
                        'formats': ['mt940'] * len(state['mt940_streams']), 'pending_count': 0}
            raise ValueError('Unsupported FinTS state')

    def _pause(self, client, state, phase, challenge=None):
        dialog = client.pause_dialog()
        # The outer wrapper deconstructs only after leaving the paused context.
        result = {**state, 'state': 'tan_required' if challenge else 'select_account', 'phase': phase,
                  '_client': client, 'dialog': encode(dialog), 'challenge': None}
        if challenge:
            result.update(challenge=encode(challenge.get_data()), challenge_text=challenge.challenge,
                          decoupled=bool(challenge.decoupled), challenge_hhduc=challenge.challenge_hhduc)
            if challenge.challenge_matrix:
                mime, data = challenge.challenge_matrix
                if mime in ('image/png', 'image/jpeg'):
                    result['challenge_image'] = f'data:{mime};base64,' + encode(data)
        return result
