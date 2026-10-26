"""Real, pinned invoice engines. No validation mocks and no business-data writes."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.config import settings  # noqa: E402
from backend.services.e_invoice import extraction, parser, validator  # noqa: E402


def cases(folder):
    def read(name):
        return (folder / name).read_bytes()
    yield 'XRechnung UBL', read('xrechnung-ubl.xml'), 'accepted'
    yield 'XRechnung CII', read('xrechnung-cii.xml'), 'accepted'
    yield 'ZUGFeRD XML with two tax groups', read('zugferd.xml'), 'accepted'
    yield 'ZUGFeRD PDF with two tax groups', read('zugferd.pdf'), 'accepted'
    for file, title in [('ambiguous.pdf', 'Two conflicting invoice attachments'), ('broken.pdf', 'Damaged PDF')]:
        yield title, read(file), 'unreadable'
    yield 'PDF with invalid embedded XML', read('invalid-xml.pdf'), 'invalid'
    # Derived synthetic boundary cases; original upstream fixtures remain intact.
    original = read('xrechnung-ubl.xml')
    root = ET.fromstring(original)
    root.tag = parser.UBL_CREDIT
    for element in root.iter():
        local = element.tag.rsplit('}', 1)[-1]
        if local in ('InvoiceTypeCode', 'InvoiceLine', 'InvoicedQuantity'):
            renamed = {'InvoiceTypeCode': 'CreditNoteTypeCode', 'InvoiceLine': 'CreditNoteLine', 'InvoicedQuantity': 'CreditedQuantity'}[local]
            element.tag = element.tag.rsplit('}', 1)[0] + '}' + renamed
            if local == 'InvoiceTypeCode':
                element.text = '381'
    reference = ET.Element('{' + parser.NS['cac'] + '}BillingReference')
    child = ET.SubElement(reference, '{' + parser.NS['cac'] + '}InvoiceDocumentReference')
    ET.SubElement(child, '{' + parser.NS['cbc'] + '}ID').text = 'Original-123456'
    position = list(root).index(root.find('cac:AccountingSupplierParty', parser.NS))
    root.insert(position, reference)
    yield 'XRechnung credit note with original reference', ET.tostring(root), 'credit'
    root = ET.fromstring(original)
    total = root.find('cac:LegalMonetaryTotal', parser.NS)
    payable = total.find('cbc:PayableAmount', parser.NS)
    payable.text = str(Decimal(payable.text) + Decimal('0.02'))
    rounding = ET.Element('{' + parser.NS['cbc'] + '}PayableRoundingAmount', {'currencyID': 'EUR'})
    rounding.text = '0.02'
    total.insert(list(total).index(payable), rounding)
    yield 'XRechnung explicit two-cent rounding', ET.tostring(root), 'rounding'
    total.find('cbc:TaxInclusiveAmount', parser.NS).text = '9999.99'
    yield 'Manipulated gross amount', ET.tostring(root), 'invalid'
    yield 'Unsupported currency is visibly blocked', original.replace(b'>EUR<', b'>USD<').replace(b'currencyID="EUR"', b'currencyID="USD"'), 'blocked'
    yield 'External entity', b'<!DOCTYPE Invoice [<!ENTITY x SYSTEM "file:///immo-private-sentinel">]><Invoice>&x;</Invoice>', 'unreadable'
    yield 'External include', b'<Invoice xmlns:xi="http://www.w3.org/2001/XInclude"><xi:include href="https://example.invalid/secret"/></Invoice>', 'unreadable'


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--bundle', type=Path)
    cli.add_argument('--output', type=Path, default=ROOT / 'artifacts/e-invoice-runtime-results.json')
    args = cli.parse_args()
    if args.bundle:
        settings.e_invoice_bundle = str(args.bundle.resolve())
    folder = ROOT / 'backend/tests/fixtures/e-invoice-runtime'
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    for entry in manifest['files']:
        if hashlib.sha256((folder / entry['file']).read_bytes()).hexdigest() != entry['sha256']:
            raise RuntimeError('Fixture checksum mismatch')
    results = []
    for name, content, expected in cases(folder):
        start = time.monotonic()
        item = {'name': name, 'sha256': hashlib.sha256(content).hexdigest(), 'expected': expected}
        try:
            container, xml, reading = extraction.read_isolated(content)
            validation = validator.validate(content, container, reading['format'])
            state = validation['state']
            passed = state in ('valid', 'warning') and not reading['blockers']
            if expected == 'credit':
                passed = passed and reading['kind'] == 'credit_note' and reading['original_reference'] == 'Original-123456'
            elif expected == 'rounding':
                passed = passed and reading['rounding'] == '0.02'
            elif expected == 'invalid':
                passed = state == 'invalid'
            elif expected == 'blocked':
                passed = bool(reading['blockers']) and reading['currency'] == 'USD'
            elif expected == 'unreadable':
                passed = False
            if 'two tax groups' in name:
                passed = passed and len(reading['taxes']) == 2
            item.update(passed=bool(passed), reading=reading, validation=validation, xml_sha256=hashlib.sha256(xml).hexdigest())
        except parser.Unreadable as error:
            item.update(passed=expected == 'unreadable', extraction_error=str(error))
        except validator.ValidatorUnavailable as error:
            item.update(passed=False, technical_error=str(error))
        item['seconds'] = round(time.monotonic() - start, 2)
        results.append(item)
        print(('PASS ' if item['passed'] else 'FAIL ') + name, flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({'format': 'immomanager-real-invoice-corpus/1', 'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if all(item['passed'] for item in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
