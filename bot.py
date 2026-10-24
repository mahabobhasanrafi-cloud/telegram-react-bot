"""Telegram auto-react bot (no external dependencies, stdlib only).

How it works:
- Telegram sends every new channel post / group message to this server
  as a webhook update.
- The bot immediately reacts to that message with the emojis in REACTIONS
  (via Bot API setMessageReaction).
- If a chat restricts which reactions are allowed, the bot filters the
  list to that chat's available reactions (from getChat).

Setup:
1. Telegram -> @BotFather -> /newbot -> pick a name and username -> you
   get a BOT_TOKEN. Never put it in code or chat: set it as an env var.
2. Deploy (Render free tier works): the service binds $PORT and serves
   the webhook at /webhook. On boot it calls setWebhook automatically
   using RENDER_EXTERNAL_URL (or WEBHOOK_URL if you set it).
3. Channel: add the bot as an ADMIN of the channel.
   Group: make the bot an admin, or disable privacy mode via BotFather
   (/setprivacy -> Disable) so it sees every message.
4. Post something -> the bot reacts within seconds.

Env vars:
- BOT_TOKEN (required, secret): token from @BotFather.
- REACTIONS (optional): comma-separated emojis. Default is the list below.
- WEBHOOK_URL (optional): full webhook URL, e.g.
  https://your-service.onrender.com/webhook. If unset, RENDER_EXTERNAL_URL
  is used automatically on Render.
"""

import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("BOT_TOKEN", "").strip()

DEFAULT_REACTIONS = (
    "😭,🙏,😂,🤣,🙂,🙄,🤭,🥹,😅,🤔,🥲,👍,🥰,❤️,😁,😍,😡,😔,😌,😊,🥺"
)
REACTIONS = [e for e in os.environ.get("REACTIONS", DEFAULT_REACTIONS).split(",") if e.strip()]

API = "https://api.telegram.org/bot" + TOKEN if TOKEN else None

# chat_id -> set of allowed emojis (None = no restriction info, use all)
_chat_reactions = {}


def api_call(method, payload):
    """Call one Bot API method. Returns parsed JSON or None on failure."""
    if not API:
        return None
    req = urllib.request.Request(
        API + "/" + method,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as err:
        try:
            print("API error", method, err.read().decode()[:300], flush=True)
        except Exception:
            pass
        return None
    except Exception as exc:  # network trouble etc.
        print("API fail", method, exc, flush=True)
        return None


def allowed_reactions(chat_id):
    """Emojis this chat allows, or None if unknown (then try all)."""
    if chat_id in _chat_reactions:
        return _chat_reactions[chat_id]
    allowed = None
    res = api_call("getChat", {"chat_id": chat_id})
    if res and res.get("ok"):
        available = res["result"].get("available_reactions")
        if available:
            allowed = {
                item["emoji"]
                for item in available
                if item.get("type") == "emoji" and item.get("emoji")
            }
    _chat_reactions[chat_id] = allowed
    return allowed


def handle_update(update):
    # Channel posts arrive as channel_post, group messages as message.
    msg = update.get("channel_post") or update.get("message")
    if not msg:
        return
    # Never react to other bots (avoids loops).
    if msg.get("from", {}).get("is_bot"):
        return
    chat_id = msg["chat"]["id"]
    message_id = msg["message_id"]
    allowed = allowed_reactions(chat_id)
    emojis = [e for e in REACTIONS if allowed is None or e in allowed]
    if not emojis:
        return
    api_call(
        "setMessageReaction",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": [{"type": "emoji", "emoji": e} for e in emojis],
        },
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Health check endpoint for Render.
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK - react bot running")

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode() or "{}")
            handle_update(data)
        except Exception as exc:
            print("update error", exc, flush=True)
        # Always 200: Telegram retries non-200 deliveries.
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    if TOKEN:
        webhook = os.environ.get("WEBHOOK_URL", "").strip()
        if not webhook and os.environ.get("RENDER_EXTERNAL_URL"):
            webhook = os.environ["RENDER_EXTERNAL_URL"].rstrip("/") + "/webhook"
        if webhook:
            print("Setting webhook:", webhook, flush=True)
            print(api_call("setWebhook", {"url": webhook, "drop_pending_updates": True}), flush=True)
        else:
            print("No webhook URL: set WEBHOOK_URL env var.", flush=True)
    else:
        print("WARNING: BOT_TOKEN not set. Add it as an env var and restart.", flush=True)
    print("Listening on port", port, flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
