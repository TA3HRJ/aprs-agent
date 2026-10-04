#!/usr/bin/env python3
"""Fail if the program needs tweepy installed when Twitter is not used.

2026-10-04: four Dependabot alerts on oauthlib, and three on urllib3, all
arrived through tweepy - on a server where Twitter has never been enabled.
tweepy was a hard requirement only because twitter_ext imported it at the
top, and every start path imports twitter_ext.

What must hold:

  1. extensions.twitter_ext imports with tweepy absent
  2. enabling Twitter without tweepy fails at construction with a message
     that names tweepy and how to install it - the loaders catch that and
     log "[twitter] Init failed: ...", so the agent still starts
  3. requirements.txt does not install tweepy, and the Linux lock does not
     pin it or the packages only it pulls in
  4. the Windows build still bundles it: its users cannot pip install

Usage:  python tools/check_optional_tweepy.py
Exit code 1 on failure.
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ONLY_VIA_TWEEPY = ("tweepy", "requests-oauthlib", "oauthlib", "requests",
                   "urllib3", "charset-normalizer")

CFG = {"enabled": True, "api_key": "k" * 10, "api_secret": "s" * 10,
       "access_token_key": "a" * 10, "access_token_secret": "t" * 10,
       "allowed_senders": ["TA1ABC"], "allowed_recepients": ["TWSEND"]}


def main() -> int:
    fails = []
    sys.modules["tweepy"] = None          # makes `import tweepy` raise
    sys.modules.pop("extensions.twitter_ext", None)
    try:
        mod = importlib.import_module("extensions.twitter_ext")
    except ImportError as e:
        fails.append("twitter_ext does not import without tweepy: %s" % e)
        mod = None
    if mod is not None:
        try:
            mod.Twitter(dict(CFG))
            fails.append("Twitter was constructed with no tweepy installed")
        except Exception as e:
            if "tweepy" not in str(e) or "pip install" not in str(e):
                fails.append("the error does not say how to get tweepy: %r" % str(e))
    del sys.modules["tweepy"]

    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    if re.search(r"^\s*tweepy", req, re.M | re.I):
        fails.append("requirements.txt still installs tweepy")
    lock = (ROOT / "requirements-lock-linux.txt").read_text(encoding="utf-8")
    for pkg in ONLY_VIA_TWEEPY:
        if re.search(r"^%s==" % re.escape(pkg), lock, re.M | re.I):
            fails.append("Linux lock still pins %s" % pkg)
    win = (ROOT / "requirements-build-win32.txt").read_text(encoding="utf-8")
    spec = (ROOT / "aprs_agent.spec").read_text(encoding="utf-8")
    if not re.search(r"^tweepy==", win, re.M) or "'tweepy'" not in spec:
        fails.append("the Windows build no longer bundles tweepy")

    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    tweepy is optional: absent it costs Twitter, not the program")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
