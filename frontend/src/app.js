const NAV_ITEMS = [
  "Dashboard",
  "Portfolio",
  "Immobilien",
  "Einheiten",
  "Mieter & Verträge",
  "Finanzen",
  "Instandhaltung",
  "Dokumente",
  "Aufgaben",
  "Kalender",
  "Berichte",
  "Integrationen",
  "Einstellungen",
];

const DEMO_STATE = {
  kpis: [
    { label: "Immobilien gesamt", value: "20" },
    { label: "Einheiten gesamt", value: "46" },
    { label: "Vermietungsquote", value: "89,1 %" },
    { label: "Nettomiete (Monat)", value: "31.480 €" },
    { label: "Offene Forderungen", value: "2.740 €" },
  ],
  receivables: [
    { label: "Offen", value: "1.250 €" },
    { label: "Überfällig", value: "1.490 €" },
    { label: "Mahnfälle", value: "4" },
    { label: "Ø Überfälligkeit", value: "23 Tage" },
  ],
  contracts: [
    { unit: "Wohnung 2.1", tenant: "Lisa Beispiel", status: "paid", dueDate: "03.04.2026" },
    { unit: "Wohnung 3.2", tenant: "Max Mustermann", status: "overdue", dueDate: "03.03.2026" },
    { unit: "Büro 1.0", tenant: "Meyer Consulting", status: "open", dueDate: "03.04.2026" },
  ],
  campaign: [
    { receivableId: "2026-02-01", level: 2, principal: "500,00 €", fee: "5,00 €", claim: "505,00 €" },
    { receivableId: "2026-01-01", level: 3, principal: "990,00 €", fee: "7,50 €", claim: "997,50 €" },
  ],
};

function renderNav() {
  const nav = document.querySelector("#main-nav");
  nav.innerHTML = "";
  NAV_ITEMS.forEach((item, idx) => {
    const button = document.createElement("button");
    button.textContent = item;
    if (idx === 0) button.classList.add("active");
    nav.appendChild(button);
  });
}

function renderKpis() {
  const target = document.querySelector("#kpis");
  target.innerHTML = DEMO_STATE.kpis
    .map((kpi) => `<div class="kpi"><h3>${kpi.label}</h3><p>${kpi.value}</p></div>`)
    .join("");
}

function renderReceivablesSummary() {
  const target = document.querySelector("#receivables-summary");
  target.innerHTML = DEMO_STATE.receivables
    .map((stat) => `<div class="stat"><label>${stat.label}</label><strong>${stat.value}</strong></div>`)
    .join("");
}

function statusBadge(status) {
  const labels = {
    paid: "Bezahlt",
    open: "Offen",
    overdue: "Überfällig",
  };
  return `<span class="badge ${status}">${labels[status] ?? status}</span>`;
}

function renderContracts() {
  const tbody = document.querySelector("#contracts-table");
  tbody.innerHTML = DEMO_STATE.contracts
    .map(
      (row) => `
      <tr>
        <td>${row.unit}</td>
        <td>${row.tenant}</td>
        <td>${statusBadge(row.status)}</td>
        <td>${row.dueDate}</td>
      </tr>
    `,
    )
    .join("");
}

function renderCampaign() {
  const target = document.querySelector("#dunning-campaign");
  target.innerHTML = DEMO_STATE.campaign
    .map(
      (line) => `
      <div class="campaign-line">
        <strong>Forderung ${line.receivableId}</strong>
        <span>Stufe ${line.level}</span>
        <span>${line.principal} + ${line.fee}</span>
        <span>${line.claim}</span>
      </div>
    `,
    )
    .join("");
}

function bootstrap() {
  renderNav();
  renderKpis();
  renderReceivablesSummary();
  renderContracts();
  renderCampaign();

  document.querySelector("#refresh-dunning")?.addEventListener("click", renderCampaign);
}

bootstrap();
