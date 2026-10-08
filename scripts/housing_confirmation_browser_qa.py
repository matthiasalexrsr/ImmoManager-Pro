"""Real browser acceptance of the Wohnungsgeberbestätigung against an isolated local QA server.

Writes confirmations (immutable originals) into that server, so it refuses any non-loopback
URL and needs QA_ALLOW_TEST_WRITES=1. Start a fresh test version first, for example:

    python -m backend --testversion --no-browser --port 8766 --data-dir <empty directory>
    QA_BASE_URL=http://127.0.0.1:8766 QA_PASSWORD=... QA_ALLOW_TEST_WRITES=1 \\
        python scripts/housing_confirmation_browser_qa.py [screenshot directory]

Optional: QA_OWNER (default linda_reiser@web.de), QA_READONLY (default stb.hofmann),
QA_CHROMIUM (path of an installed Chromium). Prints a JSON report; exits 1 on any finding.
"""

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("QA_BASE_URL", "")
PASSWORD = os.environ.get("QA_PASSWORD", "")
if os.environ.get("QA_ALLOW_TEST_WRITES") != "1" or not PASSWORD:
    sys.exit("Set QA_PASSWORD and QA_ALLOW_TEST_WRITES=1, only for an isolated QA server.")
parts = urlsplit(BASE)
if parts.scheme not in {"http", "https"} or parts.hostname not in {"127.0.0.1", "localhost", "::1"} \
        or parts.path not in {"", "/"} or parts.username:
    sys.exit("QA_BASE_URL must be the origin of a loopback server.")
BASE = f"{parts.scheme}://{parts.netloc}"
OWNER = os.environ.get("QA_OWNER", "linda_reiser@web.de")
READONLY = os.environ.get("QA_READONLY", "stb.hofmann")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/housing-confirmation-browser")
OUT.mkdir(parents=True, exist_ok=True)

findings: list[str] = []
report: dict = {"base": BASE, "checks": []}
CONFIRMATIONS = ("tatsächlich in die Wohnung einziehen", "zur Ausstellung dieser Bestätigung befugt",
                 "tatsächliche Einzug ist")
LONG = "einziehende Person mit einem ausgesprochen langen Familiennamen Łukasz-Müller-Øster"


def check(name, condition, detail=""):
    report["checks"].append({"check": name, "ok": bool(condition), **({"detail": detail} if detail else {})})
    if not condition:
        findings.append(f"{name}: {detail}")


def watch(page, label):
    page.on("pageerror", lambda error: findings.append(f"{label} pageerror: {error}"))
    page.on("console", lambda message: findings.append(f"{label} console: {message.text}")
            if message.type == "error" and "Failed to load resource" not in message.text else None)


def login(page, user):
    page.goto(BASE + "/login")
    page.locator("input[autocomplete=username]").fill(user)
    page.locator("input[type=password]").fill(PASSWORD)
    page.locator("button[type=submit]").click()
    page.wait_for_url(lambda url: "/login" not in url, timeout=20000)
    try:   # the guided tour is offered once to a new user
        page.get_by_role("button", name="Später").click(timeout=4000)
    except Exception:
        pass


def api(page, path):
    token = page.evaluate("localStorage.getItem('access_token')")
    response = page.request.get(BASE + "/api/v1" + path, headers={"Authorization": f"Bearer {token}"})
    assert response.ok, f"{path}: {response.status}"
    return response.json()


def fill(dialog, people):
    dialog.get_by_label("Tatsächlicher Einzug").fill("2026-10-01")
    dialog.get_by_label("Anschrift der Wohnung").fill("Bautzner Straße 61 mit sehr langem Zusatz, Hinterhaus\n01099 Dresden")
    dialog.get_by_label("Name des Wohnungsgebers").fill("Linda Reiser")
    dialog.get_by_label("Anschrift des Wohnungsgebers").fill("Prießnitzstraße 4\n01099 Dresden")
    dialog.get_by_label("Eigentumsverhältnis").select_option("same")
    dialog.get_by_label("Ausstellungsdatum").fill("2026-10-07")
    dialog.get_by_label("Ausstellende Person").fill("Linda Reiser")
    dialog.get_by_label("Rolle der ausstellenden Person").select_option("housing_provider")
    dialog.get_by_label("Vollständiger Name 1", exact=True).fill("Zoë Łukasz-Müller")
    for index in range(2, people + 1):
        dialog.get_by_role("button", name="Person hinzufügen").click()
        dialog.get_by_label(f"Vollständiger Name {index}", exact=True).fill(f"{index:02d} {LONG}")


def review_and_confirm(dialog, people):
    dialog.get_by_role("button", name="Vorschau prüfen").click()
    expect(dialog.get_by_text("Vorläufige Vorschau geprüft")).to_be_visible(timeout=30000)
    check("preview counts every person", dialog.get_by_text(f"{people} Personen", exact=False).count() > 0)
    for label in CONFIRMATIONS:
        dialog.get_by_label(label, exact=False).check()


with sync_playwright() as playwright:
    executable = os.environ.get("QA_CHROMIUM")
    browser = playwright.chromium.launch(**({"executable_path": executable} if executable else {}))
    page = browser.new_page(viewport={"width": 1440, "height": 960}, locale="de-DE")
    watch(page, "1440")
    login(page, OWNER)
    contract = api(page, "/contracts?limit=1")[0]
    base_path = f"/contracts/{contract['id']}/housing-confirmations"
    report["contract"] = contract["contract_number"]

    # 1. contract list: 45 people, several PDF pages, the success answer is lost once
    page.goto(BASE + f"/contracts?search={contract['contract_number']}")
    row = page.get_by_role("row").filter(has_text=contract["contract_number"]).first
    row.get_by_role("button", name="Wohnungsgeberbestätigung").click()
    dialog = page.get_by_role("dialog", name="Wohnungsgeberbestätigung")
    check("move-in date starts empty", dialog.get_by_label("Tatsächlicher Einzug").input_value() == "")
    fill(dialog, 45)
    review_and_confirm(dialog, 45)
    dialog.get_by_role("button", name="PDF-Vorschau öffnen").click()
    dialog.locator("canvas").first.wait_for(timeout=30000)
    page.wait_for_timeout(800)
    page.screenshot(path=str(OUT / "preview-45-people-1440.png"))
    check("preview has several pages", page.evaluate(
        "() => [...document.querySelectorAll('[role=dialog] *')].some(e => /von\\s*[2-9]/.test(e.textContent || ''))"))
    dialog.get_by_role("button", name="Zurück zum Formular").click()

    lost = {"done": False}

    def lose_answer(route):
        if route.request.method == "POST" and not lost["done"]:
            lost["done"] = True
            route.fetch()        # the server stores it ...
            route.abort("connectionreset")   # ... but the answer never arrives
        else:
            route.continue_()

    page.route(f"**/api/v1{base_path}", lose_answer)
    dialog.get_by_role("button", name="Freigeben und Original speichern").click()
    expect(dialog.get_by_text("Verbindung unterbrochen")).to_be_visible(timeout=20000)
    check("form is frozen after a lost answer", dialog.get_by_label("Tatsächlicher Einzug").is_disabled())
    dialog.get_by_role("button", name="Unverändert erneut senden").click()
    expect(dialog.get_by_text("als unveränderliches Original gespeichert", exact=False)).to_be_visible(timeout=30000)
    page.unroute(f"**/api/v1{base_path}")
    history = api(page, base_path + "?limit=50")["items"]
    check("lost answer + retry stores exactly one original", len(history) == 1, f"{len(history)} stored")
    first = history[0]

    # 2. correction: a new original, the first one stays byte for byte
    first_bytes = page.request.get(BASE + first["file_url"], headers={
        "Authorization": "Bearer " + page.evaluate("localStorage.getItem('access_token')")}).body()
    dialog.get_by_role("button", name="Korrektur erstellen").first.click()
    dialog.get_by_label("Tatsächlicher Einzug").fill("2026-10-02")
    review_and_confirm(dialog, 45)
    dialog.get_by_role("button", name="Freigeben und Original speichern").click()
    expect(dialog.get_by_text("als unveränderliches Original gespeichert", exact=False)).to_be_visible(timeout=30000)
    history = api(page, base_path + "?limit=50")["items"]
    check("correction is a second original", len(history) == 2 and any(item["correction_of"] for item in history))
    again = page.request.get(BASE + first["file_url"], headers={
        "Authorization": "Bearer " + page.evaluate("localStorage.getItem('access_token')")}).body()
    check("first original unchanged", again == first_bytes and again[:5] == b"%PDF-")
    articles = dialog.locator(".housing-confirmation__history-list article")
    articles.first.get_by_role("button", name="PDF öffnen").click()
    dialog.locator("canvas").first.wait_for(timeout=30000)
    page.wait_for_timeout(800)
    page.screenshot(path=str(OUT / "original-1440.png"))
    dialog.get_by_role("button", name="Zurück zum Formular").click()
    dialog.get_by_role("button", name="Schließen").last.click()
    expect(dialog).to_be_hidden()
    check("focus returns to the row action", page.evaluate(
        "() => document.activeElement?.getAttribute('aria-label') === 'Wohnungsgeberbestätigung'"))

    # 3. document list: a readable type, no raw key
    page.goto(BASE + "/documents")
    page.get_by_role("table").first.wait_for(timeout=20000)
    page.get_by_role("textbox", name="durchsuchen").first.fill(contract["contract_number"])
    check("document list names the type", page.get_by_role("cell", name="Wohnungsgeberbestätigung", exact=True).count() >= 2)
    check("no raw type key", page.get_by_text("housing_confirmation", exact=True).count() == 0)

    # 4. party record: the exact contract card, and the panel is inert behind the dialog
    page.goto(BASE + f"/contracts?search={contract['contract_number']}")
    page.get_by_role("row").filter(has_text=contract["contract_number"]).first.locator(".party-link").first.click()
    panel = page.locator(".party-panel")
    panel.wait_for(timeout=20000)
    card = panel.locator(".party-contract-card").filter(has_text=contract["contract_number"])
    if card.count():
        card.get_by_role("button", name="Wohnungsgeberbestätigung").click()
        party_dialog = page.get_by_role("dialog", name="Wohnungsgeberbestätigung")
        party_dialog.get_by_label("Tatsächlicher Einzug").wait_for(timeout=20000)
        check("party panel inert behind the dialog", panel.get_attribute("inert") is not None)
        check("party dialog lists both originals",
              party_dialog.locator(".housing-confirmation__history-list article").count() == 2)
        party_dialog.get_by_role("button", name="Schließen").last.click()
    else:
        check("contract card in party record", False, "card for the contract not found")

    # 5. read-only role: sees the originals, no form
    reader = browser.new_page(viewport={"width": 1440, "height": 960}, locale="de-DE")
    watch(reader, "readonly")
    login(reader, READONLY)
    reader.goto(BASE + f"/contracts?search={contract['contract_number']}")
    reader.get_by_role("row").filter(has_text=contract["contract_number"]).first \
        .get_by_role("button", name="Wohnungsgeberbestätigung").click()
    reading = reader.get_by_role("dialog", name="Wohnungsgeberbestätigung")
    expect(reading.get_by_text("Nur Lesezugriff", exact=False)).to_be_visible(timeout=20000)
    check("read-only sees no form", reading.get_by_label("Tatsächlicher Einzug").count() == 0)
    check("read-only sees the originals", reading.locator(".housing-confirmation__history-list article").count() == 2)

    # 6. narrow screens: everything reachable, no sideways scrolling
    for width in (320, 360):
        narrow = browser.new_page(viewport={"width": width, "height": 780}, locale="de-DE")
        watch(narrow, str(width))
        login(narrow, OWNER)
        narrow.goto(BASE + f"/contracts?search={contract['contract_number']}")
        narrow.get_by_role("button", name="Wohnungsgeberbestätigung").first.click()
        narrow_dialog = narrow.get_by_role("dialog", name="Wohnungsgeberbestätigung")
        narrow_dialog.get_by_label("Tatsächlicher Einzug").wait_for(timeout=20000)
        overflow = narrow.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        check(f"no sideways scrolling at {width}px", overflow <= 0, f"{overflow}px")
        publish = narrow_dialog.get_by_role("button", name="Vorschau prüfen")
        publish.scroll_into_view_if_needed()
        box = publish.bounding_box()
        check(f"review button inside the screen at {width}px", box and box["x"] >= 0 and box["x"] + box["width"] <= width)
        narrow.screenshot(path=str(OUT / f"form-{width}.png"))
        narrow.close()
    browser.close()

report["findings"] = findings
print(json.dumps(report, ensure_ascii=False, indent=2))
sys.exit(1 if findings else 0)
