/**
 * The guided tour through the most important functions.
 *
 * route:  page the step shows (navigated to before the step)
 * target: CSS selectors, the first visible match is highlighted; none: a centred card
 */
export const TOUR_STEPS = [
  {
    route: '/',
    title: 'Willkommen bei ImmoManager Pro',
    body: 'Diese Tour zeigt in etwa fünf Minuten die wichtigsten Funktionen. Sie können jederzeit mit „Beenden“ '
      + 'aufhören und die Tour später über das Fragezeichen oben rechts neu starten. '
      + 'Mit den Pfeiltasten geht es vor und zurück.',
  },
  {
    route: '/',
    target: ['#primary-navigation'],
    title: 'Navigation',
    body: 'Links finden Sie alle Bereiche, gruppiert nach Bestand, Mieter & Verträge, Leerstand, Finanzen, '
      + 'Betrieb und Konfiguration. Auf kleinen Bildschirmen öffnet das Menüsymbol oben links die Navigation.',
  },
  {
    route: '/',
    target: ['[data-tour="dashboard"]', '.stats-grid', '.page'],
    title: 'Dashboard: was heute zu tun ist',
    body: 'Das Dashboard bündelt Kennzahlen und offene Arbeit: fällige Mieten, Rückstände, offene Wartungen, '
      + 'Aufgaben und Abrechnungen. Ein Klick auf eine Kachel führt direkt in die passende Liste.',
  },
  {
    route: '/',
    target: ['.search-bar-global'],
    title: 'Suche',
    body: 'Die Suche findet Mieter, Objekte, Einheiten, Verträge und Buchungen, z. B. „Bautzner“ oder den Namen '
      + 'eines Mieters.',
  },
  {
    route: '/properties',
    target: ['.data-table', '.table-scroll', '.page'],
    title: 'Immobilien',
    body: 'Der Bestand: 15 Objekte in drei Portfolios, vom Mehrfamilienhaus bis zum Garagenhof. Ein Klick auf '
      + 'eine Zeile öffnet das Objekt mit Einheiten, Mietern, Kosten und Dokumenten. Über die Filter-Schaltfläche '
      + 'lassen sich Listen eingrenzen.',
  },
  {
    route: '/units',
    target: ['.data-table', '.table-scroll', '.page'],
    title: 'Einheiten',
    body: 'Wohnungen, Gewerbe, Stellplätze und Garagen mit Fläche, Miete und Status. Zwei Wohnungen stehen '
      + 'gerade leer; für sie gibt es Inserate, Interessenten und Besichtigungstermine.',
  },
  {
    route: '/tenants',
    target: ['.data-table', '.table-scroll', '.page'],
    title: 'Mieter und Mieterkonto',
    body: 'Alle Mieter mit Kontaktdaten und Zahlungsart. Über „Konto“ in einer Zeile sehen Sie das Mieterkonto: '
      + 'je Vertrag Soll, gezahlt und Saldo sowie Zahlungen, die noch keinem Vertrag zugeordnet sind.',
  },
  {
    route: '/contracts',
    target: ['.action-cell button[aria-label="Mietverlauf"]', '.data-table', '.page'],
    title: 'Verträge und Mietverlauf',
    body: 'Jeder Vertrag hat einen Mietverlauf: Startmiete, Index- und Staffelerhöhungen, Mieterhöhungen und '
      + 'angepasste Vorauszahlungen, jeweils ab dem Monat, in dem sie gelten. Der Knopf „Mietverlauf“ zeigt ihn.',
  },
  {
    route: '/rent-adjustments',
    target: ['.data-table', '.table-scroll', '.page'],
    title: 'Mietanpassungen',
    body: 'Index-, Staffel- und Vergleichsmieterhöhungen werden hier vorbereitet und mit „Anwenden“ in den '
      + 'Mietverlauf übernommen. In den Testdaten wartet eine Indexanpassung seit Januar darauf.',
  },
  {
    route: '/bookings',
    target: ['.data-table', '.table-scroll', '.page'],
    title: 'Buchungen und Zahlungen',
    body: 'Mietzahlungen, Ausgaben und Bankimporte. Zahlungen eines Mieters werden automatisch seinen Verträgen '
      + 'zugeordnet; mit „Aufteilen“ lässt sich eine Zahlung auf mehrere Verträge verteilen (z. B. Wohnung und '
      + 'Stellplatz).',
  },
  {
    route: '/rent-overview',
    target: ['.data-table', '.table-scroll', '.page'],
    title: 'Mietübersicht und Rückstände',
    body: 'Die Sollstellungen der letzten Monate: bezahlt, teilweise bezahlt oder überfällig. Ein Mieter ist seit '
      + 'vier Monaten im Rückstand, ein anderer zahlt nur einen Teil. Rückstände erscheinen auch als Forderungen '
      + 'mit Mahnstufe.',
  },
  {
    route: '/review',
    target: ['.data-table', '.table-scroll', '.page'],
    title: 'Prüfliste',
    body: 'Hier sammelt die App, was eine Entscheidung braucht: Zahlungen ohne Mieter aus dem Kontoauszug, '
      + 'fällige, aber nicht angewendete Mietanpassungen, unplausible Angaben. Jeder Eintrag führt mit einem '
      + 'Klick dorthin, wo er erledigt wird. Probieren Sie es mit den zwei Zahlungen ohne Mieter.',
  },
  {
    route: '/statements',
    target: ['.card', '.page'],
    title: 'Nebenkostenabrechnung',
    body: 'Abrechnungen je Objekt und Jahr: Kosten erfassen, nach Fläche, Personen, Einheiten oder Verbrauch '
      + 'verteilen, bei Mieterwechsel taggenau. Die Abrechnungen 2025 für Bautzner Straße 61 und Weststraße 50 '
      + 'sind erzeugt, aber noch offen: prüfen, abschließen, Forderungen erzeugen, PDF herunterladen.',
  },
  {
    route: '/maintenance',
    target: ['.data-table', '.table-scroll', '.page'],
    title: 'Wartung und Reparaturen',
    body: 'Schadensmeldungen mit Priorität, Handwerker und Kosten. Überfällige Fälle werden über die '
      + 'Eskalationsregeln automatisch hochgestuft; dazu gibt es Benachrichtigungen (Glocke oben rechts).',
  },
  {
    route: '/tasks',
    target: ['.data-table', '.table-scroll', '.page'],
    title: 'Aufgaben, Kalender und Dokumente',
    body: 'Aufgaben mit Fälligkeit und Zuständigkeit, dazu der Kalender mit Terminen und die Dokumente: zu jedem '
      + 'laufenden Vertrag liegt ein PDF bereit.',
  },
  {
    route: '/settings',
    target: ['.tab-bar', '.page'],
    title: 'Einstellungen, Benutzer und Sicherung',
    body: 'Unter „Benutzer“ verwalten Sie Zugänge und Rollen (Eigentümer, Verwaltung, Buchhaltung, Technik, '
      + 'Nur Lesen); jede Rolle darf nur ihren Bereich ändern. Unter „System“ finden Sie Datensicherung, '
      + 'Wiederherstellung und Export/Import. Unter „Persönlich“ starten Sie diese Tour erneut.',
  },
  {
    route: '/',
    title: 'Fertig!',
    body: 'Das war der Überblick. Alle Daten der Testversion sind frei erfunden; Sie können also gefahrlos '
      + 'anlegen, ändern und löschen. Die Tour starten Sie jederzeit über das Fragezeichen oben rechts neu.',
  },
];
