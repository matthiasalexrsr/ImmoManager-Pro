"""Seed script: populate ImmoManager Pro with demo data.

Usage:
    python seed_data.py              # uses in-memory default (no DB)
    DATABASE_URL=... python seed_data.py  # populates actual database

Can also be imported and called programmatically via seed().
"""

from datetime import date, timedelta


def seed():
    """Populate the store with demo data and create a demo user."""
    from backend.dependencies import store
    from backend.auth import register_user

    # --- Demo user ---
    try:
        register_user(
            username="demo",
            email="demo@immomanager.de",
            full_name="Max Mustermann",
            password="demo123",
        )
        print("  Benutzer 'demo' erstellt (Passwort: demo123)")
    except Exception:
        print("  Benutzer 'demo' existiert bereits")

    # --- Portfolios ---
    from backend.models import (
        PortfolioCreate,
        PropertyCreate,
        UnitCreate,
        TenantCreate,
        ContractCreate,
        AccountCreate,
        BookingCreate,
        MaintenanceCaseCreate,
        TaskCreate,
    )

    p1 = store.create_portfolio(PortfolioCreate(
        name="Wohnportfolio Berlin",
        description="Wohnimmobilien in Berlin-Mitte und Prenzlauer Berg",
        status="active",
    ))
    p2 = store.create_portfolio(PortfolioCreate(
        name="Gewerbeportfolio München",
        description="Büro- und Einzelhandelsflächen in München",
        status="active",
    ))
    print(f"  {2} Portfolios erstellt")

    # --- Properties ---
    prop1 = store.create_property(PropertyCreate(
        portfolio_id=p1.id,
        name="Kastanienallee 42",
        property_type="residential",
        street="Kastanienallee 42",
        zip_code="10435",
        city="Berlin",
        country="DE",
        year_built=1905,
        total_area=480.0,
    ))
    prop2 = store.create_property(PropertyCreate(
        portfolio_id=p1.id,
        name="Schönhauser Allee 78",
        property_type="residential",
        street="Schönhauser Allee 78",
        zip_code="10439",
        city="Berlin",
        country="DE",
        year_built=1952,
        total_area=620.0,
    ))
    prop3 = store.create_property(PropertyCreate(
        portfolio_id=p2.id,
        name="Leopoldstraße 120",
        property_type="commercial",
        street="Leopoldstraße 120",
        zip_code="80802",
        city="München",
        country="DE",
        year_built=1988,
        total_area=1200.0,
    ))
    print(f"  {3} Objekte erstellt")

    # --- Units ---
    units = []
    cold_rents = []  # track rent for contracts/bookings
    # Kastanienallee – 4 Wohnungen
    for i, (label, area, rent) in enumerate([
        ("1. OG links", 65.0, 750.00),
        ("1. OG rechts", 72.0, 820.00),
        ("2. OG links", 65.0, 740.00),
        ("2. OG rechts", 72.0, 810.00),
    ], start=1):
        u = store.create_unit(UnitCreate(
            property_id=prop1.id,
            label=label,
            unit_type="apartment",
            area_sqm=area,
            rooms=2 + (i % 2),
            cold_rent=rent,
        ))
        units.append(u)
        cold_rents.append(rent)

    # Schönhauser Allee – 3 Wohnungen
    for label, area, rent in [
        ("EG links", 85.0, 950.00),
        ("EG rechts", 90.0, 1010.00),
        ("1. OG", 110.0, 1250.00),
    ]:
        u = store.create_unit(UnitCreate(
            property_id=prop2.id,
            label=label,
            unit_type="apartment",
            area_sqm=area,
            rooms=3,
            cold_rent=rent,
        ))
        units.append(u)
        cold_rents.append(rent)

    # Leopoldstraße – 2 Gewerbeeinheiten
    for label, area, rent in [
        ("Büro 1. OG", 350.0, 4500.00),
        ("Laden EG", 180.0, 3200.00),
    ]:
        u = store.create_unit(UnitCreate(
            property_id=prop3.id,
            label=label,
            unit_type="office" if "Büro" in label else "retail",
            area_sqm=area,
            cold_rent=rent,
        ))
        units.append(u)
        cold_rents.append(rent)
    print(f"  {len(units)} Einheiten erstellt")

    # --- Tenants ---
    tenant_data = [
        ("Anna Schmidt", "anna.schmidt@email.de", "+49 30 12345601"),
        ("Thomas Weber", "thomas.weber@email.de", "+49 30 12345602"),
        ("Sabine Fischer", "sabine.fischer@email.de", "+49 30 12345603"),
        ("Klaus Müller", "klaus.mueller@email.de", "+49 30 12345604"),
        ("Maria Becker", "maria.becker@email.de", "+49 30 12345605"),
        ("Jürgen Hoffmann", "juergen.hoffmann@email.de", "+49 89 98765601"),
        ("Petra Schneider", "petra.schneider@email.de", "+49 89 98765602"),
    ]
    tenants = []
    for full_name, email, phone in tenant_data:
        t = store.create_tenant(TenantCreate(
            full_name=full_name,
            email=email,
            phone=phone,
        ))
        tenants.append(t)
    print(f"  {len(tenants)} Mieter erstellt")

    # --- Contracts (assign tenants to units) ---
    today = date.today()
    contracts = []
    for i, (unit, tenant) in enumerate(zip(units[:7], tenants)):
        prop_id = prop1.id if i < 4 else prop2.id if i < 7 else prop3.id
        c = store.create_contract(ContractCreate(
            contract_number=f"MV-2024-{i + 1:03d}",
            property_id=prop_id,
            unit_id=unit.id,
            tenant_id=tenant.id,
            start_date=today - timedelta(days=365 + i * 30),
            deposit_amount=cold_rents[i] * 3,
            status="active",
        ))
        contracts.append(c)
    print(f"  {len(contracts)} Verträge erstellt")

    # --- Accounts ---
    acc1 = store.create_account(AccountCreate(
        portfolio_id=p1.id,
        name="Mietkonto Berlin",
        account_type="bank",
        iban="DE89 3704 0044 0532 0130 00",
    ))
    acc2 = store.create_account(AccountCreate(
        portfolio_id=p2.id,
        name="Mietkonto München",
        account_type="bank",
        iban="DE27 1007 0024 0123 4567 89",
    ))
    print(f"  {2} Konten erstellt")

    # --- Bookings (last 3 months of rent) ---
    booking_count = 0
    for month_offset in range(3):
        booking_date = today.replace(day=1) - timedelta(days=30 * month_offset)
        for i, contract in enumerate(contracts[:4]):
            rent = cold_rents[i]
            store.create_booking(BookingCreate(
                account_id=acc1.id,
                booking_date=booking_date,
                amount=rent,
                payment_text=f"Miete {booking_date.strftime('%m/%Y')} – {tenants[i].full_name}",
            ))
            booking_count += 1
        for i, contract in enumerate(contracts[4:7]):
            rent = cold_rents[4 + i]
            store.create_booking(BookingCreate(
                account_id=acc1.id,
                booking_date=booking_date,
                amount=rent,
                payment_text=f"Miete {booking_date.strftime('%m/%Y')} – {tenants[4 + i].full_name}",
            ))
            booking_count += 1
    print(f"  {booking_count} Buchungen erstellt")

    # --- Maintenance Cases ---
    m1 = store.create_maintenance_case(MaintenanceCaseCreate(
        property_id=prop1.id,
        title="Heizungsausfall 2. OG links",
        description="Heizkörper im Wohnzimmer wird nicht warm. Thermostat reagiert nicht.",
        category="heating",
        priority="high",
        status="open",
    ))
    m2 = store.create_maintenance_case(MaintenanceCaseCreate(
        property_id=prop2.id,
        title="Wasserschaden Badezimmer EG links",
        description="Feuchtigkeit an der Decke im Badezimmer. Möglicher Rohrbruch.",
        category="plumbing",
        priority="urgent",
        status="in_progress",
    ))
    m3 = store.create_maintenance_case(MaintenanceCaseCreate(
        property_id=prop3.id,
        title="Aufzug-Wartung fällig",
        description="Jährliche Aufzugswartung gemäß BetrSichV steht an.",
        category="elevator",
        priority="medium",
        status="open",
    ))
    print(f"  {3} Wartungsfälle erstellt")

    # --- Tasks ---
    store.create_task(TaskCreate(
        title="Nebenkostenabrechnung 2024 erstellen",
        description="Betriebskostenabrechnung für alle Mieter im Portfolio Berlin fertigstellen.",
        status="open",
        priority="high",
        due_date=today + timedelta(days=30),
    ))
    store.create_task(TaskCreate(
        title="Mieterhöhung prüfen – Kastanienallee",
        description="Ortsübliche Vergleichsmiete prüfen und ggf. Mieterhöhungsverlangen vorbereiten.",
        status="open",
        priority="medium",
        due_date=today + timedelta(days=60),
    ))
    store.create_task(TaskCreate(
        title="Rauchmelder-Prüfung Schönhauser Allee",
        description="Jährliche Funktionsprüfung aller Rauchmelder dokumentieren.",
        status="open",
        priority="medium",
        due_date=today + timedelta(days=14),
    ))
    store.create_task(TaskCreate(
        title="Versicherungspolice verlängern",
        description="Gebäudeversicherung für Leopoldstraße 120 läuft Ende März aus.",
        status="open",
        priority="high",
        due_date=today + timedelta(days=45),
    ))
    print(f"  {4} Aufgaben erstellt")

    print("\nDemo-Daten erfolgreich geladen!")
    return True


if __name__ == "__main__":
    print("ImmoManager Pro – Demo-Daten laden...\n")
    seed()
