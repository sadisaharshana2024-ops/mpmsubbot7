import os
from gdrive_handler import drive_handler

def test_gdrive():
    print("Testing Google Drive Integration...")
    
    if not os.path.exists('credentials.json'):
        print("[!] Error: credentials.json not found!")
        return

    print("Checking authentication status...")
    if not drive_handler.is_authenticated():
        print("[?] Not authenticated.")
        auth_url = drive_handler.get_auth_url()
        print(f"Please visit this URL to authenticate: {auth_url}")
        print("After authenticating, run this script again or start the bot.")
    else:
        print("[+] Authenticated!")
        print("Searching for 'test' files...")
        results = drive_handler.search_files('test')
        print(f"Found {len(results)} files.")
        for f in results:
            print(f"- {f['name']} ({f['id']})")

if __name__ == "__main__":
    test_gdrive()
