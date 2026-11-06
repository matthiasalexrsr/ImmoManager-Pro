"""Real protected full archives keep secrets/readiness at extended-length paths."""

from dataclasses import replace

from test_operations_backup import installation  # noqa: F401

from backend.services import full_backup, secret_box
from backend.services.filesystem_paths import filesystem_path


def test_deep_backup_probe_and_new_profile_keep_the_protected_bundle(installation, tmp_path):  # noqa: F811
    root = tmp_path
    while len(str(root)) < 285:
        root /= "synthetic-deep-backup-" + "x" * 30
    sources = replace(installation.sources, root=root / "archives", passphrase="owned-deep-backup-passphrase")
    event = full_backup.create_full_backup(sources=sources)
    archive = sources.root / event["archive"]
    assert len(str(archive)) > 300 and full_backup.verify_archive(archive)["ok"]
    probe = full_backup.restore_probe(archive, sources)
    assert probe["ok"] and probe["checks"]["secrets"]["decrypted"] == 1
    assert probe["checks"]["probe_dir_removed"]
    target = root / "new-owned-profile"
    restored = full_backup.restore_archive(archive, target, passphrase=sources.passphrase)
    assert restored["sessions"]["generation"] == "renewed"
    key_file = filesystem_path(target / "secrets/keyring.json")
    assert key_file.read_bytes() == installation.box.key_file.read_bytes()
    assert secret_box.SecretBox(key_file).key_ids() == installation.box.key_ids()
    assert not list(filesystem_path(sources.root).glob(".probe-*"))
    assert full_backup.read_events(sources.root)[0]["event"] == "restore_probe"
