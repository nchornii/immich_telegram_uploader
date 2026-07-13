import asyncio
import hashlib
import os
import shutil
import signal
import sqlite3
import sys
import time
import warnings
from os.path import join, dirname

# Suppress LibreSSL warning from urllib3 v2 on macOS (uses LibreSSL instead of OpenSSL)
warnings.filterwarnings('ignore', message='.*NotOpenSSLWarning.*')
warnings.filterwarnings('ignore', category=Warning, module='urllib3')
warnings.filterwarnings('ignore', message='Using async sessions support is an experimental feature')
from telethon import TelegramClient
from telethon.tl.types import User, Chat, Channel, MessageMediaPhoto, MessageMediaDocument
from dotenv import load_dotenv
from urllib.parse import urlparse
import requests
import datetime

# Intercept Ctrl+Z (SIGTSTP) to exit cleanly instead of suspending,
# preventing the SQLite session database from remaining locked.
def _handle_sigtstp(signum, frame):
    print("\n\nExiting...")
    sys.exit(0)

signal.signal(signal.SIGTSTP, _handle_sigtstp)

# Load environment variables from .env file
dotenv_path = join(dirname(__file__), '.env')
load_dotenv(dotenv_path)

api_id = int(os.environ.get('TELEGRAM_APP_ID'))
api_hash = os.environ.get('TELEGRAM_API_HASH')
session_name = 'sessions/immich_telegram_uploader'
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
    headers.setdefault('Accept', 'application/json')

    response = requests.request(method, api_url, headers=headers, data=data, files=files, json=json)

    if not response.ok:
        raise RuntimeError(f"Immich API error [{response.status_code}] {endpoint}: {response.text}")

    return response


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
    """Add asset IDs to an album. Accepts a single ID string or a list of IDs."""
    if isinstance(asset_ids, str):
        asset_ids = [asset_ids]
    payload = {'ids': asset_ids}
    return send_immich_request('PUT', f'albums/{album_id}/assets', json=payload).json()


def check_asset_exists(file_checksum):
    """Check if an asset with the given SHA-1 checksum already exists in Immich.

    Uses the bulk-upload-check endpoint which returns action 'reject' when the
    asset is a duplicate, along with the existing asset ID.

    Returns (exists: bool, asset_id: str | None).
    """
    payload = {'assets': [{'id': file_checksum, 'checksum': file_checksum}]}
    response = send_immich_request('POST', 'assets/bulk-upload-check', json=payload)
    results = response.json().get('results', [])
    if results:
        result = results[0]
        if result.get('action') == 'reject':
            return True, result.get('assetId')
    return False, None


# File extensions not supported by Immich (e.g. voice messages, stickers)
UNSUPPORTED_EXTENSIONS = {'.oga', '.ogg', '.tgs', '.webp'}


def upload_file_to_immich(file_path):
    """Check if file exists in Immich, skip if so, otherwise upload.

    Returns the asset ID in both cases (existing or newly uploaded).
    """
    filename = os.path.basename(file_path)
    ext = os.path.splitext(filename)[1].lower()

    if ext in UNSUPPORTED_EXTENSIONS:
        print(f"  -- Skipped  {filename} (unsupported type '{ext}')")
        os.remove(file_path)
        return None

    file_checksum = sha1(file_path)

    # Check before uploading to avoid redundant transfers
    exists, existing_asset_id = check_asset_exists(file_checksum)
    if exists:
        print(f"  -- Skipped  {filename} (already in Immich)")
        os.remove(file_path)
        return existing_asset_id

    file_size = os.path.getsize(file_path)
    print(f"  Uploading  {filename} ({_human_size(file_size)})...", end='', flush=True)

    # Map common extensions to MIME types for proper Immich handling
    mime_map = {
        '.heic': 'image/heic', '.heif': 'image/heif',
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.gif': 'image/gif',
        '.webp': 'image/webp', '.tiff': 'image/tiff', '.tif': 'image/tiff',
        '.mp4': 'video/mp4', '.mov': 'video/quicktime',
        '.avi': 'video/x-msvideo', '.mkv': 'video/x-matroska',
        '.webm': 'video/webm',
    }
    content_type = mime_map.get(ext, 'application/octet-stream')

    payload = {
        'deviceId': 'telegram-uploader',
        'deviceAssetId': file_checksum,
        'fileCreatedAt': datetime.datetime.fromtimestamp(os.path.getmtime(file_path), tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        'fileModifiedAt': datetime.datetime.fromtimestamp(os.path.getctime(file_path), tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        'filename': filename,
    }
    file_handle = open(file_path, 'rb')
    files = [('assetData', (filename, file_handle, content_type))]
    headers = {
        'Accept': 'application/json',
        'x-immich-checksum': file_checksum,
    }

    try:
        response = send_immich_request('POST', 'assets', headers=headers, data=payload, files=files)
    finally:
        file_handle.close()
    os.remove(file_path)

    asset_id = response.json().get('id')
    print(f"\r  Uploaded   {filename}                          ")
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
        if not message.media or (not isinstance(message.media, MessageMediaPhoto) and not isinstance(message.media, MessageMediaDocument)):
            continue

        # Determine download folder by media type
        if isinstance(message.media, MessageMediaPhoto):
            path = 'downloads/photos/'
            media_type = 'photo'
        elif isinstance(message.media, MessageMediaDocument):
            mime = message.media.document.mime_type or ''
            if mime.startswith('video/'):
                path = 'downloads/videos/'
                media_type = 'video'
            elif mime.startswith('image/'):
                path = 'downloads/photos/'
                media_type = 'photo'
            else:
                continue
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

        # Add asset to album after upload
        if is_create_album and album_id and asset_id:
            print(f"  Adding asset to album...")
            add_assets_to_album(album_id, asset_id)
            print("  Album updated.")

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
        print(f"  {i:>3}.  {display_name}")
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
        dialog_type = (User, Chat)
    elif choice == '2':
        dialog_type = Channel
    else:
        sys.exit('Invalid choice.')

    await list_channels(dialog_type)
    print("\nDone!")


async def run():
    global client
    async with TelegramClient(session_name, api_id, api_hash) as client:
        try:
            await main()
        except (KeyboardInterrupt, EOFError):
            print("\n\nExiting...")


def _unlock_session_db():
    """Ensure the session DB is not locked before starting Telethon.

    This handles the case where a previous process was killed/suspended
    without closing the database properly (e.g. Ctrl+Z in a container).
    """
    session_file = session_name + '.session'
    if not os.path.exists(session_file):
        return

    def _is_writable():
        """Test with a WRITE operation — reads can succeed even with a write lock."""
        try:
            conn = sqlite3.connect(session_file, timeout=1)
            conn.execute('BEGIN IMMEDIATE')  # Acquires a write lock
            conn.execute('ROLLBACK')
            conn.close()
            return True
        except sqlite3.OperationalError:
            return False

    if _is_writable():
        return

    print("Session database is locked. Rebuilding session file...")

    # Force recovery by copying data to a new file (new inode = no POSIX flock)
    tmp_file = session_file + '.tmp'
    try:
        shutil.copy2(session_file, tmp_file)
        os.remove(session_file)
        # Remove any leftover journal files from the original
        for suffix in ('-wal', '-shm', '-journal'):
            f = session_file + suffix
            if os.path.exists(f):
                os.remove(f)
        os.rename(tmp_file, session_file)

        if _is_writable():
            print("  Session file rebuilt successfully.")
        else:
            raise RuntimeError("Database still locked after rebuild")
    except Exception as e:
        # Last resort: delete everything
        print(f"  Rebuild failed ({e}). Deleting session file...")
        for f in [session_file, tmp_file]:
            if os.path.exists(f):
                os.remove(f)
        for suffix in ('-wal', '-shm', '-journal'):
            f = session_file + suffix
            if os.path.exists(f):
                os.remove(f)
        print("  Session file removed. You will need to re-authenticate.")


try:
    _unlock_session_db()
    asyncio.run(run())
except (KeyboardInterrupt, EOFError):
    print("\n\nExiting...")
