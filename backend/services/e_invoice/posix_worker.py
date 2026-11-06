"""Apply resource limits in an owned child before exec, never in the web process."""
import os
import stat
import sys
import time
from importlib import import_module
from pathlib import Path


def main(arguments=None):
    args = list(sys.argv[1:] if arguments is None else arguments)
    if os.name == 'nt' or len(args) < 4:
        raise RuntimeError('POSIX invoice worker arguments required')
    folder, mode, seconds, *command = args
    owned = os.environ.get('E_INVOICE_LIMIT_DIR', '')
    if (not owned or Path(folder).resolve(strict=True) != Path(owned).resolve(strict=True)
            or not Path(folder).name.startswith('immo-e-invoice-')
            or mode not in ('java', 'extract', 'text', 'image', 'document')):
        raise RuntimeError('Owned invoice resource boundary required')
    seconds = int(seconds)
    if seconds < 5 or seconds > 180 or not Path(command[0]).is_absolute():
        raise RuntimeError('Invalid invoice process budget or executable')
    resource = import_module('resource')  # absent from Windows Python/type stubs
    memory = (3072 if mode == 'java' else 768) * 1024 * 1024
    file_bytes = (128 if mode in ('text', 'image', 'document') else 8) * 1024 * 1024
    # PDFium reserves inaccessible address pools far larger than its RSS. On
    # Darwin this AS/RSS alias can even reject setrlimit before exec. Only the
    # image/Darwin document modes substitute measured RSS/process budgets for AS.
    sampled = mode in ('image', 'document')
    limits = (() if sampled else ((resource.RLIMIT_AS, memory),)) + (
        (resource.RLIMIT_CPU, seconds), (resource.RLIMIT_CORE, 0),
        (resource.RLIMIT_FSIZE, file_bytes), (resource.RLIMIT_NOFILE, 128))
    for name, value in limits:
        _, hard = resource.getrlimit(name)
        if hard != resource.RLIM_INFINITY:
            value = min(value, hard)
        resource.setrlimit(name, (value, value))
    if sampled:
        gate = Path(folder) / 'image-budget-ready'
        deadline = time.monotonic() + min(seconds, 5)
        while True:
            try:
                info = gate.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_size != len(b'image-rss-ready\n'):
                    raise RuntimeError('Invalid image RSS monitor handshake')
                if gate.read_bytes() != b'image-rss-ready\n':
                    raise RuntimeError('Invalid image RSS monitor handshake')
                break
            except FileNotFoundError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Image RSS monitor handshake missing') from None
                time.sleep(.01)
    os.execvpe(command[0], command, os.environ)


if __name__ == '__main__':
    main()
