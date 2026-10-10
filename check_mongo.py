from dotenv import load_dotenv
load_dotenv()
import os
from pymongo import MongoClient

uri = os.getenv('MONGODB_URI')
db_name = os.getenv('MONGODB_DB')

client = MongoClient(uri, serverSelectionTimeoutMS=10000)

try:
    client.admin.command('ping')
    print('MongoDB: CONNECTED')

    stats = client[db_name].command('dbStats')
    used_mb = stats['dataSize'] / 1024 / 1024
    storage_mb = stats['storageSize'] / 1024 / 1024

    print(f"dataSize:    {used_mb:.2f} MB")
    print(f"storageSize: {storage_mb:.2f} MB")
    print(f"collections: {stats['collections']}")
    print(f"objects:     {stats['objects']}")
    print(f"indexes:     {stats['indexes']}")

    if storage_mb >= 480:
        print('WARNING: Storage nearly full (limit 512 MB)')
    else:
        print('Storage OK')

except Exception as e:
    print(f'MongoDB FAIL: {e}')