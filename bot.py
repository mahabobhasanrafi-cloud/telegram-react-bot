"""Telegram auto-react bot fleet (no external dependencies, stdlib only).

One service can run MANY bots at once: set BOT_TOKENS to a comma-separated
list of tokens from @BotFather. Each bot gets its own webhook at
/hook/<bot-id> with its own secret token (generated at boot and verified
on every incoming update), and each reacts to new channel posts / group
messages with the emojis in REACTIONS (via Bot API setMessageReaction).

How it works:
- Telegram sends every new channel post / group message to this server
  as a webhook update, one delivery per bot.
- Each bot immediately reacts to that message with the emojis in
  REACTIONS. If a chat restricts which reactions are allowed, the bot
  filters the list to that chat's available reactions (from getChat).

Setup:
1. Telegram -> @BotFather -> /newbot -> pick a name and username -> you
   get a token. Repeat for every bot you want. Never put tokens in code
   or chat: set them as env vars.
2. Deploy (Render free tier works): the service binds $PORT. On boot it
   calls setWebhook for every bot automatically using RENDER_EXTERNAL_URL
   (or WEBHOOK_BASE if you set it).
3. Channel: add EVERY bot as an ADMIN of the channel.
   Group: make each bot an admin, or disable privacy mode via BotFather
   (/setprivacy -> Disable) so it sees every message.
4. Post something -> all the bots react within seconds.

Env vars:
- BOT_TOKENS (required, secret): comma-separated tokens from @BotFather.
  BOT_TOKEN (single token) still works as a fallback for one bot.
- REACTIONS (optional): comma-separated emojis. Default is the list below.
- WEBHOOK_BASE (optional): base URL, e.g. https://your-service.onrender.com.
  If unset, RENDER_EXTERNAL_URL is used automatically on Render.
"""

import json
import os
import secrets
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _load_tokens():
    raw = os.environ.get("BOT_TOKENS", "").strip()
    if not raw:
        raw = os.environ.get("BOT_TOKEN", "").strip()
    tokens = []
    for tok in raw.split(","):
        tok = tok.strip()
        if tok and tok not in tokens:
            tokens.append(tok)
    return tokens


DEFAULT_REACTIONS = (
    "😭,🙏,😂,🤣,🙂,🙄,🤭,🥹,😅,🤔,🥲,👍,🥰,❤️,😁,😍,😡,😔,😌,😊,🥺"
)
REACTIONS = [e for e in os.environ.get("REACTIONS", DEFAULT_REACTIONS).split(",") if e.strip()]


class Bot:
    """One Telegram bot: its token, webhook secret, and reaction logic."""

    def __init__(self, token):
        self.token = token
        # Bot id is the numeric part before the colon; safe to log/use in URLs.
        self.bot_id = token.split(":", 1)[0] if ":" in token else token
        # Fresh secret every boot; registered with Telegram via setWebhook
        # and checked on every incoming update. Never logged.
        self.secret = secrets.token_urlsafe(24)
        # chat_id -> set of allowed emojis (None = no restriction info, use all)
        self._chat_reactions = {}

    def api_call(self, method, payload):
        """Call one Bot API method. Returns parsed JSON or None on failure."""
        req = urllib.request.Request(
            "https://api.telegram.org/bot" + self.token + "/" + method,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as err:
            try:
                print("bot", self.bot_id, "API error", method, err.read().decode()[:200], flush=True)
            except Exception:
                pass
            return None
        except Exception as exc:  # network trouble etc.
            print("bot", self.bot_id, "API fail", method, exc, flush=True)
            return None

    def allowed_reactions(self, chat_id):
        """Emojis this chat allows, or None if unknown (then try all)."""
        if chat_id in self._chat_reactions:
            return self._chat_reactions[chat_id]
        allowed = None
        res = self.api_call("getChat", {"chat_id": chat_id})
        if res and res.get("ok"):
            available = res["result"].get("available_reactions")
            if available:
                allowed = {
                    item["emoji"]
                    for item in available
                    if item.get("type") == "emoji" and item.get("emoji")
                }
        self._chat_reactions[chat_id] = allowed
        return allowed

    def handle_update(self, update):
        # Channel posts arrive as channel_post, group messages as message.
        msg = update.get("channel_post") or update.get("message")
        if not msg:
            return
        # Never react to other bots (avoids loops).
        if msg.get("from", {}).get("is_bot"):
            return
        chat_id = msg["chat"]["id"]
        message_id = msg["message_id"]
        allowed = self.allowed_reactions(chat_id)
        emojis = [e for e in REACTIONS if allowed is None or e in allowed]
        if not emojis:
            return
        self.api_call(
            "setMessageReaction",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "reaction": [{"type": "emoji", "emoji": e} for e in emojis],
            },
        )


BOTS = {}
for _tok in _load_tokens():
    _bot = Bot(_tok)
    BOTS[_bot.bot_id] = _bot


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Health check endpoint for Render.
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK - react bot running")

    def do_POST(self):
        try:
            parts = self.path.strip("/").split("/")
            if len(parts) == 2 and parts[0] == "hook" and parts[1] in BOTS:
                bot = BOTS[parts[1]]
                # Reject forged updates: Telegram sends this header only when
                # the secret registered via setWebhook matches.
                if self.headers.get("X-Telegram-Bot-Api-Secret-Token") != bot.secret:
                    self.send_response(403)
                    self.end_headers()
                    self.wfile.write(b"forbidden")
                    return
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length).decode() or "{}")
                bot.handle_update(data)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
                return
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
        except Exception as exc:
            print("update error", exc, flush=True)
            # Always 200 on errors: Telegram retries non-200 deliveries.
            try:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
            except Exception:
                pass

    def log_message(self, *args):
        pass


def _webhook_base():
    base = os.environ.get("WEBHOOK_BASE", "").strip()
    if base:
        return base.rstrip("/")
    legacy = os.environ.get("WEBHOOK_URL", "").strip()
    if legacy.endswith("/webhook"):
        return legacy[: -len("/webhook")].rstrip("/")
    if os.environ.get("RENDER_EXTERNAL_URL"):
        return os.environ["RENDER_EXTERNAL_URL"].rstrip("/")
    return ""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    base = _webhook_base()
    if BOTS and base:
        for bot in BOTS.values():
            url = base + "/hook/" + bot.bot_id
            res = bot.api_call(
                "setWebhook",
                {"url": url, "secret_token": bot.secret, "drop_pending_updates": True},
            )
            print("bot", bot.bot_id, "webhook set ok=", bool(res and res.get("ok")), flush=True)
    elif BOTS:
        print("No webhook base: set WEBHOOK_BASE or deploy on Render.", flush=True)
    else:
        print("WARNING: no bot tokens. Set BOT_TOKENS (or BOT_TOKEN) as an env var and restart.", flush=True)
    print("Listening on port", port, "with", len(BOTS), "bot(s)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
