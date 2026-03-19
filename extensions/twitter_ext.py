"""
Twitter / X Extension
=====================
Posts incoming APRS messages to a Twitter/X account.

How it works:
1. Monitors the APRS-IS stream for message packets (data type ':')
2. Checks if the sender is in the allowed_senders list
3. Checks if the APRS recipient is in the allowed_recepients list
   (e.g. "TWSEND" is a common alias used for this purpose)
4. Posts the message to Twitter
5. Sends an APRS ACK back to the sender

Requires Twitter API v1.1 credentials with read+write access.
Get credentials at: https://developer.twitter.com

Developed by TA3HRJ & TA3PKS
"""

import asyncio
from typing import Optional

import aprslib
import tweepy

from . import Extension
from config import strip_ssid


def _mask_secret(value: str) -> str:
    """Show only first 3 and last 3 characters of a secret for safe logging."""
    if len(value) <= 6:
        return "***"
    return value[:3] + "****" + value[-3:]


class Twitter(Extension):
    """
    Forwards APRS messages to Twitter/X when addressed to a configured alias.
    Runs as a spawnable (background) extension - never writes back to APRS server
    directly (ACK is handled in handle() return value when not spawnable).
    """

    def __init__(self, config: dict):
        self._config = config
        self._validate()
        self.log(
            f"Twitter initialized | api_key={_mask_secret(config['api_key'])} "
            f"| senders={config['allowed_senders']} "
            f"| recipients={config['allowed_recepients']}"
        )

    def _validate(self) -> None:
        cfg = self._config
        if not cfg.get("api_key") or not cfg.get("api_secret"):
            raise ValueError("Twitter extension: api_key and api_secret are required")
        if not cfg.get("access_token_key") or not cfg.get("access_token_secret"):
            raise ValueError(
                "Twitter extension: access_token_key and access_token_secret are required"
            )
        if not cfg.get("allowed_recepients") or not cfg.get("allowed_senders"):
            raise ValueError(
                "Twitter extension: allowed_recepients and allowed_senders cannot be empty"
            )

    @property
    def name(self) -> str:
        return "twitter"

    @property
    def is_spawnable(self) -> bool:
        # Spawnable = runs in background, cannot return data to APRS server.
        # Twitter sends tweets and sends ACK separately via the own_writer queue.
        # Set to False so we can return the ACK packet.
        return False

    async def _send_tweet(self, tweet: str) -> None:
        """Send a tweet using the Twitter API (runs in thread to avoid blocking)."""
        cfg = self._config
        loop = asyncio.get_running_loop()

        def _do_tweet():
            auth = tweepy.OAuth1UserHandler(
                cfg["api_key"],
                cfg["api_secret"],
                cfg["access_token_key"],
                cfg["access_token_secret"],
            )
            api = tweepy.API(auth)
            api.update_status(tweet)

        try:
            await loop.run_in_executor(None, _do_tweet)
            self.log(f"tweet sent: {tweet[:60]}...")
        except tweepy.TweepyException as e:
            self.error(f"tweet error: {e}")
        except Exception as e:
            self.error(f"unexpected tweet error: {e}")

    async def handle(self, line: str) -> Optional[bytes]:
        cfg = self._config

        # Skip comment lines
        if line.startswith("#"):
            return None

        # Parse the APRS packet
        try:
            packet = aprslib.parse(line)
        except Exception:
            return None

        # Only process message packets (APRS data type ':')
        if packet.get("format") != "message":
            return None

        # Check sender callsign (without SSID)
        sender_full = packet.get("from", "")
        sender_call = strip_ssid(sender_full)
        allowed_senders = cfg.get("allowed_senders", [])
        if not any(s.upper() == sender_call.upper() for s in allowed_senders):
            return None

        # Check recipient (the APRS message addressee)
        recipient = packet.get("addresse", "").strip()
        allowed_recepients = cfg.get("allowed_recepients", [])
        if recipient not in allowed_recepients:
            return None

        # Build the tweet text
        message = packet.get("message_text", "")
        path = ",".join(packet.get("path", []))
        dest = packet.get("to", "")

        tweet_text = f"{message}\nfrom {sender_full}>{dest},{path}"
        if cfg.get("add_hash_tag", True):
            tweet_text += " #APRS"

        # Send the tweet (async, in thread)
        await self._send_tweet(tweet_text)

        # Build and return the APRS ACK packet to send back to APRS-IS
        msg_id = packet.get("msgNo", "")
        if not msg_id:
            return None

        ack = f"{recipient}>{sender_full},{path}::{sender_full:<9}:ack{msg_id}\n"
        return ack.encode("utf-8")
