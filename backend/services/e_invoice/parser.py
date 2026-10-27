"""Bounded, namespace-aware EN 16931 reading; legal validation is a separate step.

Amounts remain decimal strings. The original XML is retained by the intake; the
normalised reading is never a substitute for it or for the official rule report.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from xml.etree.ElementTree import Element, ParseError

from pypdf import PdfReader

from ..safe_xml import fromstring

MAX_XML = 8 * 1024 * 1024
MAX_FILE = 25 * 1024 * 1024
NS = {
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}
UBL_INVOICE = "{urn:oasis:names:specification:ubl:schema:xsd:Invoice-2}Invoice"
UBL_CREDIT = "{urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2}CreditNote"
CII = "{" + NS["rsm"] + "}CrossIndustryInvoice"


class Unreadable(ValueError):
    """Untrusted input could not be safely read; no validator is invoked."""


def text(node: Element, path: str, default: str = "") -> str:
    found = node.find(path, NS)
    return (found.text or "").strip() if found is not None else default


def decimal(value: str, *, required: bool = True) -> str:
    if not value and not required:
        return "0"
    try:
        number = Decimal(value)
        exponent = number.as_tuple().exponent
        if not number.is_finite() or abs(number) > Decimal("9999999999.99") or not isinstance(exponent, int) or exponent < -8:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        raise Unreadable("Ungültiger oder zu großer Zahlenwert im Rechnungsbeleg.") from None
    return format(number, "f")


def iso_date(value: str) -> str | None:
    if not value:
        return None
    try:
        return (datetime.strptime(value, "%Y%m%d").date() if len(value) == 8 else date.fromisoformat(value)).isoformat()
    except ValueError:
        raise Unreadable("Ungültiges Datum im Rechnungsbeleg.") from None


def safe_tree(xml: bytes) -> Element:
    if not xml or len(xml) > MAX_XML:
        raise Unreadable("Die Rechnungs-XML ist leer oder überschreitet 8 MiB.")
    try:
        root = fromstring(xml)
    except (ParseError, ValueError, RecursionError):
        raise Unreadable("Die Rechnungs-XML ist beschädigt oder enthält unzulässige Entitäten.") from None
    stack, count = [(root, 0)], 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > 100000 or depth > 48:
            raise Unreadable("Die Rechnungs-XML überschreitet die zulässige Strukturgröße.")
        if node.tag == "{http://www.w3.org/2001/XInclude}include":
            raise Unreadable("Externe XML-Einbindungen sind nicht zulässig.")
        # The pinned local schemas decide validation. An uploaded document must
        # never select another schema or trigger external reference resolution.
        for key in node.attrib:
            if key in {"{http://www.w3.org/2001/XMLSchema-instance}schemaLocation",
                       "{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation"}:
                raise Unreadable("Extern angegebene Schemas sind nicht zulässig; es gelten die lokalen Regelpakete.")
        stack.extend((child, depth + 1) for child in node)
    return root


def extract(content: bytes) -> tuple[str, bytes, dict]:
    if not content or len(content) > MAX_FILE:
        raise Unreadable("Der Rechnungsbeleg ist leer oder überschreitet 25 MiB.")
    if not content.startswith(b"%PDF-"):
        safe_tree(content)
        return "xml", content, {}
    try:
        pdf = PdfReader(BytesIO(content), strict=True)
        if pdf.is_encrypted:
            raise Unreadable("Verschlüsselte Rechnungs-PDFs werden nicht unterstützt.")
        attachments = list(pdf.attachment_list)
        if len(attachments) > 16:
            raise Unreadable("Die PDF enthält zu viele Anhänge.")
        candidates = [a for a in attachments if (a.name or "").casefold() in
                      {"factur-x.xml", "zugferd-invoice.xml", "xrechnung.xml"}]
        if len(candidates) != 1:
            raise Unreadable("Die PDF muss genau eine eindeutig benannte Rechnungs-XML enthalten.")
        xml = candidates[0].content
        safe_tree(xml)
        return "pdf", xml, {"embedded_filename": candidates[0].name,
                            "embedded_sha256": hashlib.sha256(xml).hexdigest()}
    except Unreadable:
        raise
    except Exception:
        raise Unreadable("Die PDF oder ihre eingebettete Rechnungs-XML ist nicht sicher lesbar.") from None


def _ubl(root: Element) -> dict:
    credit = root.tag == UBL_CREDIT
    money = root.find("cac:LegalMonetaryTotal", NS)
    if money is None:
        raise Unreadable("Rechnungssummen fehlen.")
    supplier = root.find("cac:AccountingSupplierParty/cac:Party", NS)
    if supplier is None:
        raise Unreadable("Der Rechnungsaussteller fehlt.")
    taxes = []
    for tax in root.findall("cac:TaxTotal/cac:TaxSubtotal", NS):
        taxes.append({"rate": decimal(text(tax, "cac:TaxCategory/cbc:Percent"), required=False),
                      "net": decimal(text(tax, "cbc:TaxableAmount")), "vat": decimal(text(tax, "cbc:TaxAmount")),
                      "category": text(tax, "cac:TaxCategory/cbc:ID"),
                      "exemption_reason": text(tax, "cac:TaxCategory/cbc:TaxExemptionReason"),
                      "exemption_code": text(tax, "cac:TaxCategory/cbc:TaxExemptionReasonCode")})
    lines = []
    for line in root.findall("cac:CreditNoteLine" if credit else "cac:InvoiceLine", NS):
        qty = line.find("cbc:CreditedQuantity" if credit else "cbc:InvoicedQuantity", NS)
        lines.append({"id": text(line, "cbc:ID"), "name": text(line, "cac:Item/cbc:Name"),
                      "description": text(line, "cac:Item/cbc:Description"),
                      "quantity": decimal(qty.text or "") if qty is not None else None,
                      "unit": qty.get("unitCode") if qty is not None else None,
                      "net": decimal(text(line, "cbc:LineExtensionAmount")),
                      "price": text(line, "cac:Price/cbc:PriceAmount"),
                      "tax_category": text(line, "cac:Item/cac:ClassifiedTaxCategory/cbc:ID"),
                      "tax_rate": text(line, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent")})
    return {"syntax": "UBL", "profile": text(root, "cbc:CustomizationID"),
            "type_code": text(root, "cbc:CreditNoteTypeCode" if credit else "cbc:InvoiceTypeCode"),
            "number": text(root, "cbc:ID"), "issued_on": iso_date(text(root, "cbc:IssueDate")),
            "due_on": iso_date(text(root, "cbc:DueDate") or text(root, "cac:PaymentMeans/cbc:PaymentDueDate")),
            "currency": text(root, "cbc:DocumentCurrencyCode"),
            "supplier": text(supplier, "cac:PartyLegalEntity/cbc:RegistrationName") or text(supplier, "cac:PartyName/cbc:Name"),
            "supplier_tax_ids": [text(e, "cbc:CompanyID") for e in supplier.findall("cac:PartyTaxScheme", NS)],
            "buyer_reference": text(root, "cbc:BuyerReference"),
            "buyer": text(root, "cac:AccountingCustomerParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName"),
            "original_reference": text(root, "cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID"),
            "performance_start": iso_date(text(root, "cac:InvoicePeriod/cbc:StartDate")),
            "performance_end": iso_date(text(root, "cac:InvoicePeriod/cbc:EndDate")),
            "net": decimal(text(money, "cbc:TaxExclusiveAmount")),
            "vat": str(sum((Decimal(t["vat"]) for t in taxes), Decimal(0))),
            "gross": decimal(text(money, "cbc:TaxInclusiveAmount")),
            "due": decimal(text(money, "cbc:PayableAmount")),
            "prepaid": decimal(text(money, "cbc:PrepaidAmount"), required=False),
            "rounding": decimal(text(money, "cbc:PayableRoundingAmount"), required=False),
            "payment_terms": text(root, "cac:PaymentTerms/cbc:Note"),
            "payment_reference": text(root, "cac:PaymentMeans/cbc:PaymentID"),
            "bank_accounts": [{"iban": text(m, "cac:PayeeFinancialAccount/cbc:ID"),
                               "name": text(m, "cac:PayeeFinancialAccount/cbc:Name"),
                               "bic": text(m, "cac:PayeeFinancialAccount/cac:FinancialInstitutionBranch/cbc:ID")}
                              for m in root.findall("cac:PaymentMeans", NS)
                              if text(m, "cac:PayeeFinancialAccount/cbc:ID")],
            "taxes": taxes, "lines": lines}


def _cii(root: Element) -> dict:
    header = root.find("rsm:ExchangedDocument", NS)
    trade = root.find("rsm:SupplyChainTradeTransaction", NS)
    if header is None or trade is None:
        raise Unreadable("Rechnungskopf oder Handelsdaten fehlen.")
    agreement = trade.find("ram:ApplicableHeaderTradeAgreement", NS)
    settlement = trade.find("ram:ApplicableHeaderTradeSettlement", NS)
    if agreement is None or settlement is None:
        raise Unreadable("Aussteller oder Rechnungssummen fehlen.")
    total = settlement.find("ram:SpecifiedTradeSettlementHeaderMonetarySummation", NS)
    if total is None:
        raise Unreadable("Rechnungssummen fehlen.")
    taxes = [{"rate": decimal(text(t, "ram:RateApplicablePercent"), required=False),
              "net": decimal(text(t, "ram:BasisAmount")), "vat": decimal(text(t, "ram:CalculatedAmount")),
              "category": text(t, "ram:CategoryCode"), "exemption_reason": text(t, "ram:ExemptionReason"),
              "exemption_code": text(t, "ram:ExemptionReasonCode")}
             for t in settlement.findall("ram:ApplicableTradeTax", NS)]
    lines = []
    for line in trade.findall("ram:IncludedSupplyChainTradeLineItem", NS):
        qty = line.find("ram:SpecifiedLineTradeDelivery/ram:BilledQuantity", NS)
        lines.append({"id": text(line, "ram:AssociatedDocumentLineDocument/ram:LineID"),
                      "name": text(line, "ram:SpecifiedTradeProduct/ram:Name"),
                      "description": text(line, "ram:SpecifiedTradeProduct/ram:Description"),
                      "quantity": decimal(qty.text or "") if qty is not None else None,
                      "unit": qty.get("unitCode") if qty is not None else None,
                      "net": decimal(text(line, "ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount")),
                      "price": text(line, "ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount"),
                      "tax_category": text(line, "ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:CategoryCode"),
                      "tax_rate": text(line, "ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:RateApplicablePercent")})
    return {"syntax": "CII", "profile": text(root, "rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID"),
            "type_code": text(header, "ram:TypeCode"), "number": text(header, "ram:ID"),
            "issued_on": iso_date(text(header, "ram:IssueDateTime/udt:DateTimeString")),
            "due_on": iso_date(text(settlement, "ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/udt:DateTimeString")),
            "currency": text(settlement, "ram:InvoiceCurrencyCode"),
            "supplier": text(agreement, "ram:SellerTradeParty/ram:Name"),
            "supplier_tax_ids": [text(t, "ram:ID") for t in agreement.findall("ram:SellerTradeParty/ram:SpecifiedTaxRegistration", NS)],
            "buyer": text(agreement, "ram:BuyerTradeParty/ram:Name"),
            "buyer_reference": text(agreement, "ram:BuyerReference"),
            "original_reference": text(settlement, "ram:InvoiceReferencedDocument/ram:IssuerAssignedID"),
            "performance_start": iso_date(text(settlement, "ram:BillingSpecifiedPeriod/ram:StartDateTime/udt:DateTimeString")),
            "performance_end": iso_date(text(settlement, "ram:BillingSpecifiedPeriod/ram:EndDateTime/udt:DateTimeString")),
            "net": decimal(text(total, "ram:TaxBasisTotalAmount")),
            "vat": str(sum((Decimal(t["vat"]) for t in taxes), Decimal(0))),
            "gross": decimal(text(total, "ram:GrandTotalAmount")), "due": decimal(text(total, "ram:DuePayableAmount")),
            "prepaid": decimal(text(total, "ram:TotalPrepaidAmount"), required=False),
            "rounding": decimal(text(total, "ram:RoundingAmount"), required=False),
            "payment_terms": text(settlement, "ram:SpecifiedTradePaymentTerms/ram:Description"),
            "payment_reference": text(settlement, "ram:PaymentReference"),
            "bank_accounts": [{"iban": text(m, "ram:PayeePartyCreditorFinancialAccount/ram:IBANID"),
                               "name": text(m, "ram:PayeePartyCreditorFinancialAccount/ram:AccountName"),
                               "bic": text(m, "ram:PayeeSpecifiedCreditorFinancialInstitution/ram:BICID")}
                              for m in settlement.findall("ram:SpecifiedTradeSettlementPaymentMeans", NS)
                              if text(m, "ram:PayeePartyCreditorFinancialAccount/ram:IBANID")],
            "taxes": taxes, "lines": lines}


def read(xml: bytes, container: str) -> dict:
    root = safe_tree(xml)
    if root.tag in {UBL_INVOICE, UBL_CREDIT}:
        value = _ubl(root)
    elif root.tag == CII:
        value = _cii(root)
    else:
        raise Unreadable("Kein unterstützter UBL- oder CrossIndustryInvoice-Beleg.")
    blockers = []
    profile = value["profile"].casefold()
    value["format"] = "xrechnung" if "xrechnung" in profile else "zugferd"
    if value["format"] == "zugferd" and (value["syntax"] != "CII" or profile != "urn:cen.eu:en16931:2017"):
        blockers.append("Unterstützt werden XRechnung und ZUGFeRD im Profil EN 16931.")
    if container == "pdf" and value["format"] != "zugferd":
        blockers.append("Ein PDF-Eingang muss ZUGFeRD im Profil EN 16931 enthalten.")
    value["kind"] = {"380": "invoice", "381": "credit_note"}.get(value["type_code"])
    if value["kind"] is None or (root.tag == UBL_CREDIT and value["kind"] != "credit_note"):
        blockers.append("Diese Belegart wird nicht übernommen: " + value["type_code"])
    if value["currency"] != "EUR":
        blockers.append("Diese Währung wird im Rechnungseingang nicht unterstützt: " + value["currency"])
    if any(not value[key] for key in ("number", "supplier", "issued_on")):
        blockers.append("Rechnungsnummer, Aussteller oder Rechnungsdatum fehlen.")
    if bool(value["performance_start"]) != bool(value["performance_end"]):
        blockers.append("Der Leistungszeitraum ist unvollständig.")
    if value["performance_start"] and value["performance_end"] and value["performance_start"] > value["performance_end"]:
        blockers.append("Das Ende des Leistungszeitraums liegt vor seinem Beginn.")
    if abs(Decimal(value["rounding"])) > 1:
        blockers.append("Ein Rundungsbetrag über einem Euro benötigt eine gesonderte fachliche Klärung.")
    if Decimal(value["gross"]) + Decimal(value["rounding"]) - Decimal(value["prepaid"]) != Decimal(value["due"]):
        blockers.append("Bruttobetrag, Rundung, Vorauszahlung und Zahlbetrag stimmen nicht überein.")
    for key, limit in {"number": 100, "supplier": 300, "payment_terms": 500, "payment_reference": 200}.items():
        if len(value[key]) > limit:
            blockers.append(f"Das Feld {key} überschreitet die unterstützte Länge ({limit} Zeichen).")
    if Decimal(value["prepaid"]) != 0:
        blockers.append("Bereits geleistete Zahlungen müssen vor einer Übernahme fachlich zugeordnet werden.")
    if Decimal(value["due"]) < 0 or any(Decimal(value[key]) < 0 for key in ("net", "vat", "gross")):
        blockers.append("Negative Rechnungssummen werden nicht stillschweigend umgedeutet.")
    if len(value["taxes"]) > 10:
        blockers.append("Die vorhandene Rechnungsprüfung unterstützt höchstens zehn Steuergruppen.")
    if not value["taxes"]:
        blockers.append("Die Steueraufschlüsselung fehlt.")
    if any(len(tax["exemption_reason"]) > 2000 or len(tax["exemption_code"]) > 100 or not tax["category"] for tax in value["taxes"]):
        blockers.append("Steuergruppen oder Befreiungsgründe überschreiten den unterstützten Umfang.")
    value["blockers"] = blockers
    return value
