"""
Bluesky API connection and post test.
Run: python test_bluesky.py
"""
import sys

try:
    from atproto import Client
except ImportError:
    print("ERROR: atproto not installed. Run: pip install atproto")
    sys.exit(1)

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        print("ERROR: tomli not installed. Run: pip install tomli")
        sys.exit(1)

config_path = "aprsconfig.toml"
with open(config_path, "rb") as f:
    cfg = tomllib.load(f)

bsky = cfg.get("extensions", {}).get("bluesky", {})
username   = bsky.get("username", "")
app_pass   = bsky.get("app_password", "")

if not username or not app_pass:
    print("ERROR: bluesky.username or bluesky.app_password is empty in config")
    sys.exit(1)

print(f"Credentials: {username} / {app_pass[:4]}****{app_pass[-4:]}")

print("\nLogging in to Bluesky...")
try:
    client = Client()
    profile = client.login(username, app_pass)
    print(f"Login OK — handle: @{profile.handle}  did: {profile.did}")
except Exception as e:
    print(f"Login FAILED: {type(e).__name__}: {e}")
    sys.exit(1)

post_text = "APRS-Agent Bluesky test. 73 de TA3HRJ #APRS"
print(f"\nSending test post: {post_text}")
try:
    response = client.send_post(text=post_text)
    print(f"SUCCESS — uri: {response.uri}")
    print(f"           cid: {response.cid}")
except Exception as e:
    print(f"Post FAILED: {type(e).__name__}: {e}")
    sys.exit(1)
