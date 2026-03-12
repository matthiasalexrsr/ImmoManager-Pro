"""Seed script: populate ImmoManager Pro with comprehensive demo data.

Usage:
    python seed_data.py              # uses in-memory default (no DB)
    DATABASE_URL=... python seed_data.py  # populates actual database

Can also be imported and called programmatically via seed().
"""

from datetime import date, datetime, timedelta


def seed():
    """Populate the store with comprehensive, realistic demo data."""
    from backend.dependencies import store
    from backend.auth import register_user

    today = date.today()

    # =========================================================================
    # BENUTZER (Users)
    # =========================================================================
    users = {}
    user_configs = [
        ("demo", "demo@immomanager.de", "Max Mustermann", "Demo1234", "eigentuemer"),
        ("verwalter", "sarah.klein@immomanager.de", "Sarah Klein", "Verwalter1", "verwalter"),
        ("techniker", "frank.wagner@immomanager.de", "Frank Wagner", "Techniker1", "techniker"),
    ]
    for username, email, full_name, password, role in user_configs:
        try:
            u = register_user(username=username, email=email, full_name=full_name, password=password, role=role)
            users[username] = u
            print(f"  Benutzer '{username}' erstellt (Passwort: {password}, Rolle: {role})")
        except Exception as exc:
            detail = getattr(exc, "detail", str(exc))
            if "409" in str(getattr(exc, "status_code", "")) or "existiert" in str(detail):
                print(f"  Benutzer '{username}' existiert bereits")
            else:
                print(f"  WARNUNG: Benutzer '{username}' konnte nicht erstellt werden: {detail}")

    # =========================================================================
    # IMPORTS
    # =========================================================================
    from backend.models import (
        AccountCreate,
        BookingCreate,
        BudgetCreate,
        CalendarEventCreate,
        ContactCreate,
        ContractCreate,
        DepositCreate,
        HandoverProtocolCreate,
        DocumentCreate,
        EscalationRuleCreate,
        InsuranceCreate,
        InvoiceCreate,
        LeadCreate,
        ListingCreate,
        MaintenanceCaseCreate,
        MeterCreate,
        MessageCreate,
        MessageThreadCreate,
        NotificationCreate,
        NotificationTemplateCreate,
        PortfolioCreate,
        PropertyCreate,
        ReceivableCreate,
        RentAdjustmentCreate,
        RentChargeCreate,
        StandaloneMeterReadingCreate,
        TaskCreate,
        TaxRateCreate,
        TenantCreate,
        UnitCreate,
        ViewingAppointmentCreate,
    )

    # =========================================================================
    # PORTFOLIOS
    # =========================================================================
    p1 = store.create_portfolio(PortfolioCreate(
        name="Wohnportfolio Berlin",
        description="Wohnimmobilien in Berlin-Mitte, Prenzlauer Berg und Kreuzberg",
        owner_name="Max Mustermann",
        currency="EUR",
        status="active",
    ))
    p2 = store.create_portfolio(PortfolioCreate(
        name="Gewerbeportfolio München",
        description="Büro- und Einzelhandelsflächen in München-Schwabing und Maxvorstadt",
        owner_name="Max Mustermann",
        currency="EUR",
        status="active",
    ))
    p3 = store.create_portfolio(PortfolioCreate(
        name="Mischportfolio Hamburg",
        description="Wohn- und Gewerbeimmobilien in Hamburg-Eppendorf und Winterhude",
        owner_name="Max Mustermann",
        currency="EUR",
        status="active",
    ))
    print(f"  {3} Portfolios erstellt")

    # =========================================================================
    # PROPERTIES (Immobilien)
    # =========================================================================
    # Berlin
    prop_berlin1 = store.create_property(PropertyCreate(
        portfolio_id=p1.id, name="Kastanienallee 42", property_type="residential",
        address_line="Kastanienallee 42", postal_code="10435", city="Berlin", country="DE",
        year_built=1905, living_area_sqm=480.0, plot_area_sqm=320.0,
        purchase_price=2_400_000.0, purchase_date=date(2018, 3, 15),
        market_value=3_200_000.0, valuation_date=date(2025, 6, 1),
    ))
    prop_berlin2 = store.create_property(PropertyCreate(
        portfolio_id=p1.id, name="Schönhauser Allee 78", property_type="residential",
        address_line="Schönhauser Allee 78", postal_code="10439", city="Berlin", country="DE",
        year_built=1952, living_area_sqm=620.0, plot_area_sqm=450.0,
        purchase_price=3_100_000.0, purchase_date=date(2019, 7, 1),
        market_value=4_000_000.0, valuation_date=date(2025, 6, 1),
    ))
    prop_berlin3 = store.create_property(PropertyCreate(
        portfolio_id=p1.id, name="Oranienstraße 15", property_type="residential",
        address_line="Oranienstraße 15", postal_code="10999", city="Berlin", country="DE",
        year_built=1895, living_area_sqm=550.0, plot_area_sqm=280.0,
        purchase_price=2_800_000.0, purchase_date=date(2020, 1, 10),
        market_value=3_600_000.0, valuation_date=date(2025, 6, 1),
    ))
    # München
    prop_muc1 = store.create_property(PropertyCreate(
        portfolio_id=p2.id, name="Leopoldstraße 120", property_type="commercial",
        address_line="Leopoldstraße 120", postal_code="80802", city="München", country="DE",
        year_built=1988, living_area_sqm=1200.0, plot_area_sqm=600.0,
        purchase_price=5_500_000.0, purchase_date=date(2017, 11, 20),
        market_value=7_200_000.0, valuation_date=date(2025, 9, 1),
    ))
    prop_muc2 = store.create_property(PropertyCreate(
        portfolio_id=p2.id, name="Türkenstraße 35", property_type="commercial",
        address_line="Türkenstraße 35", postal_code="80799", city="München", country="DE",
        year_built=1975, living_area_sqm=450.0, plot_area_sqm=300.0,
        purchase_price=2_200_000.0, purchase_date=date(2021, 4, 1),
        market_value=2_900_000.0, valuation_date=date(2025, 9, 1),
    ))
    # Hamburg
    prop_hh1 = store.create_property(PropertyCreate(
        portfolio_id=p3.id, name="Eppendorfer Baum 12", property_type="residential",
        address_line="Eppendorfer Baum 12", postal_code="20249", city="Hamburg", country="DE",
        year_built=1962, living_area_sqm=400.0, plot_area_sqm=350.0,
        purchase_price=1_900_000.0, purchase_date=date(2022, 8, 15),
        market_value=2_300_000.0, valuation_date=date(2025, 9, 1),
    ))
    prop_hh2 = store.create_property(PropertyCreate(
        portfolio_id=p3.id, name="Winterhuder Weg 88", property_type="mixed",
        address_line="Winterhuder Weg 88", postal_code="22299", city="Hamburg", country="DE",
        year_built=2010, living_area_sqm=800.0, plot_area_sqm=500.0,
        purchase_price=4_200_000.0, purchase_date=date(2023, 2, 1),
        market_value=4_600_000.0, valuation_date=date(2025, 9, 1),
    ))
    all_props = [prop_berlin1, prop_berlin2, prop_berlin3, prop_muc1, prop_muc2, prop_hh1, prop_hh2]
    print(f"  {len(all_props)} Objekte erstellt")

    # =========================================================================
    # UNITS (Einheiten)
    # =========================================================================
    units = []
    cold_rents = []
    unit_props = []

    # Kastanienallee 42 – 6 Wohnungen (Altbau)
    for label, area, rooms, rent, floor in [
        ("EG links", 58.0, 2, 680.00, "EG"),
        ("EG rechts", 62.0, 2.5, 720.00, "EG"),
        ("1. OG links", 65.0, 3, 780.00, "1. OG"),
        ("1. OG rechts", 72.0, 3, 840.00, "1. OG"),
        ("2. OG links", 65.0, 3, 760.00, "2. OG"),
        ("2. OG rechts", 72.0, 3, 830.00, "2. OG"),
    ]:
        u = store.create_unit(UnitCreate(
            property_id=prop_berlin1.id, label=label, unit_type="apartment",
            area_sqm=area, rooms=rooms, floor=floor, cold_rent=rent,
            service_charge_advance=180.0, heating_advance=90.0,
        ))
        units.append(u); cold_rents.append(rent); unit_props.append(prop_berlin1)

    # Schönhauser Allee 78 – 5 Wohnungen
    for label, area, rooms, rent, floor in [
        ("EG links", 85.0, 3, 950.00, "EG"),
        ("EG rechts", 90.0, 3.5, 1010.00, "EG"),
        ("1. OG links", 78.0, 3, 880.00, "1. OG"),
        ("1. OG rechts", 110.0, 4, 1250.00, "1. OG"),
        ("2. OG", 95.0, 3.5, 1080.00, "2. OG"),
    ]:
        u = store.create_unit(UnitCreate(
            property_id=prop_berlin2.id, label=label, unit_type="apartment",
            area_sqm=area, rooms=rooms, floor=floor, cold_rent=rent,
            service_charge_advance=200.0, heating_advance=100.0,
        ))
        units.append(u); cold_rents.append(rent); unit_props.append(prop_berlin2)

    # Oranienstraße 15 – 4 Wohnungen + 1 Laden
    for label, area, rooms, rent, floor, utype in [
        ("Laden EG", 120.0, 1, 2800.00, "EG", "retail"),
        ("1. OG links", 70.0, 2.5, 820.00, "1. OG", "apartment"),
        ("1. OG rechts", 75.0, 3, 870.00, "1. OG", "apartment"),
        ("2. OG links", 70.0, 2.5, 800.00, "2. OG", "apartment"),
        ("2. OG rechts", 75.0, 3, 850.00, "2. OG", "apartment"),
    ]:
        u = store.create_unit(UnitCreate(
            property_id=prop_berlin3.id, label=label, unit_type=utype,
            area_sqm=area, rooms=rooms, floor=floor, cold_rent=rent,
            service_charge_advance=220.0 if utype == "retail" else 170.0,
            heating_advance=80.0,
        ))
        units.append(u); cold_rents.append(rent); unit_props.append(prop_berlin3)

    # Leopoldstraße 120 – 3 Gewerbeeinheiten
    for label, area, rent, floor, utype in [
        ("Büro 1. OG", 350.0, 4500.00, "1. OG", "office"),
        ("Büro 2. OG", 320.0, 4200.00, "2. OG", "office"),
        ("Laden EG", 180.0, 3200.00, "EG", "retail"),
    ]:
        u = store.create_unit(UnitCreate(
            property_id=prop_muc1.id, label=label, unit_type=utype,
            area_sqm=area, floor=floor, cold_rent=rent,
            service_charge_advance=500.0, heating_advance=250.0,
        ))
        units.append(u); cold_rents.append(rent); unit_props.append(prop_muc1)

    # Türkenstraße 35 – 2 Gewerbeeinheiten
    for label, area, rent, floor, utype in [
        ("Praxis EG", 180.0, 2400.00, "EG", "office"),
        ("Büro 1. OG", 220.0, 2800.00, "1. OG", "office"),
    ]:
        u = store.create_unit(UnitCreate(
            property_id=prop_muc2.id, label=label, unit_type=utype,
            area_sqm=area, floor=floor, cold_rent=rent,
            service_charge_advance=350.0, heating_advance=180.0,
        ))
        units.append(u); cold_rents.append(rent); unit_props.append(prop_muc2)

    # Eppendorfer Baum 12 – 4 Wohnungen
    for label, area, rooms, rent, floor in [
        ("EG links", 65.0, 2, 750.00, "EG"),
        ("EG rechts", 70.0, 2.5, 800.00, "EG"),
        ("1. OG links", 68.0, 2.5, 780.00, "1. OG"),
        ("1. OG rechts", 72.0, 3, 820.00, "1. OG"),
    ]:
        u = store.create_unit(UnitCreate(
            property_id=prop_hh1.id, label=label, unit_type="apartment",
            area_sqm=area, rooms=rooms, floor=floor, cold_rent=rent,
            service_charge_advance=160.0, heating_advance=85.0,
        ))
        units.append(u); cold_rents.append(rent); unit_props.append(prop_hh1)

    # Winterhuder Weg 88 – 4 Wohnungen + 2 Gewerbe
    for label, area, rooms, rent, floor, utype in [
        ("Laden EG links", 100.0, 1, 2200.00, "EG", "retail"),
        ("Café EG rechts", 80.0, 1, 1800.00, "EG", "retail"),
        ("1. OG links", 85.0, 3, 1050.00, "1. OG", "apartment"),
        ("1. OG rechts", 90.0, 3.5, 1100.00, "1. OG", "apartment"),
        ("2. OG links", 85.0, 3, 1020.00, "2. OG", "apartment"),
        ("2. OG rechts", 90.0, 3.5, 1080.00, "2. OG", "apartment"),
    ]:
        u = store.create_unit(UnitCreate(
            property_id=prop_hh2.id, label=label, unit_type=utype,
            area_sqm=area, rooms=rooms, floor=floor, cold_rent=rent,
            service_charge_advance=250.0 if utype == "retail" else 190.0,
            heating_advance=100.0,
        ))
        units.append(u); cold_rents.append(rent); unit_props.append(prop_hh2)

    print(f"  {len(units)} Einheiten erstellt")

    # =========================================================================
    # TENANTS (Mieter)
    # =========================================================================
    tenant_data = [
        # Berlin tenants
        ("Anna Schmidt", "anna.schmidt@email.de", "+49 30 12345601", "Kastanienallee 10, 10435 Berlin"),
        ("Thomas Weber", "thomas.weber@email.de", "+49 30 12345602", None),
        ("Sabine Fischer", "sabine.fischer@email.de", "+49 30 12345603", None),
        ("Klaus Müller", "klaus.mueller@email.de", "+49 30 12345604", "Danziger Str. 5, 10435 Berlin"),
        ("Maria Becker", "maria.becker@email.de", "+49 30 12345605", None),
        ("Stefan Richter", "stefan.richter@email.de", "+49 30 12345606", None),
        ("Laura Hoffmann", "laura.hoffmann@email.de", "+49 30 12345607", None),
        ("Michael König", "michael.koenig@email.de", "+49 30 12345608", None),
        ("Petra Neumann", "petra.neumann@email.de", "+49 30 12345609", None),
        ("Andreas Braun", "andreas.braun@email.de", "+49 30 12345610", None),
        ("Claudia Zimmermann", "c.zimmermann@email.de", "+49 30 12345611", None),
        # München tenants (Gewerbe)
        ("TechStart GmbH", "info@techstart.de", "+49 89 98765601", "Maximilianstr. 10, 80539 München"),
        ("Designbüro Kreativ", "mail@designbuero-kreativ.de", "+49 89 98765602", None),
        ("Buchhandlung Lesezeit", "kontakt@lesezeit.de", "+49 89 98765603", None),
        ("Dr. med. Eva Hartmann", "praxis@dr-hartmann.de", "+49 89 98765604", None),
        ("Consulting Partners AG", "office@consulting-partners.de", "+49 89 98765605", None),
        # Hamburg tenants
        ("Jürgen Sommer", "juergen.sommer@email.de", "+49 40 11223301", None),
        ("Katrin Vogt", "katrin.vogt@email.de", "+49 40 11223302", None),
        ("Biomarkt Eppendorf GmbH", "info@biomarkt-eppendorf.de", "+49 40 11223303", None),
        ("Café Winterhude", "hallo@cafe-winterhude.de", "+49 40 11223304", None),
        ("Markus Engel", "markus.engel@email.de", "+49 40 11223305", None),
        ("Sophie Lange", "sophie.lange@email.de", "+49 40 11223306", None),
        ("Hassan Al-Rahman", "hassan.alrahman@email.de", "+49 40 11223307", None),
        ("Christina Wolf", "christina.wolf@email.de", "+49 40 11223308", None),
    ]
    tenants = []
    for full_name, email, phone, addr in tenant_data:
        t = store.create_tenant(TenantCreate(
            full_name=full_name, email=email, phone=phone,
            address_line=addr,
            payment_method="SEPA" if tenants.__len__() % 3 == 0 else "Überweisung",
        ))
        tenants.append(t)
    print(f"  {len(tenants)} Mieter erstellt")

    # =========================================================================
    # CONTRACTS (Mietverträge) – assign tenants to units
    # =========================================================================
    contracts = []
    # Map: unit_index -> tenant_index (leave some units vacant for listings)
    assignments = [
        # Kastanienallee (units 0-5, tenants 0-4, unit 5 vacant)
        (0, 0), (1, 1), (2, 2), (3, 3), (4, 4),
        # Schönhauser Allee (units 6-10, tenants 5-8, unit 10 vacant)
        (6, 5), (7, 6), (8, 7), (9, 8),
        # Oranienstraße (units 11-15, tenants 9-10 + unit 11 retail)
        (11, 9), (12, 10), (13, 9),
        # Leopoldstraße (units 16-18, tenants 11-13)
        (16, 11), (17, 12), (18, 13),
        # Türkenstraße (units 19-20, tenants 14-15)
        (19, 14), (20, 15),
        # Eppendorfer Baum (units 21-24, tenants 16-17, 2 vacant)
        (21, 16), (22, 17),
        # Winterhuder Weg (units 25-30, tenants 18-23)
        (25, 18), (26, 19), (27, 20), (28, 21), (29, 22), (30, 23),
    ]

    for idx, (unit_idx, tenant_idx) in enumerate(assignments):
        prop = unit_props[unit_idx]
        start = today - timedelta(days=365 + idx * 45)
        c = store.create_contract(ContractCreate(
            contract_number=f"MV-{start.year}-{idx + 1:03d}",
            property_id=prop.id,
            unit_id=units[unit_idx].id,
            tenant_id=tenants[tenant_idx].id,
            start_date=start,
            deposit_amount=cold_rents[unit_idx] * 3,
            notice_period="3 Monate",
            status="active",
        ))
        contracts.append(c)
    print(f"  {len(contracts)} Verträge erstellt")

    # =========================================================================
    # ACCOUNTS (Konten)
    # =========================================================================
    acc_berlin = store.create_account(AccountCreate(
        portfolio_id=p1.id, name="Mietkonto Berlin", account_type="bank",
        bank_name="Deutsche Bank", iban="DE89 3704 0044 0532 0130 00", bic="COBADEFFXXX",
        opening_balance=50000.0, balance=127450.0,
    ))
    acc_muc = store.create_account(AccountCreate(
        portfolio_id=p2.id, name="Mietkonto München", account_type="bank",
        bank_name="HypoVereinsbank", iban="DE27 1007 0024 0123 4567 89", bic="HYVEDEMM",
        opening_balance=80000.0, balance=195300.0,
    ))
    acc_hh = store.create_account(AccountCreate(
        portfolio_id=p3.id, name="Mietkonto Hamburg", account_type="bank",
        bank_name="Hamburger Sparkasse", iban="DE45 2005 0550 1234 5678 90", bic="HASPDEHHXXX",
        opening_balance=30000.0, balance=68200.0,
    ))
    acc_instand = store.create_account(AccountCreate(
        portfolio_id=p1.id, name="Instandhaltungsrücklage Berlin", account_type="savings",
        bank_name="Deutsche Bank", iban="DE12 3704 0044 0532 0131 01", bic="COBADEFFXXX",
        opening_balance=25000.0, balance=42300.0,
    ))
    print(f"  {4} Konten erstellt")

    # =========================================================================
    # BOOKINGS (Buchungen) – last 6 months of rent payments
    # =========================================================================
    booking_count = 0
    for month_offset in range(6):
        d = today.replace(day=3) - timedelta(days=30 * month_offset)
        for i, contract in enumerate(contracts):
            unit_idx = assignments[i][0]
            tenant_idx = assignments[i][1]
            rent = cold_rents[unit_idx]
            total = rent + 180 + 90  # rent + service + heating approx
            acc = acc_berlin if unit_props[unit_idx] in [prop_berlin1, prop_berlin2, prop_berlin3] else (
                acc_muc if unit_props[unit_idx] in [prop_muc1, prop_muc2] else acc_hh
            )
            store.create_booking(BookingCreate(
                account_id=acc.id,
                booking_date=d,
                amount=total,
                payment_text=f"Miete {d.strftime('%m/%Y')} – {tenants[tenant_idx].full_name}",
                property_id=unit_props[unit_idx].id,
                unit_id=units[unit_idx].id,
                tenant_id=tenants[tenant_idx].id,
            ))
            booking_count += 1
    # Some additional expense bookings
    expense_bookings = [
        (acc_berlin, today - timedelta(days=15), -2850.0, "Heizungswartung Kastanienallee – Fa. Wärmemeister"),
        (acc_berlin, today - timedelta(days=45), -1200.0, "Treppenhausreinigung Q4/2025 – Reinigungsdienst Sauber"),
        (acc_berlin, today - timedelta(days=60), -4500.0, "Dachreparatur Schönhauser Allee – Dachdeckerei Hoch"),
        (acc_muc, today - timedelta(days=20), -3200.0, "Aufzugswartung Leopoldstraße – Schindler AG"),
        (acc_muc, today - timedelta(days=50), -890.0, "Grundsteuer Q1/2026 München"),
        (acc_hh, today - timedelta(days=10), -1650.0, "Gartenpflege Winterhuder Weg – GaLaBau Nord"),
        (acc_hh, today - timedelta(days=30), -750.0, "Schädlingsbekämpfung Eppendorfer Baum"),
        (acc_instand, today - timedelta(days=5), -8500.0, "Fassadensanierung Anteil – Kastanienallee"),
    ]
    for acc, bdate, amount, text in expense_bookings:
        store.create_booking(BookingCreate(
            account_id=acc.id, booking_date=bdate, amount=amount, payment_text=text,
        ))
        booking_count += 1
    print(f"  {booking_count} Buchungen erstellt")

    # =========================================================================
    # MAINTENANCE CASES (Wartungsfälle)
    # =========================================================================
    maint_cases = [
        (prop_berlin1, units[4], "Heizungsausfall 2. OG links",
         "Heizkörper im Wohnzimmer wird nicht warm. Thermostat reagiert nicht. Mieter friert seit 2 Tagen.",
         "heating", "high", "open", "Maria Becker", "Frank Wagner", today + timedelta(days=2), 350.0),
        (prop_berlin2, units[6], "Wasserschaden Badezimmer EG links",
         "Feuchtigkeit an der Decke im Badezimmer. Möglicher Rohrbruch oberhalb. Schimmelgefahr.",
         "plumbing", "urgent", "in_progress", "Stefan Richter", "Frank Wagner", today - timedelta(days=1), 2200.0),
        (prop_berlin1, None, "Treppenhausbeleuchtung defekt",
         "Mehrere Leuchtmittel im Treppenhaus ausgefallen. Sicherheitsrisiko bei Dunkelheit.",
         "electrical", "medium", "open", "Anna Schmidt", None, today + timedelta(days=7), 180.0),
        (prop_muc1, None, "Aufzug-Wartung fällig",
         "Jährliche Aufzugswartung gemäß BetrSichV steht an. TÜV-Prüfung erforderlich.",
         "elevator", "medium", "open", None, None, today + timedelta(days=14), 1800.0),
        (prop_berlin3, units[12], "Fenster undicht – 1. OG rechts",
         "Zugluft durch Wohnzimmerfenster. Dichtung porös. Mieter klagt über Heizkosten.",
         "windows", "medium", "open", "Claudia Zimmermann", None, today + timedelta(days=21), 450.0),
        (prop_hh2, units[25], "Schaufensterscheibe gesprungen – Laden EG",
         "Riss in der Schaufensterscheibe. Muss zeitnah ausgetauscht werden.",
         "glass", "high", "in_progress", "Biomarkt Eppendorf GmbH", "Frank Wagner", today + timedelta(days=3), 1600.0),
        (prop_muc2, units[19], "Klimaanlage defekt – Praxis EG",
         "Klimaanlage kühlt nicht mehr. Kompressor-Geräusche. Praxisbetrieb eingeschränkt.",
         "hvac", "high", "open", "Dr. med. Eva Hartmann", None, today + timedelta(days=5), 2800.0),
        (prop_hh1, None, "Klingelanlage Austausch",
         "Sprechanlage funktioniert nur sporadisch. Komplettaustausch empfohlen.",
         "electrical", "low", "open", "Jürgen Sommer", None, today + timedelta(days=30), 3500.0),
        (prop_berlin2, units[9], "Schimmel im Bad – 1. OG rechts",
         "Schwarzer Schimmel an der Decke und an den Fliesenfugen. Lüftungsverhalten geprüft.",
         "mold", "high", "in_progress", "Michael König", "Frank Wagner", today - timedelta(days=3), 900.0),
        (prop_muc1, units[18], "Rollladen klemmt – Laden EG",
         "Elektrischer Rollladen an der Eingangstür fährt nicht mehr hoch. Motor defekt.",
         "mechanical", "medium", "completed", "Buchhandlung Lesezeit", "Frank Wagner", today - timedelta(days=10), 650.0),
    ]
    for prop, unit, title, desc, cat, prio, status, reporter, assignee, due, cost in maint_cases:
        store.create_maintenance_case(MaintenanceCaseCreate(
            property_id=prop.id, unit_id=unit.id if unit else None,
            title=title, description=desc, category=cat, priority=prio, status=status,
            reported_by=reporter, assignee=assignee, due_date=due, estimated_cost=cost,
        ))
    print(f"  {len(maint_cases)} Wartungsfälle erstellt")

    # =========================================================================
    # TASKS (Aufgaben)
    # =========================================================================
    task_data = [
        ("Nebenkostenabrechnung 2025 erstellen",
         "Betriebskostenabrechnung für alle Mieter im Portfolio Berlin fertigstellen. Frist: 31.12.2026.",
         "high", "open", today + timedelta(days=30), prop_berlin1.id),
        ("Mieterhöhung prüfen – Kastanienallee",
         "Ortsübliche Vergleichsmiete prüfen (Mietspiegel 2025). Ggf. Mieterhöhungsverlangen für EG und 1. OG vorbereiten.",
         "medium", "open", today + timedelta(days=60), prop_berlin1.id),
        ("Rauchmelder-Prüfung Schönhauser Allee",
         "Jährliche Funktionsprüfung aller Rauchmelder dokumentieren. Wartungsprotokoll erstellen.",
         "medium", "in_progress", today + timedelta(days=14), prop_berlin2.id),
        ("Versicherungspolice verlängern – Leopoldstraße",
         "Gebäudeversicherung für Leopoldstraße 120 läuft Ende Juni aus. Angebote vergleichen.",
         "high", "open", today + timedelta(days=45), prop_muc1.id),
        ("Mietvertrag verlängern – TechStart GmbH",
         "Gewerbemietvertrag läuft in 6 Monaten aus. Gespräch zur Verlängerung planen.",
         "medium", "open", today + timedelta(days=90), prop_muc1.id),
        ("Hausverwalterbericht Q1/2026 erstellen",
         "Quartalsbericht für alle drei Portfolios erstellen inkl. Leerstandsquote, Mieteinnahmen, Instandhaltungskosten.",
         "high", "open", today + timedelta(days=20), None),
        ("Grundsteuer-Bescheide prüfen",
         "Neue Grundsteuerbescheide für Berlin und Hamburg prüfen und ggf. Einspruch einlegen.",
         "medium", "open", today + timedelta(days=40), None),
        ("Energieausweis erneuern – Oranienstraße",
         "Energieausweis läuft im September ab. Energieberater beauftragen.",
         "low", "open", today + timedelta(days=120), prop_berlin3.id),
        ("Mieterkommunikation: Modernisierungsankündigung",
         "Mieter in der Kastanienallee über geplante Fassadensanierung informieren (§555c BGB).",
         "high", "in_progress", today + timedelta(days=7), prop_berlin1.id),
        ("SEPA-Lastschriften aktualisieren",
         "Neue Bankverbindung von 3 Mietern in das System übernehmen.",
         "low", "completed", today - timedelta(days=5), None),
        ("Wohnungsübergabe planen – 2. OG rechts Kastanienallee",
         "Einzugsprotokoll für neuen Mieter vorbereiten. Schlüsselübergabe koordinieren.",
         "medium", "open", today + timedelta(days=10), prop_berlin1.id),
        ("Winterdienst beauftragen – Hamburg",
         "Winterdienstvertrag für Eppendorfer Baum und Winterhuder Weg abschließen.",
         "medium", "completed", today - timedelta(days=30), None),
    ]
    for title, desc, prio, status, due, prop_id in task_data:
        store.create_task(TaskCreate(
            title=title, description=desc, priority=prio, status=status,
            due_date=due, property_id=prop_id,
            assignee="Sarah Klein" if status != "completed" else "Max Mustermann",
        ))
    print(f"  {len(task_data)} Aufgaben erstellt")

    # =========================================================================
    # DOCUMENTS (Dokumente)
    # =========================================================================
    doc_data = [
        (prop_berlin1.id, None, None, "Grundbuchauszug Kastanienallee 42", "grundbuch", date(2024, 3, 15)),
        (prop_berlin1.id, None, None, "Energieausweis 2022", "energieausweis", date(2022, 8, 1)),
        (prop_berlin2.id, None, None, "Teilungserklärung Schönhauser Allee 78", "teilungserklaerung", date(2019, 7, 1)),
        (prop_muc1.id, None, None, "Baugenehmigung Aufzugserneuerung", "genehmigung", date(2023, 11, 15)),
        (prop_berlin1.id, units[0].id, contracts[0].id if contracts else None, "Mietvertrag Anna Schmidt", "mietvertrag", contracts[0].start_date if contracts else today),
        (prop_hh2.id, None, None, "Flurkarte Winterhuder Weg 88", "flurkarte", date(2023, 2, 1)),
        (prop_muc2.id, None, None, "Gebäudeversicherungspolice Türkenstraße", "versicherung", date(2024, 1, 1)),
        (prop_berlin3.id, None, None, "Denkmalschutz-Bescheid Oranienstraße", "bescheid", date(2020, 5, 20)),
        (None, None, None, "Hausverwalterbericht Q4/2025", "bericht", date(2026, 1, 15)),
        (prop_hh1.id, None, None, "Protokoll Eigentümerversammlung 2025", "protokoll", date(2025, 10, 5)),
    ]
    for prop_id, unit_id, contract_id, title, doc_type, doc_date in doc_data:
        store.create_document(DocumentCreate(
            property_id=prop_id, unit_id=unit_id, contract_id=contract_id,
            title=title, document_type=doc_type, document_date=doc_date,
            file_url=f"/uploads/demo/{doc_type}_{doc_date.isoformat()}.pdf",
        ))
    print(f"  {len(doc_data)} Dokumente erstellt")

    # =========================================================================
    # INVOICES (Rechnungen)
    # =========================================================================
    invoice_data = [
        (prop_berlin1.id, "Wärmemeister GmbH", today - timedelta(days=15), 2394.96, 19.0, "paid"),
        (prop_berlin2.id, "Dachdeckerei Hoch & Söhne", today - timedelta(days=45), 3781.51, 19.0, "paid"),
        (prop_berlin1.id, "Reinigungsdienst Sauber", today - timedelta(days=10), 1008.40, 19.0, "open"),
        (prop_muc1.id, "Schindler Aufzüge AG", today - timedelta(days=20), 2689.08, 19.0, "paid"),
        (prop_muc2.id, "Kältetechnik Müller", today - timedelta(days=5), 2352.10, 19.0, "open"),
        (prop_hh2.id, "GaLaBau Nord GmbH", today - timedelta(days=10), 1386.55, 19.0, "open"),
        (prop_berlin3.id, "Glaserei Klarsicht", today - timedelta(days=2), 1344.54, 19.0, "open"),
        (prop_hh1.id, "Schädlingsbekämpfung Nord", today - timedelta(days=30), 630.25, 19.0, "paid"),
        (prop_berlin1.id, "Fassadenbau Berlin GmbH", today - timedelta(days=3), 42016.81, 19.0, "open"),
        (prop_muc1.id, "Stadt München – Grundsteuer", today - timedelta(days=50), 890.00, 0.0, "paid"),
    ]
    for prop_id, supplier, inv_date, net, vat_rate, status in invoice_data:
        vat_amount = round(net * vat_rate / 100, 2)
        gross = round(net + vat_amount, 2)
        store.create_invoice(InvoiceCreate(
            property_id=prop_id, supplier=supplier, invoice_date=inv_date,
            due_date=inv_date + timedelta(days=30),
            net_amount=net, vat_rate=vat_rate, vat_amount=vat_amount, gross_amount=gross,
            status=status,
        ))
    print(f"  {len(invoice_data)} Rechnungen erstellt")

    # =========================================================================
    # CALENDAR EVENTS (Kalendereinträge)
    # =========================================================================
    cal_events = [
        ("Eigentümerversammlung Berlin", "meeting", today + timedelta(days=21), "14:00",
         "Konferenzraum Schönhauser Allee", "Max Mustermann, Sarah Klein", prop_berlin2.id),
        ("Heizungswartung Kastanienallee", "maintenance", today + timedelta(days=5), "09:00",
         "Kastanienallee 42", "Frank Wagner, Wärmemeister GmbH", prop_berlin1.id),
        ("Besichtigung 2. OG rechts", "viewing", today + timedelta(days=3), "15:30",
         "Kastanienallee 42, 2. OG rechts", "Sarah Klein, Interessent Müller", prop_berlin1.id),
        ("TÜV-Aufzugsprüfung Leopoldstraße", "inspection", today + timedelta(days=14), "10:00",
         "Leopoldstraße 120", "Frank Wagner, TÜV Süd", prop_muc1.id),
        ("Mietvertragsgespräch TechStart", "meeting", today + timedelta(days=10), "11:00",
         "Leopoldstraße 120, Büro 1. OG", "Max Mustermann, Hr. Berger (TechStart)", prop_muc1.id),
        ("Nebenkostenabrechnung Frist", "deadline", today + timedelta(days=285), None,
         None, None, None),
        ("Rauchmelderprüfung Hamburg", "maintenance", today + timedelta(days=28), "08:00",
         "Eppendorfer Baum 12", "Frank Wagner", prop_hh1.id),
        ("Quartalsbericht Q1 erstellen", "deadline", today + timedelta(days=20), None,
         None, "Sarah Klein", None),
        ("Energieberater-Termin Oranienstraße", "inspection", today + timedelta(days=35), "13:00",
         "Oranienstraße 15", "Energieberatung Berlin, Sarah Klein", prop_berlin3.id),
        ("Schlüsselübergabe Neuer Mieter", "handover", today + timedelta(days=10), "16:00",
         "Kastanienallee 42, 2. OG rechts", "Sarah Klein, neuer Mieter", prop_berlin1.id),
    ]
    for title, etype, edate, etime, loc, parts, prop_id in cal_events:
        store.create_calendar_event(CalendarEventCreate(
            title=title, event_type=etype, event_date=edate, event_time=etime,
            location=loc, participants=parts, property_id=prop_id,
        ))
    print(f"  {len(cal_events)} Kalendereinträge erstellt")

    # =========================================================================
    # DEPOSITS (Kautionen)
    # =========================================================================
    for i, contract in enumerate(contracts):
        unit_idx = assignments[i][0]
        amount = cold_rents[unit_idx] * 3
        store.create_deposit(DepositCreate(
            contract_id=contract.id,
            amount=amount,
            status="held",
            held_date=contract.start_date + timedelta(days=5),
            notes=f"Kaution für Vertrag {contract.contract_number}",
        ))
    print(f"  {len(contracts)} Kautionen erstellt")

    # =========================================================================
    # NOTIFICATIONS (Benachrichtigungen)
    # =========================================================================
    notif_data = [
        ("overdue_payment", "Zahlungsrückstand: Markus Engel", "Miete für März 2026 ist seit 5 Tagen überfällig (1.020,00 €).", "warning"),
        ("contract_expiry", "Vertrag läuft aus: TechStart GmbH", "Der Gewerbemietvertrag MV-2023-014 läuft in 6 Monaten aus.", "info"),
        ("maintenance", "Dringende Reparatur: Wasserschaden", "Wasserschaden im Badezimmer EG links, Schönhauser Allee. Sofortmaßnahmen erforderlich.", "error"),
        ("task_due", "Fällige Aufgabe: Rauchmelderprüfung", "Die Rauchmelderprüfung Schönhauser Allee ist in 14 Tagen fällig.", "warning"),
        ("general", "Grundsteuerbescheid erhalten", "Neue Grundsteuerbescheide für Berlin-Objekte eingetroffen. Bitte prüfen.", "info"),
        ("overdue_payment", "Teilzahlung eingegangen: Sophie Lange", "Sophie Lange hat 800,00 € von 1.080,00 € überwiesen. Differenz: 280,00 €.", "warning"),
        ("maintenance", "Wartung abgeschlossen: Rollladen", "Rollladen im Laden EG Leopoldstraße wurde repariert. Kosten: 650,00 €.", "info"),
        ("contract_expiry", "Mieterhöhung möglich", "Für 5 Wohnungen in der Kastanienallee ist eine Mieterhöhung nach Mietspiegel möglich.", "info"),
    ]
    for ntype, title, content, severity in notif_data:
        store.create_notification(NotificationCreate(
            notification_type=ntype, title=title, content=content, severity=severity,
        ))
    print(f"  {len(notif_data)} Benachrichtigungen erstellt")

    # =========================================================================
    # CONTACTS (Kontakte)
    # =========================================================================
    contact_data = [
        ("supplier", "Hans", "Wärmemeister", "Wärmemeister GmbH", "info@waermemeister.de", "+49 30 5551001", "Heizungstr. 5", "10115", "Berlin"),
        ("supplier", "Karl", "Hoch", "Dachdeckerei Hoch & Söhne", "info@dach-hoch.de", "+49 30 5551002", "Dachstr. 12", "10245", "Berlin"),
        ("supplier", "Maria", "Sauber", "Reinigungsdienst Sauber", "kontakt@sauber-berlin.de", "+49 30 5551003", "Putzweg 8", "10369", "Berlin"),
        ("supplier", None, None, "Schindler Aufzüge AG", "service@schindler.de", "+49 89 5552001", "Liftstr. 20", "80331", "München"),
        ("supplier", "Thomas", "Müller", "Kältetechnik Müller", "info@kaeltetechnik-mueller.de", "+49 89 5552002", "Kühlweg 3", "80469", "München"),
        ("supplier", None, None, "GaLaBau Nord GmbH", "info@galabau-nord.de", "+49 40 5553001", "Gartenstr. 15", "22301", "Hamburg"),
        ("manager", "Sarah", "Klein", None, "sarah.klein@immomanager.de", "+49 30 9990001", "Verwaltungsstr. 1", "10117", "Berlin"),
        ("owner", "Max", "Mustermann", None, "max.mustermann@email.de", "+49 170 1234567", "Eigenheimweg 42", "10115", "Berlin"),
        ("supplier", "Peter", "Klarsicht", "Glaserei Klarsicht", "info@glaserei-klarsicht.de", "+49 30 5551004", "Glasweg 7", "10997", "Berlin"),
        ("supplier", None, None, "Fassadenbau Berlin GmbH", "office@fassadenbau-berlin.de", "+49 30 5551005", "Fassadenstr. 22", "10961", "Berlin"),
    ]
    for ctype, first, last, company, email, phone, street, zip_code, city in contact_data:
        store.create_contact(ContactCreate(
            contact_type=ctype, first_name=first, last_name=last, company_name=company,
            email=email, phone=phone, street=street, zip_code=zip_code, city=city, country="DE",
        ))
    print(f"  {len(contact_data)} Kontakte erstellt")

    # =========================================================================
    # INSURANCES (Versicherungen)
    # =========================================================================
    ins_data = [
        (prop_berlin1.id, "building", "Allianz Versicherung", "GV-2024-BER-001", 3200000.0, 1850.0, date(2024, 1, 1), date(2026, 12, 31)),
        (prop_berlin1.id, "liability", "Allianz Versicherung", "HV-2024-BER-001", 5000000.0, 420.0, date(2024, 1, 1), date(2026, 12, 31)),
        (prop_berlin2.id, "building", "HDI Versicherung", "GV-2024-BER-002", 4000000.0, 2100.0, date(2024, 1, 1), date(2026, 12, 31)),
        (prop_berlin3.id, "building", "Allianz Versicherung", "GV-2024-BER-003", 3600000.0, 1950.0, date(2024, 1, 1), date(2026, 12, 31)),
        (prop_muc1.id, "building", "Bayerische Versicherung", "GV-2024-MUC-001", 7200000.0, 3200.0, date(2024, 1, 1), date(2026, 6, 30)),
        (prop_muc1.id, "liability", "Bayerische Versicherung", "HV-2024-MUC-001", 10000000.0, 680.0, date(2024, 1, 1), date(2026, 6, 30)),
        (prop_muc2.id, "building", "Bayerische Versicherung", "GV-2024-MUC-002", 2900000.0, 1400.0, date(2024, 1, 1), date(2026, 12, 31)),
        (prop_hh1.id, "building", "HanseMerkur", "GV-2024-HH-001", 2300000.0, 1250.0, date(2024, 7, 1), date(2027, 6, 30)),
        (prop_hh2.id, "building", "HanseMerkur", "GV-2024-HH-002", 4600000.0, 2400.0, date(2024, 7, 1), date(2027, 6, 30)),
        (prop_hh2.id, "contents", "HanseMerkur", "IV-2024-HH-001", 500000.0, 380.0, date(2024, 7, 1), date(2027, 6, 30)),
    ]
    for prop_id, itype, provider, policy, coverage, premium, start, end in ins_data:
        store.create_insurance(InsuranceCreate(
            property_id=prop_id, insurance_type=itype, provider=provider,
            policy_number=policy, coverage_amount=coverage, premium_amount=premium,
            premium_interval="annual", start_date=start, end_date=end, status="active",
        ))
    print(f"  {len(ins_data)} Versicherungen erstellt")

    # =========================================================================
    # TAX RATES (Steuersätze)
    # =========================================================================
    tax_rates = [
        ("Regelsteuersatz", 19.0, "Normaler Umsatzsteuersatz Deutschland", True),
        ("Ermäßigter Satz", 7.0, "Ermäßigter Umsatzsteuersatz (z.B. Bücher, Lebensmittel)", False),
        ("Steuerfrei", 0.0, "Umsatzsteuerbefreit (z.B. Wohnraumvermietung §4 Nr. 12a UStG)", False),
    ]
    for name, rate, desc, is_default in tax_rates:
        store.create_tax_rate(TaxRateCreate(
            name=name, rate=rate, description=desc, is_default=is_default,
            valid_from=date(2024, 1, 1),
        ))
    print(f"  {len(tax_rates)} Steuersätze erstellt")

    # =========================================================================
    # RENT ADJUSTMENTS (Mietanpassungen)
    # =========================================================================
    if len(contracts) >= 5:
        adj_data = [
            (contracts[0].id, "index", today - timedelta(days=180), 680.0, 720.0, 5.88, "Indexanpassung gem. VPI 2024"),
            (contracts[1].id, "index", today - timedelta(days=180), 690.0, 720.0, 4.35, "Indexanpassung gem. VPI 2024"),
            (contracts[4].id, "stepped", today - timedelta(days=90), 740.0, 760.0, 2.70, "Staffelmieterhöhung lt. Vertrag"),
            (contracts[6].id, "index", today - timedelta(days=120), 850.0, 880.0, 3.53, "Indexanpassung gem. VPI 2024"),
        ]
        for contract_id, adj_type, eff_date, prev, new, pct, notes in adj_data:
            store.create_rent_adjustment(RentAdjustmentCreate(
                contract_id=contract_id, adjustment_type=adj_type, effective_date=eff_date,
                previous_rent=prev, new_rent=new, increase_percent=pct, notes=notes, status="approved",
            ))
        print(f"  {len(adj_data)} Mietanpassungen erstellt")

    # =========================================================================
    # BUDGETS (Budgets)
    # =========================================================================
    budget_data = [
        (prop_berlin1.id, 2026, "maintenance", 15000.0, 3050.0, "Laufende Instandhaltung inkl. Fassade"),
        (prop_berlin1.id, 2026, "operating_costs", 8000.0, 1200.0, "Betriebskosten (Reinigung, Garten, Versicherung)"),
        (prop_berlin1.id, 2026, "reserve", 12000.0, 8500.0, "Instandhaltungsrücklage"),
        (prop_berlin2.id, 2026, "maintenance", 10000.0, 4500.0, "Inkl. Dachsanierung"),
        (prop_berlin2.id, 2026, "operating_costs", 6000.0, 1200.0, None),
        (prop_muc1.id, 2026, "maintenance", 20000.0, 6400.0, "Aufzug, Fassade, Allgemeinbereiche"),
        (prop_muc1.id, 2026, "renovation", 50000.0, 0.0, "Geplante Sanierung Büro 2. OG"),
        (prop_hh2.id, 2026, "maintenance", 12000.0, 2400.0, "Garten, Winterdienst, lfd. Reparaturen"),
        (prop_hh2.id, 2026, "operating_costs", 9000.0, 1650.0, None),
    ]
    for prop_id, year, cat, planned, actual, notes in budget_data:
        store.create_budget(BudgetCreate(
            property_id=prop_id, year=year, category=cat,
            planned_amount=planned, actual_amount=actual, notes=notes,
        ))
    print(f"  {len(budget_data)} Budgets erstellt")

    # =========================================================================
    # LISTINGS (Inserate) – for vacant units
    # =========================================================================
    # unit 5 = Kastanienallee 2. OG rechts (vacant)
    # unit 10 = Schönhauser 2. OG (vacant)
    # units 23, 24 = Eppendorfer Baum 1. OG (vacant)
    listing_data = [
        (units[5], "Charmante 3-Zimmer-Altbauwohnung in Prenzlauer Berg",
         "Lichtdurchflutete Altbauwohnung mit Stuck, Dielen und Balkon zum ruhigen Innenhof. "
         "Zentrale Lage nahe Kastanienallee. Bezugsfrei ab sofort.",
         "ImmoScout24", 830.0, 180.0, today + timedelta(days=14)),
        (units[10], "Geräumige 3,5-Zimmer-Wohnung Schönhauser Allee",
         "Helle Wohnung im 2. OG mit Blick auf die Allee. Laminat, Einbauküche, Balkon. "
         "Gute Anbindung U2/Tram. Sofort verfügbar.",
         "ImmoScout24", 1100.0, 200.0, today),
        (units[23], "2,5-Zimmer in Eppendorf – ruhige Lage",
         "Gemütliche Wohnung in gepflegtem Mehrfamilienhaus. Nähe UKE und Eppendorfer Park. "
         "Keller, Fahrradraum. Ab 01.05.2026.",
         "ImmobilienScout24", 800.0, 160.0, today + timedelta(days=50)),
    ]
    listings = []
    for unit, title, desc, portal, rent, sc, avail in listing_data:
        l = store.create_listing(ListingCreate(
            unit_id=unit.id, title=title, description=desc, portal=portal,
            target_rent=rent, service_charge=sc, available_from=avail,
            status="active", contact_name="Sarah Klein", contact_email="sarah.klein@immomanager.de",
        ))
        listings.append(l)
    print(f"  {len(listing_data)} Inserate erstellt")

    # =========================================================================
    # LEADS (Interessenten)
    # =========================================================================
    lead_data = [
        (listings[0].id, units[5].id, "Julia Neumann", "julia.neumann@email.de", "+49 176 5551001", "ImmoScout24", "new"),
        (listings[0].id, units[5].id, "Robert Schwarz", "robert.schwarz@email.de", "+49 151 5551002", "ImmoScout24", "contacted"),
        (listings[0].id, units[5].id, "Elif Yilmaz", "elif.yilmaz@email.de", "+49 172 5551003", "Empfehlung", "qualified"),
        (listings[1].id, units[10].id, "Daniel Koch", "daniel.koch@email.de", "+49 160 5551004", "ImmoScout24", "new"),
        (listings[1].id, units[10].id, "Sandra Meier", "sandra.meier@email.de", "+49 175 5551005", "ImmoScout24", "viewing_scheduled"),
        (listings[2].id, units[23].id, "Lars Petersen", "lars.petersen@email.de", "+49 179 5551006", "ImmobilienScout24", "new"),
    ]
    leads = []
    for listing_id, unit_id, name, email, phone, source, status in lead_data:
        l = store.create_lead(LeadCreate(
            listing_id=listing_id, unit_id=unit_id, full_name=name,
            email=email, phone=phone, source=source, status=status,
        ))
        leads.append(l)
    print(f"  {len(lead_data)} Interessenten erstellt")

    # =========================================================================
    # VIEWING APPOINTMENTS (Besichtigungstermine)
    # =========================================================================
    if leads:
        viewing_data = [
            (leads[2].id, units[5].id, datetime.combine(today + timedelta(days=3), datetime.min.time().replace(hour=15, minute=30)), "scheduled", "Sarah Klein"),
            (leads[4].id, units[10].id, datetime.combine(today + timedelta(days=5), datetime.min.time().replace(hour=10, minute=0)), "scheduled", "Sarah Klein"),
            (leads[1].id, units[5].id, datetime.combine(today - timedelta(days=2), datetime.min.time().replace(hour=14, minute=0)), "completed", "Sarah Klein"),
        ]
        for lead_id, unit_id, scheduled, status, agent in viewing_data:
            store.create_viewing_appointment(ViewingAppointmentCreate(
                lead_id=lead_id, unit_id=unit_id, scheduled_at=scheduled,
                status=status, agent=agent,
            ))
        print(f"  {len(viewing_data)} Besichtigungstermine erstellt")

    # =========================================================================
    # METERS (Zähler) & READINGS
    # =========================================================================
    meters = []
    meter_configs = [
        # Kastanienallee – Zähler für erste 3 Wohnungen
        (units[0].id, "electricity", "ELK-001-2020", "Keller, Zählerschrank links", date(2020, 5, 1)),
        (units[0].id, "cold_water", "WK-001-2020", "Keller, Wasserverteilung", date(2020, 5, 1)),
        (units[0].id, "heating", "HZ-001-2020", "Keller, Heizraum", date(2020, 5, 1)),
        (units[1].id, "electricity", "ELK-002-2020", "Keller, Zählerschrank rechts", date(2020, 5, 1)),
        (units[1].id, "cold_water", "WK-002-2020", "Keller, Wasserverteilung", date(2020, 5, 1)),
        (units[2].id, "electricity", "ELK-003-2019", "Keller, Zählerschrank links", date(2019, 3, 1)),
        (units[2].id, "gas", "GAS-003-2019", "Keller, Gaszähler", date(2019, 3, 1)),
        # Hamburg – Zähler
        (units[21].id, "electricity", "ELK-HH-001", "Keller, Zählerschrank", date(2022, 8, 15)),
        (units[21].id, "cold_water", "WK-HH-001", "Keller", date(2022, 8, 15)),
        (units[22].id, "electricity", "ELK-HH-002", "Keller, Zählerschrank", date(2022, 8, 15)),
    ]
    for unit_id, mtype, serial, location, inst_date in meter_configs:
        m = store.create_meter(MeterCreate(
            unit_id=unit_id, meter_type=mtype, serial_number=serial,
            location=location, installation_date=inst_date,
            next_inspection=inst_date + timedelta(days=365*6), is_active=True,
        ))
        meters.append(m)

    # Meter readings for last 4 quarters
    reading_count = 0
    for m_idx, meter in enumerate(meters):
        base_value = 1000.0 + m_idx * 500
        for q in range(4):
            rd = today - timedelta(days=90 * q)
            value = base_value + (4 - q) * 250 + m_idx * 30
            store.create_standalone_meter_reading(StandaloneMeterReadingCreate(
                meter_id=meter.id, reading_date=rd, value=value,
                recorded_by="Frank Wagner",
            ))
            reading_count += 1
    print(f"  {len(meters)} Zähler und {reading_count} Ablesungen erstellt")

    # =========================================================================
    # RENT CHARGES (Mietforderungen)
    # =========================================================================
    rc_count = 0
    for month_offset in range(6):
        month_date = today.replace(day=1) - timedelta(days=30 * month_offset)
        month_str = month_date.strftime("%Y-%m")
        for i, contract in enumerate(contracts[:10]):  # first 10 contracts
            unit_idx = assignments[i][0]
            cr = cold_rents[unit_idx]
            sc = 180.0
            hc = 90.0
            paid = cr + sc + hc if month_offset > 0 else (cr + sc + hc if i < 8 else cr)  # some partial payments this month
            store.create_rent_charge(RentChargeCreate(
                contract_id=contract.id, month=month_str,
                cold_rent=cr, service_charge=sc, heating_charge=hc,
                amount_paid=paid,
                status="paid" if paid >= cr + sc + hc else "partial",
            ))
            rc_count += 1
    print(f"  {rc_count} Mietforderungen erstellt")

    # =========================================================================
    # RECEIVABLES (Offene Forderungen)
    # =========================================================================
    receivable_data = []
    if len(contracts) > 20:
        receivable_data = [
            (contracts[20].id, today - timedelta(days=5), 1020.0 + 190.0 + 100.0, "1", "overdue"),
            (contracts[21].id, today - timedelta(days=35), 1080.0 + 190.0 + 100.0, "2", "overdue"),
        ]
    for contract_id, due, amount, dunning, status in receivable_data:
        store.create_receivable(ReceivableCreate(
            contract_id=contract_id, due_date=due, amount_due=amount,
            dunning_level=dunning, status=status,
        ))
    if receivable_data:
        print(f"  {len(receivable_data)} Offene Forderungen erstellt")

    # =========================================================================
    # ESCALATION RULES
    # =========================================================================
    esc_rules = [
        ("Mahnung bei Zahlungsverzug > 7 Tage", "receivable", "due_date", 7, "notify", "verwalter", "warning"),
        ("2. Mahnung bei Zahlungsverzug > 21 Tage", "receivable", "due_date", 21, "escalate_priority", "eigentuemer", "error"),
        ("Wartungsfall überfällig > 3 Tage", "maintenance", "due_date", 3, "notify", "verwalter", "warning"),
        ("Aufgabe überfällig > 5 Tage", "task", "due_date", 5, "reassign", "verwalter", "warning"),
    ]
    for name, etype, field, days, action, role, sev in esc_rules:
        store.create_escalation_rule(EscalationRuleCreate(
            name=name, entity_type=etype, condition_field=field,
            days_overdue=days, action=action, target_role=role,
            notification_severity=sev, is_active=True,
        ))
    print(f"  {len(esc_rules)} Eskalationsregeln erstellt")

    # =========================================================================
    # NOTIFICATION TEMPLATES
    # =========================================================================
    notif_templates = [
        ("Zahlungserinnerung", "overdue_payment", "Zahlungserinnerung: {{tenant_name}}",
         "Sehr geehrte/r {{tenant_name}}, die Miete für {{month}} in Höhe von {{amount}} € ist seit {{days_overdue}} Tagen überfällig.", "warning"),
        ("Vertrag läuft aus", "contract_expiry", "Vertragsverlängerung: {{contract_number}}",
         "Der Mietvertrag {{contract_number}} mit {{tenant_name}} läuft am {{end_date}} aus. Bitte prüfen.", "info"),
        ("Wartungsbenachrichtigung", "maintenance", "Wartungsfall: {{title}}",
         "Ein neuer Wartungsfall wurde gemeldet: {{title}} (Priorität: {{priority}}). Objekt: {{property_name}}.", "warning"),
        ("Aufgabe fällig", "task_due", "Aufgabe fällig: {{title}}",
         "Die Aufgabe '{{title}}' ist am {{due_date}} fällig. Bitte zeitnah erledigen.", "info"),
    ]
    for name, ntype, title_tmpl, content_tmpl, sev in notif_templates:
        store.create_notification_template(NotificationTemplateCreate(
            name=name, notification_type=ntype, title_template=title_tmpl,
            content_template=content_tmpl, severity=sev,
        ))
    print(f"  {len(notif_templates)} Benachrichtigungsvorlagen erstellt")

    # =========================================================================
    # MESSAGE THREADS & MESSAGES
    # =========================================================================
    threads = []
    thread_data = [
        ("Wasserschaden EG links – Sofortmaßnahmen", prop_berlin2.id, units[6].id),
        ("Mieterhöhung Kastanienallee – Information", prop_berlin1.id, None),
        ("Nebenkostenabrechnung 2025 – Rückfragen", prop_berlin1.id, None),
        ("Klimaanlage Praxis – Statusupdate", prop_muc2.id, units[19].id),
    ]
    for subject, prop_id, unit_id in thread_data:
        th = store.create_message_thread(MessageThreadCreate(
            subject=subject, property_id=prop_id, unit_id=unit_id,
        ))
        threads.append(th)

    # Messages for threads
    msg_data = [
        (threads[0].id, "Stefan Richter", "Guten Tag, im Badezimmer tropft es von der Decke. Die Feuchtigkeit breitet sich aus. Bitte dringend um Hilfe!"),
        (threads[0].id, "Sarah Klein", "Vielen Dank für die Meldung, Herr Richter. Wir haben einen Klempner beauftragt. Er kommt morgen früh zwischen 8-10 Uhr. Bitte stellen Sie sicher, dass jemand in der Wohnung ist."),
        (threads[0].id, "Frank Wagner", "Habe den Schaden begutachtet. Es handelt sich um ein undichtes Abflussrohr in der Wohnung darüber. Reparatur wird morgen durchgeführt. Trocknungsgerät wird aufgestellt."),
        (threads[1].id, "Sarah Klein", "Sehr geehrte Mieter, nach Prüfung des aktuellen Mietspiegels planen wir moderate Mietanpassungen zum 01.07.2026. Details folgen in den nächsten Wochen per Post."),
        (threads[2].id, "Anna Schmidt", "Hallo, ich habe eine Frage zur Position 'Hauswart' in der Nebenkostenabrechnung. Können Sie mir erklären, welche Leistungen darunter fallen?"),
        (threads[2].id, "Sarah Klein", "Guten Tag Frau Schmidt, die Hauswartkosten umfassen: Treppenhausreinigung (2x wöchentlich), Gartenpflege, Winterdienst, kleinere Reparaturen und Kontrolle der Haustechnik."),
        (threads[3].id, "Dr. med. Eva Hartmann", "Die Klimaanlage in meiner Praxis funktioniert seit gestern nicht mehr. Bei den aktuellen Temperaturen ist ein Praxisbetrieb kaum möglich. Bitte um schnelle Lösung!"),
        (threads[3].id, "Sarah Klein", "Frau Dr. Hartmann, wir haben sofort die Firma Kältetechnik Müller beauftragt. Ein Techniker kommt übermorgen. Wir halten Sie auf dem Laufenden."),
    ]
    for thread_id, sender, body in msg_data:
        store.create_message(MessageCreate(
            thread_id=thread_id, sender_name=sender, body=body,
        ))
    print(f"  {len(thread_data)} Nachrichtenthreads mit {len(msg_data)} Nachrichten erstellt")

    # =========================================================================
    # HANDOVER PROTOCOLS (Übergabeprotokolle)
    # =========================================================================
    if len(contracts) >= 2:
        hp_data = [
            (contracts[0].id, units[0].id, "move_in", contracts[0].start_date, 3, "Haustür, Wohnungstür, Briefkasten", "good", "Keine Schäden festgestellt. Wohnung frisch renoviert."),
            (contracts[1].id, units[1].id, "move_in", contracts[1].start_date, 3, "Haustür, Wohnungstür, Kellerschlüssel", "good", "Kleine Kratzer am Parkettboden im Flur. Sonst einwandfrei."),
        ]
        for contract_id, unit_id, ptype, pdate, keys, key_det, cond, notes in hp_data:
            store.create_handover_protocol(HandoverProtocolCreate(
                contract_id=contract_id, unit_id=unit_id,
                protocol_type=ptype, protocol_date=pdate,
                key_count=keys, key_details=key_det,
                overall_condition=cond, notes=notes,
            ))
        print(f"  {len(hp_data)} Übergabeprotokolle erstellt")

    print("\n  ========================================")
    print("  Demo-Daten erfolgreich geladen!")
    print("  ========================================")
    print(f"\n  Anmeldedaten:")
    print(f"    Eigentümer:  demo / Demo1234")
    print(f"    Verwalter:   verwalter / Verwalter1")
    print(f"    Techniker:   techniker / Techniker1")
    print()
    return True


if __name__ == "__main__":
    print("ImmoManager Pro – Demo-Daten laden...\n")
    seed()
