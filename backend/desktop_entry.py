"""PyInstaller's windowed entry point, kept separate from the maintenance CLI."""

import multiprocessing
import runpy
import sys


def report_startup_failure(error):
    """Keep an actionable traceback when Qt fails before a window can exist."""
    import logging
    from logging.handlers import RotatingFileHandler

    from backend.desktop import _arguments, _data_directory, ctypes_message

    message = "ImmoManager Pro konnte nicht gestartet werden.\n\n" + str(error)
    try:
        destination = _data_directory(_arguments()) / "logs" / "desktop-startup.log"
        destination.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(destination, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger = logging.Logger("desktop-startup")
        logger.addHandler(handler)
        try:
            logger.error("Desktop startup failed", exc_info=(type(error), error, error.__traceback__))
        finally:
            logger.removeHandler(handler)
            handler.close()
        message += "\n\nStartprotokoll: " + str(destination)
    except Exception:
        # Reporting must not hide the original startup error, even when a disk
        # or the explicitly selected data directory itself is unavailable.
        pass
    ctypes_message(message)

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from backend.desktop_control import ensure_standard_streams

    ensure_standard_streams()
    # Older callers may re-execute sys.executable for a file-based worker. These
    # operations must bypass Tk completely. New worker calls use the CLI sibling.
    if sys.argv[1:2] and sys.argv[1] in {
        "document-text-worker", "document-pdf-worker", "e-invoice-read-worker",
        "e-invoice-limit-worker", "upgrade", "ops",
    }:
        runpy.run_module("backend.__main__", run_name="__main__")
    else:
        try:
            from backend.desktop import main

            raise SystemExit(main())
        except Exception as exc:
            report_startup_failure(exc)
            raise SystemExit(1) from exc
