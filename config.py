"""
Configuration Management
========================
Loads, validates, and saves the APRS-Agent configuration from a TOML file.

Supports:
  --write-default-config   Write a fresh template config file and exit
  --print-config           Print the loaded config and exit
  --sync-config-to-file    Add any missing default values to the config file

Developed by TA3HRJ & TA3PKS
"""
from __future__ import annotations


import copy
import re
import sys
from pathlib import Path
from typing import Any

# Single source of truth for the application version.
# Imported by aprs_connection.py (for the APRS-IS login banner) and gui.py.
VERSION = "3.2.97"

# ── Secret handling for the HTTP API ────────────────────────────────────────
# print_config()'s masking below is for human eyes: it keeps the first and last
# few characters so an operator can tell one key from another, and it cannot be
# reversed. The API needs the opposite properties — reveal nothing at all, and
# survive a round trip, because the Web GUI reads the config into a form and
# posts the whole thing back on Save. So a masked field comes back as this
# exact sentinel and is restored from the file rather than overwriting the key
# with asterisks.
#
# ASCII on purpose. This was first written with U+2022 bullets, and a client
# that mangled the encoding turned the sentinel into something that no longer
# compared equal — so unmask_secrets() treated it as a new value and wrote the
# mangled text over a real bot token. A credential must not depend on every
# client preserving non-ASCII byte for byte.
SECRET_MASK = "*" * 8

# Anchored on the whole field name on purpose. A loose search for "key" would
# also swallow logger.keyword_filter, and a masked filter list would be shown
# to the operator as if it were a credential.
_SECRET_NAME = re.compile(
    r"^(api_keys?|api_secret|app_secret|app_password"
    r"|access_token(_key|_secret)?|bot_token|verify_token"
    r"|[a-z0-9_]*password|[a-z0-9_]*passcode|[a-z0-9_]*_token"
    r"|token|secret)$",
    re.IGNORECASE,
)


def mask_secrets(config: dict[str, Any]) -> dict[str, Any]:
    """Config with every credential replaced by SECRET_MASK.

    Values under a secret-named parent (extensions.ai_gateway.api_keys, whose
    own keys are provider names) are masked too. Empty stays empty, so the GUI
    still shows an unset field as unset.
    """
    def walk(node: Any, secret: bool) -> Any:
        if isinstance(node, dict):
            return {k: walk(v, secret or bool(_SECRET_NAME.match(str(k))))
                    for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, secret) for v in node]
        if secret and isinstance(node, str) and node:
            return SECRET_MASK
        return node

    return walk(copy.deepcopy(config), False)


def unmask_secrets(incoming: dict[str, Any],
                   current: dict[str, Any]) -> dict[str, Any]:
    """Restore untouched credentials from the on-disk config.

    Any field that still carries the sentinel was never edited, so the stored
    value is put back. Without this, one Save from a masked form would wipe
    every key the operator did not retype.
    """
    def walk(new: Any, old: Any) -> Any:
        if isinstance(new, dict):
            return {k: walk(v, old.get(k) if isinstance(old, dict) else None)
                    for k, v in new.items()}
        if isinstance(new, str) and new == SECRET_MASK:
            return old if isinstance(old, str) else ""
        return new

    return walk(copy.deepcopy(incoming), current)

# tomllib is built-in from Python 3.11 onwards.
# For older Python versions, install the 'tomli' package.
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            print(
                "ERROR: 'tomli' package is required for Python < 3.11.\n"
                "       Run: pip install tomli",
                file=sys.stderr,
            )
            sys.exit(1)

try:
    import tomli_w  # type: ignore
except ImportError:
    tomli_w = None  # type: ignore


# =============================================================================
# Default values - all anonymous, no personal data
# =============================================================================

DEFAULTS: dict[str, Any] = {
    "server": "rotate.aprs2.net",
    "port": 14580,
    "callsign": "N0CALL",
    "allowed_callsigns": ["N0*"],
    "print_config_on_startup": False,
    "auto_start_agent": False,
    "full_feed": False,
    "rate_limit_pps": 50,
    "repeater_db_path": "",
    # Read-only public monitoring page (0 = disabled). Serves Live Log /
    # Stations / Map without any admin endpoints — safe to expose.
    "public_port": 0,
    # Identity shown in the public page header (empty = generic defaults)
    "public_title": "",
    "public_subtitle": "",
    # Optional "Home" link in the public header — a project site the map
    # belongs to. Empty = no link, which is the right default: this page is
    # often the only thing an operator publishes.
    "public_home_url": "",
    "monitor": {
        "enabled": False,
        "watch_callsigns": [],
        "notify_channel": "telegram",
        "check_interval_mins": 10,
        # Maidenhead fields to scope silence detection to (empty = worldwide)
        "silence_grids": [],
        # Batch silence alerts into one notification every N minutes
        # (0 = send each alert immediately)
        "silence_digest_mins": 0,
        # Maidenhead fields (first 2 characters) a propagation opening must
        # touch — on either the sender's or the gate's end of at least one
        # link — to be NOTIFIED. The map/timeline still show every opening
        # worldwide; this only scopes the Telegram/email message, since a
        # US-to-Western-Europe opening is not actionable for an operator who
        # only cares about their own region. Empty = notify on every opening.
        "prop_notify_grids": [],
    },
    "station_ai": {
        "enabled": False,
        "interval_hours": 24,
        "max_batch": 20,
    },
    "extension_server": {
        "enabled": False,
        "host": "127.0.0.1",
        "port": 65080,
    },
    "extensions": {
        "twitter": {
            "enabled": False,
            "api_key": "",
            "api_secret": "",
            "access_token_key": "",
            "access_token_secret": "",
            "add_hash_tag": True,
            "allowed_recepients": ["twsend", "TWSEND"],
            "allowed_senders": ["N0CALL"],
        },
        "logger": {
            "enabled": True,
            "log_comments": True,
            "filter_by_message_type": [
                "!", "/", "\\", "@", "~", "`", "^", "&", "*",
                "(", ")", "_", "-", "=", "+", "[", "]", "{",
                "}", "|", ";", ":", '"', "<", ">", "?", ".",
            ],
            "exclude_by_message_type": [],
            "keyword_filter": [],
            # Packet lines go to the Web GUI Live Log and, if a path is set
            # here, to this file. They no longer go to the process stderr
            # that journald captures: in World Mode the feed was 97% of the
            # system journal, ~47 MB an hour, and it evicted every
            # diagnostic line within a day. Empty = Live Log only.
            "log_file": "",
            "log_max_mb": 50,
            "log_backups": 3,
        },
        "fixed_beacon": {
            "enabled": False,
            "ssid": "N0CALL-10",
            "lat": "0000.00N",
            "lon": "00000.00E",
            "symbol_table": "/",
            "symbol": "-",
            "comment": "APRS-Agent | https://github.com/YOUR_USERNAME/aprs-agent",
            # A separate APRS status packet, shown by aprs.fi as "Last
            # status" beside the comment rather than instead of it. Empty
            # = nothing sent.
            "status_text": "",
            "beacon_interval_mins": 15,
        },
        "bluesky": {
            "enabled": False,
            "username": "",
            "app_password": "",
            "add_hash_tag": True,
            "allowed_recepients": ["BSKYSEND"],
            "allowed_senders": ["N0CALL"],
        },
        "whatsapp": {
            "enabled": False,
            "phone_number_id": "",
            "access_token": "",
            "verify_token": "",
            "app_secret": "",
            "recipient_phone": "",
            "add_hash_tag": True,
            "allowed_recepients": ["WASEND"],
            "allowed_senders": ["N0CALL"],
            "from_callsign": "",
            "aprs_destination": "",
            "allowed_phones": [],
        },
        "telegram": {
            "enabled": False,
            "bot_token": "",
            "chat_id": "",
            "add_hash_tag": True,
            "allowed_recepients": ["TGSEND"],
            "allowed_senders": ["N0CALL"],
            "poll_enabled": False,
            "poll_interval_secs": 5,
            "from_callsign": "",
            "aprs_destination": "",
        },
        "ai_gateway": {
            "enabled": False,
            "callsign": "N0CALL",
            "provider": "puter",
            # Legacy single-key field — kept only so configs saved before
            # per-provider keys still work (resolve_ai_api_key() falls back
            # to it). New saves populate api_keys instead.
            "api_key": "",
            # provider id -> API key, so switching providers recalls that
            # provider's own key instead of overwriting one shared field.
            "api_keys": {},
            "base_url": "",
            "model": "",
            "system_prompt": "",
            "trigger_prefix": "",
            "trigger_aliases": [],
            "extra_sms": 0,
            "whitelist_enabled": False,
            "whitelist": [],
            # Per-sender token bucket. Defaults match the extension's own, so
            # a config written from the UI cannot quietly disable a limiter
            # that was in force a moment earlier.
            "rate_burst": 4,
            "rate_refill_s": 180,
            # Whole-instance ceiling per UTC day. 0 = none, which is what an
            # open gateway on somebody's own hardware usually wants; it exists
            # because per-sender limits do nothing against many strangers
            # asking once each.
            "daily_limit": 0,
            # How far away a weather reading may come from and still count as
            # "here". Coverage is regional: on this instance 235 stations sat
            # within 100 km and none of them measured weather, while the
            # nearest that did was 213 km off. The answer always names the
            # distance, so a reader can judge a far one for themselves.
            "wx_radius_km": 250,
            # An APRS status packet naming who operates this gateway.
            # The addressee is not a callsign and identifies software,
            # not a station — but somebody who meets it on aprs.fi
            # should be able to find the operator without asking.
            # Empty text or 0 minutes = nothing is sent, which is the
            # right default: it is not for us to publish anyone's name.
            "status_text": "",
            "status_interval_mins": 0,
        },
        "imap": {
            "enabled": False,
            "imap_server": "imap.gmail.com:993",
            "imap_username": "",
            "imap_password": "",
            "poll_interval_mins": 5,
            "from_callsign": "EMAIL-5",
            "allowed_senders": [],
        },
        "smtp": {
            "enabled": False,
            "smtp_server": "smtp.example.com:587",
            "smtp_username": "your@email.com",
            "smtp_password": "",
            "allowed_senders": ["N0CALL"],
            "allowed_recipients": ["EMAIL"],
            "allowed_receiver_emails": [],
            "from_email": "APRS-Agent <aprs@example.com>",
        },
    },
}


class ConfigError(Exception):
    """A config file exists but could not be parsed.

    Raised instead of calling sys.exit() so that callers which are not a
    short-lived CLI -- the Desktop GUI's Save/Start buttons, the Web GUI's
    request handlers -- can report the problem and carry on. SystemExit
    derives from BaseException, so an ordinary `except Exception` around
    load_config() would NOT have caught it: a single typo in the TOML took
    the whole Desktop GUI down with no message.
    """


def resolve_ai_api_key(ai_cfg: dict[str, Any], provider: str) -> str:
    """The AI Gateway API key for `provider`, from the per-provider
    api_keys dict — falling back to the legacy flat api_key field for
    configs saved before per-provider keys existed (pre-v2.10.12)."""
    keys = ai_cfg.get("api_keys") or {}
    return keys.get(provider) or ai_cfg.get("api_key", "") or ""


def strip_ssid(callsign: str) -> str:
    """Return the base callsign without SSID suffix.

    Example: "TA3HRJ-7" → "TA3HRJ",  "N0CALL" → "N0CALL"
    Used by calculate_passcode() and the Twitter/SMTP extensions.
    """
    return callsign.split("-")[0]


def apply_partial(stored: dict, incoming: dict) -> dict:
    """Overlay a partial config onto the stored one.

    The Web GUI's settings form posts the fields it renders, which is not the
    whole file. Writing that dict straight out silently reverted every key the
    form has no widget for — public_title vanished from a live deployment this
    way, and the page went back to appending a callsign nobody had asked it to
    show. A form that shows part of the config must be allowed to save part of
    the config.

    Keys present in `incoming` win, including deliberately emptied ones. Keys
    absent from it keep whatever is on disk.
    """
    return _deep_merge(stored, incoming)


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. override wins on conflicts."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def calculate_passcode(callsign: str) -> int:
    """
    Calculate the APRS-IS passcode for a given callsign.

    This is the standard APRS passcode algorithm used by all APRS-IS servers
    to verify that the connecting station holds a valid amateur radio license.
    The passcode is derived from the base callsign (without SSID).

    This algorithm is publicly documented in the APRS-IS specification.
    """
    callsign = strip_ssid(callsign).upper()
    code = 0x73E2
    for i, char in enumerate(callsign):
        if i % 2 == 0:
            code ^= ord(char) << 8
        else:
            code ^= ord(char)
    return code & 0x7FFF


def load_config(config_path: str) -> dict[str, Any]:
    """
    Load configuration from a TOML file.

    If the file does not exist, writes a fresh default config and uses it.
    Missing keys are filled in with default values.
    """
    path = Path(config_path)

    if not path.exists():
        print(
            f"Config file '{config_path}' not found. "
            f"Writing default config and starting with defaults.",
            file=sys.stderr,
        )
        write_default_config(config_path)
        return copy.deepcopy(DEFAULTS)

    try:
        raw = path.read_bytes()
        # Notepad on Windows writes a UTF-8 BOM, and a bare tomllib.load()
        # rejects it as "Invalid statement (at line 1, column 1)" — which
        # points the operator at their first setting rather than at an
        # invisible three-byte prefix they cannot see in the editor.
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        user_config = tomllib.loads(raw.decode("utf-8"))
    except Exception as e:
        raise ConfigError(
            f"Failed to parse config file '{config_path}': {e}") from e

    # Merge user config over defaults so missing keys get default values
    return _deep_merge(DEFAULTS, user_config)


def write_default_config(config_path: str) -> None:
    """
    Write a fresh template config file with all default values and comments.
    Uses the annotated TOML template (aprsconfig.toml in the project folder).
    If tomli_w is available, also writes a machine-generated version.
    """
    # Look for the annotated template first (the .template file ships with the repo)
    # then fall back to a plain aprsconfig.toml if present
    template_path = Path(__file__).parent / "aprsconfig.toml.template"
    if not template_path.exists():
        template_path = Path(__file__).parent / "aprsconfig.toml"
    dest_path = Path(config_path)

    if template_path.exists() and template_path != dest_path:
        # Copy the human-readable annotated template
        dest_path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Default config written to '{config_path}'", file=sys.stderr)
    elif tomli_w is not None:
        # Fall back to machine-generated TOML if template not available
        with open(dest_path, "wb") as f:
            tomli_w.dump(DEFAULTS, f)
        print(
            f"Default config written to '{config_path}' (no template found, "
            f"comments not included)",
            file=sys.stderr,
        )
    else:
        print(
            f"ERROR: Cannot write default config. "
            f"Either place 'aprsconfig.toml' template next to this script "
            f"or install 'tomli_w' (pip install tomli-w).",
            file=sys.stderr,
        )


def sync_config_to_file(config: dict[str, Any], config_path: str) -> None:
    """
    Write the fully-merged config (defaults + user values) back to file.
    This adds any missing default keys to an existing config file.
    """
    if tomli_w is None:
        print(
            "ERROR: 'tomli_w' is required for --sync-config-to-file. "
            "Run: pip install tomli-w",
            file=sys.stderr,
        )
        return

    dest_path = Path(config_path)
    with open(dest_path, "wb") as f:
        tomli_w.dump(config, f)
    print(f"Config synced to '{config_path}'", file=sys.stderr)


def print_config(config: dict[str, Any]) -> None:
    """Print the loaded config, masking sensitive values."""
    import copy

    safe = copy.deepcopy(config)

    def mask(d: dict, keys: list[str]) -> None:
        for key in keys:
            if key in d and d[key]:
                val = str(d[key])
                d[key] = val[:3] + "****" + val[-3:] if len(val) > 6 else "***"

    tw = safe.get("extensions", {}).get("twitter", {})
    mask(tw, ["api_key", "api_secret", "access_token_key", "access_token_secret"])

    bsky = safe.get("extensions", {}).get("bluesky", {})
    mask(bsky, ["app_password"])

    wa = safe.get("extensions", {}).get("whatsapp", {})
    mask(wa, ["access_token"])

    tg = safe.get("extensions", {}).get("telegram", {})
    mask(tg, ["bot_token"])

    ai = safe.get("extensions", {}).get("ai_gateway", {})
    mask(ai, ["api_key"])

    imap = safe.get("extensions", {}).get("imap", {})
    mask(imap, ["imap_password"])

    sm = safe.get("extensions", {}).get("smtp", {})
    mask(sm, ["smtp_password"])

    import pprint
    pprint.pprint(safe, stream=sys.stderr)
