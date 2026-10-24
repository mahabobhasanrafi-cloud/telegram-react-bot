# Telegram Auto-React Bot Fleet

Bots that react to every new post in your channel/group instantly.
One service runs as many bots as you want — each bot reacts with ONE
emoji, a different one per bot (bots can only set a single reaction
per message), so a post collects a row of different emojis. No external
Python packages needed (stdlib only).

## How it works

1. Telegram delivers each new post to this server as a webhook update,
   one delivery per bot, at `/hook/<bot-id>`.
2. Each bot calls Bot API `setMessageReaction` with its own single
   emoji from your list (different per bot, by fleet position).
3. If a chat restricts reactions, each bot picks from that chat's
   allowed reactions (from `getChat`). If its emoji is rejected, it
   tries the next one and remembers the working emoji for that chat.
4. Each bot's webhook carries its own secret token (generated at boot),
   verified on every update, so forged updates are rejected.

## Deploy (Render free tier)

1. Push this folder to a GitHub repo.
2. Render dashboard -> New -> Web Service -> connect the repo.
3. Environment: Docker, Plan: Free.
4. After creation, go to Service -> Environment -> Add Environment
   Variable: Key `BOT_TOKENS`, Value = your tokens from @BotFather,
   comma-separated, no spaces. Save (the service restarts
   automatically). For a single bot, `BOT_TOKEN` also works.
5. Each bot sets its webhook itself on boot using Render's
   `RENDER_EXTERNAL_URL` (or set `WEBHOOK_BASE` yourself, e.g.
   `https://your-service.onrender.com`).

## Make them react

- **Channel:** add EVERY bot as an ADMIN of the channel.
- **Group:** make each bot an admin, OR disable privacy mode via
  @BotFather (`/setprivacy` -> Disable) so it sees every message.
- Post something -> all the bots react within seconds.

## Change the reactions

Set the `REACTIONS` env var to a comma-separated emoji list and
restart the service. Two notes: Telegram may not offer very new
emojis (e.g. 🫩) as reactions, and the ♥️ suit is not a Telegram
reaction — ❤️ is. The default list already excludes those two.

## Limits (honest)

- Render free services sleep when idle: the first reaction after a
  quiet period can take ~30-60s (webhook wake-up). After that,
  reactions arrive within seconds while the service is warm.
- Each bot reacts as its own account: a post gets one set of reactions
  per bot. Every bot must be an admin of the channel to react there.
- Only the token holder controls a bot: keep BOT_TOKENS secret.
  Never commit tokens to the repo or paste them in chat.
- Only react in chats you own/manage, and only download/react to
  content you have the right to use.
