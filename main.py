"""
APRS-Agent
==========
An APRS-IS server agent with an extensible plugin system.

Features:
  - Connects to APRS-IS and filters packets by callsign
  - Logger: logs received packets to the terminal
  - Twitter/X: forwards APRS messages to Twitter
  - SMTP: forwards APRS messages to email
  - Fixed Beacon: periodically sends your station position
  - Extension Server: provides a local TCP stream for other software

Usage:
  python main.py                          Start with default config file
  python main.py -c /path/to/config.toml  Use a specific config file
  python main.py --write-default-config   Write a fresh template config and exit
  python main.py --print-config           Show loaded config values and exit
  python main.py --sync-config-to-file    Add missing defaults to existing config

Developed by TA3HRJ & TA3PKS
MIT License - see LICENSE file
"""
from __future__ import annotations


import argparse
import asyncio
import sys

import config as cfg_module
import aprs_connection
import extension_server as ext_server_module
from extensions import ExtensionRegistry
from extensions.logger_ext import Logger
from extensions.twitter_ext import Twitter
from extensions.bluesky_ext import Bluesky
from extensions.whatsapp_ext import WhatsApp
from extensions.telegram_ext import Telegram
from extensions.ai_gateway_ext import AIGateway
from extensions.imap_ext import ImapReceiver
from extensions.smtp_ext import SmtpEmailer
from extensions.fixed_beacon import FixedBeacon


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="APRS-Agent - APRS-IS server agent with extension system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py\n"
            "  python main.py -c /etc/aprs-agent/aprsconfig.toml\n"
            "  python main.py --write-default-config\n"
        ),
    )
    parser.add_argument(
        "-c", "--config",
        default="./aprsconfig.toml",
        help="Path to config file (default: ./aprsconfig.toml)",
    )
    parser.add_argument(
        "-w", "--write-default-config",
        action="store_true",
        help="Write a fresh template config file and exit",
    )
    parser.add_argument(
        "-p", "--print-config",
        action="store_true",
        help="Print the loaded configuration and exit",
    )
    parser.add_argument(
        "-s", "--sync-config-to-file",
        action="store_true",
        help="Add missing default values to the existing config file and exit",
    )
    return parser.parse_args()


def register_extensions(config: dict) -> None:
    """Instantiate and register enabled extensions."""
    ext_cfg = config.get("extensions", {})

    if ext_cfg.get("twitter", {}).get("enabled"):
        try:
            ExtensionRegistry.register(Twitter(ext_cfg["twitter"]))
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    if ext_cfg.get("logger", {}).get("enabled"):
        ExtensionRegistry.register(Logger(ext_cfg["logger"]))

    if ext_cfg.get("smtp", {}).get("enabled"):
        try:
            ExtensionRegistry.register(SmtpEmailer(ext_cfg["smtp"]))
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    if ext_cfg.get("fixed_beacon", {}).get("enabled"):
        try:
            ExtensionRegistry.register(FixedBeacon(ext_cfg["fixed_beacon"]))
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    if ext_cfg.get("bluesky", {}).get("enabled"):
        try:
            ExtensionRegistry.register(Bluesky(ext_cfg["bluesky"]))
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    if ext_cfg.get("whatsapp", {}).get("enabled"):
        try:
            ExtensionRegistry.register(WhatsApp(ext_cfg["whatsapp"]))
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    if ext_cfg.get("telegram", {}).get("enabled"):
        try:
            ExtensionRegistry.register(Telegram(ext_cfg["telegram"]))
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    if ext_cfg.get("ai_gateway", {}).get("enabled"):
        try:
            ExtensionRegistry.register(AIGateway(ext_cfg["ai_gateway"]))
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    if ext_cfg.get("imap", {}).get("enabled"):
        try:
            ExtensionRegistry.register(ImapReceiver(ext_cfg["imap"]))
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)


async def main() -> None:
    args = parse_args()

    # --- Handle one-shot flags (write config / print / sync) ---

    if args.write_default_config:
        cfg_module.write_default_config(args.config)
        return

    try:
        config = cfg_module.load_config(args.config)
    except cfg_module.ConfigError as e:
        # load_config() used to sys.exit(1) itself; for the CLI that is still
        # the right response, so keep it here where it belongs.
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if args.print_config:
        cfg_module.print_config(config)
        return

    if args.sync_config_to_file:
        cfg_module.sync_config_to_file(config, args.config)
        return

    # --- Normal startup ---

    if config.get("print_config_on_startup"):
        cfg_module.print_config(config)

    # Start extension TCP server (if enabled)
    if config["extension_server"]["enabled"]:
        ext_con_store = ext_server_module.start(config)
    else:
        ext_con_store = ext_server_module.ConStore()

    # Register extensions
    register_extensions(config)

    # Start APRS-IS connection loop (never returns)
    await aprs_connection.start_server(config, ext_con_store)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down APRS-Agent. 73!", file=sys.stderr)
