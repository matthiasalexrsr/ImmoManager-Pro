"""The test version's portfolio: 15 properties of a small property management in Saxony.

Everything is fictitious: names, addresses (real streets, invented house numbers),
companies, bank accounts. Rents follow typical local levels; the history starts in
January three years before today and runs up to today.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

PASSWORD = "Immo-Test-2026"

# username, e-mail, full name, role
MASTERS = [
    ("linda.reiser", "linda_reiser@web.de", "Linda Reiser", "eigentuemer"),
    ("mat.thias", "mat.thias@online.de", "Matthias", "eigentuemer"),
]
STAFF = [
    ("s.krause", "s.krause@reiser-verwaltung.example", "Sandra Krause", "verwalter"),
    ("p.lindner", "p.lindner@reiser-verwaltung.example", "Petra Lindner", "buchhaltung"),
    ("j.vogel", "j.vogel@reiser-verwaltung.example", "Jens Vogel", "techniker"),
    ("stb.hofmann", "kanzlei@hofmann-steuer.example", "Kanzlei Hofmann (Steuerberatung)", "readonly"),
]

CONTRACTORS = [
    # company, trade, phone, city
    ("Sanitär Böhme GmbH", "Sanitär", "0341 4928170", "Leipzig"),
    ("Elektro Hänel", "Elektro", "0341 2251904", "Leipzig"),
    ("Heizungsbau Lorenz GmbH", "Heizung", "0351 8104420", "Dresden"),
    ("Dachdeckerei Kunze", "Dach", "0345 6870231", "Halle (Saale)"),
    ("Malerbetrieb Seifert", "Maler", "0371 3320915", "Chemnitz"),
    ("Grünwerk Gartenpflege", "Garten", "0341 9615570", "Leipzig"),
    ("Schlüsseldienst Schnell & Sicher", "Schlüssel", "0351 4799020", "Dresden"),
    ("Hausmeisterservice Weiß", "Hausmeister", "0341 5508812", "Leipzig"),
]

FIRST = ["Anna", "Thomas", "Sabine", "Michael", "Julia", "Stefan", "Katrin", "Andreas", "Laura", "Markus",
         "Claudia", "Daniel", "Nicole", "Sebastian", "Franziska", "Tobias", "Melanie", "Christian", "Sarah",
         "Matthias", "Lisa", "Florian", "Jana", "Philipp", "Kathrin", "Martin", "Susanne", "Robert", "Lena",
         "Felix", "Ines", "Jörg", "Carolin", "Sven", "Ayşe", "Mehmet", "Olena", "Piotr", "Nguyen Thi", "Marco"]
LAST = ["Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner", "Becker", "Schulz", "Hoffmann",
        "Richter", "Klein", "Wolf", "Schröder", "Neumann", "Schwarz", "Zimmermann", "Braun", "Krüger", "Hartmann",
        "Lange", "Schmitt", "Werner", "Krause", "Meier", "Lehmann", "Köhler", "Herrmann", "König", "Walter",
        "Böhm", "Fuchs", "Kaiser", "Lorenz", "Günther", "Frank", "Berger", "Winkler", "Roth", "Beck",
        "Yılmaz", "Kowalski", "Hoang", "Petrenko", "Rossi"]

# street, house number, postal code, city, €/m² cold rent today
PLACES = {
    "leipzig": 7.4, "dresden": 8.2, "halle": 6.6, "chemnitz": 5.9, "markkleeberg": 9.1, "taucha": 8.4,
}


@dataclass
class UnitSpec:
    label: str
    kind: str              # flat | commercial | parking | house
    area: Optional[float]
    rooms: Optional[float]
    floor: Optional[str]
    cold: float            # cold rent today (new letting)
    service: float
    heating: float
    persons: Optional[int]
    unit_type: str
    id: Optional[str] = None


@dataclass
class PropertySpec:
    portfolio: str
    name: str
    property_type: str
    street: str
    postal_code: str
    city: str
    place: str
    year_built: int
    purchase: tuple[int, int, int, float]    # year, month, day, price
    market_value: float
    units: list[UnitSpec] = field(default_factory=list)
    bill: bool = True      # yearly utility statement
    id: Optional[str] = None


@dataclass
class TenantSpec:
    name: str
    email: Optional[str]
    phone: Optional[str]
    company: bool = False
    payment: str = "bank_transfer"
    id: Optional[str] = None


@dataclass
class TenancySpec:
    unit: UnitSpec
    prop: PropertySpec
    tenant: TenantSpec
    start: date
    end: Optional[date]
    notice: Optional[date]          # when the notice arrived (end known from then on)
    rent_model: str                 # fixed | index | stepped
    behaviour: str                  # punctual | late | sepa | partial | arrears
    deposit_months: int
    number: str = ""
    id: Optional[str] = None
    steps: list = field(default_factory=list)   # (valid_from, cold, service, heating)


PORTFOLIOS = [
    ("Privatbestand Reiser", "Linda Reiser", "Wohnhäuser und Eigentumswohnungen in Leipzig und Umgebung"),
    ("Reiser & Thias Immobilien GbR", "Reiser & Thias GbR", "Mehrfamilien- und Geschäftshäuser in Dresden, Halle und Chemnitz"),
    ("Fremdverwaltung Erbengemeinschaft Kühn", "Erbengemeinschaft Kühn", "Verwaltung im Auftrag, Abrechnung an die Eigentümer"),
]


def _flat(label, area, rooms, floor, rate, persons, rnd: random.Random) -> UnitSpec:
    cold = round(area * rate * rnd.uniform(0.95, 1.06), 0)
    return UnitSpec(label, "flat", area, rooms, floor, cold, round(area * 1.6, 0), round(area * 1.0, 0), persons,
                    "Wohnung")


def _shop(label, area, floor, rate, unit_type, rnd: random.Random) -> UnitSpec:
    cold = round(area * rate * rnd.uniform(0.95, 1.05), 0)
    return UnitSpec(label, "commercial", area, None, floor, cold, round(area * 2.0, 0), round(area * 1.0, 0), 0, unit_type)


def _parking(label, rent) -> UnitSpec:
    return UnitSpec(label, "parking", None, None, None, rent, 0.0, 0.0, 0, "Stellplatz")


def _floors(count: int) -> list[str]:
    return ["EG"] + [f"{n}. OG" for n in range(1, count)]


def build_properties(rnd: random.Random) -> list[PropertySpec]:
    """The 15 properties with their units."""
    props: list[PropertySpec] = []
    pf1, pf2, pf3 = (p[0] for p in PORTFOLIOS)

    def mfh(portfolio, name, ptype, street, plz, city, place, year, purchase, value, floors, sizes, parking=0,
            garage_rent=45.0, bill=True):
        prop = PropertySpec(portfolio, name, ptype, street, plz, city, place, year, purchase, value, bill=bill)
        rate = PLACES[place] * (1.12 if year >= 2015 else 1.0)
        for floor in _floors(floors):
            for side, (area, rooms) in zip(("links", "rechts", "Mitte"), sizes):
                persons = 1 if area < 50 else (2 if area < 75 else rnd.choice([3, 4]))
                prop.units.append(_flat(f"{floor} {side}", area, rooms, floor, rate, persons, rnd))
        for n in range(1, parking + 1):
            prop.units.append(_parking(f"Stellplatz {n}", garage_rent))
        return prop

    props.append(mfh(pf1, "Karl-Heine-Straße 42", "multi_family", "Karl-Heine-Straße 42", "04229", "Leipzig",
                     "leipzig", 1904, (2014, 6, 1, 640_000), 1_150_000, 4, [(68.5, 3), (54.0, 2)]))
    props.append(mfh(pf1, "Gohliser Straße 17", "multi_family", "Gohliser Straße 17", "04155", "Leipzig",
                     "leipzig", 1912, (2017, 3, 15, 720_000), 1_080_000, 3, [(74.0, 3), (61.5, 2)], parking=4))
    wgh = PropertySpec(pf1, "Eisenbahnstraße 88", "mixed", "Eisenbahnstraße 88", "04315", "Leipzig", "leipzig",
                       1898, (2019, 9, 1, 610_000), 790_000)
    wgh.units.append(_shop("Laden EG", 96.0, "EG", 10.5, "Laden", rnd))
    for floor in _floors(4)[1:]:
        wgh.units.append(_flat(f"{floor}", 72.0, 3, floor, PLACES["leipzig"], 2, rnd))
    wgh.units.append(_flat("DG", 48.0, 2, "DG", PLACES["leipzig"], 1, rnd))
    props.append(wgh)
    etw = PropertySpec(pf1, "ETW Kurt-Eisner-Straße 70, WE 8", "condominium", "Kurt-Eisner-Straße 70", "04275",
                       "Leipzig", "leipzig", 1996, (2016, 11, 1, 168_000), 245_000, bill=False)
    etw.units.append(_flat("WE 8 (3. OG)", 66.0, 2.5, "3. OG", 8.6, 2, rnd))
    props.append(etw)
    efh = PropertySpec(pf1, "Einfamilienhaus Seeblick 4", "single_family", "Seeblick 4", "04416", "Markkleeberg",
                       "markkleeberg", 2008, (2015, 4, 1, 310_000), 495_000, bill=False)
    efh.units.append(UnitSpec("Haus", "house", 132.0, 5, "EG–DG", 1290.0, 140.0, 0.0, 4, "Haus"))
    props.append(efh)
    dhh = PropertySpec(pf1, "Doppelhaushälfte Am Birkenwäldchen 9", "single_family", "Am Birkenwäldchen 9", "04425",
                       "Taucha", "taucha", 2001, (2020, 2, 1, 265_000), 330_000, bill=False)
    dhh.units.append(UnitSpec("Haushälfte", "house", 108.0, 4, "EG–DG", 980.0, 120.0, 0.0, 3, "Haus"))
    props.append(dhh)

    props.append(mfh(pf2, "Bautzner Straße 61", "multi_family", "Bautzner Straße 61", "01099", "Dresden",
                     "dresden", 1910, (2018, 1, 1, 1_250_000), 1_720_000, 5, [(78.0, 3), (58.0, 2)]))
    wgh2 = PropertySpec(pf2, "Alaunstraße 33", "mixed", "Alaunstraße 33", "01099", "Dresden", "dresden", 1889,
                        (2021, 7, 1, 890_000), 960_000)
    wgh2.units.append(_shop("Café EG", 84.0, "EG", 12.0, "Gastronomie", rnd))
    for floor in _floors(3)[1:]:
        for side, area, rooms in (("links", 63.0, 2), ("rechts", 81.0, 3)):
            wgh2.units.append(_flat(f"{floor} {side}", area, rooms, floor, PLACES["dresden"], 2, rnd))
    props.append(wgh2)
    gew = PropertySpec(pf2, "Geschäftshaus Leipziger Straße 23", "commercial", "Leipziger Straße 23", "06108",
                       "Halle (Saale)", "halle", 1994, (2016, 5, 1, 820_000), 940_000)
    gew.units.append(_shop("Laden EG", 140.0, "EG", 11.0, "Laden", rnd))
    gew.units.append(_shop("Praxis 1. OG", 165.0, "1. OG", 9.5, "Praxis", rnd))
    gew.units.append(_shop("Büro 2. OG", 158.0, "2. OG", 8.5, "Büro", rnd))
    props.append(gew)
    props.append(mfh(pf2, "Bernburger Straße 9", "multi_family", "Bernburger Straße 9", "06108", "Halle (Saale)",
                     "halle", 1928, (2019, 3, 1, 540_000), 690_000, 3, [(70.0, 3), (52.0, 2)]))
    props.append(mfh(pf2, "Weststraße 50", "multi_family", "Weststraße 50", "09112", "Chemnitz", "chemnitz", 1903,
                     (2015, 10, 1, 380_000), 560_000, 4, [(76.0, 3), (59.0, 2)]))
    props.append(mfh(pf2, "Zschochersche Straße 12", "multi_family", "Zschochersche Straße 12", "04229",
                     "Leipzig", "leipzig", 2019, (2019, 12, 1, 2_900_000), 3_350_000, 4,
                     [(88.0, 3), (64.0, 2), (46.0, 1.5)], parking=6, garage_rent=65.0))
    etw2 = PropertySpec(pf2, "ETW Paulusviertel, Lessingstraße 21, WE 4", "condominium", "Lessingstraße 21", "06114",
                        "Halle (Saale)", "halle", 1907, (2022, 5, 1, 189_000), 205_000, bill=False)
    etw2.units.append(_flat("WE 4 (2. OG)", 84.0, 3, "2. OG", 7.6, 2, rnd))
    props.append(etw2)

    garagen = PropertySpec(pf3, "Garagenhof Am Sportforum", "parking", "Am Sportforum 3", "04105", "Leipzig",
                           "leipzig", 1978, (2012, 1, 1, 95_000), 140_000, bill=False)
    for n in range(1, 11):
        garagen.units.append(_parking(f"Garage {n:02d}", 55.0))
    props.append(garagen)
    props.append(mfh(pf3, "Lindenauer Markt 5", "multi_family", "Lindenauer Markt 5", "04177", "Leipzig",
                     "leipzig", 1925, (2010, 8, 1, 410_000), 820_000, 3, [(65.0, 2.5), (65.0, 2.5)]))
    return props


def person_name(rnd: random.Random, used: set[str]) -> str:
    while True:
        name = f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"
        if name not in used:
            used.add(name)
            return name


COMPANY_TENANTS = {
    "Laden EG|Eisenbahnstraße 88": ("Orient-Markt Eisenbahnstraße e.K.", "Laden"),
    "Café EG|Alaunstraße 33": ("Café Kornblume GmbH", "Café"),
    "Laden EG|Geschäftshaus Leipziger Straße 23": ("Optik am Markt GmbH", "Laden"),
    "Praxis 1. OG|Geschäftshaus Leipziger Straße 23": ("Physiotherapie Bewegungsraum, Inh. M. Sauer", "Praxis"),
    "Büro 2. OG|Geschäftshaus Leipziger Straße 23": ("Steuerkanzlei Albrecht & Partner", "Büro"),
}


def email_for(name: str, rnd: random.Random) -> Optional[str]:
    if rnd.random() < 0.1:
        return None                               # some tenants give no e-mail address
    plain = (name.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
             .replace("ı", "i").replace("ş", "s").replace(" ", ".").replace(",", ""))
    return f"{plain}@beispiel-mail.de"


def phone_for(city: str, rnd: random.Random) -> str:
    prefix = {"Leipzig": "0341", "Dresden": "0351", "Halle (Saale)": "0345", "Chemnitz": "0371",
              "Markkleeberg": "0341", "Taucha": "034298"}.get(city, "0341")
    if rnd.random() < 0.5:
        return f"01{rnd.choice(['51', '52', '60', '70', '76'])} {rnd.randint(1000000, 9999999)}"
    return f"{prefix} {rnd.randint(200000, 9999999)}"
