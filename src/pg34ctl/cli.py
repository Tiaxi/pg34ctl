"""Command-line interface: ``pg34ctl aspect 16:9`` and friends."""

from __future__ import annotations

import argparse
import sys

from .aspect import Aspect, AspectError, Scaling, current_aspect, switch_aspect
from .ddc import DdcError, MonitorNotFound, UnsupportedFeature, open_backend
from .features import BY_KEY, FEATURES, Feature, Kind
from .monitor import Monitor

SCALING_NAMES = {"pixel": Scaling.PIXEL_BY_PIXEL, "full": Scaling.FULL}


def _parse_code(text: str) -> int:
    code = int(text, 16)
    if not 0 <= code <= 0xFF:
        raise argparse.ArgumentTypeError(f"VCP code out of range: {text}")
    return code


def _parse_value(feature: Feature, text: str) -> int:
    wanted = text.strip().lower()
    if feature.kind is Kind.TOGGLE and wanted in ("on", "off", "1", "0", "true", "false"):
        return 1 if wanted in ("on", "1", "true") else 0
    if feature.kind is Kind.CHOICE:
        squashed = wanted.replace(" ", "")
        labels = {value: label.lower().replace(" ", "") for value, label in feature.choices.items()}
        exact = [value for value, label in labels.items() if label == squashed]
        prefixed = [value for value, label in labels.items() if label.startswith(squashed)]
        if exact or len(prefixed) == 1:
            return (exact or prefixed)[0]
    try:
        return int(text, 0)
    except ValueError:
        options = ", ".join(feature.choices.values()) or "a number"
        raise SystemExit(f"{feature.label}: expected {options}, got {text!r}") from None


def _feature_line(state) -> str:
    feature = state.feature
    if state.value is None:
        shown = "(no answer)"
    elif state.locked:
        shown = "(greyed out in the current mode)"
    elif not state.available:
        shown = "(not available now)"
    else:
        shown = feature.label_for(state.value)
        if feature.kind is Kind.RANGE:
            shown += f" / {state.maximum}"
    flag = "" if feature.verified else "  ?"
    return f"{feature.key:26} {feature.label:30} {shown}{flag}"


def cmd_status(monitor: Monitor, _args) -> None:
    backend = monitor.backend
    rows = [
        ("Monitor", f"ASUS PG34WCDN on {backend.description}"),
        ("Firmware", monitor.firmware()),
        ("Usage", f"{monitor.usage_hours()} h"),
        ("Aspect", current_aspect(backend).value),
    ]
    states = monitor.read_all([BY_KEY[k] for k in ("gamevisual", "power_setting", "hdr_mode")])
    for state in states.values():
        value = state.feature.label_for(state.value) if state.available else "Off"
        rows.append((state.feature.label, value))
    for label, value in rows:
        print(f"{label + ':':15}{value}")


def cmd_aspect(monitor: Monitor, args) -> None:
    backend = monitor.backend
    if args.ratio is None:
        print(current_aspect(backend).value)
        return
    if args.ratio == "toggle":
        now = current_aspect(backend)
        target = Aspect.STANDARD if now is Aspect.WIDE else Aspect.WIDE
    else:
        target = Aspect(args.ratio)
    changed = switch_aspect(backend, target, SCALING_NAMES[args.scaling], on_step=print)
    print(f"Aspect is {target.value}" + ("" if changed else " (unchanged)"))


def cmd_list(monitor: Monitor, _args) -> None:
    for state in monitor.read_all().values():
        print(_feature_line(state))
    print("\n? = mapping taken from DisplayWidget Center, not yet confirmed on this monitor")


def _resolve(target: str) -> Feature | int:
    if target in BY_KEY:
        return BY_KEY[target]
    try:
        return _parse_code(target)
    except (ValueError, argparse.ArgumentTypeError):
        raise SystemExit(f"unknown feature {target!r}; see 'pg34ctl list'") from None


def cmd_get(monitor: Monitor, args) -> None:
    target = _resolve(args.feature)
    if isinstance(target, Feature):
        print(_feature_line(monitor.read(target)))
        return
    reading = monitor.backend.get_vcp(target)
    print(f"VCP 0x{target:02X}: current 0x{reading.current:04X}  max 0x{reading.maximum:04X}")


def cmd_set(monitor: Monitor, args) -> None:
    target = _resolve(args.feature)
    if isinstance(target, Feature):
        if target.confirm and not args.yes:
            raise SystemExit(f"{target.confirm} Re-run with --yes to do it anyway.")
        print(_feature_line(monitor.write(target, _parse_value(target, args.value))))
        return
    if not args.yes:
        raise SystemExit("Writing a raw VCP code can do anything. Re-run with --yes.")
    monitor.backend.set_vcp(target, int(args.value, 0))


def cmd_dump(monitor: Monitor, args) -> None:
    codes = range(1, 0x100) if args.all else sorted({f.code for f in FEATURES} | {0xC0, 0xFF})
    for code in codes:
        try:
            r = monitor.backend.get_vcp(code)
            print(f"{code:02X} current=0x{r.current:04X} max=0x{r.maximum:04X}")
        except UnsupportedFeature:
            if not args.all:
                print(f"{code:02X} unsupported")
        except DdcError as exc:
            print(f"{code:02X} error: {exc}")


def cmd_caps(monitor: Monitor, _args) -> None:
    print(monitor.backend.capabilities())


def cmd_pixel_cleaning(monitor: Monitor, args) -> None:
    if not args.yes:
        raise SystemExit(
            "Pixel cleaning blanks the screen for about 6-8 minutes. Re-run with --yes."
        )
    monitor.start_pixel_cleaning()
    print("Pixel cleaning started.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pg34ctl", description=__doc__)
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="model, firmware, aspect mode and picture mode")
    p = sub.add_parser("aspect", help="show or switch the 21:9 / 16:9 aspect mode")
    p.add_argument("ratio", nargs="?", choices=["21:9", "16:9", "toggle"])
    p.add_argument("--scaling", choices=SCALING_NAMES, default="pixel")
    sub.add_parser("list", help="every known setting and its current value")
    p = sub.add_parser("get", help="read a setting by name or raw hex VCP code")
    p.add_argument("feature")
    p = sub.add_parser("set", help="change a setting, e.g. 'set gamevisual racing'")
    p.add_argument("feature")
    p.add_argument("value")
    p.add_argument("--yes", action="store_true", help="skip safety refusals")
    p = sub.add_parser("dump", help="raw VCP values for debugging")
    p.add_argument("--all", action="store_true", help="probe every code 0x01-0xFF")
    sub.add_parser("caps", help="print the DDC/CI capabilities string")
    p = sub.add_parser("pixel-cleaning", help="start an OLED pixel cleaning run")
    p.add_argument("--yes", action="store_true")
    sub.add_parser("gui", help="open the settings window")
    return parser


COMMANDS = {
    "status": cmd_status,
    "aspect": cmd_aspect,
    "list": cmd_list,
    "get": cmd_get,
    "set": cmd_set,
    "dump": cmd_dump,
    "caps": cmd_caps,
    "pixel-cleaning": cmd_pixel_cleaning,
}


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command in (None, "gui"):
        from .gui.app import main as gui_main

        gui_main()
        return
    try:
        monitor = Monitor(open_backend())
    except MonitorNotFound as exc:
        sys.exit(f"pg34ctl: {exc}")
    try:
        COMMANDS[args.command](monitor, args)
    except (AspectError, DdcError, MonitorNotFound, ValueError, OSError) as exc:
        sys.exit(f"pg34ctl: {exc}")
    finally:
        monitor.close()
