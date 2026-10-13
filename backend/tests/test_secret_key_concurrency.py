"""Workers sharing a data directory must never replace each other's encryption keys."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from backend.services import secret_box


def _concurrent_mutations(boxes, operation, monkeypatch):
    original_write = secret_box.write_private_file
    start = threading.Barrier(len(boxes))

    def slow_write(path, data):
        # Keep both independent workers in the read/modify/write window. A real
        # file lock serializes this; an instance-local lock cannot protect it.
        time.sleep(0.05)
        original_write(path, data)

    monkeypatch.setattr(secret_box, "write_private_file", slow_write)

    def mutate(box):
        start.wait(timeout=5)
        return operation(box)

    with ThreadPoolExecutor(max_workers=len(boxes)) as executor:
        return list(executor.map(mutate, boxes))


def test_simultaneous_first_secrets_share_one_persisted_key(tmp_path, monkeypatch):
    key_file = tmp_path / "keyring.json"
    boxes = [secret_box.SecretBox(key_file), secret_box.SecretBox(key_file)]
    tokens = _concurrent_mutations(boxes, lambda box: box.seal("secret", "field"), monkeypatch)
    restarted = secret_box.SecretBox(key_file)
    assert [restarted.open(token, "field") for token in tokens] == ["secret", "secret"]
    assert len(restarted.key_ids()) == 1


def test_simultaneous_rotations_retain_every_old_and_new_key(tmp_path, monkeypatch):
    key_file = tmp_path / "keyring.json"
    seed = secret_box.SecretBox(key_file)
    original = seed.seal("original", "field")
    boxes = [secret_box.SecretBox(key_file), secret_box.SecretBox(key_file)]
    rotated = _concurrent_mutations(boxes, lambda box: box.rotate(), monkeypatch)
    restarted = secret_box.SecretBox(key_file)
    assert set(rotated) <= set(restarted.key_ids())
    assert restarted.open(original, "field") == "original"
