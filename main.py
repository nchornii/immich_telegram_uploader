import os
import sys
from os.path import join, dirname
from telethon import TelegramClient
from telethon.tl.types import User, Channel, MessageMediaPhoto
from dotenv import load_dotenv

dotenv_path = join(dirname(__file__), '.env')
load_dotenv(dotenv_path)

api_id = int(os.environ.get('APP_ID'))
api_hash = os.environ.get('API_HASH')
session_name = os.environ.get('SESSION_NAME')

# === Output folders ===
os.makedirs("downloads/photos", exist_ok=True)
os.makedirs("downloads/videos", exist_ok=True)

async def saveMedia(channelId):
    channel = await client.get_entity(channelId)

    async for message in client.iter_messages(channel, limit=None):
        if message.media:
            # === Photos ===
            if isinstance(message.media, MessageMediaPhoto):
                file_path = await message.download_media(file="downloads/photos/")
                print(f"📷 Saved photo: {file_path}")


async def listChannels(type):
    dialogs = await client.get_dialogs()

    list = [d for d in dialogs if isinstance(d.entity, type)]

    for i, chat in enumerate(list, start=1):
        entity = chat.entity
        print(f"{i} - {entity.id} | {entity.title} (@{entity.username or 'no_username'})")

    choice = int(input('Select id of chat: '))

    if 1 <= choice <= len(list):
        selected = list[choice - 1]
        print(f"You selected: {selected.entity.id}")
        await saveMedia(selected.entity.id)
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

    await listChannels(type)


with TelegramClient(session_name, api_id, api_hash) as client:
    client.loop.run_until_complete(main())