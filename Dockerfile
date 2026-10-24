FROM python:3.12-slim

WORKDIR /app
COPY bot.py /app/bot.py

# Render sets $PORT; the bot binds to it and serves the webhook.
EXPOSE 10000
CMD ["python", "bot.py"]
