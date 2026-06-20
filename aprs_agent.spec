# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec file for APRS-Agent
#
# Build with:
#   pyinstaller aprs_agent.spec
#
# Output: dist/aprs-agent/aprs-agent.exe  (folder mode, easiest to distribute)
#         dist/aprs-agent-gui/aprs-agent-gui.exe

import sys
from pathlib import Path

ROOT = Path(SPECPATH)
# ico is kept in the project folder (same dir as this spec) for reliable embedding
ICON = str(ROOT / 'aprs-agent.ico')

# ── Common hidden imports needed by the extensions ───────────────────────────
_hidden = [
    'aprslib',
    'aprslib.parsing',
    'tweepy',
    'tweepy.auth',
    'atproto',
    'atproto_client',
    'atproto_client.models',
    'aiosmtplib',
    'tomllib',
    'tomli_w',
    'pystray',
    'pystray._win32',
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageTk',
    'email.mime.text',
    'email.utils',
    'smtplib',
    'asyncio',
    'threading',
]

# ── CLI (headless) version ────────────────────────────────────────────────────
cli_analysis = Analysis(
    ['main.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        ('aprsconfig.toml.template', '.'),
        ('HELP.html', '.'),                            # user guide
        ('aprs-agent.ico', '.'),                       # icon (runtime tray/window use)
        ('aprs-symbols-24-0.png', '.'),                # APRS symbol sprites - primary table
        ('aprs-symbols-24-1.png', '.'),                # APRS symbol sprites - alternate table
    ],
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'pystray'],
    noarchive=False,
)

cli_pyz = PYZ(cli_analysis.pure)

cli_exe = EXE(
    cli_pyz,
    cli_analysis.scripts,
    [],
    exclude_binaries=True,
    name='aprs-agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,           # CLI: keeps the terminal window
    icon=ICON if Path(ICON).exists() else None,
)

cli_coll = COLLECT(
    cli_exe,
    cli_analysis.binaries,
    cli_analysis.zipfiles,
    cli_analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='aprs-agent',
)

# ── GUI version ───────────────────────────────────────────────────────────────
gui_analysis = Analysis(
    ['gui.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        ('aprsconfig.toml.template', '.'),
        ('HELP.html', '.'),                            # user guide
        ('aprs-agent.ico', '.'),                       # icon (runtime tray/window use)
        ('aprs-symbols-24-0.png', '.'),                # APRS symbol sprites - primary table
        ('aprs-symbols-24-1.png', '.'),                # APRS symbol sprites - alternate table
    ],
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

gui_pyz = PYZ(gui_analysis.pure)

gui_exe = EXE(
    gui_pyz,
    gui_analysis.scripts,
    [],
    exclude_binaries=True,
    name='aprs-agent-gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI: no terminal window on startup
    icon=ICON if Path(ICON).exists() else None,
)

gui_coll = COLLECT(
    gui_exe,
    gui_analysis.binaries,
    gui_analysis.zipfiles,
    gui_analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='aprs-agent-gui',
)
