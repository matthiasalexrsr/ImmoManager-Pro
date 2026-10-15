"""Workers sharing a data directory must never replace each other's encryption keys."""

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows byte-range lock semantics")
def test_empty_windows_lock_file_waits_without_an_unlocked_initialization_write(tmp_path, monkeypatch):
    import msvcrt

    key_file = tmp_path / "keyring.json"
    lock_file = key_file.with_name(key_file.name + ".lock")
    holder = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o600)
    locking = msvcrt.locking
    write = os.write
    attempted = threading.Event()
    entered = threading.Event()

    def observe_lock(descriptor, mode, count):
        if descriptor != holder and mode == msvcrt.LK_LOCK:
            attempted.set()
        return locking(descriptor, mode, count)

    def observe_write(descriptor, data):
        try:
            return write(descriptor, data)
        finally:
            if threading.current_thread().name.startswith("keyring-lock-waiter"):
                attempted.set()

    def wait_for_lock():
        with secret_box._keyring_write_lock(key_file):
            entered.set()

    try:
        # Windows locks may cover bytes beyond EOF. This is also the state a
        # worker with a stale zero-size fstat observes after another worker locks.
        locking(holder, msvcrt.LK_NBLCK, 1)
        monkeypatch.setattr(msvcrt, "locking", observe_lock)
        monkeypatch.setattr(secret_box.os, "write", observe_write)
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="keyring-lock-waiter") as executor:
            waiter = executor.submit(wait_for_lock)
            try:
                assert attempted.wait(timeout=5)
                assert not entered.is_set()
            finally:
                locking(holder, msvcrt.LK_UNLCK, 1)
            waiter.result(timeout=5)
    finally:
        os.close(holder)
    assert entered.is_set()
    assert lock_file.stat().st_size == 0
