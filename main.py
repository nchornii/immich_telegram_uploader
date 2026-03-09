import hashlib
import os
import sys
import warnings
from os.path import join, dirname

# Suppress LibreSSL warning from urllib3 v2 on macOS (uses LibreSSL instead of OpenSSL)
warnings.filterwarnings('ignore', message='.*NotOpenSSLWarning.*')
warnings.filterwarnings('ignore', category=Warning, module='urllib3')
from telethon import TelegramClient
from telethon.tl.types import User, Channel, MessageMediaPhoto, MessageMediaDocument
from dotenv import load_dotenv
from urllib.parse import urlparse
import requests
import datetime

# Load environment variables from .env file
dotenv_path = join(dirname(__file__), '.env')
load_dotenv(dotenv_path)

api_id = int(os.environ.get('APP_ID'))
api_hash = os.environ.get('API_HASH')
session_name = os.environ.get('SESSION_NAME')
immich_server_url = os.environ.get('IMMICH_API_URL')
immich_api_key = os.environ.get('IMMICH_API_KEY')

# Ensure local download folders exist
os.makedirs("downloads/photos", exist_ok=True)
os.makedirs("downloads/videos", exist_ok=True)


# ──────────────────────────────────────────────
#  Immich helpers
# ──────────────────────────────────────────────

def send_immich_request(method, endpoint, headers=None, data=None, files=None, json=None):
    """Make an authenticated HTTP request to the Immich API."""
    immich_parsed_url = urlparse(immich_server_url)
    base_url = f'{immich_parsed_url.scheme}://{immich_parsed_url.netloc}'
    api_url = f'{base_url}/api/{endpoint}'

    if headers is None:
        headers = {}
    headers.setdefault('x-api-key', immich_api_key)

    return requests.request(method, api_url, headers=headers, data=data, files=files, json=json)


def sha1(file_path):
    """Return the SHA-1 hex digest of a file (used as Immich upload checksum)."""
    with open(file_path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


def create_album(name):
    """Return the ID of an existing album by name, or create a new one."""
    response = send_immich_request('GET', 'albums')
    albums = response.json()

    for album in albums:
        if album['albumName'] == name:
            print(f" Album already exists: '{name}'")
            return album['id']

    print(f" Creating album '{name}'...")
    create_response = send_immich_request('POST', 'albums', json={'albumName': name})
    new_album = create_response.json()
    print(f" Album created: '{name}'")
    return new_album['id']


def add_assets_to_album(album_id, asset_ids):
    """Add a list of asset IDs to an album."""
    payload = {'assetIds': asset_ids, 'albumIds': [album_id]}
    return send_immich_request('PUT', 'albums/assets', json=payload).json()


def upload_file_to_immich(file_path):
    """Upload a single file to Immich and return its asset ID."""
    filename = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    print(f"Uploading  {filename} ({_human_size(file_size)})...", end='', flush=True)

    payload = {
        'deviceId': 'telegram-uploader',
        'deviceAssetId': sha1(file_path),
        'fileCreatedAt': datetime.datetime.fromtimestamp(os.path.getmtime(file_path)).strftime("%Y-%m-%d %H:%M:%S"),
        'fileModifiedAt': datetime.datetime.fromtimestamp(os.path.getctime(file_path)).strftime("%Y-%m-%d %H:%M:%S"),
        'filename': filename,
    }
    files = [('assetData', open(file_path, 'rb'))]
    headers = {
        'Accept': 'application/json',
        'x-immich-checksum': sha1(file_path),
    }

    response = send_immich_request('POST', 'assets', headers=headers, data=payload, files=files)
    os.remove(file_path)

    asset_id = response.json().get('id')
    print(f"\r Uploaded   {filename}                          ")
    return asset_id


# ──────────────────────────────────────────────
#  Telegram helpers
# ──────────────────────────────────────────────

# Tracks the filename being downloaded so the progress bar can show it
_current_download_filename = ''


def download_progress_callback(current, total):
    """Print a single-line progress bar that updates in place during download."""
    if total:
        filled = int(20 * current / total)
        bar = '█' * filled + '░' * (20 - filled)
        pct = current / total * 100
        print(
            f"\rDownloading {_current_download_filename} [{bar}] {pct:5.1f}%"
            f"  {_human_size(current)}/{_human_size(total)}   ",
            end='',
            flush=True,
        )


def _human_size(num_bytes):
    """Convert a byte count to a human-readable string (KB / MB)."""
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


async def save_media(channel_id, name, is_create_album: bool):
    """Download all media from a channel/chat and upload each file to Immich."""
    global _current_download_filename

    channel = await client.get_entity(channel_id)

    print(f"\nScanning messages in '{name}'...", end='', flush=True)

    # First pass: count total media messages
    total_media = 0
    async for message in client.iter_messages(channel, limit=None):
        if message.media and isinstance(message.media, (MessageMediaPhoto, MessageMediaDocument)):
            total_media += 1
    print(f" found {total_media} media file(s).\n")

    album_id = None
    if is_create_album:
        album_id = create_album(name)
        print()

    asset_ids = []
    media_count = 0

    async for message in client.iter_messages(channel, limit=None):
        if not message.media:
            continue

        # Determine download folder by media type
        if isinstance(message.media, MessageMediaPhoto):
            path = 'downloads/photos/'
            media_type = 'photo'
        elif isinstance(message.media, MessageMediaDocument):
            path = 'downloads/videos/'
            media_type = 'video'
        else:
            continue

        media_count += 1
        print(f"[{media_count}/{total_media}] {media_type.capitalize()}  (msg id {message.id})")

        # Download – progress shown via callback
        _current_download_filename = f"msg_{message.id}"
        file_path = await message.download_media(
            file=path,
            progress_callback=download_progress_callback,
        )
        print()  # newline after the progress bar

        if not file_path:
            print("Download returned no file, skipping.\n")
            continue

        _current_download_filename = os.path.basename(file_path)

        # Upload to Immich
        asset_id = upload_file_to_immich(file_path)
        if asset_id:
            asset_ids.append(asset_id)

        print()

    print(f"Processed {media_count} media file(s).")

    # Bulk-add all uploaded assets to the album
    if is_create_album and album_id and asset_ids:
        print(f"\nAdding {len(asset_ids)} asset(s) to album...")
        add_assets_to_album(album_id, asset_ids)
        print("Album updated.")


# ──────────────────────────────────────────────
#  Interactive menu
# ──────────────────────────────────────────────

async def list_channels(dialog_type):
    """List dialogs of the given type, prompt user to pick one, then start upload."""
    dialogs = await client.get_dialogs()
    dialog_list = [d for d in dialogs if isinstance(d.entity, dialog_type)]

    print()
    for i, chat in enumerate(dialog_list, start=1):
        entity = chat.entity
        # Channels/groups have .title; User objects have first_name/last_name
        if hasattr(entity, 'title'):
            display_name = entity.title
        else:
            display_name = ' '.join(filter(None, [entity.first_name, entity.last_name]))
        _current_title = display_name
        print(f"  {i:>3}.  {display_name}  (@{entity.username or 'no_username'})")
    print()

    choice = int(input('Select number: '))
    if not (1 <= choice <= len(dialog_list)):
        print("Invalid choice.")
        return

    selected = dialog_list[choice - 1]
    if hasattr(selected.entity, 'title'):
        display_name = selected.entity.title
    else:
        display_name = ' '.join(filter(None, [selected.entity.first_name, selected.entity.last_name]))
    print(f"\nSelected: {display_name}")

    # Ask whether to create an Immich album
    while True:
        answer = input("Create Immich album for this chat? (yes/no): ").strip().lower()
        if answer in ('yes', 'y'):
            create_album_flag = True
            break
        elif answer in ('no', 'n'):
            create_album_flag = False
            break
        else:
            print("  Please enter 'yes' or 'no'.")

    await save_media(selected.entity.id, display_name, create_album_flag)


async def main():
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("   Telegram → Immich Uploader")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    choice = input("\nChoose source:\n  1 - Private Chats\n  2 - Channels\nYour choice: ")

    if choice == '1':
        dialog_type = User
    elif choice == '2':
        dialog_type = Channel
    else:
        sys.exit('Invalid choice.')

    await list_channels(dialog_type)
    print("\nDone!")


with TelegramClient(session_name, api_id, api_hash) as client:
    client.loop.run_until_complete(main())
