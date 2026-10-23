from pathlib import Path

import pytest

from backend.services.bank_formats import BankFormatError, cents, parse

FIXTURES = Path(__file__).parent / 'fixtures' / 'bank'


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '1.001', '1,00', '1e2', '--1'])
def test_strict_cent_rejection(value):
    with pytest.raises(BankFormatError):
        cents(value)


@pytest.mark.parametrize('options', [{'columns': []}, {'columns': {'date': None}}, {'date_format': []}, {'decimal': 'unknown'}])
def test_malformed_mapping_options_are_explicit_format_errors(options):
    with pytest.raises(BankFormatError):
        parse(b'date;amount;text\n2026-10-01;1.00;Miete\n', 'csv', options)


def test_cp1252_german_csv_unknown_fields_and_multiline():
    raw = 'Buchung;Wert;Zweck;Unbekannt\r\n16.10.2026;-1.234,56;"Müll\nGebühr";bewahren\r\n'.encode('cp1252')
    data = parse(raw, 'csv', {'encoding': 'cp1252', 'decimal': ',', 'date_format': '%d.%m.%Y',
        'columns': {'date': 'Buchung', 'amount': 'Wert', 'text': 'Zweck'}})
    assert data['errors'] == []
    assert data['total_cents'] == -123456
    assert data['rows'][0]['text'] == 'Müll\nGebühr'
    assert data['rows'][0]['raw']['Unbekannt'] == 'bewahren'


def test_mt940_balance_reference_reversal_and_unknown_tags():
    data = parse((FIXTURES / 'statement.sta').read_bytes(), 'mt940', {})
    assert data['errors'] == []
    assert [r['cents'] for r in data['rows']] == [12345, -100, -200]
    assert data['total_cents'] == 12045
    assert data['rows'][2]['reversal']
    assert ['99', 'UNKNOWN-ORIGINAL-FIELD'] in data['metadata']['tags']


def test_mt940_entry_date_and_value_date_keep_year_rollover_separate():
    raw = b':20:SYNTHETIC\n:60F:C261231EUR0,00\n:61:2612310101C1,00NTRFNONREF//YEAR-1\n:86:Miete\n:62F:C270101EUR1,00\n'
    data = parse(raw, 'mt940', {})
    assert data['errors'] == []
    assert data['rows'][0]['date'] == '2027-01-01'
    assert data['rows'][0]['value_date'] == '2026-12-31'


@pytest.mark.parametrize('version', ['02', '04', '08', '10'])
@pytest.mark.parametrize('kind', ['052', '053', '054'])
def test_camt_aggregate_subentries_charges_reversal_and_balance(version, kind):
    raw = (FIXTURES / 'camt053.xml').read_bytes().replace(b'001.08', f'001.{version}'.encode())
    container, entry = {'052': ('BkToCstmrAcctRpt', 'Rpt'), '053': ('BkToCstmrStmt', 'Stmt'), '054': ('BkToCstmrDbtCdtNtfctn', 'Ntfctn')}[kind]
    raw = raw.replace(b'camt.053', f'camt.{kind}'.encode()).replace(b'BkToCstmrStmt', container.encode()).replace(b'<Stmt>', f'<{entry}>'.encode()).replace(b'</Stmt>', f'</{entry}>'.encode())
    data = parse(raw, 'camt', {})
    assert data['errors'] == []
    assert [r['cents'] for r in data['rows']] == [10001, 299, -301]
    assert data['total_cents'] == 9999
    assert data['rows'][2]['reversal']
    assert 'UnknownBankField' in data['rows'][0]['raw']
    assert 'Chrgs' in data['rows'][2]['raw']


def test_camt_wrong_aggregate_and_balance_are_blocked():
    raw = (FIXTURES / 'camt053.xml').read_bytes().replace(b'100.01', b'100.02')
    data = parse(raw, 'camt', {})
    assert len(data['errors']) == 2


def test_camt_rejects_unsupported_namespace_and_entities():
    for raw in [b'<!DOCTYPE Document [<!ENTITY x "hi">]><Document>&x;</Document>', b'<Document xmlns="unknown"/>']:
        with pytest.raises(BankFormatError):
            parse(raw, 'camt', {})


def test_camt_more_than_ten_thousand_entries_has_independent_balance_oracle():
    entries = ''.join(f'<Ntry><Amt Ccy="EUR">0.01</Amt><CdtDbtInd>CRDT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts>'
                      f'<BookgDt><Dt>2026-10-01</Dt></BookgDt><AcctSvcrRef>BANK-{index}</AcctSvcrRef></Ntry>'
                      for index in range(10003))
    raw = ('<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt>'
           '<Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">0.00</Amt><CdtDbtInd>CRDT</CdtDbtInd></Bal>'
           '<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">100.03</Amt><CdtDbtInd>CRDT</CdtDbtInd></Bal>'
           + entries + '</Stmt></BkToCstmrStmt></Document>').encode()
    data = parse(raw, 'camt', {})
    assert not data['errors']
    assert len(data['rows']) == 10003
    assert data['total_cents'] == 10003
    assert {r['cents'] for r in data['rows']} == {1}
    assert len({r['reference'] for r in data['rows']}) == 10003
