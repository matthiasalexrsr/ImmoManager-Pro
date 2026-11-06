"""Stream only selected Qt/Chromium/test diagnostics; never save the raw stream."""

import re
import sys


DENY = re.compile(r"command.?line|(?:^|\s)--[a-z]|(?:authorization|cookie|bearer|token|password|secret)\s*[:=]|^\s*[A-Z][A-Z0-9_]*=", re.I)
ALLOW = re.compile(
    r"^(?:qt\.|js:|\s*(?:GL |Surface |QSG |RHI |GPU |Graphics |Vulkan |OpenGL |"
    r"Device |Driver |Backend |Chromium |Qt |is[A-Z]|use[A-Z])|"
    r"\[[0-9]+:[^\]]*\b(?:INFO|WARNING|ERROR|FATAL):|"
    r"test_|Ran [0-9]+ tests?|OK\b|FAILED\b|ERROR\b|FAIL:|Traceback |  File |"
    r"AssertionError|ValueError|RuntimeError|ImportError|ModuleNotFoundError|"
    r"QT_PDF_|PDFJS_RENDER_|-+$|=+$)", re.I
)


def selected(line):
    if DENY.search(line) or not ALLOW.search(line):
        return None
    # All fixture URLs are synthetic. Strip query/fragment values nevertheless.
    return re.sub(r"((?:https?|blob|chrome-extension|qrc)://[^\s?#]+)[?#][^\s]*", r"\1[query/fragment omitted]", line.rstrip())[:4096]


def main():
    emitted = 0
    omitted = 0
    for line in sys.stdin:
        filtered = selected(line)
        if filtered is not None and emitted < 20000:
            print(filtered, flush=True)
            emitted += 1
        else:
            omitted += 1
    print(f"DIAGNOSTIC_LOG_FILTER selected={emitted} omitted={omitted}", flush=True)


if __name__ == "__main__":
    main()
