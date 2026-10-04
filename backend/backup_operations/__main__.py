"""External full backup CLI. Scheduling never imports the web application."""

import argparse
import getpass
import json
import os
import subprocess
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

from scripts.private_server_backup import BackupError, _windows_sid, private_workspace, protected_new_file

from .journal import Journal
from .plan import BackupOperationError, BackupPlan, Installation
from .runner import run_once
from .state import load_plan, passphrase, plan_lock, private_directory, read_json, save_plan


def task_name(plan):
    return "ImmoManagerPro-FullBackup-" + str(plan.id)


def run_arguments(plan, directory):
    prefix = ["--backup-operations"] if plan.installation.packaged else ["-m", "backend.backup_operations"]
    return prefix + ["run", "--plan-dir", str(directory)]


def task_xml(plan, directory):
    task = Element("Task", {"version": "1.4", "xmlns": "http://schemas.microsoft.com/windows/2004/02/mit/task"})
    trigger = SubElement(SubElement(task, "Triggers"), "CalendarTrigger")
    repetition = SubElement(trigger, "Repetition")
    SubElement(repetition, "Interval").text = "PT15M"
    SubElement(repetition, "Duration").text = "P1D"
    SubElement(trigger, "StartBoundary").text = (datetime.now() + timedelta(minutes=1)).replace(second=0, microsecond=0).isoformat()
    SubElement(trigger, "Enabled").text = "true"
    SubElement(SubElement(trigger, "ScheduleByDay"), "DaysInterval").text = "1"
    principal = SubElement(SubElement(task, "Principals"), "Principal", {"id": "Author"})
    SubElement(principal, "UserId").text = _windows_sid()
    SubElement(principal, "LogonType").text = "InteractiveToken"
    SubElement(principal, "RunLevel").text = "LeastPrivilege"
    settings = SubElement(task, "Settings")
    for name, value in (("MultipleInstancesPolicy", "IgnoreNew"), ("DisallowStartIfOnBatteries", "false"),
                        ("StopIfGoingOnBatteries", "false"), ("StartWhenAvailable", "true"),
                        ("ExecutionTimeLimit", "PT0S"), ("Enabled", "true"), ("Hidden", "true")):
        SubElement(settings, name).text = value
    command = SubElement(SubElement(task, "Actions", {"Context": "Author"}), "Exec")
    SubElement(command, "Command").text = str(plan.installation.python)
    SubElement(command, "Arguments").text = subprocess.list2cmdline(run_arguments(plan, directory))
    SubElement(command, "WorkingDirectory").text = str(plan.installation.app_root)
    return tostring(task, encoding="utf-16", xml_declaration=True)


def schedule(plan, directory, remove=False):
    if os.name != "nt":
        raise BackupOperationError("use_systemd_timer_files_on_this_platform")
    if remove:
        command = ["schtasks", "/delete", "/tn", task_name(plan), "/f"]
        subprocess.run(command, capture_output=True, check=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        # Reviewable task XML contains paths only; credentials remain in private files.
        with private_workspace() as (workspace, _):
            path = workspace / "full-backup-task.xml"
            path.write_bytes(task_xml(plan, directory))
            subprocess.run(["schtasks", "/create", "/tn", task_name(plan), "/xml", str(path), "/f"],
                capture_output=True, check=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    return {"task": task_name(plan), "registered": not remove}


def _unit_quote(value):
    # systemd expands percent specifiers even in quoted arguments.
    if any(ord(character) < 32 for character in str(value)):
        raise BackupOperationError("scheduler_path_contains_control_character")
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def timer_files(plan, directory, output):
    output = private_directory(output)
    name = "immomanager-full-backup-" + str(plan.id)
    command = " ".join(_unit_quote(value) for value in [plan.installation.python, *run_arguments(plan, directory)])
    service = f"[Unit]\nDescription=ImmoManager complete encrypted backups and restore exercises\n\n[Service]\nType=oneshot\nWorkingDirectory={_unit_quote(plan.installation.app_root)}\nExecStart={command}\nUMask=0077\n"
    timer = f"[Unit]\nDescription=Poll ImmoManager complete backup plan\n\n[Timer]\nOnCalendar=*:0/15\nPersistent=true\nUnit={name}.service\n\n[Install]\nWantedBy=timers.target\n"
    for suffix, raw in (("service", service), ("timer", timer)):
        with protected_new_file(output / (name + "." + suffix)) as handle:
            handle.write(raw.encode())
    return {"timer": name + ".timer", "directory": str(output), "installed": False}


def status(directory):
    with plan_lock(directory):
        plan = load_plan(directory)
        with Journal(directory) as journal:
            runs = []
            for item in journal.recent():
                document = item["document"]
                runs.append({key: item[key] for key in ("id", "kind", "period", "created", "updated", "status", "error", "retry_at")}
                            | {"phase": document.get("phase"), "resume_required": "resume" in document,
                               "probe_cleanup_required": "probe_ownership" in document})
            return {"plan_id": str(plan.id), "revision": plan.revision, "enabled": plan.enabled,
                    "timezone": plan.timezone, "daily_at": plan.daily_at.isoformat(), "monthly_at": plan.monthly_at.isoformat(),
                    "retention_days": plan.retention_days, "secondary_configured": plan.second_destination is not None,
                    "retention_error": journal.get_metadata("retention_error"), "runs": runs}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verschlüsselte Vollbackups täglich und isolierte Restoreprobe monatlich")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "configure", "run", "status", "schedule", "unschedule", "timer-files"):
        command = commands.add_parser(name)
        command.add_argument("--plan-dir", type=Path, required=True)
        if name == "init":
            command.add_argument("--backend", choices=["sqlite", "private_server"], default="sqlite")
            command.add_argument("--app-root", type=Path, required=True)
            command.add_argument("--python", type=Path, default=Path(sys.executable))
            command.add_argument("--packaged", action="store_true", help="--python ist die gebaute ImmoManager.exe")
            command.add_argument("--data-dir", type=Path)
            command.add_argument("--project")
            command.add_argument("--compose-file", type=Path)
            command.add_argument("--env-file", type=Path)
            command.add_argument("--destination", type=Path, required=True)
            command.add_argument("--second-destination", type=Path)
            command.add_argument("--key-file", type=Path, required=True)
            command.add_argument("--timezone", default="Europe/Berlin")
            command.add_argument("--retention-days", type=int, default=90)
            command.add_argument("--capacity-file", type=Path)
        elif name == "configure":
            command.add_argument("--definition", type=Path, required=True)
            command.add_argument("--expected-revision", type=int, required=True)
        elif name == "run":
            command.add_argument("--force", choices=["backup", "probe"])
        elif name == "timer-files":
            command.add_argument("--output", type=Path, required=True)
    key = commands.add_parser("key-new", help="Neue private Passphrasedatei interaktiv erstellen")
    key.add_argument("--key-file", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
        if args.command == "key-new":
            if not sys.stdin.isatty():
                raise BackupOperationError("interactive_passphrase_terminal_required")
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                value = getpass.getpass("Sicherungspassphrase (mindestens 12 Zeichen): ")
                if len(value) < 12 or value != getpass.getpass("Passphrase wiederholen: ") or "\x00" in value:
                    raise BackupOperationError("backup_passphrase_invalid")
            with protected_new_file(args.key_file.absolute()) as handle:
                handle.write(value.encode("utf-8"))
            result = {"private_key_file_created": True}
        else:
            directory = private_directory(args.plan_dir.absolute())
            if args.command == "init":
                installation = Installation(**{key: getattr(args, key) for key in ("backend", "app_root", "python", "packaged", "data_dir", "project", "compose_file", "env_file")})
                plan = BackupPlan(installation=installation, destination=args.destination, second_destination=args.second_destination,
                    key_files={"initial": args.key_file}, timezone=args.timezone, retention_days=args.retention_days, capacity_file=args.capacity_file)
                passphrase(plan)  # Validate the private key before enabling any downtime.
                save_plan(directory, plan)
                result = {"plan_id": str(plan.id), "revision": plan.revision, "saved": True}
            elif args.command == "configure":
                plan = BackupPlan.model_validate(read_json(args.definition))
                passphrase(plan)
                save_plan(directory, plan, expected_revision=args.expected_revision)
                result = {"plan_id": str(plan.id), "revision": plan.revision, "saved": True}
            elif args.command == "run":
                result = run_once(directory, force=args.force)
            elif args.command == "status":
                result = status(directory)
            else:
                with plan_lock(directory):
                    plan = load_plan(directory)
                    result = timer_files(plan, directory, args.output.absolute()) if args.command == "timer-files" else schedule(plan, directory, args.command == "unschedule")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 1 if result.get("state") == "attention" else 0
    except BackupOperationError as error:
        code = error.code
    except (BackupError, OSError, ValueError, subprocess.SubprocessError, EOFError, getpass.GetPassWarning):
        code = "backup_operation_failed"
    except KeyboardInterrupt:
        code = "backup_operation_interrupted_resume_receipt_retained"
    except Exception:
        code = "backup_operation_failed"
    print(json.dumps({"state": "attention", "error": code}), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
