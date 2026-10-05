"""The simulated world: portfolios, buildings, units and tenancies over the test period.

Deterministic for a seed. Nothing here talks to the API; the phases create it and keep
the ids on the same objects.
"""

from __future__ import annotations

import calendar
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

FIRST_NAMES = ["Anna", "Ben", "Clara", "David", "Elif", "Finn", "Greta", "Hakan", "Ines", "Jonas", "Katarzyna",
               "Leon", "Mia", "Nils", "Olga", "Paul", "Quirin", "Rosa", "Sven", "Tamara", "Umut", "Vera", "Wim",
               "Xenia", "Yusuf", "Zoe", "Émile", "Åsa", "Łukasz", "Søren"]
LAST_NAMES = ["Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner", "Becker", "Schulz",
              "Hoffmann", "Yılmaz", "Nguyen", "Kowalski", "Rossi", "O'Brien", "García", "Popescu", "Ivanova",
              "Al-Hassan", "van der Berg", "Groß", "Weiß", "Öztürk", "Jäger"]
COMPANIES = ["Bäckerei Krume GmbH", "Physio Plus UG", "Kanzlei Recht & Ordnung", "Späti 24 e.K.",
             "Café Bohne & Co. KG", "IT-Service Nord GmbH", "Blumen Lotti", "Friseur Schnittpunkt"]
CITIES = [("Leipzig", "04", 7.5), ("Berlin", "10", 11.0), ("München", "80", 17.5), ("Köln", "50", 11.5),
          ("Dresden", "01", 7.8), ("Hamburg", "20", 13.0), ("Görlitz", "02", 5.2)]
STREETS = ["Hauptstraße", "Lindenallee", "Am Markt", "Bahnhofstraße", "Gartenweg", "Schillerstraße",
           "Goethestraße", "Ringstraße", "Mühlenweg", "Kirchplatz"]
BEHAVIOURS = [("punctual", 58), ("late", 12), ("partial", 8), ("arrears", 5), ("overpay", 3), ("sepa_return", 4),
              ("quarterly", 3), ("typo", 3), ("cash", 2), ("silent_stop", 2)]


@dataclass
class Unit:
    key: str
    label: str
    kind: str          # flat | commercial | parking | storage
    unit_type: str     # what is stored (mixes German words and English codes on purpose)
    area: Optional[float]
    rooms: Optional[float]
    floor: Optional[str]
    cold: float
    service: float
    heating: float
    persons: Optional[int]
    id: str | None = None


@dataclass
class Tenancy:
    unit: Unit
    tenant: "Tenant"
    start: date
    end: Optional[date]
    rent_model: str            # index | stepped | fixed
    behaviour: str
    deposit: Optional[float]
    number: str = ""
    id: str | None = None
    combined_with: Optional["Tenancy"] = None  # garage paid with the flat in one transfer
    steps: list = field(default_factory=list)  # applied rent history: (valid_from, cold, service, heating)


@dataclass
class Tenant:
    name: str
    email: Optional[str]
    phone: Optional[str]
    iban: Optional[str]
    company: bool = False
    id: str | None = None


@dataclass
class Property:
    name: str
    kind: str          # residential | mixed | commercial | condominium | single_family
    city: str
    postal_code: Optional[str]
    street: Optional[str]
    year_built: Optional[int]
    units: list[Unit] = field(default_factory=list)
    id: str | None = None


@dataclass
class Portfolio:
    name: str
    owner: str
    properties: list[Property] = field(default_factory=list)
    id: str | None = None
    account_id: str | None = None
    categories: dict = field(default_factory=dict)


@dataclass
class World:
    seed: int
    start: date
    end: date
    portfolios: list[Portfolio]
    tenancies: list[Tenancy]
    tenants: list[Tenant]

    @property
    def units(self) -> list[Unit]:
        return [u for pf in self.portfolios for p in pf.properties for u in p.units]

    def property_of(self, unit: Unit) -> Property:
        return next(p for pf in self.portfolios for p in pf.properties if unit in p.units)

    def portfolio_of(self, unit: Unit) -> Portfolio:
        return next(pf for pf in self.portfolios for p in pf.properties if unit in p.units)


def month_end(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def add_months(day: date, months: int) -> date:
    y, m = divmod(day.month - 1 + months, 12)
    year, month = day.year + y, m + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def months(start: date, end: date):
    current = start.replace(day=1)
    while current <= end:
        yield current
        current = add_months(current, 1)


def build_world(seed: int = 2026, units: int = 120, years: int = 5, today: date | None = None) -> World:
    rnd = random.Random(seed)
    today = today or date.today()
    end = today.replace(day=1) - timedelta(days=1)          # last full month
    start = add_months(end.replace(day=1), -12 * years + 1)
    portfolios: list[Portfolio] = []
    owners = ["Familie Brandt", "Erbengemeinschaft Kühn", "Stadtwohnen GmbH", "Dr. Ilse Martens",
              "Kapitalanlage Seidel", "Gewerbe & Wohnen KG"]
    for i in range(max(2, min(6, units // 20))):
        portfolios.append(Portfolio(f"Bestand {owners[i]}", owners[i]))

    made = 0
    house_no = 1
    while made < units:
        pf = portfolios[len([p for x in portfolios for p in x.properties]) % len(portfolios)]
        city, zip_prefix, per_sqm = rnd.choice(CITIES)
        kind = rnd.choices(["residential", "mixed", "commercial", "condominium", "single_family"], [50, 20, 8, 12, 10])[0]
        street = f"{rnd.choice(STREETS)} {house_no}"
        house_no += 1
        incomplete = rnd.random() < 0.15
        prop = Property(name=f"{ {'residential': 'MFH', 'mixed': 'WGH', 'commercial': 'Gewerbehof', 'condominium': 'ETW', 'single_family': 'EFH'}[kind]} {street}",
                        kind=kind, city=city, postal_code=None if incomplete else f"{zip_prefix}{rnd.randint(100, 999)}",
                        street=None if incomplete and rnd.random() < 0.5 else street,
                        year_built=None if incomplete else rnd.randint(1890, 2020))
        size = {"residential": rnd.randint(4, 14), "mixed": rnd.randint(4, 10), "commercial": rnd.randint(2, 6),
                "condominium": 1, "single_family": 1}[kind]
        size = min(size, units - made)
        for n in range(size):
            if kind == "commercial" or (kind == "mixed" and n < 2):
                ukind = "commercial"
            elif kind in ("residential", "mixed") and n >= size - 2 and size > 4:
                ukind = rnd.choice(["parking", "parking", "storage"])
            else:
                ukind = "flat"
            area = {"flat": rnd.choice([28, 42, 55, 63, 71, 78, 86, 95, 110, 140]), "commercial": rnd.randint(40, 260),
                    "parking": 12.5, "storage": 8}[ukind]
            unit_type = rnd.choice({"flat": ["Wohnung", "residential", "Wohnung"], "commercial": ["Gewerbe", "commercial"],
                                    "parking": ["Stellplatz", "parking", "Garage"], "storage": ["Keller", "storage"]}[ukind])
            cold = round(area * per_sqm * rnd.uniform(0.85, 1.2), 2) if ukind in ("flat", "commercial") else \
                float(rnd.choice([45, 60, 75, 90, 120]))
            sparse = rnd.random() < 0.12
            unit = Unit(key=f"{prop.name}|{n + 1}",
                        label={"flat": f"WE {n + 1:02d}", "commercial": f"Gewerbe {n + 1}", "parking": f"Stellplatz {n + 1}",
                               "storage": f"Keller {n + 1}"}[ukind] if kind not in ("condominium", "single_family") else
                        ("Wohnung" if kind == "condominium" else "Haus"),
                        kind=ukind, unit_type=unit_type, area=None if sparse else area,
                        rooms=None if ukind != "flat" or sparse else max(1, round(area / 25)),
                        floor=None if sparse else rnd.choice(["EG", "1.OG", "2.OG", "3.OG", "DG", "UG"]),
                        cold=cold,
                        service=round(area * rnd.uniform(1.6, 2.8), 2) if ukind in ("flat", "commercial") else 0.0,
                        heating=round(area * rnd.uniform(0.8, 1.4), 2) if ukind in ("flat", "commercial") else 0.0,
                        persons=None if ukind != "flat" or sparse else rnd.randint(1, 5))
            prop.units.append(unit)
            made += 1
        pf.properties.append(prop)

    tenants: list[Tenant] = []
    tenancies: list[Tenancy] = []

    def new_tenant(company: bool = False) -> Tenant:
        if company:
            name = rnd.choice(COMPANIES)
        else:
            first, last = rnd.choice(FIRST_NAMES), rnd.choice(LAST_NAMES)
            name = rnd.choice([f"{first} {last}", f"Familie {last}", f"{first} {last} & {rnd.choice(FIRST_NAMES)} "
                                                                       f"{rnd.choice(LAST_NAMES)}"])
        sparse = rnd.random() < 0.15
        tenant = Tenant(name=name, company=company,
                        email=None if sparse else f"{name.split()[-1].lower().replace(chr(39), '')}{len(tenants)}@example.de",
                        phone=None if sparse or rnd.random() < 0.2 else f"+49 {rnd.randint(30, 911)} {rnd.randint(100000, 9999999)}",
                        iban=None if sparse else f"DE{rnd.randint(10, 99)}{rnd.randint(10**17, 10**18 - 1)}")
        tenants.append(tenant)
        return tenant

    for pf in portfolios:
        for prop in pf.properties:
            for unit in prop.units:
                # the first tenancy may have begun years before the test period
                day = add_months(start, -rnd.randint(0, 96)).replace(day=1)
                while day <= end:
                    length = rnd.randint(14, 96)
                    finish = month_end(add_months(day, length - 1))
                    if rnd.random() < 0.08:          # moves out mid-month
                        finish = add_months(day, length - 1).replace(day=15)
                    ends_inside = finish <= end
                    tenancy = Tenancy(unit=unit, tenant=new_tenant(unit.kind == "commercial"), start=day,
                                      end=finish if ends_inside else None,
                                      rent_model=rnd.choices(["index", "stepped", "fixed"], [35, 20, 45])[0],
                                      behaviour=rnd.choices([b for b, _ in BEHAVIOURS], [w for _, w in BEHAVIOURS])[0],
                                      deposit=None if unit.kind in ("parking", "storage") or rnd.random() < 0.06 else
                                      round(unit.cold * 3, 2))
                    tenancies.append(tenancy)
                    if not ends_inside:
                        break
                    gap = rnd.choice([0, 0, 0, 1, 1, 2, 3, 5])
                    day = add_months(finish.replace(day=1), gap + 1)
                    if rnd.random() < 0.15:          # next tenant moves in mid-month
                        day = day.replace(day=16)

    # tenants with a flat often also rent a parking space in the same building and pay both at once
    by_property: dict[str, list[Tenancy]] = {}
    for t in tenancies:
        by_property.setdefault(t.unit.key.split("|")[0], []).append(t)
    for group in by_property.values():
        flats = [t for t in group if t.unit.kind == "flat"]
        for spot in [t for t in group if t.unit.kind == "parking"]:
            match = next((f for f in flats if f.start <= spot.start and (f.end is None or (spot.end and f.end >= spot.end))
                          and f.combined_with is None), None)
            if match and rnd.random() < 0.7:
                spot.tenant = match.tenant
                spot.behaviour = "combined"
                match.combined_with = spot
    used = {id(t.tenant) for t in tenancies}
    tenants = [t for t in tenants if id(t) in used]
    for n, t in enumerate(sorted(tenancies, key=lambda x: (x.start, x.unit.key)), start=1):
        t.number = f"MV-{t.start.year}-{n:04d}"
    return World(seed=seed, start=start, end=end, portfolios=portfolios, tenancies=tenancies, tenants=tenants)
