# Finanzformular-Übersetzungen

Basis: b0ee1fe, isolierter Worktree statements-review. Kein Merge/Push in Root.

## Änderung

26 neue Blattwerte je Sprache (de-DE, en-US, es-ES). Kein bestehender Blattwert
wurde verändert oder entfernt; auch Auth/Settings/rentOverview bleiben unverändert.
Das bisherige finance.bookings.status ist bereits der STRING „Status“, kein
Objekt. Deshalb verwenden die beiden Buchungsoptionen jetzt statusOptions statt
status als Elternschlüssel. Die vorhandene Tabellenüberschrift bleibt erhalten.

Exakte hinzugefügte Schlüssel (identisch für alle drei Sprachen):

```text
finance.accounts.form.accountType
finance.accounts.form.balance
finance.accounts.form.bank
finance.accounts.form.currentBalance
finance.accounts.form.name
finance.accounts.form.openingBalance
finance.accounts.form.type
finance.accounts.types.checking
finance.accounts.types.deposit
finance.accounts.types.rent
finance.accounts.types.savings
finance.bookings.form.amount
finance.bookings.form.bookingDate
finance.bookings.form.category
finance.bookings.form.date
finance.bookings.form.paymentText
finance.bookings.form.receiptUrl
finance.bookings.statusOptions.booked
finance.bookings.statusOptions.matched
pages.insurances.form.contactPhone
portfolio.properties.form.name
ui.form.none
ui.table.firstPage
ui.table.lastPage
ui.table.pagination
units.list.columns.label
```

## Prüfung

12 neue Regressionen: pro Sprache alle Literal-Schlüssel aus 14 Finanz- und
Abrechnungsseiten plus gemeinsamen Formular-/Tabellenkomponenten sowie echte
I18nProvider/FormModal-Darstellung von Konten, Buchungen und Versicherungen.
Formulartext, Optionen und Accessibility-Attribute dürfen keine rohen Schlüssel
enthalten. Die API ist für diese Komponentenregressionen simuliert.

Vor der Korrektur: 12/12 neue Tests fehlgeschlagen. Danach: gesamte Suite 130/130
bestanden, ESLint ohne Warnungen/Fehler, Produktionsbuild und git diff --check grün.
Nachweise außerhalb des Repositories: work/ui-i18n-evidence (baseline.json,
final-tests.json, lint.log, build.log, added-keys.json, catalog-audit.json).

Integration: nur diesen Folgecommit cherry-picken; b0ee1fe wurde bereits von Root
übernommen. Root löst eventuelle benachbarte JSON-Hunks mit parallelen Locale-Arbeiten.
Keine fachlichen Werte, gespeicherten Kontotypen oder Backendverträge geändert.
