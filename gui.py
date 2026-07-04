#!/usr/bin/env python3
from __future__ import annotations
"""
APRS-Agent GUI
==============
Graphical interface for configuring and running APRS-Agent.

Features:
  - Form-based configuration editor for all settings
  - Start / Stop the APRS agent with one click
  - Minimize to system tray with tray icon
  - Real-time log output panel
  - English / Turkish dual language support

Run with:   python gui.py
            python gui.py -c /path/to/aprsconfig.toml

Developed by TA3HRJ & TA3PKS
"""

import argparse
import asyncio
import queue
import re
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Optional

try:
    import pystray
    from PIL import Image, ImageDraw
    _TRAY_OK = True
except ImportError:
    _TRAY_OK = False

import config as cfg_module
import aprs_connection
import extension_server as ext_server_module
from extensions import ExtensionRegistry

# ─── Constants ───────────────────────────────────────────────────────────────

_VERSION = cfg_module.VERSION  # single source of truth in config.py
_DEFAULT_CFG = Path(__file__).parent / "aprsconfig.toml"


def _find_icon() -> Path:
    """
    Locate the application icon (.ico) file.
    Works both when running as a Python script and when packaged by PyInstaller.
    """
    # PyInstaller extracts bundled data to sys._MEIPASS
    if hasattr(sys, "_MEIPASS"):
        p = Path(sys._MEIPASS) / "aprs-agent.ico"
        if p.exists():
            return p

    # Running as Python script — check script dir and its parent
    candidates = [
        Path(__file__).parent / "aprs-agent.ico",        # same folder
        Path(__file__).parent.parent / "aprs-agent.ico", # one level up (original location)
    ]
    for p in candidates:
        if p.exists():
            return p

    return Path("aprs-agent.ico")   # last-resort relative path


_ICON_PATH = _find_icon()

# ─── Windows autostart (registry) ────────────────────────────────────────────

_AUTOSTART_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_NAME = "APRS-Agent"
_MUTEX_HANDLE   = None   # kept alive for process lifetime


def _ensure_single_instance() -> None:
    """
    Allow only one running copy of the GUI.
    On Windows: create a named mutex; if it already exists bring the
    existing window to the foreground and exit immediately.
    On other platforms: no-op (lock files would be more complex, skip for now).
    """
    global _MUTEX_HANDLE
    if sys.platform != "win32":
        return
    import ctypes
    kernel32 = ctypes.windll.kernel32
    user32   = ctypes.windll.user32
    _MUTEX_HANDLE = kernel32.CreateMutexW(None, True, "APRS-Agent-SingleInstance-v1")
    if kernel32.GetLastError() == 183:          # ERROR_ALREADY_EXISTS
        hwnd = user32.FindWindowW(None, "APRS-Agent")
        if hwnd:
            user32.ShowWindow(hwnd, 9)          # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
        sys.exit(0)


def _autostart_get() -> bool:
    """Return True if the app is registered to start with Windows."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY, 0,
                             winreg.KEY_READ)
        winreg.QueryValueEx(key, _AUTOSTART_NAME)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _autostart_set(enabled: bool, cfg_path: str) -> None:
    """Add or remove the Windows startup registry entry."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY, 0,
                             winreg.KEY_SET_VALUE)
        if enabled:
            exe = sys.executable          # works for both script and PyInstaller
            val = f'"{exe}" -c "{cfg_path}"'
            winreg.SetValueEx(key, _AUTOSTART_NAME, 0, winreg.REG_SZ, val)
        else:
            try:
                winreg.DeleteValue(key, _AUTOSTART_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception:
        pass   # not Windows or no access — silently skip


def _load_sprites() -> "tuple[Optional[Any], Optional[Any]]":
    """
    Load APRS symbol sprite sheets (24 px per cell, 16 cols × 6 rows).
    Returns (primary_img, alternate_img) PIL Images, or (None, None) on failure.
    """
    try:
        from PIL import Image

        def _find_sprite(name: str) -> Optional[Path]:
            if hasattr(sys, "_MEIPASS"):
                p = Path(sys._MEIPASS) / name
                if p.exists():
                    return p
            p = Path(__file__).parent / name
            return p if p.exists() else None

        p0 = _find_sprite("aprs-symbols-24-0.png")
        p1 = _find_sprite("aprs-symbols-24-1.png")
        s0 = Image.open(str(p0)).convert("RGBA") if p0 else None
        s1 = Image.open(str(p1)).convert("RGBA") if p1 else None
        return s0, s1
    except Exception:
        return None, None


_SPRITE_PRIMARY, _SPRITE_ALTERNATE = _load_sprites()


# ─── APRS Symbol tables ───────────────────────────────────────────────────────
# Each entry: (char, english_name, turkish_name)

_APRS_PRIMARY_SYMBOLS: list[tuple[str, str, str]] = [
    # ── Standard primary table symbols (APRS 1.01) ────────────────────────────
    ('!',  'Police Station',    'Polis Merkezi'),
    ('#',  'Digipeater',        'Digipeater'),
    ('$',  'Telephone',         'Telefon'),
    ('%',  'DX Cluster',        'DX Cluster'),
    ('&',  'HF Gateway',        'HF Gateway'),
    ("'",  'Small Aircraft',    'Küçük Uçak'),
    ('(',  'Mobile Satellite',  'Mobil Uydu'),
    (')',  'Wheelchair',        'Tekerlekli Sandalye'),
    ('*',  'Snowflake',         'Kar Tanesi'),
    ('+',  'Red Cross',         'Kızılhaç'),
    (',',  'Boy Scouts',        'İzcilik'),
    ('-',  'House (QTH)',       'Ev (QTH)'),
    ('.',  'Red Dot',           'Kırmızı Nokta'),
    (':',  'Fire',              'Yangın'),
    (';',  'Campground',        'Kamp Alanı'),
    ('<',  'Motorcycle',        'Motosiklet'),
    ('=',  'Train / Railway',   'Tren / Demiryolu'),
    ('>',  'Car',               'Araba'),
    ('?',  'File Server',       'Dosya Sunucusu'),
    ('@',  'Hurricane',         'Kasırga'),
    ('A',  'Aid Station',       'İlk Yardım'),
    ('B',  'BBS / PBBS',        'BBS / PBBS'),
    ('E',  'Eyeball (Events)',  'Göz (Etkinlik)'),
    ('H',  'Hotel',             'Otel'),
    ('K',  'School',            'Okul'),
    ('N',  'NTS Station',       'NTS İstasyonu'),
    ('O',  'Balloon',           'Balon'),
    ('P',  'Police Car',        'Polis Arabası'),
    ('R',  'RV',                'Karavan'),
    ('S',  'Space Shuttle',     'Uzay Mekiği'),
    ('U',  'Bus',               'Otobüs'),
    ('X',  'Helicopter',        'Helikopter'),
    ('Y',  'Yacht',             'Yat'),
    ('[',  'Jogger / Runner',   'Koşucu'),
    ('^',  'Large Aircraft',    'Büyük Uçak'),
    ('_',  'Weather Station',   'Hava İstasyonu'),
    ('`',  'Dish Antenna',      'Çanak Anten'),
    ('a',  'Ambulance',         'Ambulans'),
    ('b',  'Bicycle',           'Bisiklet'),
    ('f',  'Fire Truck',        'İtfaiye Aracı'),
    ('g',  'Glider',            'Planör'),
    ('h',  'Hospital',          'Hastane'),
    ('j',  'Jeep',              'Jeep'),
    ('k',  'Truck',             'Kamyon'),
    ('l',  'Laptop',            'Dizüstü Bilgisayar'),
    ('n',  'Node / Net',        'Ağ Düğümü'),
    ('o',  'Balloon (small)',   'Küçük Balon'),
    ('p',  'Police Car (sm)',   'Küçük Polis'),
    ('r',  'Restaurant',        'Restoran'),
    ('s',  'Sailboat',          'Yelkenli'),
    ('t',  'Thunderstorm',      'Fırtına'),
    ('u',  'Truck (18-wheel)',  'Kamyon (TIR)'),
    ('v',  'Van',               'Minibüs'),
    ('w',  'Water Station',     'Su İstasyonu'),
    ('x',  'X Marker',          'X İşareti'),
    ('y',  'Yagi Antenna',      'Yagi Anten'),
]

_APRS_ALTERNATE_SYMBOLS: list[tuple[str, str, str]] = [
    # ── Standard alternate table symbols (APRS 1.01 / \ prefix) ──────────────
    ('!',  'Emergency',         'Acil Durum'),
    ('#',  'Digi (numbered)',    'Digi (numaralı)'),
    ('$',  'Bank / ATM',        'Banka / ATM'),
    ('-',  'Fallback Dot',      'Yedek Nokta'),
    ('.',  'Numbered Dot',      'Numaralı Nokta'),
    ('>',  'Car (overlay)',     'Araba (örtüşme)'),
    ('@',  'Storm',             'Fırtına'),
    ('^',  'Aircraft (ovly)',   'Uçak (örtüşme)'),
    ('_',  'Wx Stn (overlay)',  'Hava İst. (örtüşme)'),
    ('a',  'ARES / RACES',      'ARES / RACES'),
    ('b',  'Bike (overlay)',    'Bisiklet (örtüşme)'),
    ('c',  'ICP',               'Olay Komuta'),
    ('e',  'EOC',               'Acil Yönetim Mrk.'),
    ('f',  'NTS Net',           'NTS Ağı'),
    ('g',  'Ground Station',    'Yer İstasyonu'),
    ('h',  'Hospital',          'Hastane'),
    ('i',  'WinAPRS',           'WinAPRS'),
    ('k',  'Special Vehicle',   'Özel Araç'),
    ('m',  'Milepost',          'Kilometre Taşı'),
    ('n',  'NTS',               'NTS'),
    ('o',  'EOC (overlay)',     'Acil Yön. (örtüşme)'),
    ('p',  'Parking',           'Park Yeri'),
    ('q',  'Search & Rescue',   'Arama & Kurtarma'),
    ('r',  'Restaurant',        'Restoran'),
    ('s',  'Satellite',         'Uydu'),
    ('t',  'Thunderstorm',      'Fırtına'),
    ('u',  'ATM Machine',       'ATM Makinesi'),
    ('v',  'Triangle',          'Üçgen'),
    ('w',  'Wx Stn (alt)',      'Hava İst. (alt)'),
    ('x',  'Pharmacy / Rx',     'Eczane'),
    ('y',  'Radiology',         'Radyoloji'),
]


def _aprs_symbol_name(table: str, char: str, lang: str) -> str:
    """Return the human-readable name for an APRS symbol."""
    symbols = _APRS_PRIMARY_SYMBOLS if table == "/" else _APRS_ALTERNATE_SYMBOLS
    is_en = lang == "en"
    for c, ne, nt in symbols:
        if c == char:
            return ne if is_en else nt
    return f"({char})"


# ─── Maidenhead / QTH Locator ↔ Lat/Lon conversions ──────────────────────────

def maidenhead_to_latlon(loc: str) -> Optional[tuple[float, float]]:
    """
    Convert a Maidenhead grid locator (4, 6, or 8 characters) to decimal degrees.
    Returns (latitude, longitude) or None on invalid input.

    Examples:
      "KM38nk"   → (38.4375,   27.125)     ~5 km precision
      "KM38nk23" → (38.43125,  27.1125)    ~600 m precision
    """
    loc = loc.strip()
    if len(loc) < 4:
        return None
    try:
        loc_u = loc.upper()
        # Field (letters A–R): 20° lon × 10° lat
        lon = (ord(loc_u[0]) - ord('A')) * 20.0 - 180.0
        lat = (ord(loc_u[1]) - ord('A')) * 10.0 - 90.0
        # Square (digits 0–9): 2° lon × 1° lat
        lon += int(loc[2]) * 2.0
        lat += int(loc[3]) * 1.0
        if len(loc) >= 6:
            # Sub-square (letters a–x): 5' lon × 2.5' lat
            sub_lon = ord(loc[4].lower()) - ord('a')
            sub_lat = ord(loc[5].lower()) - ord('a')
            lon += sub_lon * (5.0 / 60.0)
            lat += sub_lat * (2.5 / 60.0)
            if len(loc) >= 8:
                # Extended square (digits 0–9): 0.5' lon × 0.25' lat
                ext_lon = int(loc[6])
                ext_lat = int(loc[7])
                lon += ext_lon * (0.5 / 60.0)
                lat += ext_lat * (0.25 / 60.0)
                # Centre of extended square
                lon += 0.25 / 60.0
                lat += 0.125 / 60.0
            else:
                # Centre of sub-square
                lon += 2.5 / 60.0
                lat += 1.25 / 60.0
        else:
            # Centre of square
            lon += 1.0
            lat += 0.5
        return lat, lon
    except (ValueError, IndexError):
        return None


def latlon_to_maidenhead(lat: float, lon: float) -> str:
    """
    Convert decimal degrees to an 8-character Maidenhead grid locator (~600 m).

    Example: (38.43125, 27.1125) → "KM38nk23"
    """
    lon += 180.0
    lat += 90.0
    field_lon = int(lon / 20)
    field_lat = int(lat / 10)
    lon -= field_lon * 20.0
    lat -= field_lat * 10.0
    sq_lon = int(lon / 2)
    sq_lat = int(lat)
    lon -= sq_lon * 2.0
    lat -= sq_lat
    sub_lon = int(lon * 12)        # 2° / 24 subdivisions
    sub_lat = int(lat * 24)        # 1° / 24 subdivisions
    lon -= sub_lon / 12.0
    lat -= sub_lat / 24.0
    ext_lon = min(int(lon * 120), 9)   # 0.5'/step → ×120
    ext_lat = min(int(lat * 240), 9)   # 0.25'/step → ×240
    return (
        chr(ord('A') + field_lon)
        + chr(ord('A') + field_lat)
        + str(sq_lon)
        + str(sq_lat)
        + chr(ord('a') + sub_lon)
        + chr(ord('a') + sub_lat)
        + str(ext_lon)
        + str(ext_lat)
    )


def decimal_to_aprs_lat(lat: float) -> str:
    """38.4375 → '3826.25N'"""
    hemi = 'N' if lat >= 0 else 'S'
    lat = abs(lat)
    deg = int(lat)
    mins = (lat - deg) * 60.0
    return f"{deg:02d}{mins:05.2f}{hemi}"


def decimal_to_aprs_lon(lon: float) -> str:
    """27.125 → '02707.50E'"""
    hemi = 'E' if lon >= 0 else 'W'
    lon = abs(lon)
    deg = int(lon)
    mins = (lon - deg) * 60.0
    return f"{deg:03d}{mins:05.2f}{hemi}"


def aprs_lat_to_decimal(s: str) -> Optional[float]:
    """'3826.25N' → 38.4375"""
    s = s.strip().upper()
    if len(s) < 7:
        return None
    try:
        hemi = s[-1]
        deg = int(s[:2])
        mins = float(s[2:-1])
        v = deg + mins / 60.0
        return v if hemi == 'N' else -v
    except (ValueError, IndexError):
        return None


def aprs_lon_to_decimal(s: str) -> Optional[float]:
    """'02707.50E' → 27.125"""
    s = s.strip().upper()
    if len(s) < 8:
        return None
    try:
        hemi = s[-1]
        deg = int(s[:3])
        mins = float(s[3:-1])
        v = deg + mins / 60.0
        return v if hemi == 'E' else -v
    except (ValueError, IndexError):
        return None


# ─── Language strings ────────────────────────────────────────────────────────

_S = {
    "en": {
        "title":              "APRS-Agent",
        "lang_btn":           "🌐 TR",
        "cfg_label":          "Config file:",
        "browse":             "Browse…",
        # tabs
        "tab_conn":           "Connection",
        "tab_log":            "Logger",
        "tab_beacon":         "Fixed Beacon",
        "tab_twitter":        "Twitter / X",
        "tab_bluesky":        "Bluesky",
        "tab_wa":             "WhatsApp",
        "tab_tg":             "Telegram",
        "tab_ai":             "AI Gateway",
        "tab_email":          "Email",
        "email_send":         "📤 Send — Radio → Email (SMTP)",
        "email_recv":         "📥 Receive — Email → Radio (IMAP)",
        "tab_monitor":        "Monitor",
        "tab_ext":            "Ext. Server",
        "mon_enabled":        "Repeater Monitor",
        "mon_sub":            "Notify when a DB repeater goes offline or comes back online",
        "mon_channel":        "Notify via:",
        "mon_interval":       "Check interval (min):",
        "mon_watch":          "Watch callsigns:",
        "mon_watch_hint":     "Comma-separated base callsigns. Empty = all DB repeaters.",
        # connection
        "server":             "APRS-IS Server:",
        "port":               "Port:",
        "callsign":           "Callsign:",
        "allowed_cs":         "Station Filter:",
        "allowed_cs_hint":    "Which stations to monitor. Wildcards OK  e.g.  TA3* = all TA3 stations",
        "st_packets":         "Packets",
        "st_stations":        "Stations",
        "st_calls":           "Callsigns",
        "st_uptime":          "Uptime",
        "full_feed":          "Full World Feed (port 10152)",
        "full_feed_warn":     (
            "⚠  Receives ALL worldwide APRS traffic (~50–100 pkt/s). "
            "Extensions only respond to their own whitelisted callsigns. "
            "Rate limit below is strongly recommended."
        ),
        "rate_limit_pps":     "Rate limit (pkt/s):",
        "rate_limit_hint":    "Max packets dispatched to extensions per second. 0 = unlimited.",
        "repeater_db_path":   "Repeater DB Path:",
        "repeater_db_hint":   "Path to repeaters.json (Turkey Repeaters). Stations tab enriches matching callsigns with city, frequency and tone.",
        "print_cfg":          "Print config on startup",
        "autostart":          "Start with Windows",
        "autostart_agent":    "Start agent automatically on launch",
        # logger
        "log_enabled":        "Enable Logger",
        "log_comments":       "Log server comment lines (#)",
        "filter_type":        "Filter by packet type:",
        "filter_type_hint":   "Comma-separated chars  e.g.  !, :, ;, @",
        "exclude_type":       "Exclude packet types:",
        "kw_filter":          "Keyword filter:",
        "kw_filter_hint":     "Comma-separated, case-insensitive",
        # beacon
        "bcn_enabled":        "Enable Fixed Beacon",
        "bcn_locator":        "QTH Locator:",
        "bcn_locator_hint":   "Maidenhead grid  e.g.  KM38nk23  (4/6/8 chars) ← updates lat/lon automatically",
        "bcn_ssid":           "Station SSID:",
        "bcn_ssid_hint":      "Your callsign + SSID  e.g.  N0CALL-10",
        "bcn_lat":            "Latitude:",
        "bcn_lat_hint":       "DDMM.MMN format  e.g.  4100.00N",
        "bcn_lon":            "Longitude:",
        "bcn_lon_hint":       "DDDMM.MME format  e.g.  02900.00E",
        "bcn_sym_tbl":        "Symbol:",
        "bcn_sym_pick":       "Choose Symbol…",
        "bcn_comment":        "Beacon comment:",
        "bcn_interval":       "Interval (minutes):",
        # twitter
        "tw_enabled":         "Enable Twitter / X",
        "tw_api_key":         "API Key:",
        "tw_api_secret":      "API Secret:",
        "tw_tok_key":         "Access Token Key:",
        "tw_tok_secret":      "Access Token Secret:",
        "tw_hashtag":         "Add #APRS hashtag automatically",
        "tw_recepients":      "Allowed APRS recipients:",
        "tw_senders":         "Allowed APRS senders:",
        "tw_cs_hint":         "Comma-separated callsigns",
        # bluesky
        "bsky_enabled":       "Enable Bluesky",
        "bsky_username":      "Username (handle):",
        "bsky_username_hint": "e.g.  yourname.bsky.social",
        "bsky_app_pass":      "App Password:",
        "bsky_app_pass_hint": "Create at bsky.app → Settings → App Passwords",
        "bsky_hashtag":       "Add #APRS hashtag automatically",
        "bsky_recepients":    "Allowed APRS recipients:",
        "bsky_senders":       "Allowed APRS senders:",
        "bsky_cs_hint":       "Comma-separated callsigns",
        # whatsapp
        "wa_enabled":         "Enable WhatsApp",
        "wa_phone_id":        "Phone Number ID:",
        "wa_token":           "Access Token:",
        "wa_verify":          "Webhook Verify Token:",
        "wa_recipient":       "Recipient Phone:",
        "wa_hashtag":         "Add #APRS hashtag",
        "wa_recepients":      "Allowed APRS recipients:",
        "wa_senders":         "Allowed APRS senders:",
        "wa_from_call":       "From callsign:",
        "wa_aprs_dest":       "Default APRS destination:",
        "wa_allowed_phones":  "Allowed phone numbers:",
        # telegram
        "tg_enabled":         "Enable Telegram",
        "tg_token":           "Bot Token:",
        "tg_chat_id":         "Chat ID:",
        "tg_hashtag":         "Add #APRS hashtag",
        "tg_recepients":      "Allowed APRS recipients:",
        "tg_senders":         "Allowed APRS senders:",
        "tg_poll_enabled":    "Poll Telegram (inbound)",
        "tg_poll_interval":   "Poll interval (seconds):",
        "tg_from_call":       "From callsign:",
        "tg_aprs_dest":       "Default APRS destination:",
        # ai gateway
        "ai_enabled":         "Enable AI Gateway",
        "ai_callsign":        "AI Callsign:",
        "ai_callsign_hint":   "Messages to this callsign trigger AI  e.g.  N0CALL",
        "ai_provider":        "Provider:",
        "ai_api_key":         "API Key:",
        "ai_base_url":        "Custom Base URL:",
        "ai_base_url_hint":   "Only for custom provider. Leave empty for default.",
        "ai_model":           "Model:",
        "ai_model_hint":      "Leave empty for provider default",
        "ai_system_prompt":   "System Prompt:",
        "ai_trigger_prefix":  "Trigger Prefix:",
        "ai_trigger_prefix_hint": "Only messages starting with this prefix trigger AI",
        "ai_trigger_aliases": "Trigger Aliases:",
        "ai_trigger_aliases_hint": "Extra APRS addressees, comma-separated",
        "ai_extra_sms":       "Extra SMS Parts:",
        "ai_extra_sms_hint":  "0=single reply, 1-5=multi-part (5s delay)",
        "ai_wl_enabled":      "Enable Whitelist",
        "ai_whitelist":       "Whitelist:",
        "ai_whitelist_hint":  "Comma-separated callsigns, wildcards OK: TA3*",
        # imap
        "imap_enabled":       "Enable IMAP Receiver",
        "imap_server":        "IMAP Server:",
        "imap_server_hint":   "host:port  e.g.  imap.gmail.com:993",
        "imap_user":          "Username:",
        "imap_pass":          "Password:",
        "imap_pass_hint":     "Gmail: use an App Password",
        "imap_interval":      "Poll interval (minutes):",
        "imap_from":          "From callsign:",
        "imap_from_hint":     "APRS sender callsign for forwarded emails",
        "imap_allowed":       "Allowed sender emails:",
        "imap_allowed_hint":  "Comma-separated. Leave empty to allow all.",
        # smtp
        "smtp_enabled":       "Enable SMTP Email",
        "smtp_server":        "SMTP Server:",
        "smtp_server_hint":   "host:port  e.g.  smtp.gmail.com:587",
        "smtp_user":          "Username:",
        "smtp_pass":          "Password:",
        "smtp_senders":       "Allowed APRS senders:",
        "smtp_recip":         "Allowed APRS recipients:",
        "smtp_emails":        "Allowed destination emails:",
        "smtp_emails_hint":   "Comma-separated, leave empty to allow all",
        "smtp_from":          "From address:",
        # ext server
        "ext_enabled":        "Enable Extension Server",
        "ext_host":           "Listen host:",
        "ext_port":           "Listen port:",
        "ext_hint":           (
            "Allows other programs on this machine to receive a live APRS "
            "stream over TCP.\n"
            "Protocol: client sends 'ping', server replies 'pong <timestamp>'.\n"
            "All packets are forwarded as  'data <aprs_line>'."
        ),
        # bottom bar
        "status_stopped":     "● Stopped",
        "status_running":     "● Running",
        "btn_start":          "▶  Start",
        "btn_stop":           "■  Stop",
        "btn_save":           "💾  Save Config",
        "btn_tray":           "⇩  Minimize to Tray",
        # tray menu
        "tray_show":          "Show",
        "tray_start":         "Start agent",
        "tray_stop":          "Stop agent",
        "tray_quit":          "Quit",
        # dialogs
        "save_ok":            "Configuration saved.",
        "save_err":           "Failed to save configuration:\n{}",
        "no_callsign":        "Please enter your callsign before starting.",
        "confirm_quit":       "The agent is still running. Quit anyway?",
        "tray_not_avail":     (
            "System tray not available.\n"
            "Install pystray and Pillow:\n"
            "  pip install pystray Pillow"
        ),
        # help / about
        "btn_help":           "?  Help",
        "btn_about":          "ℹ  About",
        "about_title":        "About APRS-Agent",
        "about_desc":         (
            "A multi-extension APRS-IS agent for amateur radio operators.\n"
            "Supports Twitter/X, SMTP email, fixed position beaconing,\n"
            "and an extension server for third-party integrations."
        ),
        "about_devs":         "Developers",
        "about_license":      "Released under the MIT License.",
        "about_source":       "Source code:",
        "about_close":        "Close",
        "about_contact":      "Contact developers:",
    },
    "tr": {
        "title":              "APRS-Agent",
        "lang_btn":           "🌐 EN",
        "cfg_label":          "Ayar dosyası:",
        "browse":             "Gözat…",
        # tabs
        "tab_conn":           "Bağlantı",
        "tab_log":            "Logger",
        "tab_beacon":         "Sabit Konum",
        "tab_twitter":        "Twitter / X",
        "tab_bluesky":        "Bluesky",
        "tab_wa":             "WhatsApp",
        "tab_tg":             "Telegram",
        "tab_ai":             "AI Gateway",
        "tab_email":          "E-Posta",
        "email_send":         "📤 Gönder — Telsiz → E-Posta (SMTP)",
        "email_recv":         "📥 Al — E-Posta → Telsiz (IMAP)",
        "tab_monitor":        "İzleyici",
        "tab_ext":            "Ext. Sunucu",
        "mon_enabled":        "Röle İzleyici",
        "mon_sub":            "DB'deki röle çevrimdışı/çevrimiçi olduğunda bildirim gönder",
        "mon_channel":        "Bildirim kanalı:",
        "mon_interval":       "Kontrol aralığı (dk):",
        "mon_watch":          "İzlenecek çağrı işaretleri:",
        "mon_watch_hint":     "Virgülle ayır. Boş = DB'deki tüm röleleri izle.",
        # connection
        "server":             "APRS-IS Sunucusu:",
        "port":               "Port:",
        "callsign":           "Çağrı İşareti:",
        "allowed_cs":         "İstasyon Filtresi:",
        "allowed_cs_hint":    "APRS-IS'den hangi istasyonlar izlenecek. Joker OK  örn.  TA3* = tüm TA3 istasyonları",
        "st_packets":         "Paket",
        "st_stations":        "İstasyon",
        "st_calls":           "Çağrı İşareti",
        "st_uptime":          "Süre",
        "full_feed":          "Tüm Dünya Akışı (port 10152)",
        "full_feed_warn":     (
            "⚠  Tüm dünya APRS trafiğini alır (~50–100 pkt/s). "
            "Extension'lar yalnızca kendi listelerindeki çağrı işaretlerine yanıt verir. "
            "Aşağıdaki hız sınırı şiddetle tavsiye edilir."
        ),
        "rate_limit_pps":     "Hız sınırı (pkt/sn):",
        "rate_limit_hint":    "Saniyede extension'lara iletilen maksimum paket. 0 = sınırsız.",
        "repeater_db_path":   "Röle DB Dosyası:",
        "repeater_db_hint":   "repeaters.json dosyasının yolu (Turkey Repeaters). Stations sekmesi eşleşen çağrı işaretlerini şehir, frekans ve ton bilgisiyle zenginleştirir.",
        "print_cfg":          "Başlangıçta ayarları ekrana yaz",
        "autostart":          "Windows ile başlat",
        "autostart_agent":    "Başlangıçta ajanı otomatik başlat",
        # logger
        "log_enabled":        "Logger'ı Etkinleştir",
        "log_comments":       "Sunucu yorum satırlarını (#) logla",
        "filter_type":        "Paket türü filtresi:",
        "filter_type_hint":   "Virgülle ayırılmış karakterler  örn.  !, :, ;, @",
        "exclude_type":       "Hariç tutulacak paket türleri:",
        "kw_filter":          "Anahtar kelime filtresi:",
        "kw_filter_hint":     "Virgülle ayır, büyük/küçük harf önemsiz",
        # beacon
        "bcn_enabled":        "Sabit Konum Yayınını Etkinleştir",
        "bcn_locator":        "QTH Locator:",
        "bcn_locator_hint":   "Maidenhead grid  örn.  KM38nk23  (4/6/8 hane) ← enlem/boylamı otomatik günceller",
        "bcn_ssid":           "İstasyon SSID:",
        "bcn_ssid_hint":      "Çağrı işareti + SSID  örn.  TA3HRJ-10",
        "bcn_lat":            "Enlem:",
        "bcn_lat_hint":       "DDMM.MMN formatı  örn.  4100.00N",
        "bcn_lon":            "Boylam:",
        "bcn_lon_hint":       "DDDMM.MME formatı  örn.  02900.00E",
        "bcn_sym_tbl":        "Sembol:",
        "bcn_sym_pick":       "Sembol Seç…",
        "bcn_comment":        "Beacon açıklaması:",
        "bcn_interval":       "Gönderim aralığı (dakika):",
        # twitter
        "tw_enabled":         "Twitter / X Entegrasyonunu Etkinleştir",
        "tw_api_key":         "API Anahtarı:",
        "tw_api_secret":      "API Gizli Anahtarı:",
        "tw_tok_key":         "Erişim Token Anahtarı:",
        "tw_tok_secret":      "Erişim Token Gizli Anahtarı:",
        "tw_hashtag":         "#APRS hashtag otomatik ekle",
        "tw_recepients":      "İzin verilen APRS alıcıları:",
        "tw_senders":         "İzin verilen APRS göndericileri:",
        "tw_cs_hint":         "Virgülle ayırılmış çağrı işaretleri",
        # bluesky
        "bsky_enabled":       "Bluesky Entegrasyonunu Etkinleştir",
        "bsky_username":      "Kullanıcı adı (handle):",
        "bsky_username_hint": "örn.  adınız.bsky.social",
        "bsky_app_pass":      "Uygulama Şifresi:",
        "bsky_app_pass_hint": "bsky.app → Ayarlar → App Passwords bölümünden oluşturun",
        "bsky_hashtag":       "#APRS hashtag otomatik ekle",
        "bsky_recepients":    "İzin verilen APRS alıcıları:",
        "bsky_senders":       "İzin verilen APRS göndericileri:",
        "bsky_cs_hint":       "Virgülle ayırılmış çağrı işaretleri",
        # whatsapp
        "wa_enabled":         "WhatsApp Etkinleştir",
        "wa_phone_id":        "Telefon Numarası ID:",
        "wa_token":           "Erişim Token:",
        "wa_verify":          "Webhook Doğrulama Token:",
        "wa_recipient":       "Alıcı Telefon:",
        "wa_hashtag":         "#APRS hashtag ekle",
        "wa_recepients":      "İzin verilen APRS alıcıları:",
        "wa_senders":         "İzin verilen APRS göndericileri:",
        "wa_from_call":       "Gönderen çağrı işareti:",
        "wa_aprs_dest":       "Varsayılan APRS hedefi:",
        "wa_allowed_phones":  "İzin verilen telefon numaraları:",
        # telegram
        "tg_enabled":         "Telegram Etkinleştir",
        "tg_token":           "Bot Token:",
        "tg_chat_id":         "Chat ID:",
        "tg_hashtag":         "#APRS hashtag ekle",
        "tg_recepients":      "İzin verilen APRS alıcıları:",
        "tg_senders":         "İzin verilen APRS göndericileri:",
        "tg_poll_enabled":    "Telegram yokla (gelen)",
        "tg_poll_interval":   "Yoklama aralığı (saniye):",
        "tg_from_call":       "Gönderen çağrı işareti:",
        "tg_aprs_dest":       "Varsayılan APRS hedefi:",
        # ai gateway
        "ai_enabled":         "AI Gateway'i Etkinleştir",
        "ai_callsign":        "AI Çağrı İşareti:",
        "ai_callsign_hint":   "Bu çağrı işaretine gelen mesajlar AI yanıtı tetikler",
        "ai_provider":        "Sağlayıcı:",
        "ai_api_key":         "API Anahtarı:",
        "ai_base_url":        "Özel Base URL:",
        "ai_base_url_hint":   "Sadece özel sağlayıcı için. Varsayılan için boş bırakın.",
        "ai_model":           "Model:",
        "ai_model_hint":      "Varsayılan için boş bırakın",
        "ai_system_prompt":   "Sistem Promptu:",
        "ai_trigger_prefix":  "Tetikleme Ön Eki:",
        "ai_trigger_prefix_hint": "Sadece bu ön ekle başlayan mesajlar AI'ı tetikler",
        "ai_trigger_aliases": "Tetikleme Takma Adları:",
        "ai_trigger_aliases_hint": "Ek APRS alıcı adları, virgülle ayır",
        "ai_extra_sms":       "Ek SMS Parçası:",
        "ai_extra_sms_hint":  "0=tek yanıt, 1-5=çok parçalı (5s gecikme)",
        "ai_wl_enabled":      "Whitelist'i Etkinleştir",
        "ai_whitelist":       "Whitelist:",
        "ai_whitelist_hint":  "Virgülle ayırılmış çağrı işaretleri, joker OK: TA3*",
        # imap
        "imap_enabled":       "IMAP Alıcıyı Etkinleştir",
        "imap_server":        "IMAP Sunucusu:",
        "imap_server_hint":   "host:port  örn.  imap.gmail.com:993",
        "imap_user":          "Kullanıcı adı:",
        "imap_pass":          "Şifre:",
        "imap_pass_hint":     "Gmail: Uygulama Şifresi kullanın",
        "imap_interval":      "Yoklama aralığı (dakika):",
        "imap_from":          "Gönderen çağrı işareti:",
        "imap_from_hint":     "İletilen e-postalar için APRS gönderen çağrı işareti",
        "imap_allowed":       "İzin verilen gönderen e-postalar:",
        "imap_allowed_hint":  "Virgülle ayırın, boş bırakırsanız hepsi kabul edilir.",
        # smtp
        "smtp_enabled":       "SMTP E-posta Entegrasyonunu Etkinleştir",
        "smtp_server":        "SMTP Sunucusu:",
        "smtp_server_hint":   "host:port  örn.  smtp.gmail.com:587",
        "smtp_user":          "Kullanıcı adı:",
        "smtp_pass":          "Şifre:",
        "smtp_senders":       "İzin verilen APRS göndericileri:",
        "smtp_recip":         "İzin verilen APRS alıcıları:",
        "smtp_emails":        "İzin verilen hedef e-posta adresleri:",
        "smtp_emails_hint":   "Virgülle ayır, boş bırakırsan hepsi serbest",
        "smtp_from":          "Gönderen adresi:",
        # ext server
        "ext_enabled":        "Extension Sunucusunu Etkinleştir",
        "ext_host":           "Dinleme adresi:",
        "ext_port":           "Dinleme portu:",
        "ext_hint":           (
            "Bu bilgisayardaki diğer programların TCP üzerinden canlı APRS akışı "
            "almasını sağlar.\n"
            "Protokol: istemci 'ping' gönderir, sunucu 'pong <zaman>' yanıtlar.\n"
            "Tüm paketler  'data <aprs_satırı>'  olarak iletilir."
        ),
        # bottom bar
        "status_stopped":     "● Durduruldu",
        "status_running":     "● Çalışıyor",
        "btn_start":          "▶  Başlat",
        "btn_stop":           "■  Durdur",
        "btn_save":           "💾  Ayarları Kaydet",
        "btn_tray":           "⇩  Tepsiye Küçült",
        # tray menu
        "tray_show":          "Göster",
        "tray_start":         "Ajanı başlat",
        "tray_stop":          "Ajanı durdur",
        "tray_quit":          "Çıkış",
        # dialogs
        "save_ok":            "Ayarlar kaydedildi.",
        "save_err":           "Ayarlar kaydedilemedi:\n{}",
        "no_callsign":        "Başlatmadan önce çağrı işaretinizi girin.",
        "confirm_quit":       "Ajan hâlâ çalışıyor. Yine de çıkmak istiyor musunuz?",
        "tray_not_avail":     (
            "Sistem tepsisi kullanılamıyor.\n"
            "Kurulum için:\n"
            "  pip install pystray Pillow"
        ),
        # help / about
        "btn_help":           "?  Yardım",
        "btn_about":          "ℹ  Hakkında",
        "about_title":        "APRS-Agent Hakkında",
        "about_desc":         (
            "Amatör radyo operatörleri için çok eklentili bir APRS-IS ajanı.\n"
            "Twitter/X, SMTP e-posta, sabit konum yayını ve\n"
            "üçüncü taraf entegrasyonları için extension sunucusu destekler."
        ),
        "about_devs":         "Geliştiriciler",
        "about_license":      "MIT Lisansı ile yayımlanmıştır.",
        "about_source":       "Kaynak kod:",
        "about_close":        "Kapat",
        "about_contact":      "Geliştiricilere ulaşın:",
    },
}


# ─── Queue-based stderr redirector ───────────────────────────────────────────

class _QueueWriter:
    """Captures all stderr output and puts it into a queue for the GUI log panel."""

    def __init__(self, q: queue.Queue):
        self._q = q

    def write(self, text: str) -> None:
        if text:
            self._q.put(text)

    def flush(self) -> None:
        pass


# ─── About dialog ────────────────────────────────────────────────────────────

class _AboutDialog:
    """
    Modal 'About' dialog showing version, description, and developer contacts.
    Email addresses are clickable (opens default mail client via mailto:).
    """

    _DEVELOPERS = [
        ("TA3HRJ", "ta3hrj@gmail.com",    "https://github.com/TA3HRJ"),
        ("TA3PKS", "ta3pks@mugsoft.io",   "https://github.com/TA3PKS"),
        ("TA3EKM", None,                   "https://github.com/ArdaYalinOzkan"),
    ]
    _GITHUB_URL = "https://github.com/TA3HRJ/aprs-agent"

    def __init__(self, parent: tk.Widget, lang: str):
        import webbrowser

        s = _S[lang]

        dlg = tk.Toplevel(parent)
        dlg.title(s["about_title"])
        dlg.resizable(False, False)
        dlg.transient(parent)
        dlg.grab_set()
        if _ICON_PATH.exists():
            try:
                dlg.iconbitmap(str(_ICON_PATH))
            except Exception:
                pass

        outer = ttk.Frame(dlg, padding=20)
        outer.pack(fill="both")

        # ── Logo ──
        try:
            if _ICON_PATH.exists():
                from PIL import Image, ImageTk
                img = Image.open(str(_ICON_PATH)).resize((64, 64), Image.LANCZOS)
                _photo = ImageTk.PhotoImage(img)
                lbl_img = tk.Label(outer, image=_photo, bg=outer.cget("background"))
                lbl_img.image = _photo          # keep reference
                lbl_img.pack()
        except Exception:
            pass

        # ── App name + version ──
        ttk.Label(
            outer,
            text="APRS-Agent",
            font=("TkDefaultFont", 16, "bold"),
        ).pack(pady=(8, 0))

        ttk.Label(
            outer,
            text=f"v{_VERSION}",
            font=("TkDefaultFont", 10),
            foreground="#666666",
        ).pack()

        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=10)

        # ── Description ──
        ttk.Label(
            outer,
            text=s["about_desc"],
            justify="center",
            font=("TkDefaultFont", 9),
            foreground="#333333",
        ).pack()

        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=10)

        # ── Developers ──
        ttk.Label(
            outer,
            text=s["about_devs"],
            font=("TkDefaultFont", 10, "bold"),
        ).pack()

        dev_frame = ttk.Frame(outer, padding=(0, 4))
        dev_frame.pack()

        for callsign, email, gh_url in self._DEVELOPERS:
            row = ttk.Frame(dev_frame)
            row.pack(anchor="w", pady=2)

            ttk.Label(
                row,
                text=callsign,
                font=("Courier New", 10, "bold"),
                foreground="#1a5276",
                width=8,
                anchor="w",
            ).pack(side="left")

            if email:
                mail_lnk = tk.Label(
                    row,
                    text=email,
                    font=("TkDefaultFont", 9, "underline"),
                    foreground="#1a73e8",
                    cursor="hand2",
                )
                mail_lnk.pack(side="left")
                mail_lnk.bind("<Button-1>", lambda e, m=email: webbrowser.open(f"mailto:{m}"))
                ttk.Label(row, text="  |  ", foreground="#cccccc").pack(side="left")

            gh_lnk = tk.Label(
                row,
                text=gh_url,
                font=("TkDefaultFont", 9, "underline"),
                foreground="#1a73e8",
                cursor="hand2",
            )
            gh_lnk.pack(side="left")
            gh_lnk.bind("<Button-1>", lambda e, u=gh_url: webbrowser.open(u))

        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=10)

        # ── Source / License ──
        src_row = ttk.Frame(outer)
        src_row.pack()
        ttk.Label(
            src_row,
            text=s["about_source"] + "  ",
            font=("TkDefaultFont", 9),
        ).pack(side="left")
        gh_link = tk.Label(
            src_row,
            text=self._GITHUB_URL,
            font=("TkDefaultFont", 9, "underline"),
            foreground="#1a73e8",
            cursor="hand2",
        )
        gh_link.pack(side="left")
        gh_link.bind("<Button-1>", lambda e: webbrowser.open(self._GITHUB_URL))

        ttk.Label(
            outer,
            text=s["about_license"],
            font=("TkDefaultFont", 9),
            foreground="#666666",
        ).pack(pady=(4, 0))

        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=10)

        # ── Close ──
        ttk.Button(outer, text=s["about_close"], command=dlg.destroy).pack()

        # ── Centre over parent ──
        parent.update_idletasks()
        dlg.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width()  - dlg.winfo_width())  // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{px}+{py}")

        dlg.wait_window()


# ─── APRS Symbol picker dialog ───────────────────────────────────────────────

class _SymbolPickerDialog:
    """
    Modal dialog for picking an APRS symbol from a visual grid.
    Shows common symbols from the Primary (/) or Alternate (\\) table.
    Returns (table, char) on accept, or None on cancel.
    """

    _COLS = 8   # symbols per row

    def __init__(self, parent: tk.Widget, lang: str,
                 current_table: str, current_sym: str):
        self._lang = lang
        self._result: Optional[tuple[str, str]] = None
        self._selected: Optional[tuple[str, str]] = (current_table, current_sym)
        self._table_var = tk.StringVar(value=current_table)
        self._btn_frames: dict[tuple[str, str], tk.Frame] = {}
        self._sprite_refs: list = []   # keep PhotoImage refs alive

        self._dlg = tk.Toplevel(parent)
        is_en = lang == "en"
        self._dlg.title("Select Symbol" if is_en else "Sembol Seç")
        self._dlg.resizable(False, False)
        self._dlg.transient(parent)
        self._dlg.grab_set()
        if _ICON_PATH.exists():
            try:
                self._dlg.iconbitmap(str(_ICON_PATH))
            except Exception:
                pass

        self._build(is_en)

        # Centre over parent
        parent.update_idletasks()
        self._dlg.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width()  - self._dlg.winfo_width())  // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - self._dlg.winfo_height()) // 2
        self._dlg.geometry(f"+{px}+{py}")

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self, is_en: bool) -> None:
        # ── Table radio buttons ──
        tbl_frame = ttk.LabelFrame(
            self._dlg,
            text="Table" if is_en else "Tablo",
            padding=(10, 6),
        )
        tbl_frame.pack(fill="x", padx=12, pady=(12, 4))

        ttk.Radiobutton(
            tbl_frame,
            text="/ Primary" if is_en else "/ Birincil",
            variable=self._table_var, value="/",
            command=self._refresh_grid,
        ).pack(side="left", padx=(0, 24))
        ttk.Radiobutton(
            tbl_frame,
            text="\\ Alternate" if is_en else "\\ Alternatif",
            variable=self._table_var, value="\\",
            command=self._refresh_grid,
        ).pack(side="left")

        # ── Symbol grid container ──
        self._grid_frame = ttk.Frame(self._dlg, padding=(8, 4))
        self._grid_frame.pack(fill="both", padx=12)

        # ── Preview line ──
        self._preview_var = tk.StringVar()
        ttk.Label(
            self._dlg, textvariable=self._preview_var,
            font=("TkDefaultFont", 9), foreground="#555555",
        ).pack(padx=12, pady=(4, 2))

        # ── Accept / Cancel ──
        btn_frame = ttk.Frame(self._dlg, padding=(12, 4, 12, 12))
        btn_frame.pack(fill="x")
        ttk.Button(
            btn_frame,
            text="Accept" if is_en else "Tamam",
            command=self._accept,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            btn_frame,
            text="Cancel" if is_en else "İptal",
            command=self._cancel,
        ).pack(side="left")

        self._refresh_grid()

    # ── Grid refresh ──────────────────────────────────────────────────────────

    def _refresh_grid(self) -> None:
        for w in self._grid_frame.winfo_children():
            w.destroy()
        self._btn_frames.clear()
        self._sprite_refs.clear()

        table        = self._table_var.get()
        symbols      = _APRS_PRIMARY_SYMBOLS if table == "/" else _APRS_ALTERNATE_SYMBOLS
        is_en        = self._lang == "en"
        sprite_sheet = _SPRITE_PRIMARY if table == "/" else _SPRITE_ALTERNATE
        use_sprites  = sprite_sheet is not None

        # PIL / ImageTk import — only needed when sprites are available
        if use_sprites:
            try:
                from PIL import ImageTk
            except ImportError:
                use_sprites = False

        for idx, (char, name_en, name_tr) in enumerate(symbols):
            name   = name_en if is_en else name_tr
            col    = idx % self._COLS
            row    = idx // self._COLS
            key    = (table, char)
            is_sel = self._selected == key
            bg     = "#3a78c9" if is_sel else "#e8e8e8"

            cell = tk.Frame(
                self._grid_frame,
                relief="sunken" if is_sel else "raised",
                bd=2,
                bg=bg,
                cursor="hand2",
                padx=3, pady=2,
            )
            cell.grid(row=row, column=col, padx=2, pady=2)

            if use_sprites:
                # Crop the 24×24 sprite for this character
                offset  = ord(char) - ord('!')
                sx, sy  = (offset % 16) * 24, (offset // 16) * 24
                sprite  = sprite_sheet.crop((sx, sy, sx + 24, sy + 24))
                photo   = ImageTk.PhotoImage(sprite)
                self._sprite_refs.append(photo)
                img_lbl = tk.Label(cell, image=photo, bg=bg, cursor="hand2")
                img_lbl.pack()
            else:
                # Fallback: show the APRS character in a monospace font
                img_lbl = tk.Label(
                    cell,
                    text=char,
                    font=("Courier New", 16, "bold"),
                    width=2,
                    bg=bg,
                    fg="white" if is_sel else "#111111",
                )
                img_lbl.pack()

            name_lbl = tk.Label(
                cell,
                text=name[:12],
                font=("TkDefaultFont", 7),
                wraplength=60,
                bg=bg,
                fg="#f0f0f0" if is_sel else "#555555",
            )
            name_lbl.pack()

            for w in (cell, img_lbl, name_lbl):
                w.bind("<Button-1>", lambda e, k=key, n=name: self._select(k, n))

            self._btn_frames[key] = cell

        self._update_preview()

    # ── Selection ─────────────────────────────────────────────────────────────

    def _apply_cell_style(self, key: tuple[str, str], selected: bool) -> None:
        """Update the visual highlight of a single cell without rebuilding the grid."""
        cell = self._btn_frames.get(key)
        if cell is None:
            return
        bg     = "#3a78c9" if selected else "#e8e8e8"
        relief = "sunken"  if selected else "raised"
        cell.configure(bg=bg, relief=relief)
        children = cell.winfo_children()
        for i, child in enumerate(children):
            child.configure(bg=bg)
            try:                                   # text label has fg; image label does not
                if i == 0:
                    child.configure(fg="white" if selected else "#111111")
                else:
                    child.configure(fg="#f0f0f0" if selected else "#555555")
            except tk.TclError:
                pass

    def _select(self, key: tuple[str, str], name: str) -> None:
        """Select a symbol cell: unhighlight old, highlight new, update preview."""
        old = self._selected
        self._selected = key
        if old is not None and old != key:
            self._apply_cell_style(old, False)
        self._apply_cell_style(key, True)
        self._update_preview()

    def _update_preview(self) -> None:
        if not self._selected:
            self._preview_var.set("")
            return
        table, char = self._selected
        name = _aprs_symbol_name(table, char, self._lang)
        tbl_label = ("Primary" if table == "/" else "Alternate") if self._lang == "en" \
                    else ("Birincil" if table == "/" else "Alternatif")
        self._preview_var.set(f"{table}{char}  —  {name}  ({tbl_label})")

    def _accept(self) -> None:
        self._result = self._selected
        self._dlg.destroy()

    def _cancel(self) -> None:
        self._dlg.destroy()

    def show(self) -> Optional[tuple[str, str]]:
        self._dlg.wait_window()
        return self._result


# ─── Agent runner (background asyncio thread) ────────────────────────────────

class AgentRunner:
    """
    Runs the APRS-Agent event loop in a background daemon thread.
    Safe to call start()/stop() from the main (tkinter) thread.
    """

    def __init__(self, log_queue: queue.Queue):
        self._log_q = log_queue
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None
        self.running = False

    def start(self, config: dict) -> None:
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(
            target=self._thread_main,
            args=(config,),
            daemon=True,
            name="aprs-agent",
        )
        self._thread.start()

    def stop(self) -> None:
        if not self.running or self._loop is None:
            return
        if self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)

    def _thread_main(self, config: dict) -> None:
        old_stderr = sys.stderr
        sys.stderr = _QueueWriter(self._log_q)

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run(config))
        except Exception as e:
            self._log_q.put(f"[agent] Fatal error: {e}\n")
        finally:
            sys.stderr = old_stderr
            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None
            self._stop_event = None
            self.running = False

    async def _run(self, config: dict) -> None:
        self._stop_event = asyncio.Event()

        # Clear extensions from any previous run
        ExtensionRegistry.clear()

        # Extension server
        if config["extension_server"]["enabled"]:
            ext_store = ext_server_module.start(config)
        else:
            ext_store = ext_server_module.ConStore()

        # Import and register extensions
        from extensions.logger_ext import Logger
        from extensions.twitter_ext import Twitter
        from extensions.bluesky_ext import Bluesky
        from extensions.telegram_ext import Telegram
        from extensions.ai_gateway_ext import AIGateway
        from extensions.imap_ext import ImapReceiver
        from extensions.smtp_ext import SmtpEmailer
        from extensions.fixed_beacon import FixedBeacon

        ext_cfg = config.get("extensions", {})
        _pairs = [
            ("twitter",      Twitter,      ext_cfg.get("twitter", {})),
            ("bluesky",      Bluesky,      ext_cfg.get("bluesky", {})),
            ("telegram",     Telegram,     ext_cfg.get("telegram", {})),
            ("ai_gateway",   AIGateway,    ext_cfg.get("ai_gateway", {})),
            ("imap",         ImapReceiver, ext_cfg.get("imap", {})),
            ("logger",       Logger,       ext_cfg.get("logger", {})),
            ("smtp",         SmtpEmailer,  ext_cfg.get("smtp", {})),
            ("fixed_beacon", FixedBeacon,  ext_cfg.get("fixed_beacon", {})),
        ]
        for name, cls, cfg in _pairs:
            if cfg.get("enabled"):
                try:
                    ExtensionRegistry.register(cls(cfg))
                except Exception as e:
                    print(f"[{name}] Init failed: {e}", file=sys.stderr)

        # Start APRS connection task and wait until stop signal
        server_task = asyncio.create_task(
            aprs_connection.start_server(config, ext_store)
        )
        await self._stop_event.wait()
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

        # Cancel any remaining background tasks (e.g. the Fixed Beacon loop).
        # Without this, beacon tasks would keep sleeping until their interval
        # expires even though the agent has stopped.
        current = asyncio.current_task()
        for task in asyncio.all_tasks():
            if task is not current and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        print("[agent] stopped.", file=sys.stderr)


# ─── Main GUI class ───────────────────────────────────────────────────────────

class APRSAgentGUI:

    def __init__(self, config_path: str):
        self._cfg_path = config_path
        self._lang = "en"
        self._lang_widgets: list[tuple] = []   # (widget, attr, key)
        self._runner = AgentRunner(log_queue := queue.Queue())
        self._log_q: queue.Queue = log_queue
        self._tray_icon: Optional[object] = None
        self._scroll_canvases: list[tk.Canvas] = []  # one canvas per scrollable tab
        # Live stats
        self._stat_pkt_count = 0
        self._stat_unique_count = 0
        self._stat_calls_count = 0
        self._stat_seen_calls: set = set()
        self._stat_seen_base: set = set()
        self._stat_started_at: Optional[float] = None
        self._stat_src_re = re.compile(
            r'\[logger\] ([A-Z0-9]{3,9}(?:-[A-Z0-9]{1,2})?)>'
        )

        self.root = tk.Tk()
        self.root.title(self._t("title"))
        self.root.geometry("960x700")
        self.root.minsize(800, 600)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Set window icon — try both methods for cross-version compatibility.
        # iconphoto(True, ...) also propagates automatically to all child Toplevel windows.
        if _ICON_PATH.exists():
            try:
                self.root.iconbitmap(str(_ICON_PATH))
            except Exception:
                pass
            try:
                from PIL import Image, ImageTk
                _ico_img = Image.open(str(_ICON_PATH))
                _ico_photos = [
                    ImageTk.PhotoImage(_ico_img.resize((s, s), Image.LANCZOS))
                    for s in (16, 32, 48)
                ]
                self.root.iconphoto(True, *_ico_photos)
                self._icon_photos = _ico_photos   # prevent garbage collection
            except Exception:
                pass

        self._apply_theme()
        self._build_ui()
        self._load_config_to_form()
        self._poll_log_queue()

    # ── Translation helper ────────────────────────────────────────────────────

    def _t(self, key: str) -> str:
        return _S[self._lang].get(key, key)

    def _reg(self, widget, attr: str, key: str) -> None:
        """Register a widget for automatic language updates."""
        self._lang_widgets.append((widget, attr, key))

    def _lbl(self, parent, key: str, **kw) -> ttk.Label:
        w = ttk.Label(parent, text=self._t(key), **kw)
        self._reg(w, "text", key)
        return w

    def _hint(self, parent, key: str) -> ttk.Label:
        w = ttk.Label(parent, text=self._t(key), foreground="#888888",
                      font=("TkDefaultFont", 8))
        self._reg(w, "text", key)
        return w

    def _btn_reg(self, parent, key: str, cmd, **kw) -> ttk.Button:
        w = ttk.Button(parent, text=self._t(key), command=cmd, **kw)
        self._reg(w, "text", key)
        return w

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TNotebook.Tab", padding=[12, 5])
        style.configure("Start.TButton", foreground="white", background="#2a7a2a",
                        font=("TkDefaultFont", 10, "bold"))
        style.map("Start.TButton", background=[("active", "#1f5e1f")])
        style.configure("Stop.TButton", foreground="white", background="#8b1a1a",
                        font=("TkDefaultFont", 10, "bold"))
        style.map("Stop.TButton", background=[("active", "#6a1212")])
        style.configure("Running.TLabel", foreground="#1a8c1a",
                        font=("TkDefaultFont", 10, "bold"))
        style.configure("Stopped.TLabel", foreground="#888888",
                        font=("TkDefaultFont", 10, "bold"))

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._build_top_bar()
        self._build_notebook()
        self._setup_mousewheel()
        self._build_log_area()
        self._build_bottom_bar()

    def _build_top_bar(self) -> None:
        bar = ttk.Frame(self.root, padding=(8, 6, 8, 2))
        bar.pack(fill="x")

        self._lbl(bar, "cfg_label").pack(side="left")

        self._cfg_path_var = tk.StringVar(value=self._cfg_path)
        ttk.Entry(bar, textvariable=self._cfg_path_var, width=50).pack(
            side="left", padx=(4, 4))

        self._btn_reg(bar, "browse", self._browse_config).pack(side="left")

        lang_btn = ttk.Button(bar, text=self._t("lang_btn"),
                              command=self._toggle_language, width=8)
        self._reg(lang_btn, "text", "lang_btn")
        lang_btn.pack(side="right")

        self._btn_reg(bar, "btn_about", self._show_about, width=10).pack(
            side="right", padx=(0, 4))

        self._btn_reg(bar, "btn_help", self._open_help, width=8).pack(
            side="right", padx=(0, 4))

    def _build_notebook(self) -> None:
        self._nb = ttk.Notebook(self.root, padding=4)
        self._nb.pack(fill="both", expand=True, padx=8, pady=(4, 0))

        tab_keys = ["tab_conn", "tab_log", "tab_beacon",
                    "tab_twitter", "tab_bluesky", "tab_wa",
                    "tab_tg", "tab_ai", "tab_email", "tab_monitor", "tab_ext"]
        builders = [
            self._build_conn_tab,
            self._build_logger_tab,
            self._build_beacon_tab,
            self._build_twitter_tab,
            self._build_bluesky_tab,
            self._build_whatsapp_tab,
            self._build_telegram_tab,
            self._build_ai_tab,
            self._build_email_tab,
            self._build_monitor_tab,
            self._build_extserver_tab,
        ]
        self._tab_keys = tab_keys
        self._nb_tab_frames = []
        for key, builder in zip(tab_keys, builders):
            frame = ttk.Frame(self._nb)
            self._nb.add(frame, text=self._t(key))
            self._nb_tab_frames.append(frame)
            builder(frame)

    def _scrollable(self, parent) -> ttk.Frame:
        """Return a scrollable frame inside parent.

        The canvas reference is appended to self._scroll_canvases so that
        _setup_mousewheel() can route the single root-level MouseWheel binding
        to the currently active tab's canvas.
        """
        canvas = tk.Canvas(parent, highlightthickness=0)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = ttk.Frame(canvas, padding=(12, 8))
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_resize(event):
            canvas.itemconfig(win_id, width=event.width)
        canvas.bind("<Configure>", _on_resize)

        def _on_content(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", _on_content)

        self._scroll_canvases.append(canvas)
        return inner

    def _setup_mousewheel(self) -> None:
        """Register a single root-level MouseWheel binding that routes to the
        active tab's canvas.  Called once after all tabs are built."""
        def _on_wheel(event: tk.Event) -> None:
            try:
                idx = self._nb.index(self._nb.select())
                self._scroll_canvases[idx].yview_scroll(
                    int(-1 * (event.delta / 120)), "units"
                )
            except Exception:
                pass
        self.root.bind_all("<MouseWheel>", _on_wheel)

    def _row(self, frame, row, key, var,
             hint_key=None, show=False, width=42) -> ttk.Entry:
        """Helper: add label + entry on a grid row. Returns the Entry."""
        self._lbl(frame, key).grid(row=row, column=0, sticky="w",
                                   padx=(0, 8), pady=(6, 0))
        e = ttk.Entry(frame, textvariable=var, width=width,
                      show="●" if show else "")
        e.grid(row=row, column=1, sticky="ew", pady=(6, 0))
        if hint_key:
            self._hint(frame, hint_key).grid(
                row=row + 1, column=1, sticky="w", pady=(0, 2))
        return e

    def _check(self, frame, row, key, var, command=None) -> ttk.Checkbutton:
        kw = {"command": command} if command else {}
        w = ttk.Checkbutton(frame, text=self._t(key), variable=var, **kw)
        self._reg(w, "text", key)
        w.grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 2))
        return w

    # ── Connection tab ────────────────────────────────────────────────────────

    def _build_conn_tab(self, parent) -> None:
        f = self._scrollable(parent)
        f.columnconfigure(1, weight=1)

        self._v_server = tk.StringVar()
        self._v_port = tk.StringVar()
        self._v_callsign = tk.StringVar()
        self._v_allowed_cs = tk.StringVar()
        self._v_print_cfg      = tk.BooleanVar()
        self._v_autostart      = tk.BooleanVar(value=_autostart_get())
        self._v_autostart_agent = tk.BooleanVar()
        self._v_full_feed      = tk.BooleanVar()
        self._v_rate_limit     = tk.StringVar()
        self._v_repeater_db    = tk.StringVar()

        self._row(f, 0, "server",      self._v_server, width=42)
        self._row(f, 2, "port",        self._v_port,   width=10)
        self._row(f, 4, "callsign",    self._v_callsign, width=20)
        self._row(f, 6, "allowed_cs",  self._v_allowed_cs,
                  hint_key="allowed_cs_hint", width=42)
        self._check(f, 8,  "print_cfg",      self._v_print_cfg)
        self._check(f, 10, "autostart_agent", self._v_autostart_agent)
        if sys.platform == "win32":
            self._check(f, 12, "autostart", self._v_autostart,
                        command=self._toggle_autostart)
        self._check(f, 14, "full_feed", self._v_full_feed)
        self._full_feed_warn = ttk.Label(
            f, text=self._t("full_feed_warn"),
            foreground="#dcdcaa", wraplength=420, justify="left",
        )
        self._full_feed_warn.grid(row=15, column=0, columnspan=2,
                                  sticky="w", padx=8, pady=(0, 4))
        self._lang_widgets.append((self._full_feed_warn, "text", "full_feed_warn"))
        self._row(f, 16, "rate_limit_pps", self._v_rate_limit,
                  hint_key="rate_limit_hint", width=10)
        self._row(f, 18, "repeater_db_path", self._v_repeater_db,
                  hint_key="repeater_db_hint", width=42)

    # ── Logger tab ────────────────────────────────────────────────────────────

    def _build_logger_tab(self, parent) -> None:
        f = self._scrollable(parent)
        f.columnconfigure(1, weight=1)

        self._v_log_enabled = tk.BooleanVar()
        self._v_log_comments = tk.BooleanVar()
        self._v_filter_type = tk.StringVar()
        self._v_exclude_type = tk.StringVar()
        self._v_kw_filter = tk.StringVar()

        self._check(f, 0, "log_enabled",   self._v_log_enabled)
        self._check(f, 1, "log_comments",  self._v_log_comments)
        self._row(f, 2, "filter_type",  self._v_filter_type,
                  hint_key="filter_type_hint", width=42)
        self._row(f, 4, "exclude_type", self._v_exclude_type, width=42)
        self._row(f, 6, "kw_filter",    self._v_kw_filter,
                  hint_key="kw_filter_hint", width=42)

    # ── Fixed beacon tab ──────────────────────────────────────────────────────

    def _build_beacon_tab(self, parent) -> None:
        f = self._scrollable(parent)
        f.columnconfigure(1, weight=1)

        self._v_bcn_enabled  = tk.BooleanVar()
        self._v_bcn_locator  = tk.StringVar()
        self._v_bcn_lat      = tk.StringVar()
        self._v_bcn_lon      = tk.StringVar()
        self._v_bcn_ssid     = tk.StringVar()
        self._v_bcn_sym_tbl  = tk.StringVar()
        self._v_bcn_sym      = tk.StringVar()
        self._v_bcn_comment  = tk.StringVar()
        self._v_bcn_interval = tk.StringVar()

        # Flag to prevent circular trace updates
        self._coord_updating = False

        # ── Enabled checkbox ──
        self._check(f, 0, "bcn_enabled", self._v_bcn_enabled)

        # ── QTH Locator (Maidenhead) ──
        self._row(f, 1, "bcn_locator", self._v_bcn_locator,
                  hint_key="bcn_locator_hint", width=12)

        # ── Visual separator ──
        ttk.Separator(f, orient="horizontal").grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(10, 4))

        # ── Lat / Lon (auto-filled from locator, or edit directly) ──
        self._row(f, 4, "bcn_lat", self._v_bcn_lat,
                  hint_key="bcn_lat_hint", width=15)
        self._row(f, 6, "bcn_lon", self._v_bcn_lon,
                  hint_key="bcn_lon_hint", width=15)

        # ── Second separator before symbol/other settings ──
        ttk.Separator(f, orient="horizontal").grid(
            row=8, column=0, columnspan=2, sticky="ew", pady=(10, 4))

        # ── SSID ──
        self._row(f, 9, "bcn_ssid", self._v_bcn_ssid,
                  hint_key="bcn_ssid_hint", width=20)

        # ── Symbol picker ──
        self._v_bcn_sym_display = tk.StringVar()
        self._lbl(f, "bcn_sym_tbl").grid(row=11, column=0, sticky="w",
                                          padx=(0, 8), pady=(6, 0))
        sym_row = ttk.Frame(f)
        sym_row.grid(row=11, column=1, sticky="w", pady=(6, 0))
        ttk.Label(sym_row, textvariable=self._v_bcn_sym_display,
                  font=("Courier New", 11), foreground="#333333",
                  width=28, anchor="w").pack(side="left", padx=(0, 8))
        self._btn_reg(sym_row, "bcn_sym_pick", self._pick_symbol).pack(side="left")

        self._row(f, 13, "bcn_comment",  self._v_bcn_comment, width=42)
        self._row(f, 15, "bcn_interval", self._v_bcn_interval, width=8)

        # ── Wire bidirectional traces ──
        self._v_bcn_locator.trace_add("write", self._on_locator_changed)
        self._v_bcn_lat.trace_add("write", self._on_latlon_changed)
        self._v_bcn_lon.trace_add("write", self._on_latlon_changed)

    def _pick_symbol(self) -> None:
        """Open the APRS symbol picker dialog and apply the selection."""
        result = _SymbolPickerDialog(
            self.root, self._lang,
            self._v_bcn_sym_tbl.get() or "/",
            self._v_bcn_sym.get() or "-",
        ).show()
        if result:
            table, char = result
            self._v_bcn_sym_tbl.set(table)
            self._v_bcn_sym.set(char)
            self._update_sym_display()

    def _update_sym_display(self) -> None:
        """Refresh the symbol preview label in the beacon tab."""
        table = self._v_bcn_sym_tbl.get() or "/"
        char  = self._v_bcn_sym.get() or "-"
        name  = _aprs_symbol_name(table, char, self._lang)
        self._v_bcn_sym_display.set(f"{table}{char}  {name}")

    def _on_locator_changed(self, *_) -> None:
        """Locator field changed → update lat/lon fields."""
        if self._coord_updating:
            return
        self._coord_updating = True
        try:
            result = maidenhead_to_latlon(self._v_bcn_locator.get())
            if result:
                lat, lon = result
                self._v_bcn_lat.set(decimal_to_aprs_lat(lat))
                self._v_bcn_lon.set(decimal_to_aprs_lon(lon))
        finally:
            self._coord_updating = False

    def _on_latlon_changed(self, *_) -> None:
        """Lat or lon field changed → update locator field."""
        if self._coord_updating:
            return
        self._coord_updating = True
        try:
            lat = aprs_lat_to_decimal(self._v_bcn_lat.get())
            lon = aprs_lon_to_decimal(self._v_bcn_lon.get())
            if lat is not None and lon is not None:
                self._v_bcn_locator.set(latlon_to_maidenhead(lat, lon))
        finally:
            self._coord_updating = False

    # ── Twitter tab ───────────────────────────────────────────────────────────

    def _build_twitter_tab(self, parent) -> None:
        f = self._scrollable(parent)
        f.columnconfigure(1, weight=1)

        self._v_tw_enabled    = tk.BooleanVar()
        self._v_tw_api_key    = tk.StringVar()
        self._v_tw_api_secret = tk.StringVar()
        self._v_tw_tok_key    = tk.StringVar()
        self._v_tw_tok_secret = tk.StringVar()
        self._v_tw_hashtag    = tk.BooleanVar()
        self._v_tw_recepients = tk.StringVar()
        self._v_tw_senders    = tk.StringVar()

        self._check(f, 0,  "tw_enabled",    self._v_tw_enabled)
        self._row(f, 1,  "tw_api_key",    self._v_tw_api_key,    width=42)
        self._row(f, 3,  "tw_api_secret", self._v_tw_api_secret,
                  show=True, width=42)
        self._row(f, 5,  "tw_tok_key",    self._v_tw_tok_key,    width=42)
        self._row(f, 7,  "tw_tok_secret", self._v_tw_tok_secret,
                  show=True, width=42)
        self._check(f, 9,  "tw_hashtag",   self._v_tw_hashtag)
        self._row(f, 10, "tw_recepients", self._v_tw_recepients,
                  hint_key="tw_cs_hint", width=42)
        self._row(f, 12, "tw_senders",    self._v_tw_senders,
                  hint_key="tw_cs_hint", width=42)

    # ── Bluesky tab ───────────────────────────────────────────────────────────

    def _build_bluesky_tab(self, parent) -> None:
        f = self._scrollable(parent)
        f.columnconfigure(1, weight=1)

        self._v_bsky_enabled  = tk.BooleanVar()
        self._v_bsky_username = tk.StringVar()
        self._v_bsky_app_pass = tk.StringVar()
        self._v_bsky_hashtag  = tk.BooleanVar()
        self._v_bsky_recepients = tk.StringVar()
        self._v_bsky_senders  = tk.StringVar()

        self._check(f, 0,  "bsky_enabled",    self._v_bsky_enabled)
        self._row(f, 1,  "bsky_username",   self._v_bsky_username,
                  hint_key="bsky_username_hint", width=42)
        self._row(f, 3,  "bsky_app_pass",   self._v_bsky_app_pass,
                  show=True, hint_key="bsky_app_pass_hint", width=42)
        self._check(f, 5,  "bsky_hashtag",   self._v_bsky_hashtag)
        self._row(f, 6,  "bsky_recepients", self._v_bsky_recepients,
                  hint_key="bsky_cs_hint", width=42)
        self._row(f, 8,  "bsky_senders",    self._v_bsky_senders,
                  hint_key="bsky_cs_hint", width=42)

    # ── WhatsApp tab ─────────────────────────────────────────────────────────

    def _build_whatsapp_tab(self, parent) -> None:
        f = self._scrollable(parent)
        f.columnconfigure(1, weight=1)

        self._v_wa_enabled   = tk.BooleanVar()
        self._v_wa_phone_id  = tk.StringVar()
        self._v_wa_token     = tk.StringVar()
        self._v_wa_verify    = tk.StringVar()
        self._v_wa_recipient = tk.StringVar()
        self._v_wa_hashtag   = tk.BooleanVar()
        self._v_wa_recepients = tk.StringVar()
        self._v_wa_senders   = tk.StringVar()
        self._v_wa_from_call = tk.StringVar()
        self._v_wa_aprs_dest = tk.StringVar()
        self._v_wa_phones    = tk.StringVar()

        self._check(f, 0,  "wa_enabled",     self._v_wa_enabled)
        self._row(f, 1,  "wa_phone_id",    self._v_wa_phone_id, width=42)
        self._row(f, 3,  "wa_token",       self._v_wa_token, show=True, width=42)
        self._row(f, 5,  "wa_verify",      self._v_wa_verify, width=42)
        self._row(f, 7,  "wa_recipient",   self._v_wa_recipient, width=24)
        self._check(f, 9,  "wa_hashtag",    self._v_wa_hashtag)
        self._row(f, 10, "wa_recepients",  self._v_wa_recepients, width=42)
        self._row(f, 12, "wa_senders",     self._v_wa_senders, width=42)
        self._row(f, 14, "wa_from_call",   self._v_wa_from_call, width=20)
        self._row(f, 16, "wa_aprs_dest",   self._v_wa_aprs_dest, width=20)
        self._row(f, 18, "wa_allowed_phones", self._v_wa_phones, width=42)

    # ── Telegram tab ──────────────────────────────────────────────────────────

    def _build_telegram_tab(self, parent) -> None:
        f = self._scrollable(parent)
        f.columnconfigure(1, weight=1)

        self._v_tg_enabled   = tk.BooleanVar()
        self._v_tg_token     = tk.StringVar()
        self._v_tg_chat_id   = tk.StringVar()
        self._v_tg_hashtag   = tk.BooleanVar()
        self._v_tg_recepients = tk.StringVar()
        self._v_tg_senders   = tk.StringVar()
        self._v_tg_poll      = tk.BooleanVar()
        self._v_tg_poll_int  = tk.StringVar(value="5")
        self._v_tg_from_call = tk.StringVar()
        self._v_tg_aprs_dest = tk.StringVar()

        self._check(f, 0,  "tg_enabled",     self._v_tg_enabled)
        self._row(f, 1,  "tg_token",       self._v_tg_token, show=True, width=42)
        self._row(f, 3,  "tg_chat_id",     self._v_tg_chat_id, width=20)
        self._check(f, 5,  "tg_hashtag",    self._v_tg_hashtag)
        self._row(f, 6,  "tg_recepients",  self._v_tg_recepients, width=42)
        self._row(f, 8,  "tg_senders",     self._v_tg_senders, width=42)
        self._check(f, 10, "tg_poll_enabled", self._v_tg_poll)
        self._row(f, 11, "tg_poll_interval", self._v_tg_poll_int, width=8)
        self._row(f, 13, "tg_from_call",   self._v_tg_from_call, width=20)
        self._row(f, 15, "tg_aprs_dest",   self._v_tg_aprs_dest, width=20)

    # ── AI Gateway tab ────────────────────────────────────────────────────────

    def _build_ai_tab(self, parent) -> None:
        f = self._scrollable(parent)
        f.columnconfigure(1, weight=1)

        self._v_ai_enabled    = tk.BooleanVar()
        self._v_ai_callsign   = tk.StringVar()
        self._v_ai_provider   = tk.StringVar(value="puter")
        self._v_ai_api_key    = tk.StringVar()
        self._v_ai_base_url   = tk.StringVar()
        self._v_ai_model      = tk.StringVar()
        self._v_ai_sys_prompt = tk.StringVar()
        self._v_ai_prefix     = tk.StringVar()
        self._v_ai_aliases    = tk.StringVar()
        self._v_ai_extra_sms  = tk.StringVar(value="0")
        self._v_ai_wl_enabled = tk.BooleanVar()
        self._v_ai_whitelist  = tk.StringVar()

        self._check(f, 0,  "ai_enabled",    self._v_ai_enabled)
        self._row(f, 1,  "ai_callsign",   self._v_ai_callsign,
                  hint_key="ai_callsign_hint", width=20)

        # Provider dropdown
        self._lbl(f, "ai_provider").grid(row=3, column=0, sticky="w",
                                          padx=(0, 8), pady=(6, 0))
        prov_combo = ttk.Combobox(f, textvariable=self._v_ai_provider, width=22,
                                  values=["puter", "groq", "openrouter", "custom"],
                                  state="readonly")
        prov_combo.grid(row=3, column=1, sticky="w", pady=(6, 0))

        self._row(f, 4,  "ai_api_key",    self._v_ai_api_key,
                  show=True, width=42)
        self._row(f, 6,  "ai_base_url",   self._v_ai_base_url,
                  hint_key="ai_base_url_hint", width=42)
        self._row(f, 8,  "ai_model",      self._v_ai_model,
                  hint_key="ai_model_hint", width=36)
        self._row(f, 10, "ai_system_prompt", self._v_ai_sys_prompt, width=42)
        self._row(f, 12, "ai_trigger_prefix", self._v_ai_prefix,
                  hint_key="ai_trigger_prefix_hint", width=20)
        self._row(f, 14, "ai_trigger_aliases", self._v_ai_aliases,
                  hint_key="ai_trigger_aliases_hint", width=42)
        self._row(f, 16, "ai_extra_sms",  self._v_ai_extra_sms,
                  hint_key="ai_extra_sms_hint", width=8)
        self._check(f, 18, "ai_wl_enabled", self._v_ai_wl_enabled)
        self._row(f, 19, "ai_whitelist",  self._v_ai_whitelist,
                  hint_key="ai_whitelist_hint", width=42)

    # ── Email tab (SMTP send + IMAP receive) ────────────────────────────────

    def _build_email_tab(self, parent) -> None:
        f = self._scrollable(parent)
        f.columnconfigure(1, weight=1)

        # ── SMTP Send section ──
        self._lbl(f, "email_send").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(4, 6))

        self._v_smtp_enabled  = tk.BooleanVar()
        self._v_smtp_server   = tk.StringVar()
        self._v_smtp_user     = tk.StringVar()
        self._v_smtp_pass     = tk.StringVar()
        self._v_smtp_senders  = tk.StringVar()
        self._v_smtp_recip    = tk.StringVar()
        self._v_smtp_emails   = tk.StringVar()
        self._v_smtp_from     = tk.StringVar()

        self._check(f, 1,  "smtp_enabled",  self._v_smtp_enabled)
        self._row(f, 2,  "smtp_server",   self._v_smtp_server,
                  hint_key="smtp_server_hint", width=42)
        self._row(f, 4,  "smtp_user",     self._v_smtp_user,   width=42)
        self._row(f, 6,  "smtp_pass",     self._v_smtp_pass,
                  show=True, width=42)
        self._row(f, 8,  "smtp_senders",  self._v_smtp_senders, width=42)
        self._row(f, 10, "smtp_recip",    self._v_smtp_recip,   width=42)
        self._row(f, 12, "smtp_emails",   self._v_smtp_emails,
                  hint_key="smtp_emails_hint", width=42)
        self._row(f, 14, "smtp_from",     self._v_smtp_from,    width=42)

        # ── Separator ──
        ttk.Separator(f, orient="horizontal").grid(
            row=16, column=0, columnspan=2, sticky="ew", pady=(16, 8))

        # ── IMAP Receive section ──
        self._lbl(f, "email_recv").grid(
            row=17, column=0, columnspan=2, sticky="w", pady=(4, 6))

        self._v_imap_enabled  = tk.BooleanVar()
        self._v_imap_server   = tk.StringVar()
        self._v_imap_user     = tk.StringVar()
        self._v_imap_pass     = tk.StringVar()
        self._v_imap_interval = tk.StringVar(value="5")
        self._v_imap_from     = tk.StringVar()
        self._v_imap_allowed  = tk.StringVar()

        self._check(f, 18, "imap_enabled",  self._v_imap_enabled)
        self._row(f, 19, "imap_server",   self._v_imap_server,
                  hint_key="imap_server_hint", width=42)
        self._row(f, 21, "imap_user",     self._v_imap_user, width=42)
        self._row(f, 23, "imap_pass",     self._v_imap_pass,
                  show=True, hint_key="imap_pass_hint", width=42)
        self._row(f, 25, "imap_interval", self._v_imap_interval, width=8)
        self._row(f, 27, "imap_from",     self._v_imap_from,
                  hint_key="imap_from_hint", width=20)
        self._row(f, 29, "imap_allowed",  self._v_imap_allowed,
                  hint_key="imap_allowed_hint", width=42)

    # ── Extension server tab ──────────────────────────────────────────────────

    def _build_extserver_tab(self, parent) -> None:
        f = self._scrollable(parent)
        f.columnconfigure(1, weight=1)

        self._v_ext_enabled = tk.BooleanVar()
        self._v_ext_host    = tk.StringVar()
        self._v_ext_port    = tk.StringVar()

        self._check(f, 0, "ext_enabled", self._v_ext_enabled)
        self._row(f, 1,  "ext_host",    self._v_ext_host, width=24)
        self._row(f, 3,  "ext_port",    self._v_ext_port, width=10)
        self._hint(f, "ext_hint").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(16, 0))

    # ── Monitor tab ───────────────────────────────────────────────────────────

    def _build_monitor_tab(self, parent) -> None:
        f = self._scrollable(parent)
        f.columnconfigure(1, weight=1)

        self._v_mon_enabled  = tk.BooleanVar()
        self._v_mon_channel  = tk.StringVar(value="telegram")
        self._v_mon_interval = tk.StringVar(value="10")
        self._v_mon_watch    = tk.StringVar()

        self._check(f, 0, "mon_enabled", self._v_mon_enabled)
        ttk.Label(f, text=self._t("mon_sub"), foreground="#888888",
                  wraplength=420, justify="left").grid(
            row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 6))

        # Channel selector
        row_lbl = ttk.Label(f, text=self._t("mon_channel"))
        row_lbl.grid(row=2, column=0, sticky="w", padx=8, pady=2)
        self._lang_widgets.append((row_lbl, "text", "mon_channel"))
        ch_frame = ttk.Frame(f)
        ch_frame.grid(row=2, column=1, sticky="w", padx=4, pady=2)
        self._v_mon_channel_combo = ttk.Combobox(
            ch_frame, textvariable=self._v_mon_channel,
            values=["telegram", "smtp"], state="readonly", width=14)
        self._v_mon_channel_combo.pack(side="left")

        self._row(f, 4, "mon_interval", self._v_mon_interval,
                  hint_key=None, width=8)
        self._row(f, 6, "mon_watch", self._v_mon_watch,
                  hint_key="mon_watch_hint", width=42)

    # ── Log area ──────────────────────────────────────────────────────────────

    def _build_log_area(self) -> None:
        frame = ttk.LabelFrame(self.root, text=" Log ", padding=4)
        frame.pack(fill="both", padx=8, pady=(4, 0))

        self._log_text = scrolledtext.ScrolledText(
            frame, height=8, state="disabled",
            font=("Courier", 9), bg="#1e1e1e", fg="#d4d4d4",
            insertbackground="white", relief="flat",
        )
        self._log_text.pack(fill="both", expand=True)

        # Color tags
        self._log_text.tag_config("green",  foreground="#4ec94e")
        self._log_text.tag_config("red",    foreground="#f44747")
        self._log_text.tag_config("yellow", foreground="#dcdcaa")
        self._log_text.tag_config("normal", foreground="#d4d4d4")

        # Stats bar below log text
        stats = ttk.Frame(frame)
        stats.pack(fill="x", pady=(4, 0))
        dim = {"foreground": "#888888", "font": ("TkDefaultFont", 8)}
        self._lbl_packets  = ttk.Label(stats, text=f"{self._t('st_packets')}: 0",   **dim)
        self._lbl_stations = ttk.Label(stats, text=f"{self._t('st_stations')}: 0",  **dim)
        self._lbl_calls    = ttk.Label(stats, text=f"{self._t('st_calls')}: 0",     **dim)
        self._lbl_uptime   = ttk.Label(stats, text=f"{self._t('st_uptime')}: —",    **dim)
        self._lbl_packets.pack(side="left", padx=(0, 16))
        self._lbl_stations.pack(side="left", padx=(0, 16))
        self._lbl_calls.pack(side="left", padx=(0, 16))
        self._lbl_uptime.pack(side="left")

    # ── Bottom bar ────────────────────────────────────────────────────────────

    def _build_bottom_bar(self) -> None:
        bar = ttk.Frame(self.root, padding=(8, 6, 8, 8))
        bar.pack(fill="x", side="bottom")

        # Status label (left)
        self._status_lbl = ttk.Label(bar, text=self._t("status_stopped"),
                                      style="Stopped.TLabel", width=18)
        self._status_lbl.pack(side="left")

        # Buttons (right)
        self._btn_tray = self._btn_reg(
            bar, "btn_tray", self._minimize_to_tray)
        self._btn_tray.pack(side="right", padx=(4, 0))

        self._btn_save_cfg = self._btn_reg(
            bar, "btn_save", self._save_config)
        self._btn_save_cfg.pack(side="right", padx=(4, 0))

        self._btn_stop = ttk.Button(bar, text=self._t("btn_stop"),
                                     command=self._stop_agent,
                                     style="Stop.TButton", state="disabled")
        self._reg(self._btn_stop, "text", "btn_stop")
        self._btn_stop.pack(side="right", padx=(4, 0))

        self._btn_start = ttk.Button(bar, text=self._t("btn_start"),
                                      command=self._start_agent,
                                      style="Start.TButton")
        self._reg(self._btn_start, "text", "btn_start")
        self._btn_start.pack(side="right", padx=(4, 0))

        if not _TRAY_OK:
            self._btn_tray.configure(state="disabled")

    # ── Config ↔ form ─────────────────────────────────────────────────────────

    def _load_config_to_form(self) -> None:
        try:
            cfg = cfg_module.load_config(self._cfg_path_var.get())
        except SystemExit:
            import copy
            cfg = copy.deepcopy(cfg_module.DEFAULTS)

        def _csv(lst):
            return ", ".join(str(x) for x in lst)

        # Connection
        self._v_server.set(cfg.get("server", ""))
        self._v_port.set(str(cfg.get("port", 14580)))
        self._v_callsign.set(cfg.get("callsign", ""))
        self._v_allowed_cs.set(_csv(cfg.get("allowed_callsigns", [])))
        self._v_full_feed.set(cfg.get("full_feed", False))
        self._v_rate_limit.set(str(cfg.get("rate_limit_pps", 50)))
        self._v_repeater_db.set(cfg.get("repeater_db_path", ""))
        mon = cfg.get("monitor", {})
        self._v_mon_enabled.set(mon.get("enabled", False))
        self._v_mon_channel.set(mon.get("notify_channel", "telegram"))
        self._v_mon_interval.set(str(mon.get("check_interval_mins", 10)))
        self._v_mon_watch.set(", ".join(mon.get("watch_callsigns", [])))
        self._v_print_cfg.set(cfg.get("print_config_on_startup", False))
        self._v_autostart_agent.set(cfg.get("auto_start_agent", False))
        if cfg.get("auto_start_agent", False):
            self.root.after(1200, self._start_agent)

        # Logger
        l = cfg.get("extensions", {}).get("logger", {})
        self._v_log_enabled.set(l.get("enabled", True))
        self._v_log_comments.set(l.get("log_comments", True))
        self._v_filter_type.set(_csv(l.get("filter_by_message_type", [])))
        self._v_exclude_type.set(_csv(l.get("exclude_by_message_type", [])))
        self._v_kw_filter.set(_csv(l.get("keyword_filter", [])))

        # Beacon
        b = cfg.get("extensions", {}).get("fixed_beacon", {})
        self._v_bcn_enabled.set(b.get("enabled", False))
        self._v_bcn_ssid.set(b.get("ssid", ""))
        self._v_bcn_lat.set(b.get("lat", ""))
        self._v_bcn_lon.set(b.get("lon", ""))
        # Compute locator from stored lat/lon (if valid)
        _lat = aprs_lat_to_decimal(b.get("lat", ""))
        _lon = aprs_lon_to_decimal(b.get("lon", ""))
        if _lat is not None and _lon is not None:
            self._v_bcn_locator.set(latlon_to_maidenhead(_lat, _lon))
        else:
            self._v_bcn_locator.set("")
        self._v_bcn_sym_tbl.set(b.get("symbol_table", "/"))
        self._v_bcn_sym.set(b.get("symbol", "-"))
        self._update_sym_display()
        self._v_bcn_comment.set(b.get("comment", ""))
        self._v_bcn_interval.set(str(b.get("beacon_interval_mins", 15)))

        # Twitter
        tw = cfg.get("extensions", {}).get("twitter", {})
        self._v_tw_enabled.set(tw.get("enabled", False))
        self._v_tw_api_key.set(tw.get("api_key", ""))
        self._v_tw_api_secret.set(tw.get("api_secret", ""))
        self._v_tw_tok_key.set(tw.get("access_token_key", ""))
        self._v_tw_tok_secret.set(tw.get("access_token_secret", ""))
        self._v_tw_hashtag.set(tw.get("add_hash_tag", True))
        self._v_tw_recepients.set(_csv(tw.get("allowed_recepients", [])))
        self._v_tw_senders.set(_csv(tw.get("allowed_senders", [])))

        # Bluesky
        bsky = cfg.get("extensions", {}).get("bluesky", {})
        self._v_bsky_enabled.set(bsky.get("enabled", False))
        self._v_bsky_username.set(bsky.get("username", ""))
        self._v_bsky_app_pass.set(bsky.get("app_password", ""))
        self._v_bsky_hashtag.set(bsky.get("add_hash_tag", True))
        self._v_bsky_recepients.set(_csv(bsky.get("allowed_recepients", [])))
        self._v_bsky_senders.set(_csv(bsky.get("allowed_senders", [])))

        # WhatsApp
        wa = cfg.get("extensions", {}).get("whatsapp", {})
        self._v_wa_enabled.set(wa.get("enabled", False))
        self._v_wa_phone_id.set(wa.get("phone_number_id", ""))
        self._v_wa_token.set(wa.get("access_token", ""))
        self._v_wa_verify.set(wa.get("verify_token", ""))
        self._v_wa_recipient.set(wa.get("recipient_phone", ""))
        self._v_wa_hashtag.set(wa.get("add_hash_tag", True))
        self._v_wa_recepients.set(_csv(wa.get("allowed_recepients", [])))
        self._v_wa_senders.set(_csv(wa.get("allowed_senders", [])))
        self._v_wa_from_call.set(wa.get("from_callsign", ""))
        self._v_wa_aprs_dest.set(wa.get("aprs_destination", ""))
        self._v_wa_phones.set(_csv(wa.get("allowed_phones", [])))

        # Telegram
        tg = cfg.get("extensions", {}).get("telegram", {})
        self._v_tg_enabled.set(tg.get("enabled", False))
        self._v_tg_token.set(tg.get("bot_token", ""))
        self._v_tg_chat_id.set(tg.get("chat_id", ""))
        self._v_tg_hashtag.set(tg.get("add_hash_tag", True))
        self._v_tg_recepients.set(_csv(tg.get("allowed_recepients", [])))
        self._v_tg_senders.set(_csv(tg.get("allowed_senders", [])))
        self._v_tg_poll.set(tg.get("poll_enabled", False))
        self._v_tg_poll_int.set(str(tg.get("poll_interval_secs", 5)))
        self._v_tg_from_call.set(tg.get("from_callsign", ""))
        self._v_tg_aprs_dest.set(tg.get("aprs_destination", ""))

        # AI Gateway
        ai = cfg.get("extensions", {}).get("ai_gateway", {})
        self._v_ai_enabled.set(ai.get("enabled", False))
        self._v_ai_callsign.set(ai.get("callsign", ""))
        self._v_ai_provider.set(ai.get("provider", "puter"))
        self._v_ai_api_key.set(ai.get("api_key", ""))
        self._v_ai_base_url.set(ai.get("base_url", ""))
        self._v_ai_model.set(ai.get("model", ""))
        self._v_ai_sys_prompt.set(ai.get("system_prompt", ""))
        self._v_ai_prefix.set(ai.get("trigger_prefix", ""))
        self._v_ai_aliases.set(_csv(ai.get("trigger_aliases", [])))
        self._v_ai_extra_sms.set(str(ai.get("extra_sms", 0)))
        self._v_ai_wl_enabled.set(ai.get("whitelist_enabled", False))
        self._v_ai_whitelist.set(_csv(ai.get("whitelist", [])))

        # IMAP
        im = cfg.get("extensions", {}).get("imap", {})
        self._v_imap_enabled.set(im.get("enabled", False))
        self._v_imap_server.set(im.get("imap_server", ""))
        self._v_imap_user.set(im.get("imap_username", ""))
        self._v_imap_pass.set(im.get("imap_password", ""))
        self._v_imap_interval.set(str(im.get("poll_interval_mins", 5)))
        self._v_imap_from.set(im.get("from_callsign", ""))
        self._v_imap_allowed.set(_csv(im.get("allowed_senders", [])))

        # SMTP
        sm = cfg.get("extensions", {}).get("smtp", {})
        self._v_smtp_enabled.set(sm.get("enabled", False))
        self._v_smtp_server.set(sm.get("smtp_server", ""))
        self._v_smtp_user.set(sm.get("smtp_username", ""))
        self._v_smtp_pass.set(sm.get("smtp_password", ""))
        self._v_smtp_senders.set(_csv(sm.get("allowed_senders", [])))
        self._v_smtp_recip.set(_csv(sm.get("allowed_recipients", [])))
        self._v_smtp_emails.set(_csv(sm.get("allowed_receiver_emails", [])))
        self._v_smtp_from.set(sm.get("from_email", ""))

        # Ext server
        es = cfg.get("extension_server", {})
        self._v_ext_enabled.set(es.get("enabled", False))
        self._v_ext_host.set(es.get("host", "127.0.0.1"))
        self._v_ext_port.set(str(es.get("port", 65080)))

    def _form_to_config(self) -> dict:
        """Read all form fields and return a config dict."""

        def _lst(s: str) -> list:
            return [x.strip() for x in s.split(",") if x.strip()]

        def _chars(s: str) -> list:
            # Comma-separated single chars; handle escaped backslash
            parts = [x.strip() for x in s.split(",") if x.strip()]
            result = []
            for p in parts:
                if p == "\\\\" or p == "\\":
                    result.append("\\")
                elif len(p) == 1:
                    result.append(p)
            return result

        sym_table = self._v_bcn_sym_tbl.get() or "/"

        return {
            "server":                 self._v_server.get().strip(),
            "port":                   int(self._v_port.get().strip() or 14580),
            "callsign":               self._v_callsign.get().strip().upper(),
            "allowed_callsigns":      _lst(self._v_allowed_cs.get()),
            "full_feed":              self._v_full_feed.get(),
            "rate_limit_pps":         max(0, int(self._v_rate_limit.get().strip() or 50)),
            "repeater_db_path":       self._v_repeater_db.get().strip(),
            "monitor": {
                "enabled":             self._v_mon_enabled.get(),
                "notify_channel":      self._v_mon_channel.get(),
                "check_interval_mins": max(1, int(self._v_mon_interval.get().strip() or 10)),
                "watch_callsigns":     [c.strip().upper() for c in self._v_mon_watch.get().split(",") if c.strip()],
            },
            "print_config_on_startup": self._v_print_cfg.get(),
            "auto_start_agent":        self._v_autostart_agent.get(),
            "extension_server": {
                "enabled": self._v_ext_enabled.get(),
                "host":    self._v_ext_host.get().strip(),
                "port":    int(self._v_ext_port.get().strip() or 65080),
            },
            "extensions": {
                "logger": {
                    "enabled":                 self._v_log_enabled.get(),
                    "log_comments":            self._v_log_comments.get(),
                    "filter_by_message_type":  _chars(self._v_filter_type.get()),
                    "exclude_by_message_type": _chars(self._v_exclude_type.get()),
                    "keyword_filter":          _lst(self._v_kw_filter.get()),
                },
                "fixed_beacon": {
                    "enabled":              self._v_bcn_enabled.get(),
                    "ssid":                 self._v_bcn_ssid.get().strip().upper(),
                    "lat":                  self._v_bcn_lat.get().strip(),
                    "lon":                  self._v_bcn_lon.get().strip(),
                    "symbol_table":         sym_table,
                    "symbol":               self._v_bcn_sym.get().strip()[:1] or "-",
                    "comment":              self._v_bcn_comment.get().strip(),
                    "beacon_interval_mins": int(self._v_bcn_interval.get().strip() or 15),
                },
                "twitter": {
                    "enabled":              self._v_tw_enabled.get(),
                    "api_key":              self._v_tw_api_key.get().strip(),
                    "api_secret":           self._v_tw_api_secret.get().strip(),
                    "access_token_key":     self._v_tw_tok_key.get().strip(),
                    "access_token_secret":  self._v_tw_tok_secret.get().strip(),
                    "add_hash_tag":         self._v_tw_hashtag.get(),
                    "allowed_recepients":   _lst(self._v_tw_recepients.get()),
                    "allowed_senders":      _lst(self._v_tw_senders.get()),
                },
                "bluesky": {
                    "enabled":              self._v_bsky_enabled.get(),
                    "username":             self._v_bsky_username.get().strip(),
                    "app_password":         self._v_bsky_app_pass.get(),
                    "add_hash_tag":         self._v_bsky_hashtag.get(),
                    "allowed_recepients":   _lst(self._v_bsky_recepients.get()),
                    "allowed_senders":      _lst(self._v_bsky_senders.get()),
                },
                "whatsapp": {
                    "enabled":              self._v_wa_enabled.get(),
                    "phone_number_id":      self._v_wa_phone_id.get().strip(),
                    "access_token":         self._v_wa_token.get(),
                    "verify_token":         self._v_wa_verify.get().strip(),
                    "recipient_phone":      self._v_wa_recipient.get().strip(),
                    "add_hash_tag":         self._v_wa_hashtag.get(),
                    "allowed_recepients":   _lst(self._v_wa_recepients.get()),
                    "allowed_senders":      _lst(self._v_wa_senders.get()),
                    "from_callsign":        self._v_wa_from_call.get().strip().upper(),
                    "aprs_destination":     self._v_wa_aprs_dest.get().strip().upper(),
                    "allowed_phones":       _lst(self._v_wa_phones.get()),
                },
                "telegram": {
                    "enabled":              self._v_tg_enabled.get(),
                    "bot_token":            self._v_tg_token.get(),
                    "chat_id":              self._v_tg_chat_id.get().strip(),
                    "add_hash_tag":         self._v_tg_hashtag.get(),
                    "allowed_recepients":   _lst(self._v_tg_recepients.get()),
                    "allowed_senders":      _lst(self._v_tg_senders.get()),
                    "poll_enabled":         self._v_tg_poll.get(),
                    "poll_interval_secs":   int(self._v_tg_poll_int.get().strip() or 5),
                    "from_callsign":        self._v_tg_from_call.get().strip().upper(),
                    "aprs_destination":     self._v_tg_aprs_dest.get().strip().upper(),
                },
                "ai_gateway": {
                    "enabled":              self._v_ai_enabled.get(),
                    "callsign":             self._v_ai_callsign.get().strip().upper(),
                    "provider":             self._v_ai_provider.get(),
                    "api_key":              self._v_ai_api_key.get(),
                    "base_url":             self._v_ai_base_url.get().strip(),
                    "model":                self._v_ai_model.get().strip(),
                    "system_prompt":        self._v_ai_sys_prompt.get(),
                    "trigger_prefix":       self._v_ai_prefix.get().strip(),
                    "trigger_aliases":      _lst(self._v_ai_aliases.get()),
                    "extra_sms":            int(self._v_ai_extra_sms.get().strip() or 0),
                    "whitelist_enabled":    self._v_ai_wl_enabled.get(),
                    "whitelist":            _lst(self._v_ai_whitelist.get()),
                },
                "imap": {
                    "enabled":              self._v_imap_enabled.get(),
                    "imap_server":          self._v_imap_server.get().strip(),
                    "imap_username":        self._v_imap_user.get().strip(),
                    "imap_password":        self._v_imap_pass.get(),
                    "poll_interval_mins":   int(self._v_imap_interval.get().strip() or 5),
                    "from_callsign":        self._v_imap_from.get().strip().upper(),
                    "allowed_senders":      _lst(self._v_imap_allowed.get()),
                },
                "smtp": {
                    "enabled":               self._v_smtp_enabled.get(),
                    "smtp_server":           self._v_smtp_server.get().strip(),
                    "smtp_username":         self._v_smtp_user.get().strip(),
                    "smtp_password":         self._v_smtp_pass.get(),
                    "allowed_senders":       _lst(self._v_smtp_senders.get()),
                    "allowed_recipients":    _lst(self._v_smtp_recip.get()),
                    "allowed_receiver_emails": _lst(self._v_smtp_emails.get()),
                    "from_email":            self._v_smtp_from.get().strip(),
                },
            },
        }

    # ── Actions ───────────────────────────────────────────────────────────────

    def _open_help(self) -> None:
        """Open HELP.html in the system's default web browser."""
        # Look next to this script (also handles PyInstaller _MEIPASS)
        candidates = [
            Path(__file__).parent / "HELP.html",
        ]
        if hasattr(sys, "_MEIPASS"):
            candidates.insert(0, Path(sys._MEIPASS) / "HELP.html")
        for p in candidates:
            if p.exists():
                webbrowser.open(p.as_uri())
                return
        # Fallback: open online README
        webbrowser.open("https://github.com/TA3HRJ/aprs-agent")

    def _toggle_autostart(self) -> None:
        _autostart_set(self._v_autostart.get(), self._cfg_path_var.get())

    def _show_about(self) -> None:
        _AboutDialog(self.root, self._lang)

    def _browse_config(self) -> None:
        path = filedialog.askopenfilename(
            title="Select config file",
            filetypes=[("TOML files", "*.toml"), ("All files", "*.*")],
            initialfile=self._cfg_path_var.get(),
        )
        if path:
            self._cfg_path_var.set(path)
            self._load_config_to_form()

    def _save_config(self) -> None:
        try:
            cfg = self._form_to_config()
            cfg_module.sync_config_to_file(cfg, self._cfg_path_var.get())
            self._log(self._t("save_ok"), "green")
        except Exception as e:
            messagebox.showerror("Error", self._t("save_err").format(e))

    def _start_agent(self) -> None:
        if self._runner.running:
            return
        cs = self._v_callsign.get().strip()
        if not cs or cs == "N0CALL":
            messagebox.showwarning("", self._t("no_callsign"))
            return
        self._save_config()
        cfg = self._form_to_config()
        self._stat_pkt_count = 0
        self._stat_unique_count = 0
        self._stat_calls_count = 0
        self._stat_seen_calls.clear()
        self._stat_seen_base.clear()
        self._stat_started_at = None
        self._lbl_packets.configure(text=f"{self._t('st_packets')}: 0")
        self._lbl_stations.configure(text=f"{self._t('st_stations')}: 0")
        self._lbl_uptime.configure(text=f"{self._t('st_uptime')}: 0s")
        self._runner.start(cfg)
        self._stat_started_at = __import__("time").time()
        self._update_status(running=True)
        self._tick_uptime()

    def _stop_agent(self) -> None:
        self._runner.stop()
        self._stat_started_at = None
        self._update_status(running=False)

    def _tick_uptime(self) -> None:
        if not self._runner.running or self._stat_started_at is None:
            return
        secs = int(__import__("time").time() - self._stat_started_at)
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        if h:
            txt = f"{h}h {m}m"
        elif m:
            txt = f"{m}m {s}s"
        else:
            txt = f"{s}s"
        self._lbl_uptime.configure(text=f"{self._t('st_uptime')}: {txt}")
        self.root.after(1000, self._tick_uptime)

    def _update_status(self, running: bool) -> None:
        if running:
            self._status_lbl.configure(
                text=self._t("status_running"), style="Running.TLabel")
            self._btn_start.configure(state="disabled")
            self._btn_stop.configure(state="normal")
        else:
            self._status_lbl.configure(
                text=self._t("status_stopped"), style="Stopped.TLabel")
            self._btn_start.configure(state="normal")
            self._btn_stop.configure(state="disabled")

    # ── Tray ─────────────────────────────────────────────────────────────────

    def _make_tray_image(self) -> "Image.Image":
        try:
            if _ICON_PATH.exists():
                return Image.open(str(_ICON_PATH)).resize((64, 64)).convert("RGBA")
        except Exception:
            pass
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, 62, 62], fill=(30, 90, 140, 255))
        draw.ellipse([18, 18, 46, 46], fill=(255, 165, 0, 255))
        return img

    def _minimize_to_tray(self) -> None:
        if not _TRAY_OK:
            messagebox.showinfo("", self._t("tray_not_avail"))
            return
        self.root.withdraw()
        if self._tray_icon is None:
            self._tray_icon = pystray.Icon(
                "aprs-agent",
                self._make_tray_image(),
                "APRS-Agent",
                menu=pystray.Menu(
                    pystray.MenuItem(
                        self._t("tray_show"),
                        lambda icon, item: self.root.after(0, self._restore_window),
                        default=True,
                    ),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(
                        self._t("tray_start"),
                        lambda icon, item: self.root.after(0, self._start_agent),
                    ),
                    pystray.MenuItem(
                        self._t("tray_stop"),
                        lambda icon, item: self.root.after(0, self._stop_agent),
                    ),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(
                        self._t("tray_quit"),
                        lambda icon, item: self.root.after(0, self._quit),
                    ),
                ),
            )
            threading.Thread(
                target=self._tray_icon.run, daemon=True
            ).start()

    def _restore_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    # ── Language toggle ───────────────────────────────────────────────────────

    def _toggle_language(self) -> None:
        self._lang = "tr" if self._lang == "en" else "en"
        self.root.title(self._t("title"))

        # Update all registered widgets
        for widget, attr, key in self._lang_widgets:
            try:
                widget.configure(**{attr: self._t(key)})
            except Exception:
                pass

        # Update notebook tab labels
        for i, key in enumerate(self._tab_keys):
            self._nb.tab(i, text=self._t(key))

        # Update status label
        is_running = self._runner.running
        self._status_lbl.configure(
            text=self._t("status_running" if is_running else "status_stopped")
        )

        # Refresh symbol display (name changes with language)
        self._update_sym_display()

    # ── Logging ───────────────────────────────────────────────────────────────

    _MAX_LOG_LINES = 10_000

    def _log(self, text: str, tag: str = "normal") -> None:
        self._log_text.configure(state="normal")
        self._log_text.insert("end", text.rstrip("\n") + "\n", tag)
        if int(self._log_text.index("end-1c").split(".")[0]) > self._MAX_LOG_LINES:
            self._log_text.delete("1.0", f"{self._MAX_LOG_LINES // 10}.0")
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _poll_log_queue(self) -> None:
        """Read queued log messages and display in the log panel (runs in main thread)."""
        try:
            while True:
                msg = self._log_q.get_nowait()
                if not msg:
                    continue
                # Pick a color based on content
                if "\033[32m" in msg or "OK" in msg.lower():
                    tag = "green"
                elif "\033[31m" in msg or "error" in msg.lower() or "failed" in msg.lower():
                    tag = "red"
                elif "\033[33m" in msg or "warn" in msg.lower():
                    tag = "yellow"
                else:
                    tag = "normal"
                # Strip ANSI color codes
                clean = re.sub(r"\033\[[0-9;]*m", "", msg)
                self._log(clean, tag)

                # Track stats from logger lines
                m = self._stat_src_re.search(clean)
                if m:
                    self._stat_pkt_count += 1
                    call = m.group(1)
                    if call not in self._stat_seen_calls:
                        self._stat_seen_calls.add(call)
                        self._stat_unique_count += 1
                    base = call.split("-")[0]
                    if base not in self._stat_seen_base:
                        self._stat_seen_base.add(base)
                        self._stat_calls_count += 1
                    self._lbl_packets.configure(
                        text=f"{self._t('st_packets')}: {self._stat_pkt_count}"
                    )
                    self._lbl_stations.configure(
                        text=f"{self._t('st_stations')}: {self._stat_unique_count}"
                    )
                    self._lbl_calls.configure(
                        text=f"{self._t('st_calls')}: {self._stat_calls_count}"
                    )

                # Sync running state
                if "[agent] stopped" in clean.lower():
                    self._update_status(running=False)
        except queue.Empty:
            pass
        finally:
            self.root.after(200, self._poll_log_queue)

    # ── Window close / quit ───────────────────────────────────────────────────

    def _on_close(self) -> None:
        self._quit()

    def _quit(self) -> None:
        if self._runner.running:
            if not messagebox.askyesno("APRS-Agent", self._t("confirm_quit")):
                return
            self._runner.stop()
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self) -> None:
        self.root.mainloop()


# ─── Entry point ─────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="APRS-Agent GUI")
    p.add_argument("-c", "--config", default=str(_DEFAULT_CFG),
                   help="Config file path")
    return p.parse_args()


def main() -> None:
    _ensure_single_instance()
    args = _parse_args()
    APRSAgentGUI(args.config).run()


if __name__ == "__main__":
    main()
