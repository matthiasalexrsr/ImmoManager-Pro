"""Invoice review rules without storage: duplicates, arithmetic and VAT, the § 14 UStG checklist,
deviations of the factual check and the settlement (what is payable, paid, open, disputed).

Every amount is exact cents (domain.money). Findings are hints for the reviewer; none of them
rejects an invoice by itself. Each finding carries a code and parameters (the UI words it in
its language) and a German message for API users.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from .money import ZERO, as_number, cents, money

ONE_CENT = Decimal("0.01")
HUNDRED = Decimal("100")
# rates of German VAT law (16/5 % applied in the second half of 2020)
KNOWN_RATES = frozenset({Decimal("0"), Decimal("5"), Decimal("7"), Decimal("16"), Decimal("19")})
_LEGAL_FORMS = frozenset({"gmbh", "mbh", "ag", "kg", "ohg", "gbr", "ug", "ek", "e", "k", "co", "haftungsbeschrankt",
                          "inh", "und", "kgaa", "se", "partg"})


def _de_amount(value: Decimal) -> str:
    text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} €"


def _de_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def finding(code: str, severity: str, message: str, **params: Any) -> dict:
    return {"code": code, "severity": severity, "message": message,
            "params": {k: (as_number(v) if isinstance(v, Decimal) else
                           v.isoformat() if isinstance(v, date) else v) for k, v in params.items()}}


# ─── Duplicates ──────────────────────────────────────────────────────────────

def _fold(text: str | None) -> str:
    plain = unicodedata.normalize("NFKD", text or "")
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch)).casefold()
    return re.sub(r"[^0-9a-z]+", " ", plain).strip()


def supplier_key(name: str | None) -> str:
    """The supplier as the duplicate key compares it: case, accents, punctuation and legal form ignored."""
    words = [word for word in _fold(name).split() if word not in _LEGAL_FORMS]
    return " ".join(words) or _fold(name)


def number_key(number: str | None) -> str:
    """The invoice number without spaces, separators and leading zeros ("RE-0042" = "re42")."""
    folded = _fold(number).replace(" ", "")
    return re.sub(r"(?<![0-9])0+(?=[0-9])", "", folded)


@dataclass(frozen=True)
class InvoiceFacts:
    id: str
    supplier: str
    invoice_number: str | None
    invoice_date: date
    gross: Decimal


def duplicates(candidate: InvoiceFacts, others: Iterable[InvoiceFacts], window_days: int) -> list[dict]:
    """Suspected duplicates of the candidate: same supplier and number (the key), or same supplier,
    same gross amount and an invoice date at most `window_days` apart."""
    found: list[dict] = []
    supplier = supplier_key(candidate.supplier)
    number = number_key(candidate.invoice_number)
    for other in others:
        if other.id == candidate.id or supplier_key(other.supplier) != supplier or not supplier:
            continue
        days = abs((other.invoice_date - candidate.invoice_date).days)
        if number and number_key(other.invoice_number) == number:
            found.append({"invoice_id": other.id, "reason": "same_number", "invoice_number": other.invoice_number,
                          "invoice_date": other.invoice_date.isoformat(), "gross_amount": as_number(other.gross),
                          "days_apart": days})
        elif money(other.gross) == money(candidate.gross) and days <= window_days:
            found.append({"invoice_id": other.id, "reason": "same_amount_near_date",
                          "invoice_number": other.invoice_number, "invoice_date": other.invoice_date.isoformat(),
                          "gross_amount": as_number(other.gross), "days_apart": days})
    return sorted(found, key=lambda item: (item["reason"] != "same_number", item["days_apart"], item["invoice_id"]))


# ─── Arithmetic: net + VAT = gross per rate ──────────────────────────────────

@dataclass(frozen=True)
class VatLine:
    rate: Decimal
    net: Decimal
    vat: Decimal

    @classmethod
    def of(cls, raw: dict) -> VatLine:
        return cls(Decimal(str(raw["rate"])), money(raw["net"]), money(raw["vat"]))


def invoice_lines(net: Any, vat_amount: Any, gross: Any, vat_rate: Any, lines: Sequence[dict] | None) -> list[VatLine]:
    """The VAT lines the review checks: the recorded breakdown, else the invoice's single rate."""
    if lines:
        return [VatLine.of(line) for line in lines]
    vat = money(vat_amount)
    if vat == 0 and money(gross) != money(net):
        vat = money(gross) - money(net)        # older invoices often kept no VAT amount
    return [VatLine(Decimal(str(vat_rate if vat_rate is not None else 19)), money(net), vat)]


def arithmetic_findings(net: Any, vat_amount: Any, gross: Any, vat_rate: Any,
                        lines: Sequence[dict] | None) -> list[dict]:
    net_total, gross_total = money(net), money(gross)
    found: list[dict] = []
    breakdown = invoice_lines(net, vat_amount, gross, vat_rate, lines)
    if gross_total <= 0 or net_total < 0:
        found.append(finding("non_positive_amount", "error",
                             "Rechnungsbeträge müssen positiv sein (eine Gutschrift wird als Gutschrift erfasst).",
                             gross=gross_total, net=net_total))
    for line in breakdown:
        expected = cents(line.net * line.rate / HUNDRED)
        difference = line.vat - expected
        if line.rate not in KNOWN_RATES:
            found.append(finding("unusual_rate", "warning",
                                 f"Ungewöhnlicher Steuersatz {line.rate.normalize():f} %.", rate=float(line.rate)))
        if abs(difference) > ONE_CENT:
            found.append(finding("vat_mismatch", "error",
                                 f"Steuer zu {line.rate.normalize():f} % auf {_de_amount(line.net)}: berechnet "
                                 f"{_de_amount(expected)}, ausgewiesen {_de_amount(line.vat)} "
                                 f"(Abweichung {_de_amount(difference)}).",
                                 rate=float(line.rate), net=line.net, vat=line.vat, expected=expected,
                                 difference=difference))
        elif difference != 0:
            found.append(finding("vat_rounding", "info",
                                 f"Steuer zu {line.rate.normalize():f} % weicht um einen Cent ab (Rundung).",
                                 rate=float(line.rate), difference=difference))
    line_net = sum((line.net for line in breakdown), ZERO)
    line_vat = sum((line.vat for line in breakdown), ZERO)
    if lines and line_net != net_total:
        found.append(finding("net_mismatch", "error",
                             f"Die Nettobeträge der Steuersätze ergeben {_de_amount(line_net)}, die Rechnung nennt "
                             f"{_de_amount(net_total)}.", expected=line_net, actual=net_total,
                             difference=net_total - line_net))
    if line_net + line_vat != gross_total:
        found.append(finding("gross_mismatch", "error",
                             f"Netto + Steuer = {_de_amount(line_net + line_vat)}, die Rechnung nennt brutto "
                             f"{_de_amount(gross_total)} (Abweichung {_de_amount(gross_total - line_net - line_vat)}).",
                             expected=line_net + line_vat, actual=gross_total,
                             difference=gross_total - line_net - line_vat))
    if not lines and money(vat_amount) == 0 and gross_total != net_total:
        found.append(finding("vat_amount_missing", "info",
                             "Die Rechnung hat keinen Steuerbetrag gespeichert; geprüft wird brutto − netto."))
    return found


# ─── § 14 Abs. 4 UStG (and § 33 UStDV for small invoices) ────────────────────

# key, German label, required for a small invoice (§ 33 UStDV), filled automatically from
CHECKLIST: tuple[tuple[str, str, bool], ...] = (
    ("supplier_name_address", "Name und Anschrift des leistenden Unternehmers", True),
    ("recipient_name_address", "Name und Anschrift des Leistungsempfängers", False),
    ("tax_number", "Steuernummer oder USt-IdNr. des Leistenden", False),
    ("issue_date", "Ausstellungsdatum", True),
    ("invoice_number", "Fortlaufende Rechnungsnummer", False),
    ("description", "Menge und Art der Lieferung bzw. Umfang und Art der Leistung", True),
    ("service_date", "Zeitpunkt der Lieferung oder Leistung", False),
    ("amounts_by_rate", "Entgelt nach Steuersätzen aufgeschlüsselt", True),
    ("tax_rate_and_amount", "Steuersatz und Steuerbetrag oder Hinweis auf eine Steuerbefreiung", True),
    ("discount_agreement", "Im Voraus vereinbarte Entgeltminderung (z. B. Skonto)", False),
    ("retention_notice", "Hinweis auf die Aufbewahrungspflicht (§ 14 Abs. 4 Nr. 9, Leistungen an Private)", False),
)
AUTOMATIC = frozenset({"issue_date", "invoice_number", "amounts_by_rate", "tax_rate_and_amount"})


def checklist(*, gross: Any, invoice_date: date | None, invoice_number: str | None, has_skonto: bool,
              arithmetic_ok: bool, has_service_period: bool, small_limit: Any, manual: dict | None) -> dict:
    """Each mandatory field: required?, present?, filled from the data or confirmed by the reviewer.

    Automatic answers: issue date and number from the invoice, amounts and rate from the
    arithmetic check, the service date from a contract bill's service period. A missing
    field is a finding, never a rejection.
    """
    manual = manual or {}
    small = money(gross) <= money(small_limit)
    items, missing = [], []
    automatic = {"issue_date": invoice_date is not None, "invoice_number": bool((invoice_number or "").strip()),
                 "amounts_by_rate": arithmetic_ok, "tax_rate_and_amount": arithmetic_ok}
    for key, label, required_small in CHECKLIST:
        required = required_small if small else True
        if key == "discount_agreement":
            required = has_skonto
        elif key == "retention_notice":
            required = False            # the landlord receives the service as an entrepreneur
        elif key == "service_date" and small:
            required = False
        if key in automatic:
            present: bool | None = automatic[key]
            source = "auto"
            if not present and manual.get(key) is True and key == "invoice_number":
                present, source = True, "manual"
        elif key == "service_date" and has_service_period and manual.get(key) is None:
            present, source = True, "auto"
        else:
            value = manual.get(key)
            present, source = (value if isinstance(value, bool) else None), "manual"
        items.append({"key": key, "label": label, "required": required, "present": present, "source": source})
        if required and present is not True:
            missing.append(key)
    return {"small_invoice": small, "items": items, "missing": missing, "complete": not missing}


def checklist_findings(result: dict) -> list[dict]:
    labels = {key: label for key, label, _ in CHECKLIST}
    return [finding("mandatory_field_missing", "warning",
                    f"Pflichtangabe nach § 14 UStG fehlt oder ist nicht bestätigt: {labels[key]}.", field=key)
            for key in result["missing"]]


# ─── Factual check: deviations from order, contract and earlier bills ────────

def order_findings(*, gross: Decimal, ordered: Decimal, billed_elsewhere: Decimal, order_label: str,
                   change_order: tuple[str, Decimal] | None) -> list[dict]:
    found = []
    total = billed_elsewhere + gross
    if total > ordered:
        found.append(finding("over_order", "warning",
                             f"Mit dieser Rechnung sind {_de_amount(total)} auf den Auftrag {order_label} "
                             f"abgerechnet, beauftragt (inkl. genehmigter Nachträge) sind {_de_amount(ordered)} "
                             f"(über Auftrag: {_de_amount(total - ordered)}).",
                             ordered=ordered, billed=total, billed_elsewhere=billed_elsewhere,
                             difference=total - ordered))
    if change_order is not None:
        title, amount = change_order
        if gross > amount:
            found.append(finding("over_change_order", "warning",
                                 f"Die Rechnung übersteigt den Nachtrag „{title}“ ({_de_amount(amount)}) um "
                                 f"{_de_amount(gross - amount)}.", change_order=amount, difference=gross - amount))
    return found


def contract_findings(*, gross: Decimal, kind: str, planned: Decimal, credited: Decimal,
                      overlaps: Sequence[dict], has_tariff: bool) -> list[dict]:
    found = []
    if kind == "settlement":
        if planned and credited != planned:
            found.append(finding("advances_differ", "warning",
                                 f"Angerechnete Abschläge {_de_amount(credited)}, laut Tarif geplant "
                                 f"{_de_amount(planned)} (Abweichung {_de_amount(credited - planned)}).",
                                 planned=planned, credited=credited, difference=credited - planned))
    elif has_tariff and gross != planned:
        found.append(finding("tariff_deviation", "warning",
                             f"Laut Tarif waren im Leistungszeitraum {_de_amount(planned)} zu erwarten, die "
                             f"Rechnung nennt {_de_amount(gross)} (Abweichung {_de_amount(gross - planned)}).",
                             expected=planned, actual=gross, difference=gross - planned))
    for other in overlaps:
        found.append(finding("period_overlap", "warning",
                             f"Der Leistungszeitraum überschneidet sich mit der bereits geprüften Rechnung "
                             f"{other.get('invoice_number') or other['invoice_id']} "
                             f"({other['period_start']} – {other['period_end']}).", **other))
    return found


def periods_overlap(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    return a_start <= b_end and b_start <= a_end


# ─── Settlement: payable, paid, open, disputed, Skonto ───────────────────────

APPROVED = ("approved", "partially_approved")


@dataclass(frozen=True)
class Payment:
    paid_on: date
    amount: Decimal


@dataclass
class Settlement:
    gross: Decimal
    status: str                           # review status, or "legacy"
    payable: Decimal | None = None        # what is owed after decision, dispute and credits
    approved: Decimal | None = None
    credits: Decimal = ZERO
    disputed: Decimal = ZERO              # part of the invoice not approved
    dispute_open: Decimal = ZERO          # of it still open with the supplier
    dispute_settled: Decimal = ZERO       # agreed to be paid after all
    written_off: Decimal = ZERO
    paid: Decimal = ZERO
    skonto_amount: Decimal = ZERO
    skonto_until: date | None = None
    skonto_taken: Decimal = ZERO
    skonto_available: bool = False
    due_on: date | None = None
    open: Decimal = ZERO
    payment_status: str = "not_payable"
    overdue: bool = False
    findings: list[dict] = field(default_factory=list)

    def flow_amount(self) -> Decimal | None:
        """What the invoice contributes to project figures and contract costs; None: as before (legacy)."""
        if self.status == "legacy":
            return None
        if self.status == "rejected":
            return ZERO
        if self.payable is None:
            return self.gross               # received, not decided: still billed, flagged by the review
        return self.payable - self.skonto_taken

    def as_json(self) -> dict:
        def num(value: Decimal | None) -> float | None:
            return None if value is None else as_number(value)

        return {"gross": num(self.gross), "status": self.status, "payable": num(self.payable),
                "approved": num(self.approved), "credits": num(self.credits), "disputed": num(self.disputed),
                "dispute_open": num(self.dispute_open), "dispute_settled": num(self.dispute_settled),
                "written_off": num(self.written_off), "paid": num(self.paid),
                "skonto_amount": num(self.skonto_amount),
                "skonto_until": self.skonto_until.isoformat() if self.skonto_until else None,
                "skonto_taken": num(self.skonto_taken), "skonto_available": self.skonto_available,
                "due_on": self.due_on.isoformat() if self.due_on else None, "open": num(self.open),
                "payment_status": self.payment_status, "overdue": self.overdue,
                "flow_amount": num(self.flow_amount()), "findings": self.findings}


def skonto_terms(invoice_date: date, percent: Any, days: int | None) -> date | None:
    if not percent or days is None:
        return None
    return invoice_date + timedelta(days=int(days))


def settle(*, gross: Any, status: str, approved: Any = None, credits: Any = ZERO, dispute_status: str | None = None,
           dispute_outcome: str | None = None, dispute_settled: Any = None, payments: Iterable[Payment] = (),
           skonto_percent: Any = None, skonto_until: date | None = None, due_on: date | None = None,
           today: date | None = None, credit_note: bool = False) -> Settlement:
    """Derive the payment state; nothing of it is stored.

    payable = approved + agreed part of the dispute − credit beyond the disputed part.
    A credit note first covers the disputed part (the supplier corrects its invoice to what
    was approved); more credit reduces what is owed. Skonto counts when every payment was
    made by its deadline and together they reach payable − Skonto.
    """
    today = today or date.today()
    g = money(gross)
    result = Settlement(gross=g, status=status, due_on=due_on, skonto_until=skonto_until)
    payments = sorted(payments, key=lambda p: p.paid_on)
    result.paid = sum((money(p.amount) for p in payments), ZERO)
    if credit_note:
        result.payment_status = "credit_note"
        return result
    if status == "legacy":
        result.payable = g
    elif status in APPROVED:
        a = money(approved if approved is not None else g)
        c = money(credits)
        result.approved, result.credits = a, c
        result.disputed = max(g - a, ZERO)
        against_dispute = min(c, result.disputed)
        excess_credit = c - against_dispute
        settled = money(dispute_settled) if dispute_outcome == "partial_payment" else ZERO
        result.dispute_settled = settled
        remainder = result.disputed - against_dispute
        if dispute_status == "resolved":
            result.written_off = max(remainder - settled, ZERO)
        else:
            result.dispute_open = remainder
        result.payable = max(a + settled - excess_credit, ZERO)
    elif status == "rejected":
        result.payable = ZERO
    else:
        result.payable = None                # received or queried: not payable yet
    if result.payable is None:
        result.payment_status = "not_payable"
        if result.paid:
            result.findings.append(finding("paid_before_approval", "warning",
                                           f"Bereits {_de_amount(result.paid)} bezahlt, obwohl die Rechnung noch "
                                           "nicht freigegeben ist.", paid=result.paid))
        return result
    p = result.payable
    if skonto_percent and skonto_until is not None and p > 0:
        result.skonto_amount = cents(p * Decimal(str(skonto_percent)) / HUNDRED)
    on_time = bool(payments) and all(pay.paid_on <= skonto_until for pay in payments) if skonto_until else False
    if result.skonto_amount and on_time and p - result.skonto_amount <= result.paid < p:
        result.skonto_taken = p - result.paid
    target = p - result.skonto_taken
    result.open = max(target - result.paid, ZERO)
    if status == "rejected":
        result.payment_status = "rejected"
        if result.paid:
            result.findings.append(finding("paid_although_rejected", "error",
                                           f"Auf die abgelehnte Rechnung sind {_de_amount(result.paid)} gezahlt.",
                                           paid=result.paid))
    elif result.paid == 0:
        result.payment_status = "open"
    elif result.paid > target:
        result.payment_status = "overpaid"
        result.findings.append(finding("overpaid", "warning",
                                       f"Überzahlt um {_de_amount(result.paid - target)}.",
                                       difference=result.paid - target))
    elif result.paid == target:
        result.payment_status = "paid"
    else:
        result.payment_status = "partially_paid"
    result.skonto_available = bool(result.skonto_amount and skonto_until and today <= skonto_until
                                   and result.payment_status in ("open", "partially_paid"))
    result.overdue = bool(due_on and today > due_on and result.open > 0)
    return result
