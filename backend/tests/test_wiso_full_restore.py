"""Independent full-backup proof for the manual WISO worksheet and its frozen profile."""
import json
from datetime import date
from zipfile import ZipFile

from alembic import command
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db import schema_state
from backend.models import AccountCreate, CategoryCreate, PortfolioCreate, PropertyCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import annual_tax_storage as annual
from backend.services import full_backup, secret_box
from backend.services.annual_tax_export import prepare_download
from backend.services.wiso_preparation import saved_preparation
from backend.tax_models import AnnualTaxPreflightCreate
from backend.tests.test_annual_tax_projection import save_command
from backend.tests.test_wiso_preparation import wiso_cash, wiso_profile


def test_full_restore_preserves_manual_worksheet_profile_sources_and_exact_zip(tmp_path, monkeypatch):
    path = tmp_path / "source.sqlite3"
    url = "sqlite:///" + path.as_posix()
    command.upgrade(schema_state.alembic_config(url), "head")
    engine = create_engine(url)
    box = secret_box.SecretBox(tmp_path / "source-keyring.json")
    monkeypatch.setattr(annual, "default_secret_box", lambda: box)
    with Session(engine) as db:
        store = SQLAlchemyStore(db)
        portfolio = store.create_portfolio(PortfolioCreate(name="Synthetic restore portfolio"))
        properties = [store.create_property(PropertyCreate(portfolio_id=portfolio.id,
            name=f"Synthetic property {i}", property_type="residential")) for i in range(2)]
        accounts = [store.create_account(AccountCreate(portfolio_id=portfolio.id,
            name="Synthetic bank", account_type="bank"))]
        categories = [store.create_category(CategoryCreate(portfolio_id=portfolio.id,
            name=name, category_type=kind)) for name, kind in (("Rent", "income"), ("Costs", "expense"))]
        fixture = store, engine, portfolio, properties, accounts, categories
        wiso_cash(fixture)
        version = annual.create_profile(store, wiso_profile(fixture), "synthetic-actor")
        review = AnnualTaxPreflightCreate(profile_version_id=version["id"], as_of=date(2026, 10, 18))
        checked = annual.preflight(store, review)
        retained = annual.create_projection(store, save_command(review, checked), "synthetic-actor")
        original_report = saved_preparation(store, retained["id"])
        assert not original_report["vendor_file_ready"]
        download = prepare_download(store, retained["id"])
        try:
            original_bytes = download.path.read_bytes()
            with ZipFile(download.path) as zipped:
                assert json.loads(zipped.read("reviewed-profile.json"))["spec"]["wiso_preparation"]
        finally:
            download.close()
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "unchanged-source.bin").write_bytes(b"synthetic-source-original\x00\xff")
    sources = full_backup.Sources(database_url=url, data_dir=tmp_path, uploads_dir=uploads,
        root=tmp_path / "backups", integration_state=tmp_path / "absent-integrations.json",
        key_file=box.key_file, env_file=tmp_path / "absent.env")
    event = full_backup.create_full_backup("manual", sources)
    archive = sources.root / event["archive"]
    assert full_backup.verify_archive(archive)["ok"]
    probe = full_backup.restore_probe(archive, sources)
    assert probe["ok"] and probe["checks"]["secrets"]["tax_receipts_verified"] == 1
    restored = tmp_path / "restored"
    full_backup.restore_archive(archive, restored)
    assert (restored / "uploads/unchanged-source.bin").read_bytes() == b"synthetic-source-original\x00\xff"
    restored_box = secret_box.SecretBox(restored / full_backup.KEYRING)
    monkeypatch.setattr(annual, "default_secret_box", lambda: restored_box)
    restored_engine = create_engine("sqlite:///" + (restored / "immo_manager.db").as_posix())
    try:
        with Session(restored_engine) as db:
            recovered = SQLAlchemyStore(db)
            assert saved_preparation(recovered, retained["id"]) == original_report
            assert annual.get_profile(recovered, version["id"]) == version
            download = prepare_download(recovered, retained["id"])
            try:
                assert download.path.read_bytes() == original_bytes
            finally:
                download.close()
    finally:
        restored_engine.dispose()
        engine.dispose()
