"""Connected Baden-Württemberg presentation data, built through real store/services."""
from __future__ import annotations

import calendar
import io
import random
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

PROPERTIES = [
    (0, "Rosenhöfe Stuttgart", "Lerchenstraße 48", "70176", "Stuttgart", 1996, 6, 13.4),
    (0, "Neckarbogen Esslingen", "Weinbergweg 27", "73728", "Esslingen am Neckar", 1984, 6, 11.8),
    (1, "Gartenhaus Karlsruhe", "Lindenallee 39", "76135", "Karlsruhe", 2003, 6, 11.9),
    (1, "Dreisamterrassen", "Sonnenhalde 46", "79102", "Freiburg im Breisgau", 2012, 6, 13.8),
    (1, "Kurpfalzquartier", "Berggartenstraße 32", "69115", "Heidelberg", 1978, 6, 12.6),
    (2, "Donaugärten Ulm", "Auenblick 24", "89073", "Ulm", 2008, 6, 11.7),
    (2, "Am Österberg", "Panoramaweg 19", "72074", "Tübingen", 1999, 4, 12.9),
    (2, "Seegarten Konstanz", "Birkenufer 37", "78462", "Konstanz", 2017, 6, 14.2),
]
NAMES = [
    "Anna Hartwig", "Jonas Reutter", "Miriam Schenk", "David Albrecht", "Lea Winter", "Felix Körner",
    "Clara Berger", "Simon Lorenz", "Elena Baumann", "Paul Brenner", "Sophie Lindner", "Lukas Auer",
    "Nina Waldner", "Tobias Eberle", "Julia Beckmann", "Martin Faber", "Laura Heinrich", "Daniel Voss",
    "Sarah Kühn", "Florian Merz", "Nora Lang", "Philipp Haller", "Marie Eckert", "Sebastian Maurer",
    "Amira Yilmaz", "Leon Seifert", "Katharina Blum", "Andreas Weller", "Jana Schuster", "Mehmet Arslan",
    "Luisa Frank", "Stefan Reimann", "Eva Keller", "Jan Schäfer", "Mila Roth", "Christian Urban",
    "Alina Herzog", "Michael Graf", "Petra Sommer", "Fabian Kirsch", "Lena Sauer", "Robert Held",
    "Carolin Barth", "Timo Schreiber", "Isabel Neuhaus", "Alexander Fischer", "Olena Weiss", "Rafael König",
    "Annika Weber", "Markus Neumann", "Selina Frey", "Benjamin Jost", "Teresa Kuhn", "Marius Dietrich",
]
SUPPLIERS = [
    ("Heller Gebäudetechnik GmbH", "Heizung und Sanitär", "Stuttgart"),
    ("Elektro Seebach", "Elektroinstallation", "Esslingen am Neckar"),
    ("Grünraum West GmbH", "Gartenpflege", "Karlsruhe"),
    ("Breisgau Hausservice", "Hausmeisterdienst", "Freiburg im Breisgau"),
    ("Dachwerk Amann", "Dach und Fassade", "Heidelberg"),
    ("Sauber & Klar Gebäudepflege", "Treppenhausreinigung", "Ulm"),
    ("Schlüsselteam Neckar", "Schließanlagen", "Tübingen"),
    ("Seeland Aufzugservice", "Aufzugswartung", "Konstanz"),
]


def months(day: date, offset: int) -> date:
    total = day.year * 12 + day.month - 1 + offset
    year, month = divmod(total, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def iban(number: int) -> str:
    # Zero bank routing code: checksum-correct formatting without a real bank.
    bban = "00000000" + f"{number:010d}"
    return f"DE{98 - int(bban + '131400') % 97:02d}{bban}"


def email(name: str) -> str:
    slug = name.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss").replace(" ", ".")
    return slug + "@wohnen.invalid"


def pdf_bytes(title: str, paragraphs: list[str], today: date) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    fonts = Path(__file__).resolve().parents[1] / "assets/fonts"
    if "DemoNoto" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DemoNoto", str(fonts / "NotoSans-Regular.ttf")))
        pdfmetrics.registerFont(TTFont("DemoNotoBold", str(fonts / "NotoSans-Bold.ttf")))
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("Business", parent=styles["Normal"], fontName="DemoNoto", fontSize=10, leading=16, spaceAfter=10)
    heading = ParagraphStyle("Heading", parent=normal, fontName="DemoNotoBold", fontSize=19, leading=25, textColor=colors.HexColor("#176B63"), spaceAfter=20)
    small = ParagraphStyle("Small", parent=normal, fontSize=8, leading=12, textColor=colors.HexColor("#61716E"))
    output = io.BytesIO()
    document = SimpleDocTemplate(output, pagesize=(210 * mm, 297 * mm), leftMargin=24 * mm, rightMargin=24 * mm,
                                 topMargin=22 * mm, bottomMargin=23 * mm, title=title, author="Neckarbogen Immobilienverwaltung GmbH")
    story = [Paragraph("NECKARBOGEN | IMMOBILIENVERWALTUNG", ParagraphStyle("Brand", parent=normal, fontName="DemoNotoBold", textColor=colors.HexColor("#176B63"))),
             Paragraph("Lindenweg 26 · 70176 Stuttgart", small), Spacer(1, 16 * mm), Paragraph(escape(title), heading),
             Paragraph(f"Stuttgart, {today:%d.%m.%Y}", small), Spacer(1, 7 * mm)]
    story.extend(Paragraph(escape(paragraph).replace("\n", "<br/>"), normal) for paragraph in paragraphs)
    story.extend([Spacer(1, 14 * mm), Paragraph("Mit freundlichen Grüßen\nNora Seidel · Immobilienverwaltung".replace("\n", "<br/>"), normal),
                  Spacer(1, 8 * mm), Paragraph("Neckarbogen Immobilienverwaltung GmbH · Verwaltung und Vermietung · Baden-Württemberg", small)])
    document.build(story)
    return output.getvalue()


class Dataset:
    def __init__(self, store, directory: Path, today: date, owner_id: str | None):
        self.store, self.directory, self.today, self.owner_id = store, directory, today, owner_id
        self.rnd = random.Random(20261105)
        self.counts: Counter[str] = Counter()
        self.portfolios: list[Any] = []
        self.properties: list[Any] = []
        self.units: list[Any] = []
        self.contracts: list[tuple[Any, Any, Any]] = []
        self.accounts: dict[str, Any] = {}
        self.categories: dict[str, dict[str, Any]] = {}
        self.owners: list[Any] = []
        self.suppliers: list[Any] = []

    def create(self, kind: str, model: str, **values):
        from backend import models
        entity = getattr(self.store, "create_" + kind)(getattr(models, model)(**values))
        self.counts[kind] += 1
        return entity

    def document(self, title: str, paragraphs: list[str], *, prop=None, unit=None, contract=None, tenant=None, kind="Korrespondenz", day=None):
        number = self.counts["document"] + 1
        relative = f"documents/{number:03d}_{kind.replace(' ', '_')}.pdf"
        file = self.directory / "uploads" / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(pdf_bytes(title, paragraphs, day or self.today))
        return self.create("document", "DocumentCreate", title=title, document_type=kind, file_url="/uploads/" + relative,
                           property_id=prop.id if prop else None, unit_id=unit.id if unit else None,
                           contract_id=contract.id if contract else None, tenant_id=tenant.id if tenant else None,
                           document_date=day or self.today, tags="Verwaltungsakte")

    def foundation(self):
        for index, (name, owner) in enumerate((("Neckar & Alb", "Nora Seidel"), ("Rhein & Breisgau", "Familie Hagedorn"), ("Donau & Bodensee", "Leonhard Bergmann"))):
            pf = self.create("portfolio", "PortfolioCreate", name=name, owner_name=owner, description="Wohn- und Geschäftshäuser in Baden-Württemberg")
            self.portfolios.append(pf)
            contact = self.create("contact", "ContactCreate", contact_type="owner", first_name=owner.split()[0], last_name=" ".join(owner.split()[1:]),
                                  email=email(owner), street="Lindenweg " + str(26 + index), zip_code="70176", city="Stuttgart", bank_name="Hausbank Südwest", iban=iban(910000 + index))
            self.owners.append(contact)
            account = self.create("account", "AccountCreate", portfolio_id=pf.id, name="Mietkonto " + name, bank_name="Hausbank Südwest", iban=iban(810000 + index),
                                  bic="SUEWDE00XXX", account_type="bank", opening_balance=round(64800 + index * 23750, 2), owner_contact_id=contact.id)
            self.accounts[pf.id] = account
            self.categories[pf.id] = {}
            for label, category_type in (("Mieteinnahmen", "income"), ("Betriebskosten", "expense"), ("Instandhaltung", "expense"), ("Verwaltung", "expense"), ("Kaution", "income")):
                self.categories[pf.id][label] = self.create("category", "CategoryCreate", portfolio_id=pf.id, name=label, category_type=category_type)
        for number, (company, trade, city) in enumerate(SUPPLIERS):
            self.suppliers.append(self.create("contact", "ContactCreate", contact_type="supplier", company_name=company, city=city, email=f"service{number + 1}@handwerk.invalid", notes=trade))
        self.create("contact", "ContactCreate", contact_type="manager", first_name="Nora", last_name="Seidel", company_name="Neckarbogen Immobilienverwaltung GmbH", email="verwaltung@neckarbogen.invalid", city="Stuttgart")
        from backend.models_ownership import OwnershipShareCreate
        from backend.services.ownership import create_share
        for number, (portfolio, name, street, postal, city, built, count, rate) in enumerate(PROPERTIES):
            pf = self.portfolios[portfolio]
            sizes = [round(self.rnd.uniform(48, 103), 1) for _ in range(count)]
            prop = self.create("property", "PropertyCreate", portfolio_id=pf.id, name=name, property_type="multi_family", address_line=street, postal_code=postal,
                               city=city, country="DE", federal_state="BW", year_built=built, living_area_sqm=round(sum(sizes), 1),
                               plot_area_sqm=round(sum(sizes) * 1.7), purchase_date=date(2017 + number % 5, 6, 1), purchase_price=round(sum(sizes) * 2740),
                               market_value=round(sum(sizes) * (3900 + number * 95)), valuation_date=date(self.today.year - 1, 12, 31))
            self.properties.append(prop)
            create_share(self.store, OwnershipShareCreate(owner_contact_id=self.owners[portfolio].id, property_id=prop.id, share_percent=100), self.owner_id)
            self.counts["ownership_share"] += 1
            for index, size in enumerate(sizes):
                rooms = 2 if size < 65 else 3 if size < 87 else 4
                floor = ["EG", "1. OG", "2. OG"][min(index // 2, 2)]
                vacant = (number, index) in {(0,5),(2,5),(4,5),(7,5)}
                unit = self.create("unit", "UnitCreate", property_id=prop.id, label=f"{floor} {'links' if index % 2 == 0 else 'rechts'}", unit_type="apartment",
                                   status="vacant" if vacant else "occupied", area_sqm=size, rooms=rooms, floor=floor, cold_rent=round(size * rate),
                                   service_charge_advance=round(size * 1.8), heating_advance=round(size * 1.25), person_count=2 if rooms < 4 else 3,
                                   features="Balkon, Kellerabteil, Fahrradraum" if index % 2 else "Einbauküche, Tageslichtbad, Kellerabteil")
                self.units.append(unit)
                self.meters(prop, unit, number, index)
                if not vacant:
                    self.tenancy(prop, unit, len(self.contracts))
            self.create("insurance", "InsuranceCreate", property_id=prop.id, insurance_type="building", provider="Südwest Gebäudeversicherung AG", policy_number=f"GW-{321800 + number}",
                        coverage_amount=prop.market_value * 1.4, premium_amount=round(sum(sizes) * 3.9, 2), start_date=date(2021, 1, 1), contact_person="Katrin Adler")
            self.create("insurance", "InsuranceCreate", property_id=prop.id, insurance_type="liability", provider="Neckarland Haftpflicht VVaG", policy_number=f"HV-{87010 + number}",
                        coverage_amount=5000000, premium_amount=round(180 + count * 23.5, 2), start_date=date(2021, 1, 1))
            for year in (self.today.year - 1, self.today.year):
                self.create("budget", "BudgetCreate", property_id=prop.id, year=year, category="maintenance", planned_amount=round(sum(sizes) * 18, -2),
                            booking_category_ids=[self.categories[pf.id]["Instandhaltung"].id], notes="Laufende Instandhaltung und kleinere Reparaturen")
            self.document("Objektübersicht – " + prop.name, [f"{street}, {postal} {city}", f"Baujahr {built} · {count} Wohnungen · Wohnfläche {sum(sizes):.1f} m²",
                          "Ansprechpartnerin: Nora Seidel. Wartungsunterlagen, Versicherungen und laufende Vorgänge werden in der Objektakte geführt."], prop=prop, kind="Objektunterlagen")

    def meters(self, prop, unit, prop_index, unit_index):
        for kind, label, measure, base, increment in (("cold_water", "Kaltwasser", "m³", 215.4, 84.7), ("heating", "Wärme", "kWh", 16480, 5260)):
            inspection = self.today + timedelta(days=(-7, 12, 35, 68)[prop_index]) if unit_index == 0 and prop_index < 4 and kind == "cold_water" else None
            meter = self.create("meter", "MeterCreate", unit_id=unit.id, meter_type=kind, measure_unit=measure,
                                serial_number=f"{'KW' if kind == 'cold_water' else 'WM'}-{prop_index + 1:02d}{unit_index + 1:02d}6832", location="Bad" if kind == "cold_water" else "Heizkreisverteiler",
                                installation_date=date(2022, 1, 1), next_inspection=inspection, supplier="Stadtversorgung " + prop.city)
            for year_offset in (-2, -1, 0):
                day = date(self.today.year + year_offset, 1, 1)
                self.create("standalone_meter_reading", "StandaloneMeterReadingCreate", meter_id=meter.id, reading_date=day,
                            value=round(base + (year_offset + 2) * increment + unit_index * 3.2, 1), recorded_by="Markus Eberle")

    def tenancy(self, prop, unit, number):
        name = NAMES[number]
        debit = number % 4 == 0
        start = date(self.today.year - 1, 1, 1)
        tenant = self.create("tenant", "TenantCreate", full_name=name, email=email(name), address_line=prop.address_line, postal_code=prop.postal_code,
                             city=prop.city, country="DE", payment_method="sepa_direct_debit" if debit else "bank_transfer",
                             sepa_mandate=f"NB-{start.year}-{number + 1:04d}" if debit else None, sepa_iban=iban(101000 + number) if debit else None,
                             sepa_mandate_date=start - timedelta(days=12) if debit else None, sepa_account_holder=name if debit else None)
        contract = self.create("contract", "ContractCreate", property_id=prop.id, unit_id=unit.id, tenant_id=tenant.id, contract_number=f"MV-{start.year}-{number + 1:04d}",
                               start_date=start, end_date=(self.today + timedelta(days=45 + number * 30)) if number < 2 else None,
                               status="active", persons=unit.person_count, deposit_amount=unit.cold_rent * 3, notice_period="3 Monate",
                               index_rent="index" if number % 7 == 0 else None)
        self.contracts.append((contract, tenant, unit))
        self.create("contract_rent_period", "ContractRentPeriodCreate", contract_id=contract.id, valid_from=start, cold_rent=unit.cold_rent,
                    service_charge_advance=unit.service_charge_advance, heating_advance=unit.heating_advance, source="contract_start")
        self.create("deposit", "DepositCreate", contract_id=contract.id, amount=unit.cold_rent * 3, held_date=start - timedelta(days=3), status="held", notes="Getrennt geführtes Mietkautionskonto")
        self.document(f"Mietvertrag {contract.contract_number}", [f"Mietpartei: {name}", f"Mietobjekt: {prop.address_line}, {prop.postal_code} {prop.city}, {unit.label}",
                      f"Mietbeginn: {start:%d.%m.%Y}. Wohnfläche: {unit.area_sqm:.1f} m², {unit.rooms:g} Zimmer.",
                      f"Nettokaltmiete: {unit.cold_rent:.2f} EUR. Betriebskostenvorauszahlung: {unit.service_charge_advance:.2f} EUR. Heizkostenvorauszahlung: {unit.heating_advance:.2f} EUR.",
                      f"Mietsicherheit: {unit.cold_rent * 3:.2f} EUR. Die monatliche Miete wird zum vertraglich vereinbarten Fälligkeitstermin entrichtet.",
                      "Die Betriebskosten werden jährlich unter Anrechnung der geleisteten Vorauszahlungen abgerechnet. Die Hausordnung und das Übergabeprotokoll ergänzen die Vertragsunterlagen."],
                      prop=prop, unit=unit, contract=contract, tenant=tenant, kind="Mietvertrag", day=start)
        if number < 8:
            self.create("handover_protocol", "HandoverProtocolCreate", contract_id=contract.id, unit_id=unit.id, protocol_type="move_in", protocol_date=start,
                        key_count=3, key_details="2 Haustürschlüssel, 1 Briefkastenschlüssel", overall_condition="good", status="draft", notes="Wohnung besenrein; Zählerstände gemeinsam abgelesen.")
        current = self.today.replace(day=1)
        month = start
        while month <= current:
            total = round(unit.cold_rent + unit.service_charge_advance + unit.heating_advance, 2)
            recent = (current.year - month.year) * 12 + current.month - month.month
            factor = 0 if number == 2 and recent < 3 else .75 if number == 8 and recent < 2 else 1
            paid_day = month.replace(day=3)
            paid = round(total * factor, 2) if paid_day <= self.today else 0
            if paid:
                account = self.accounts[prop.portfolio_id]
                booking = self.create("booking", "BookingCreate", account_id=account.id, category_id=self.categories[prop.portfolio_id]["Mieteinnahmen"].id,
                                      property_id=prop.id, unit_id=unit.id, tenant_id=tenant.id, booking_date=paid_day, amount=paid, status="booked",
                                      payment_text=f"Miete {month:%m/%Y} {name} · {contract.contract_number}")
                self.create("payment_allocation", "PaymentAllocationCreate", booking_id=booking.id, contract_id=contract.id, amount=paid, source="auto")
            if recent < 6:
                self.create("rent_charge", "RentChargeCreate", contract_id=contract.id, month=f"{month:%Y-%m}", cold_rent=unit.cold_rent,
                            service_charge=unit.service_charge_advance, heating_charge=unit.heating_advance, amount_paid=paid,
                            status="paid" if paid >= total else "partial" if paid else "overdue")
            if paid < total and paid_day < self.today:
                self.create("receivable", "ReceivableCreate", contract_id=contract.id, due_date=paid_day, amount_due=total - paid, status="open",
                            dunning_level="2" if recent > 1 else "1", description=f"Mietzahlung {month:%m/%Y}")
            month = months(month, 1)

    def operations(self):
        for index, prop in enumerate(self.properties):
            unit = next(unit for unit in self.units if unit.property_id == prop.id)
            supplier = self.suppliers[index]
            for offset in range(12):
                day = months(self.today.replace(day=12), -offset - 1)
                amount = round(380 + index * 47.5 + (offset % 3) * 125, 2)
                self.create("booking", "BookingCreate", account_id=self.accounts[prop.portfolio_id].id,
                            category_id=self.categories[prop.portfolio_id]["Betriebskosten"].id, property_id=prop.id, booking_date=day,
                            amount=-amount, status="booked", payment_text=f"Hausservice {day:%m/%Y} · {supplier.company_name}")
            for n, (title, category) in enumerate((("Heizkörperventil im Wohnzimmer erneuern", "heating"), ("Treppenhausbeleuchtung prüfen", "electrical"))):
                self.create("maintenance_case", "MaintenanceCaseCreate", property_id=prop.id, unit_id=unit.id, title=title, category=category,
                            description="Termin mit der Mietpartei abgestimmt. Angebot und Fotodokumentation liegen in der Objektakte.", priority="high" if index == 0 else "medium",
                            status="in_progress" if n == 0 else "open", reported_by="Hausbetreuung", assignee="Markus Eberle", contractor=supplier.company_name,
                            due_date=self.today + timedelta(days=index + n + 2), estimated_cost=round(245 + index * 62.5 + n * 85, 2))
                self.create("task", "TaskCreate", property_id=prop.id, unit_id=unit.id, title=("Angebot freigeben – " if n == 0 else "Rückmeldung einholen – ") + prop.name,
                            assignee="Nora Seidel", due_date=self.today + timedelta(days=index + n), priority="high" if index % 3 == 0 else "medium", status="open",
                            description="Unterlagen prüfen und den nächsten Bearbeitungsschritt in der Objektakte dokumentieren.")
            self.create("calendar_event", "CalendarEventCreate", title="Objektbegehung " + prop.name, event_type="inspection", event_date=self.today + timedelta(days=index + 2),
                        event_time="10:30", property_id=prop.id, location=prop.address_line, description="Gemeinschaftsflächen, technische Anlagen und offene Meldungen prüfen.")
            for n in range(2):
                net = round(485 + index * 117.5 + n * 245, 2)
                day = self.today - timedelta(days=7 + index * 2 + n * 14)
                doc = self.document(f"Rechnung HS-{self.today.year}-{index + 1:03d}{n}", [f"Auftraggeber: {prop.name}, {prop.address_line}, {prop.city}",
                                    f"Leistung: {supplier.notes}. Leistungszeitraum {day:%d.%m.%Y}.",
                                    f"Nettobetrag {net:.2f} EUR. Umsatzsteuer 19 %: {net * .19:.2f} EUR. Gesamtbetrag {net * 1.19:.2f} EUR.", "Zahlbar innerhalb von 14 Tagen nach Rechnungseingang."], prop=prop, kind="Rechnung", day=day)
                self.create("invoice", "InvoiceCreate", property_id=prop.id, supplier=supplier.company_name, invoice_date=day, due_date=day + timedelta(days=14),
                            net_amount=net, vat_rate=19, vat_amount=round(net * .19, 2), gross_amount=round(net * 1.19, 2), status="paid" if n else "open")
                if n:
                    self.create("booking", "BookingCreate", account_id=self.accounts[prop.portfolio_id].id, category_id=self.categories[prop.portfolio_id]["Instandhaltung"].id,
                                property_id=prop.id, booking_date=day + timedelta(days=8), amount=-round(net * 1.19, 2), status="booked", payment_text=f"Rechnung {supplier.company_name}", receipt_url=doc.file_url)
            thread = self.create("message_thread", "MessageThreadCreate", subject="Abstimmung Hausbetreuung – " + prop.name, property_id=prop.id, unit_id=unit.id, participant_ids=supplier.id)
            for sender, body in (("Nora Seidel", "Bitte die offenen Punkte vor der nächsten Objektbegehung prüfen und einen Terminvorschlag senden."),
                                 (supplier.company_name, "Die Begehung ist eingeplant. Die Unterlagen und das Angebot sind vorbereitet."),
                                 ("Nora Seidel", "Vielen Dank. Wir geben das Angebot nach Prüfung frei und informieren die Mietparteien rechtzeitig.")):
                self.create("message", "MessageCreate", thread_id=thread.id, sender_name=sender, body=body)

    def billing(self):
        year = self.today.year - 1
        for index, prop in enumerate(self.properties):
            period = self.create("billing_period", "BillingPeriodCreate", property_id=prop.id, label=f"Betriebskosten {year}", start_date=date(year,1,1), end_date=date(year,12,31), status="draft")
            key = self.create("allocation_key", "AllocationKeyCreate", property_id=prop.id, name="Wohnfläche", key_type="area_sqm", description="Verteilung nach der vertraglichen Wohnfläche")
            units = [unit for unit in self.units if unit.property_id == prop.id]
            total_area = sum(unit.area_sqm for unit in units)
            costs = []
            for title, per_sqm, category in (("Wasser und Abwasser", 3.65, "water"), ("Gebäudeversicherung", 4.2, "insurance"),
                                             ("Treppenhausreinigung", 3.8, "cleaning"), ("Müllentsorgung", 2.6, "garbage"), ("Allgemeinstrom", 1.45, "electricity")):
                amount = round(total_area * per_sqm, 2)
                costs.append(self.create("cost_item", "CostItemCreate", billing_period_id=period.id, description=title, amount=amount, allocation_key_id=key.id, cost_category=category))
            for unit in units:
                tenancy = next((row for row in self.contracts if row[2].id == unit.id), None)
                total = round(sum(cost.amount for cost in costs) * unit.area_sqm / total_area, 2)
                advance = round(unit.service_charge_advance * 12, 2) if tenancy else 0
                self.create("utility_statement", "UtilityStatementCreate", billing_period_id=period.id, contract_id=tenancy[0].id if tenancy else None,
                            unit_id=unit.id, party="tenant" if tenancy else "vacancy", usage_start=date(year,1,1), usage_end=date(year,12,31), usage_days=365,
                            total_cost=total, advance_paid=advance, balance=round(total - advance, 2), status="draft",
                            line_items=[{"description":cost.description, "allocated_amount":round(cost.amount * unit.area_sqm / total_area, 2)} for cost in costs])
            self.document(f"Abrechnungsübersicht {year} – {prop.name}", [f"Abrechnungszeitraum 01.01.{year} bis 31.12.{year}",
                          f"Gesamtkosten der erfassten Betriebskosten: {sum(cost.amount for cost in costs):.2f} EUR. Verteilung nach Wohnfläche ({total_area:.1f} m²).",
                          "Die Kostenpositionen und zugehörigen Einzelabrechnungen sind zur sachlichen Prüfung vorbereitet. Heizkosten werden gesondert nach Verbrauch abgerechnet."], prop=prop, kind="Betriebskostenabrechnung")

    def vacancies(self):
        for index, unit in enumerate(unit for unit in self.units if unit.status == "vacant"):
            prop = next(prop for prop in self.properties if prop.id == unit.property_id)
            listing = self.create("listing", "ListingCreate", unit_id=unit.id, title=f"{unit.rooms:g} Zimmer mit Balkon in {prop.city}",
                                  description=f"Helle {unit.area_sqm:.1f} m² große Wohnung im {unit.floor}. Tageslichtbad, Balkon und Kellerraum. Gepflegtes Wohnhaus mit kurzen Wegen ins Zentrum.",
                                  status="draft" if index == 0 else "published", portal="Eigene Vermietung", target_rent=unit.cold_rent,
                                  service_charge=unit.service_charge_advance + unit.heating_advance, available_from=self.today + timedelta(days=20), contact_name="Nora Seidel", contact_email="vermietung@neckarbogen.invalid")
            for n in range(3):
                name = NAMES[-1 - index * 3 - n]
                lead = self.create("lead", "LeadCreate", listing_id=listing.id, unit_id=unit.id, full_name=name, email=email(name), source="Website" if n else "Empfehlung",
                                   status="viewing_scheduled" if n == 2 else "contacted" if n else "new", priority=n, notes="Gewünschter Einzug zum kommenden Monat. Unterlagen werden zur Besichtigung mitgebracht.")
                if n:
                    self.create("viewing_appointment", "ViewingAppointmentCreate", lead_id=lead.id, unit_id=unit.id,
                                scheduled_at=datetime.combine(self.today + timedelta(days=index + n + 2), time(16 + n,30)), agent="Nora Seidel", notes="Treffpunkt am Hauseingang")

    def finish(self):
        self.create("booking", "BookingCreate", account_id=self.accounts[self.portfolios[0].id].id, booking_date=self.today,
                    amount=950, status="open", payment_text=f"Miete {self.today:%m/%Y} · Referenz FZ-2841")
        for index, (title, entity, entity_id) in enumerate([
            ("Neue Rückmeldung zur Hausbetreuung", "property", self.properties[0].id),
            ("Zahlungseingang noch zuzuordnen", "account", self.accounts[self.portfolios[0].id].id),
            ("Besichtigungstermine diese Woche", "property", self.properties[2].id),
            ("Betriebskostenabrechnungen zur Prüfung bereit", "property", self.properties[3].id),
        ]):
            self.create("notification", "NotificationCreate", title=title, notification_type="general", content="Der Vorgang ist zur Bearbeitung vorbereitet.", severity="warning" if index == 1 else "info", entity_type=entity, entity_id=entity_id)
        for label, rate in (("Regelsteuersatz", 19), ("Ermäßigter Steuersatz", 7), ("Steuerfreie Vermietung", 0)):
            self.create("tax_rate", "TaxRateCreate", name=label, rate=rate)
        return {**dict(self.counts), "region":"Baden-Württemberg", "anchor_date":self.today.isoformat(), "dataset_version":1}

    def advanced(self):
        from backend.models_service_contracts import LocationInput, ServiceContractCreateRequest, TariffInput
        from backend.services.service_contracts import create_contract
        for index, prop in enumerate(self.properties):
            start = date(self.today.year - 1, 1, 1)
            create_contract(self.store, ServiceContractCreateRequest(
                contract_type="caretaker" if index % 2 == 0 else "cleaning", title=("Hausbetreuung " if index % 2 == 0 else "Treppenhausreinigung ") + prop.name,
                provider_contact_id=self.suppliers[index].id, contract_number=f"HV-{31000 + index}", customer_number=f"K-{82000 + index}",
                start_date=start, end_date=date(self.today.year + 1, 12, 31), renewal_mode="fixed", renewal_months=12,
                notice_period_value=3, notice_period_unit="month", recoverable=True, cost_category="caretaker" if index % 2 == 0 else "cleaning",
                payment_method="bank_transfer", locations=[LocationInput(property_id=prop.id, valid_from=start)],
                tariff=TariffInput(valid_from=start, label="Leistungspauschale", base_price=round(145 + index * 17.5, 2), base_price_period="month",
                                  advance_amount=round(145 + index * 17.5, 2), advance_interval="monthly", advance_day=15)))
            self.counts["service_contract"] += 1
        if self.owner_id:
            from backend.models_dunning import RunRequest, RunScope
            from backend.services.dunning import create_run, preview
            for index in (2, 8):
                contract = self.contracts[index][0]
                scope = RunScope(contract_id=contract.id, as_of=self.today, letter_date=self.today)
                result = preview(self.store, scope, self.owner_id)
                run = create_run(self.store, RunRequest(**scope.model_dump(), command_key=f"initial-bw-{index:03d}", preview_hash=result["preview_hash"]), self.owner_id)
                self.counts["dunning_case"] += len(run["letters"])


def seed_dataset(store, directory: Path, *, owner_id: str | None = None, today: date | None = None) -> dict:
    from backend.domain.clock import local_today
    if store.list_portfolios():
        raise RuntimeError("Der Datensatz wird nur in einen leeren Bestand geschrieben.")
    dataset = Dataset(store, directory, today or local_today(), owner_id)
    dataset.foundation()
    dataset.operations()
    dataset.billing()
    dataset.vacancies()
    dataset.advanced()
    return dataset.finish()
