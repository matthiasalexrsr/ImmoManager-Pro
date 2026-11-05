"""Windowed desktop manager for the local ImmoManager application."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
import tomllib
import webbrowser
from pathlib import Path
from typing import Any

from backend.desktop_control import (
    READY_PREFIX,
    acquire_instance_guard,
    hold_installation_mutex,
    instance_key,
    instance_window,
    ready_message,
)
from backend.services.runtime_process import frozen_cli_executable

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
TEAL, INK, MUTED, BACKGROUND = "#176B63", "#173431", "#5E7472", "#F1F6F5"


class DesktopSession:
    """Own one hidden child, its two private pipes, and a bounded diagnostic log."""

    def __init__(self, args, data_dir: Path, instance_guard=None):
        self.args, self.data_dir = args, data_dir
        self.instance_guard = instance_guard
        self.url = f"http://{args.host}:{args.port}"
        self.token = secrets.token_hex(32)
        self.process: subprocess.Popen[str] | None = None
        self.events: queue.Queue[str] = queue.Queue()
        self.log_path = data_dir / "logs" / "desktop.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logging.Logger("desktop-child", level=logging.INFO)
        self.handler = logging.handlers.RotatingFileHandler(self.log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        self.handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        self.logger.addHandler(self.handler)

    def start(self):
        command = [frozen_cli_executable()]
        if not getattr(sys, "frozen", False):
            command += ["-m", "backend"]
        command += ["--no-browser", "--host", self.args.host, "--port", str(self.args.port),
                    "--data-dir", str(self.data_dir), "--desktop-token", self.token]
        for flag in ("seed", "testversion", "demo", "no_upgrade"):
            if getattr(self.args, flag, False):
                command.append("--" + flag.replace("_", "-"))
        environment = dict(os.environ, DATA_DIR=str(self.data_dir), PYTHONUTF8="1", PYTHONUNBUFFERED="1")
        environment.pop("IMMO_DESKTOP_INSTANCE_FD", None)
        process_options = {}
        if self.instance_guard is not None:
            environment.update(self.instance_guard.child_environment())
            process_options.update(self.instance_guard.child_process_options())
        self.process = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), **process_options)
        threading.Thread(target=self._read_output, name="desktop-log", daemon=True).start()

    def _read_output(self):
        assert self.process is not None and self.process.stdout is not None
        try:
            for line in self.process.stdout:
                if line.startswith(READY_PREFIX):
                    if ready_message(line, token=self.token, pid=self.process.pid, url=self.url, allow_child_pid=True):
                        self.logger.info("Anwendung bereit.")
                        self.events.put("ready")
                    else:
                        self.logger.warning("Ungültige Startbestätigung ignoriert.")
                else:
                    self.logger.info(line.rstrip("\r\n"))
        except (OSError, ValueError):
            self.events.put("log_error")
        finally:
            self.events.put("output_closed")

    def stop(self):
        if self.process is not None and self.process.poll() is None and self.process.stdin is not None:
            try:
                self.process.stdin.write("STOP " + self.token + "\n")
                self.process.stdin.flush()
                self.process.stdin.close()
            except (BrokenPipeError, OSError, ValueError):
                pass

    def close(self):
        if self.process is not None:
            for stream in (self.process.stdin, self.process.stdout):
                if stream is not None:
                    stream.close()
        self.handler.close()


def _arguments(argv=None):
    parser = argparse.ArgumentParser(description="ImmoManager Pro – Desktop")
    parser.add_argument("--data-dir")
    parser.add_argument("--mode", choices=("standalone", "browser"), default="standalone")
    parser.add_argument("--software-rendering", action="store_true", help="Use software graphics for the standalone desktop")
    parser.add_argument("--port", type=int)
    parser.add_argument("--host", choices=("127.0.0.1", "localhost"), default="127.0.0.1")
    data_mode = parser.add_mutually_exclusive_group()
    data_mode.add_argument("--seed", action="store_true")
    data_mode.add_argument("--testversion", action="store_true")
    data_mode.add_argument("--demo", action="store_true", help="Open the separate Baden-Württemberg demo workspace")
    parser.add_argument("--no-upgrade", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    from backend import demo

    args.demo = args.demo or demo.enabled()
    if args.demo and (args.seed or args.testversion):
        parser.error("--demo cannot be combined with --seed or --testversion")
    if args.port is None:
        args.port = 8766 if args.demo else 8000
    if not 1 <= args.port <= 65535:
        parser.error("Der Port muss zwischen 1 und 65535 liegen.")
    return args


def _data_directory(args) -> Path:
    from backend import demo

    if getattr(args, "demo", False) or demo.enabled():
        args.demo = True
        return demo.configure_environment(args.data_dir)
    from backend.__main__ import _default_data_dir, _exe_dir, _is_testversion, _load_env_file

    _load_env_file(os.path.join(_exe_dir(), ".env"))
    value = args.data_dir or os.environ.get("DATA_DIR")
    if not value:
        value = _default_data_dir(testversion=args.testversion or _is_testversion())
    return Path(value).expanduser().resolve()


def main(argv=None):
    args = _arguments(argv)
    if args.mode == "standalone":
        from backend.standalone import main as standalone_main

        return standalone_main(args)
    return browser_main(args)


def browser_main(args):
    import tkinter as tk
    from tkinter import messagebox, ttk

    data_dir = _data_directory(args)
    key = instance_key(data_dir)
    instance = acquire_instance_guard(data_dir)
    install_guard = hold_installation_mutex()
    if instance.existed:
        if not instance_window(key):
            ctypes_message("ImmoManager Pro wird für diesen Datenordner bereits gestartet. Bitte warten Sie einen Moment.")
        instance.close()
        install_guard.close()
        return 0
    if os.name == "nt":
        import ctypes

        try:
            user = getattr(ctypes, "WinDLL")("user32", use_last_error=True)
            user.SetProcessDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
            user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass
        try:
            shell = getattr(ctypes, "WinDLL")("shell32")
            shell.SetCurrentProcessExplicitAppUserModelID.argtypes = (ctypes.c_wchar_p,)
            shell.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
            shell.SetCurrentProcessExplicitAppUserModelID("ImmoManagerPro.Desktop")
        except (AttributeError, OSError):
            pass
    window = tk.Tk()
    window.title("ImmoManager Pro")
    window.configure(bg=BACKGROUND)
    scale = max(1.0, float(window.tk.call("tk", "scaling")) / (96 / 72))
    window.minsize(round(620 * scale), round(400 * scale))
    width, height = round(700 * scale), round(444 * scale)
    x, y = (window.winfo_screenwidth() - width) // 2, (window.winfo_screenheight() - height) // 2
    window.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
    icon = ROOT / "assets" / "immomanager.ico"
    if os.name == "nt" and icon.is_file():
        window.iconbitmap(str(icon))
    window.option_add("*Font", "{Segoe UI} 10")
    style = ttk.Style(window)
    style.theme_use("clam")
    style.configure("TProgressbar", troughcolor="#DCEAE6", background=TEAL, borderwidth=0, thickness=4)
    header = tk.Frame(window, bg="#103E3A", padx=28, pady=22)
    header.pack(fill="x")
    tk.Label(header, text="IMMO / MANAGER", font=("Segoe UI", 10, "bold"), fg="#B6DDD5", bg="#103E3A").pack(anchor="w")
    tk.Label(header, text="Ihre Immobilien. Alles im Blick.", font=("Segoe UI", 22, "bold"), fg="white", bg="#103E3A").pack(anchor="w", pady=(5, 0))
    body = tk.Frame(window, bg=BACKGROUND, padx=28, pady=22)
    body.pack(fill="both", expand=True)
    card = tk.Frame(body, bg="white", highlightbackground="#DCE6E3", highlightthickness=1, padx=20, pady=18)
    card.pack(fill="both", expand=True)
    status = tk.StringVar(value="ImmoManager Pro wird gestartet …")
    detail = tk.StringVar(value="Ihre Anwendung wird vorbereitet. Dieser Vorgang kann beim ersten Start etwas länger dauern.")
    tk.Label(card, textvariable=status, font=("Segoe UI", 14, "bold"), fg=INK, bg="white", anchor="w").pack(fill="x")
    description = tk.Label(card, textvariable=detail, fg=MUTED, bg="white", justify="left", anchor="w", wraplength=570)
    description.pack(fill="x", pady=(8, 13))
    card.bind("<Configure>", lambda event: description.configure(wraplength=max(200, event.width - 42)))
    progress = ttk.Progressbar(card, mode="indeterminate")
    progress.pack(fill="x", pady=(0, 14))
    progress.start(15)
    buttons = tk.Frame(card, bg="white")
    buttons.pack(fill="x")
    button_options: dict[str, Any] = dict(font=("Segoe UI", 10, "bold"), padx=16, pady=9, relief="flat", borderwidth=0, cursor="hand2")
    open_button = tk.Button(buttons, text="Anwendung öffnen", bg=TEAL, fg="white", activebackground="#12534D", activeforeground="white", state="disabled", **button_options)
    open_button.pack(side="left")
    quit_button = tk.Button(buttons, text="Beenden", bg="#EAF1EF", fg=INK, activebackground="#DCE7E3", **button_options)
    quit_button.pack(side="right")
    footer = tk.Frame(body, bg=BACKGROUND)
    footer.pack(fill="x", pady=(15, 0))
    try:
        version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    except (OSError, ValueError, KeyError):
        version = ""
    tk.Label(footer, text=f"ImmoManager Pro  {version}", bg=BACKGROUND, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")
    log_button = tk.Button(footer, text="Startprotokoll öffnen", bg=BACKGROUND, fg=TEAL, relief="flat", cursor="hand2", font=("Segoe UI", 9))
    log_button.pack(side="right")
    window.update_idletasks()
    instance_window(key, window.winfo_id())
    session = None
    closing, is_ready = False, False
    stopped_at = None

    def open_browser():
        if session is not None and is_ready and session.process.poll() is None:
            if not webbrowser.open(session.url):
                messagebox.showinfo("Anwendung öffnen", "Bitte öffnen Sie diese Adresse in Ihrem Browser:\n" + session.url, parent=window)

    def show_log():
        if session is not None and session.log_path.is_file():
            try:
                if os.name == "nt":
                    getattr(os, "startfile")(str(session.log_path))
                else:
                    webbrowser.open(session.log_path.as_uri())
            except OSError as exc:
                messagebox.showerror("Startprotokoll", f"Das Protokoll konnte nicht geöffnet werden.\n{session.log_path}\n\n{exc}", parent=window)

    def close():
        nonlocal closing, stopped_at
        if session is not None and session.process is not None and session.process.poll() is None:
            if closing:
                messagebox.showinfo("Anwendung wird beendet", "ImmoManager Pro schließt laufende Vorgänge ab. Bitte lassen Sie dieses Fenster bis zum Abschluss geöffnet.", parent=window)
                return
            if not messagebox.askyesno("ImmoManager Pro beenden?", "Die lokale Anwendung wird beendet. Bitte schließen Sie vorher Ihre Bearbeitung im Browser ab.", parent=window):
                return
            closing, stopped_at = True, time.monotonic()
            open_button.configure(state="disabled")
            status.set("ImmoManager Pro wird beendet …")
            detail.set("Laufende Vorgänge werden abgeschlossen und die Anwendung wird geordnet geschlossen.")
            progress.configure(mode="indeterminate", value=0)
            progress.start(15)
            session.stop()
        else:
            window.destroy()

    def poll():
        nonlocal is_ready
        if session is not None and session.process is not None:
            code = session.process.poll()
            if code is not None:
                open_button.configure(state="disabled")
                progress.stop()
                progress.configure(mode="determinate", value=0)
                if closing:
                    window.destroy()
                    return
                status.set("Die Anwendung wurde beendet." if is_ready and code == 0 else "Die Anwendung konnte nicht gestartet werden.")
                detail.set("Sie können dieses Fenster schließen." if is_ready and code == 0 else "Möglicherweise ist die Adresse bereits belegt oder die Konfiguration muss geprüft werden. Weitere Informationen finden Sie im Startprotokoll.")
            else:
                while not session.events.empty():
                    event = session.events.get_nowait()
                    if event == "ready" and not closing:
                        is_ready = True
                        status.set("Ihre Anwendung ist bereit.")
                        detail.set("ImmoManager Pro läuft auf diesem Computer. Öffnen Sie Ihre Verwaltung im Browser. Zum vollständigen Beenden verwenden Sie dieses Fenster.")
                        progress.stop()
                        progress.configure(mode="determinate", value=100)
                        open_button.configure(state="normal")
                        if not args.no_browser:
                            open_browser()
                if closing and stopped_at is not None and time.monotonic() - stopped_at > 30:
                    detail.set("Das Beenden dauert länger, weil möglicherweise noch ein Vorgang läuft. Die Anwendung bleibt erreichbar, bis dieser geordnet abgeschlossen ist.")
        window.after(150, poll)

    open_button.configure(command=open_browser)
    quit_button.configure(command=close)
    log_button.configure(command=show_log)
    window.protocol("WM_DELETE_WINDOW", close)
    try:
        session = DesktopSession(args, data_dir, instance_guard=instance)
        session.start()
    except Exception as exc:
        status.set("Die Anwendung konnte nicht gestartet werden.")
        detail.set("Bitte prüfen Sie die Installation und den Datenordner. " + str(exc))
        progress.stop()
        progress.configure(mode="determinate", value=0)
    window.after(150, poll)
    try:
        window.mainloop()
    finally:
        if session is not None:
            session.stop()
            session.close()
        instance.close()
        install_guard.close()
    return 0


def ctypes_message(text: str):
    if os.environ.get("QT_QPA_PLATFORM", "").split(":", 1)[0] in {"offscreen", "minimal"}:
        print(text, file=sys.stderr)
        return
    if os.name == "nt":
        import ctypes

        getattr(ctypes, "windll").user32.MessageBoxW(None, text, "ImmoManager Pro", 0x40)
    else:
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("ImmoManager Pro", text, parent=root)
            root.destroy()
        except Exception:
            print(text, file=sys.stderr)
