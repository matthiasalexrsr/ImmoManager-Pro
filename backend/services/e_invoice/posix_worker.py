"""Apply resource limits in an owned child before exec, never in the web process."""
import os
import sys
from importlib import import_module
from pathlib import Path


def main(arguments=None):
    args = list(sys.argv[1:] if arguments is None else arguments)
    if os.name == 'nt' or len(args) < 4:
        raise RuntimeError('POSIX invoice worker arguments required')
    folder, mode, seconds, *command = args
    owned = os.environ.get('E_INVOICE_LIMIT_DIR', '')
    if (not owned or Path(folder).resolve(strict=True) != Path(owned).resolve(strict=True)
            or not Path(folder).name.startswith('immo-e-invoice-') or mode not in ('java', 'extract')):
        raise RuntimeError('Owned invoice resource boundary required')
    seconds = int(seconds)
    if seconds < 5 or seconds > 180 or not Path(command[0]).is_absolute():
        raise RuntimeError('Invalid invoice process budget or executable')
    resource = import_module('resource')  # absent from Windows Python/type stubs
    memory = (3072 if mode == 'java' else 768) * 1024 * 1024
    limits = ((resource.RLIMIT_AS, memory), (resource.RLIMIT_CPU, seconds),
              (resource.RLIMIT_CORE, 0), (resource.RLIMIT_FSIZE, 8 * 1024 * 1024), (resource.RLIMIT_NOFILE, 128))
    for name, value in limits:
        _, hard = resource.getrlimit(name)
        if hard != resource.RLIM_INFINITY:
            value = min(value, hard)
        resource.setrlimit(name, (value, value))
    os.execvpe(command[0], command, os.environ)


if __name__ == '__main__':
    main()
