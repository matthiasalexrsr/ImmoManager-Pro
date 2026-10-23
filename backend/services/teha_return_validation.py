"""Pure review of frozen local data. No assertion about a TEHA request schema."""
from decimal import Decimal, InvalidOperation


def validate_local_return(snapshot, *, issues=()):
    problems = list(issues)
    warnings = [{"code": "portal_contract_unverified", "message": "Dieses lokale Prüfpaket ist kein freigegebenes TEHA-Importformat und kein Versandbeleg."}]
    summary = {"currency": snapshot.get("currency"), "cost_count": 0, "contract_count": 0, "user_count": 0, "total_decimal": None,
               "selected_teha_user_count": len(snapshot.get("follow_up_sources", []))}
    if snapshot.get("portal_preview"):
        warnings.append({"code": "follow_up_user_identity_unverified", "message": "Die Nutzer-Ids stammen aus dem empfangenen Techniktermin. Ihr Abgleich mit den offenen Nutzern der Auftragsnummer im Portal steht aus; die Vorschau ist unbestätigt."})
    if snapshot.get("kind") == "cost_user_data":
        costs, contracts = snapshot.get("cost_items", []), snapshot.get("contracts", [])
        summary.update(cost_count=len(costs), contract_count=len(contracts), user_count=len(snapshot.get("users", [])))
        total = Decimal("0.00")
        try:
            for cost in costs:
                amount = Decimal(cost["amount_decimal"])
                if not amount.is_finite() or amount != amount.quantize(Decimal(".01")):
                    raise ValueError
                total += amount
            summary["total_decimal"] = format(total, ".2f")
        except (InvalidOperation, ValueError, KeyError, TypeError):
            problems.append({"code": "cost_amount_invalid", "message": "Mindestens ein Kostenbetrag ist nicht als endlicher Centbetrag prüfbar."})
        if not costs:
            warnings.append({"code": "no_cost_items", "message": "Die lokale Periode enthält keine Kostenpositionen."})
        if not contracts:
            warnings.append({"code": "no_contracts", "message": "Für den Abrechnungszeitraum wurden keine überschneidenden Mietverträge gefunden."})
        warnings.append({"code": "portal_user_mapping_unverified", "message": "Lokale Parteien und Verträge sind keine bestätigten TEHA-Nutzerkennungen."})
    return {"local_valid": not problems, "issues": problems, "warnings": warnings, "summary": summary,
            "external_write_enabled": False, "portal_acceptance": "not_verified"}
