# Mietvertrag-Wizard – Python Integration

## Highlights

- 8-Schritte-Wizard, Mehrfach-Vermieter/-Mieter
- Vorschau im Browser + validierter PDF-Export (serverseitig via FastAPI/ReportLab; pdfMake nur ohne konfigurierte Server-API)
- Druckansicht per `@media print`
- Tooltips: native Browser-Tooltips (`title`)
- Speichern/Laden (localStorage) + JSON Export/Import **inkl. dynamischer Blöcke**; Bank-/SEPA-Daten werden nicht dauerhaft im Browser-State gespeichert
- Expertenmodus (CSS: `body.expert-mode`)
- Keine CDN-Abhängigkeiten

## FastAPI

```python
from fastapi import FastAPI
from mietvertrag_wizard import mount_fastapi

app = FastAPI()
mount_fastapi(app, mount_path="/mietvertrag", static_path="/mietvertrag/static")

# UI:   GET  /mietvertrag
# PDF:  POST /mietvertrag/api/pdf   (Body: Wizard-JSON)
```

## Flask

```python
from flask import Flask
from mietvertrag_wizard import create_blueprint

app = Flask(__name__)
app.register_blueprint(create_blueprint(url_prefix="/mietvertrag", static_url_path="/mietvertrag/static"))
```
