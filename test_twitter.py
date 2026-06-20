"""
Twitter/X API v2 credential test.
Run: python test_twitter.py
"""
import sys
try:
    import tweepy
except ImportError:
    print("ERROR: tweepy not installed. Run: pip install tweepy")
    sys.exit(1)

try:
    import tomllib
except ImportError:
    import tomli as tomllib

config_path = "aprsconfig.toml"
with open(config_path, "rb") as f:
    cfg = tomllib.load(f)

tw = cfg.get("extensions", {}).get("twitter", {})
required = ["api_key", "api_secret", "access_token_key", "access_token_secret"]
for key in required:
    if not tw.get(key):
        print(f"ERROR: twitter.{key} is empty in config")
        sys.exit(1)

print("Credentials found in config.")
print(f"  api_key:          {tw['api_key'][:6]}...")
print(f"  access_token_key: {tw['access_token_key'][:6]}...")

print("\nConnecting to Twitter/X v2 API...")
try:
    client = tweepy.Client(
        consumer_key=tw["api_key"],
        consumer_secret=tw["api_secret"],
        access_token=tw["access_token_key"],
        access_token_secret=tw["access_token_secret"],
    )
    me = client.get_me()
    print(f"Auth OK — logged in as: @{me.data.username} (id: {me.data.id})")
except tweepy.TweepyException as e:
    print(f"Auth FAILED: {e}")
    if hasattr(e, 'response') and e.response is not None:
        print(f"Response body: {e.response.text[:300]}")
    sys.exit(1)

tweet_text = "APRS-Agent Twitter v2 API test. 73 de TA3HRJ #APRS"
print(f"\nSending test tweet: {tweet_text}")
try:
    resp = client.create_tweet(text=tweet_text)
    print(f"SUCCESS — tweet id: {resp.data['id']}")
except tweepy.TweepyException as e:
    print(f"Tweet FAILED: {e}")
    if hasattr(e, 'response') and e.response is not None:
        print(f"Response body: {e.response.text[:300]}")
