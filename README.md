# Telegram → Immich Uploader

<video src="https://github.com/nchornii/immich_telegram_uploader/raw/main/assets/demo.mov" controls autoplay loop muted playsinline width="100%"></video>

Downloads photos, videos, and circle messages from a Telegram chat or channel and uploads them to your self-hosted [Immich](https://immich.app) instance.

## Features

- Upload **photos** from any Telegram chat or channel to Immich
- Upload **videos** from any Telegram chat or channel to Immich
- Upload **circle messages** (video notes) from Telegram to Immich
- Optionally create **Immich albums** named after the Telegram chat or channel
- Works with both **private chats** and **channels**
- Skips duplicate files using SHA-1 checksum verification

## Requirements

- Python 3.9+
- A [Telegram API app](https://my.telegram.org/apps)
- A running Immich instance with an API key

## Installation

```bash
git clone https://github.com/nchornii/immich_telegram_uploader.git
cd immich_telegram_uploader

python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip3 install -r requirements.txt
```

## Configuration

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

```env
APP_ID=12345678
API_HASH=your_telegram_api_hash
SESSION_NAME=my_session
IMMICH_API_URL=http://192.168.1.10:2283
IMMICH_API_KEY=your_immich_api_key
```

**Getting Telegram credentials:**
1. Go to [my.telegram.org/apps](https://my.telegram.org/apps)
2. Create an app and copy the `App api_id` and `App api_hash`

**Getting Immich API key:**
1. Open Immich → Account Settings → API Keys
2. Create a new key and copy it

## Running

```bash
python3 main.py
```

On the first run, Telethon will ask for your phone number and a confirmation code sent via Telegram. After that, the session is saved locally and you won't need to authenticate again.

**Interactive prompts:**
1. Choose source type: `1` for Private Chats, `2` for Channels
2. Select a chat from the numbered list
3. Choose whether to create an Immich album named after the chat (`yes`/`no`)

The script will download all media to `downloads/photos/` and `downloads/video/`, upload each file to Immich, and optionally group them into an album.
