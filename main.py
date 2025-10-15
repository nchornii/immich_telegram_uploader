import hashlib
import os
import sys
from os.path import join, dirname
from telethon import TelegramClient
from telethon.tl.types import User, Channel, MessageMediaPhoto
from dotenv import load_dotenv
from urllib.parse import urlparse
import requests
import datetime

dotenv_path = join(dirname(__file__), '.env')
load_dotenv(dotenv_path)

api_id = int(os.environ.get('APP_ID'))
api_hash = os.environ.get('API_HASH')
session_name = os.environ.get('SESSION_NAME')
immich_server_url = os.environ.get('IMMICH_API_URL')
immich_api_key = os.environ.get('IMMICH_API_KEY')

# === Output folders ===
os.makedirs("downloads/photos", exist_ok=True)
os.makedirs("downloads/videos", exist_ok=True)


def create_album(name):
    # Get all existing albums
    response = send_immich_request('GET', 'albums')
    albums = response.json()
    
    # Check if album with this name already exists
    for album in albums:
        if album['albumName'] == name:
            print(f"Album '{name}' already exists with ID: {album['id']}")
            return album['id']
    
    # Album doesn't exist, create a new one
    print(f"Album '{name}' not found. Creating new album...")
    create_response = send_immich_request('POST', 'albums', json={'albumName': name})
    new_album = create_response.json()
    print(f"Album '{name}' created with ID: {new_album['id']}")
    return new_album['id']


def add_assets_to_album(album_id, asset_ids):
    """
    Add multiple assets to an album.
    
    Args:
        album_id: The ID of the album
        asset_ids: List of asset IDs to add to the album
    """
    payload = {'assetIds': asset_ids, "albumIds": [album_id]}
    response = send_immich_request('PUT', f'albums/assets', json=payload)
    return response.json()


async def save_media(channel_id, is_create_album: bool):
    channel = await client.get_entity(channel_id)
    
    # List to store uploaded asset IDs
    asset_ids = []
    
    album_id = None
    if is_create_album:
        album_id = create_album(channel.title)

    async for message in client.iter_messages(channel, limit=None):
        if message.media:
            # === Photos ===
            if isinstance(message.media, MessageMediaPhoto):
                file_path = await message.download_media(file="downloads/photos/")
                asset_id = upload_file_to_immich(file_path)
                
                # Add asset ID to the list if upload was successful
                if asset_id:
                    asset_ids.append(asset_id)
                
                print(f"Saved photo: {file_path}")
    
    # After all uploads, add assets to album if album was created
    if is_create_album and album_id and asset_ids:
        print(f"\nAdding {len(asset_ids)} assets to album...")
        add_assets_to_album(album_id, asset_ids)


def sha1(file_path):
    with open(file_path, "rb") as f:
        file_hash = hashlib.sha1(f.read()).hexdigest()
    return file_hash


def send_immich_request(method, endpoint, headers=None, data=None, files=None, json=None):
    """
    Method for making API calls to Immich server.
    
    Args:
        method: HTTP method (GET, POST, PUT, DELETE, etc.)
        endpoint: API endpoint path (e.g., '/api/assets', '/api/albums')
        headers: Optional dictionary of HTTP headers
        data: Optional form data
        files: Optional files for multipart upload
        json: Optional JSON payload
    
    Returns:
        Response object from the request
    """
    immich_parsed_url = urlparse(immich_server_url)
    base_url = f'{immich_parsed_url.scheme}://{immich_parsed_url.netloc}'
    api_url = f'{base_url}/api/{endpoint}'
    
    # Add API key to headers if not already present
    if headers is None:
        headers = {}
    if 'x-api-key' not in headers:
        headers['x-api-key'] = immich_api_key
    
    response = requests.request(method, api_url, headers=headers, data=data, files=files, json=json)
    return response


def upload_file_to_immich(file_path):
    print(file_path)
    payload = {
        'deviceId': 1,
        'deviceAssetId': 1,
        'fileCreatedAt': datetime.datetime.fromtimestamp(os.path.getmtime(file_path)).strftime("%Y-%m-%d %H:%M:%S"),
        'fileModifiedAt': datetime.datetime.fromtimestamp(os.path.getctime(file_path)).strftime("%Y-%m-%d %H:%M:%S"),
        'filename': os.path.basename(file_path)
    }
    files = [
        ('assetData', open(file_path, 'rb'))
    ]
    headers = {
        'Accept': 'application/json',
        'x-immich-checksum': sha1(file_path)
    }
    response = send_immich_request('POST', 'assets', headers=headers, data=payload, files=files)
    os.remove(file_path)
    
    response_data = response.json()
    print(response_data)
    
    # Return the asset ID from the response
    return response_data.get('id')


async def list_channels(dialog_type):
    dialogs = await client.get_dialogs()

    dialog_list = [d for d in dialogs if isinstance(d.entity, dialog_type)]

    for i, chat in enumerate(dialog_list, start=1):
        entity = chat.entity
        print(f"{i} - {entity.id} | {entity.title} (@{entity.username or 'no_username'})")

    choice = int(input('Select id of chat: '))

    if 1 <= choice <= len(dialog_list):
        selected = dialog_list[choice - 1]
        print(f"You selected: {selected.entity.id}")
        
        while True:
            create_album_input = input("Create album? (yes/no): ").strip().lower()
            if create_album_input in ['yes', 'y']:
                create_album = True
                break
            elif create_album_input in ['no', 'n']:
                create_album = False
                break
            else:
                print("Invalid input. Please enter 'yes' or 'no'.")
        
        await save_media(selected.entity.id, create_album)
    else:
        print("Invalid choice!")


async def main():
    choice = input("Choose:\n1 - Private Chats\n2 - Channels\nYour choice: ")

    if choice == '1':
        type = User
    elif choice == '2':
        type = Channel
    else:
        sys.exit('Invalid choice')

    await list_channels(type)


def test():
    create_album('qwe')
    # upload_file_to_immich('downloads/photos/photo_2025-08-29_21-03-28.jpg')


with TelegramClient(session_name, api_id, api_hash) as client:
    client.loop.run_until_complete(main())

# if __name__ == '__main__':
#     test()
