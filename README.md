# Telegram → Immich Uploader

Downloads photos and videos from a Telegram chat or channel and uploads them to your self-hosted [Immich](https://immich.app) instance.

## Features

- Upload photos from any Telegram chat or channel to Immich
- Upload videos from any Telegram chat or channel to Immich
- Upload video notes from Telegram to Immich
- Option to create Immich albums named after the Telegram chat or channel
- Works with private chats and channels
- Skips duplicate files using SHA-1 checksum verification

**Check out demo: https://www.youtube.com/watch?v=dgAXLGZ3uks**

## 🚀 Getting Started

### Method 1 — 🐳 Docker Compose (Recommended)

Add the following service to your existing Immich `docker-compose.yml`. Make sure it's on the same Docker network as Immich.

See the sample [docker-compose-all-immich.yml](./docker-compose-all-immich.yml) file for reference.


```yaml
services:
  # Other immich services...
  immich-telegram-uploader:
    container_name: immich_telegram_uploader
    image: ghcr.io/nchornii/immich_telegram_uploader:latest
    environment:
      TELEGRAM_APP_ID: `${TELEGRAM_APP_ID}
      TELEGRAM_API_HASH: ${TELEGRAM_API_HASH}
      IMMICH_API_URL: ${IMMICH_API_URL}
      IMMICH_API_KEY: ${IMMICH_API_KEY}
    stdin_open: true
    tty: true
    volumes:
      - ./sessions:/app/sessions
      - ./downloads:/app/downloads
```

Fill in your `.env` file:

**Getting Immich API key:**
1. Open Immich → Account Settings → API Keys
2. Create a new key and copy it

Refer here for obtaining Immich API Key: https://immich.app/docs/features/command-line-interface#obtain-the-api-key

**Getting Telegram credentials:**
1. Go to [my.telegram.org/apps](https://my.telegram.org/apps)
2. Create an app and copy the `App api_id` and `App api_hash`

Note: It can be a bit tricky to create app, telegram can return `ERROR` message. Referer to this [StackOverflow](https://stackoverflow.com/questions/38104560/telegram-api-create-new-application-error) question.

```env
TELEGRAM_APP_ID=12345678
TELEGRAM_API_HASH=your_telegram_api_hash
IMMICH_API_URL=http://immich-server:2283
IMMICH_API_KEY=your_immich_api_key
```

Then authenticate once:

```bash
docker exec -it immich_telegram_uploader python3 main.py
```

After the first login, the session is saved and you can re-run the command without re-authenticating.

---

### Method 2 — 🔧 Local Build

Clone the repo and build the image locally:

```bash
docker compose -f docker-compose.build.yml up -d
```

Then authenticate:

```bash
docker exec -it immich_telegram_uploader python3 main.py
```
---

## Running

```bash
docker exec -it immich_telegram_uploader python3 main.py
```

On the first run, Telethon will ask for your phone number and a confirmation code sent via Telegram. After that, the session is saved locally and you won't need to authenticate again.

**Interactive prompts:**
1. Choose source type: `1` for Private Chats, `2` for Channels
2. Select a chat from the numbered list
3. Choose whether to create an Immich album named after the chat (`yes`/`no`)

The script will download all media to `downloads/photos/` and `downloads/video/`, upload each file to Immich, and optionally group them into an album.
