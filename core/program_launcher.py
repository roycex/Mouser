"""Program launch targets: pure logic for the ``launch:<target_id>`` action.

This module deliberately has **no** UI-toolkit dependency -- it is imported by
the mouse-hook side (via :mod:`core.key_simulator`) and by the backend, and it
must stay importable in environments where the UI toolkit is unavailable.

Responsibilities
----------------
* action-id encoding / decoding (``launch:<target_id>``)
* launch-target normalization and validation
* launch-argument tokenization (deterministic, Windows-path safe)
* argv construction (with the macOS ``.app`` bundle fork)
* the actual process start via :func:`launch_target`

Everything here is fault tolerant: configuration files are plain JSON that a
user may edit by hand, so no public function raises on malformed input except
:func:`parse_launch_args`, which signals malformed *user text*.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from collections import deque

LAUNCH_ACTION_PREFIX = "launch:"
LAUNCH_MISSING_PREFIX = "Launch: "          # label prefix for dangling targets
MAX_TARGET_NAME_LEN = 64

# Defensive upper bound on tokenized arguments: keeps a hand-edited config
# entry from asking for an absurd argv.
MAX_ARG_TOKENS = 64


class LaunchArgsError(ValueError):
    """Raised when a launch-args text cannot be tokenized."""


# ==================================================================
# Action id encoding / decoding
# ==================================================================

def launch_action_id(target_id):
    """Build ``'launch:<target_id>'``.  Returns ``''`` for an empty id."""
    if not target_id:
        return ""
    if not isinstance(target_id, str):
        target_id = str(target_id)
    target_id = target_id.strip()
    if not target_id:
        return ""
    return LAUNCH_ACTION_PREFIX + target_id


def is_launch_action(action_id):
    """True when *action_id* is a ``launch:`` action with a non-empty payload."""
    if not isinstance(action_id, str):
        return False
    return (action_id.startswith(LAUNCH_ACTION_PREFIX)
            and len(action_id) > len(LAUNCH_ACTION_PREFIX))


def launch_target_id(action_id):
    """``'launch:t_1'`` -> ``'t_1'``; ``''`` for anything else."""
    if not is_launch_action(action_id):
        return ""
    return action_id[len(LAUNCH_ACTION_PREFIX):]


def launch_action_label(action_id, targets=()):
    """Display label for a launch action id.

    A registered target contributes its name; an unknown target degrades to a
    explicit "(missing)" label so the picker never shows something cryptic.
    Non-launch ids are returned unchanged.
    """
    if not is_launch_action(action_id):
        return action_id
    target_id = launch_target_id(action_id)
    for target in normalize_targets(targets):
        if target["id"] == target_id:
            return target["name"]
    return f"{LAUNCH_MISSING_PREFIX}{target_id} (missing)"


# ==================================================================
# Launch target model
# ==================================================================

def new_target_id():
    """Generate a stable, collision-resistant target id."""
    return f"t_{int(time.time() * 1000)}_{uuid.uuid4().hex[:4]}"


def normalize_name(text):
    """Strip control characters and surrounding blanks, then truncate."""
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    # Drop C0 controls and DEL: keeps newlines/tabs out of the picker and the
    # status bar (RK-08).
    cleaned = "".join(ch for ch in text if ch >= " " and ch != "\x7f")
    return cleaned.strip()[:MAX_TARGET_NAME_LEN]


def _normalize_path(path):
    """Absolute path with forward slashes, or ``''`` when unusable.

    Forward slashes keep ``config.json`` readable and portable; Windows accepts
    them natively, so nothing is lost.
    """
    if not isinstance(path, str):
        if path is None:
            return ""
        path = str(path)
    text = path.strip().strip('"')
    if not text:
        return ""
    text = os.path.abspath(text)
    return text.replace("\\", "/")


def _basename_label(path):
    """Cheap display name derived from a path (no catalog lookup)."""
    if not path:
        return ""
    stem = os.path.basename(str(path).rstrip("/\\"))
    if stem.lower().endswith(".app") and len(stem) > 4:
        stem = stem[:-4]
    else:
        base, ext = os.path.splitext(stem)
        if base and ext:
            stem = base
    return normalize_name(stem)


def name_from_path(path):
    """Default display name for a program path (D-06).

    Prefers the installed-application label so that a user who browses to
    ``Code.exe`` gets "Visual Studio Code" instead of "Code".
    """
    if not path:
        return ""
    normalized = _normalize_path(path)
    if not normalized:
        return ""
    label = ""
    try:
        from core import app_catalog
        entry = app_catalog.resolve_app_spec(normalized)
        if entry:
            label = entry.get("label") or ""
    except Exception:
        # The catalog is a convenience only: never let it break naming.
        label = ""
    label = normalize_name(label)
    if label:
        return label
    return _basename_label(normalized)


def make_target(path, name="", args="", cwd="", target_id=None):
    """Build a normalized target dict (five string fields)."""
    normalized_path = _normalize_path(path)
    normalized_cwd = _normalize_path(cwd)
    if isinstance(args, str):
        args_text = args.strip()
    elif args is None:
        args_text = ""
    else:
        args_text = str(args).strip()

    resolved_id = ""
    if target_id:
        resolved_id = normalize_name(target_id)[:MAX_TARGET_NAME_LEN]
    if not resolved_id:
        resolved_id = new_target_id()

    resolved_name = normalize_name(name)
    if not resolved_name:
        resolved_name = _basename_label(normalized_path)

    return {
        "id": resolved_id,
        "name": resolved_name,
        "path": normalized_path,
        "args": args_text,
        "cwd": normalized_cwd,
    }


def normalize_targets(raw):
    """Coerce whatever the config holds into a list of valid target dicts.

    Fault tolerant by contract: malformed entries are dropped instead of
    raising, because this runs on every action-list computation.
    """
    if not isinstance(raw, (list, tuple)):
        return []
    result = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            target_id = item.get("id")
            if not isinstance(target_id, str):
                continue
            target_id = target_id.strip()
            if not target_id or target_id in seen:
                continue

            path = item.get("path")
            if not isinstance(path, str) or not path.strip():
                continue
            normalized_path = _normalize_path(path)
            if not normalized_path:
                continue

            name = item.get("name")
            resolved_name = normalize_name(name) if isinstance(name, str) else ""
            if not resolved_name:
                resolved_name = _basename_label(normalized_path)

            args = item.get("args")
            if not isinstance(args, str):
                args = ""

            cwd = item.get("cwd")
            cwd_text = _normalize_path(cwd) if isinstance(cwd, str) else ""

            seen.add(target_id)
            result.append({
                "id": target_id,
                "name": resolved_name,
                "path": normalized_path,
                "args": args,
                "cwd": cwd_text,
            })
        except Exception:
            # A single rotten entry must never hide the healthy ones.
            continue
    return result


def validate_target(target):
    """Return a human-readable error message, or ``''`` when the target is ok.

    The order of the checks is part of the contract: the UI surfaces the first
    failure, and users read them top-down.
    """
    if not isinstance(target, dict):
        return "Invalid target"

    path = target.get("path") or ""
    if not path:
        return "Program path is required"
    if not os.path.isabs(path):
        return "Program path must be absolute"
    if not os.path.exists(path):
        return f"Program not found: {path}"

    if not (target.get("name") or ""):
        return "Name is required"

    args = target.get("args")
    if not isinstance(args, str):
        args = ""
    try:
        parse_launch_args(args)
    except LaunchArgsError as exc:
        return f"Invalid arguments: {exc}"

    cwd = target.get("cwd") or ""
    if cwd and not os.path.exists(cwd):
        return f"Working directory not found: {cwd}"

    return ""


# ==================================================================
# Launch argument tokenization (DM-04)
# ==================================================================

def parse_launch_args(text):
    """Split an arguments text into tokens.

    Rules (deliberately not ``shlex``): whitespace separates tokens, single or
    double quotes group a token, and **a backslash is always a literal
    character**.  Using ``shlex`` with ``posix=True`` would silently turn
    ``--path=C:\\foo`` into ``--path=C:foo``.

    Raises :class:`LaunchArgsError` on an unclosed quote or too many tokens.
    """
    if text is None:
        return []
    if not isinstance(text, str):
        text = str(text)

    tokens = []
    current = []
    quote = None
    saw_char = False

    for ch in text:
        if quote:
            if ch == quote:
                quote = None
            else:
                current.append(ch)
            saw_char = True
        elif ch in ("'", '"'):
            quote = ch
            saw_char = True
        elif ch in (" ", "\t"):
            if current or saw_char:
                tokens.append("".join(current))
                current = []
            saw_char = False
        else:
            current.append(ch)
            saw_char = True

    if quote:
        raise LaunchArgsError("unclosed quote")
    if current or saw_char:
        tokens.append("".join(current))
    if len(tokens) > MAX_ARG_TOKENS:
        raise LaunchArgsError("too many arguments")
    return tokens


def format_launch_args(tokens):
    """Inverse of :func:`parse_launch_args`, for dialog echo."""
    if not tokens:
        return ""
    parts = []
    for token in tokens:
        text = token if isinstance(token, str) else str(token)
        if text == "" or any(ch in text for ch in (" ", "\t")):
            parts.append('"' + text + '"')
        else:
            parts.append(text)
    return " ".join(parts)


# ==================================================================
# Platform argv construction (DM-03)
# ==================================================================

def is_macos_bundle(path, platform=None):
    """True when *path* points at a macOS ``.app`` directory."""
    platform = platform or sys.platform
    if platform != "darwin":
        return False
    if not path or not isinstance(path, str):
        return False
    if not path.endswith(".app"):
        return False
    return os.path.isdir(path)


def build_launch_argv(target, platform=None):
    """Build the argv list for *target*.

    A macOS ``.app`` is a *directory*: handing it to ``Popen`` fails, and the
    correct semantic is to go through LaunchServices via ``open``.  Everything
    else is executed directly.
    """
    platform = platform or sys.platform
    if not isinstance(target, dict):
        raise LaunchArgsError("invalid target")

    path = target.get("path") or ""
    args = target.get("args")
    tokens = parse_launch_args(args if isinstance(args, str) else "")

    if is_macos_bundle(path, platform):
        argv = ["open", "-a", path]
        if tokens:
            argv.append("--args")
            argv.extend(tokens)
        return argv

    return [path] + tokens


def resolve_launch_cwd(target):
    """Working directory for *target* (D-05), ``''`` when unknowable.

    Falls back to the program's own folder so that relative resources resolve
    the way a double-click would.
    """
    if not isinstance(target, dict):
        return ""
    cwd = target.get("cwd") or ""
    if cwd and os.path.isdir(cwd):
        return cwd
    path = target.get("path") or ""
    if not path:
        return ""
    if is_macos_bundle(path):
        # Inside a bundle the working directory is meaningless; the folder
        # holding the bundle is the closest sane equivalent.
        return os.path.dirname(path.rstrip("/")) or ""
    return os.path.dirname(path) or ""


# ==================================================================
# Process start
# ==================================================================

# Keep a bounded reference to started processes so Python does not emit
# ResourceWarning noise for the discarded Popen objects (RK-10).
_recent_processes = deque(maxlen=16)


def _prune_recent_processes():
    while _recent_processes:
        process = _recent_processes[0]
        try:
            still_running = process.poll() is None
        except Exception:
            still_running = False
        if still_running:
            break
        _recent_processes.popleft()


def launch_target(target):
    """Validate, build argv and start *target*.

    Returns ``(ok, message)`` and **never raises**: every failure mode becomes
    ``(False, reason)`` so the caller can surface it in the status bar (IF-02).
    The command is always passed as an argv list with ``shell`` disabled, so
    quoting characters in user input cannot turn into a command.
    """
    error = validate_target(target)
    if error:
        return False, error

    try:
        argv = build_launch_argv(target)
    except LaunchArgsError as exc:
        return False, f"Invalid arguments: {exc}"
    except Exception as exc:
        return False, f"Launch failed: {exc}"

    kwargs = {"shell": False}
    cwd = resolve_launch_cwd(target)
    if cwd:
        kwargs["cwd"] = cwd
    if sys.platform != "win32":
        # Detach from this process group so quitting the app does not take the
        # launched program with it.
        kwargs["start_new_session"] = True

    path = target.get("path", "")
    try:
        _prune_recent_processes()
        _recent_processes.append(subprocess.Popen(argv, **kwargs))
    except FileNotFoundError:
        return False, f"Program not found: {path}"
    except PermissionError:
        return False, f"Permission denied: {path}"
    except OSError as exc:
        return False, f"Launch failed: {exc}"

    name = target.get("name") or ""
    return True, name if isinstance(name, str) else str(name)
