import os
import pickle
import io
import mimetypes
import base64
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/drive']

class GoogleDriveHandler:
    def __init__(self, credentials_path='credentials.json', token_path='token.pickle'):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = None
        
        # Heroku Support: Rebuild files from environment variables if missing
        env_creds = os.environ.get("GDRIVE_CREDENTIALS")
        if env_creds and not os.path.exists(self.credentials_path):
            with open(self.credentials_path, 'w') as f:
                f.write(env_creds)
            print("Rebuilt credentials.json from environment variable.")

        env_token_b64 = os.environ.get("GDRIVE_TOKEN_BASE64")
        if env_token_b64 and not os.path.exists(self.token_path):
            try:
                with open(self.token_path, 'wb') as f:
                    f.write(base64.b64decode(env_token_b64))
                print("Rebuilt token.pickle from environment variable.")
            except Exception as e:
                print(f"Error decoding GDRIVE_TOKEN_BASE64: {e}")

    def get_auth_url(self):
        """Returns the auth URL for the user to visit."""
        if not os.path.exists(self.credentials_path):
            return None
        
        flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
        flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
        auth_url, _ = flow.authorization_url(prompt='consent')
        return auth_url

    def get_service(self):
        """Returns the Drive service, authenticating if necessary."""
        if self.service:
            return self.service
        if self.authenticate():
            return self.service
        return None

    def authenticate(self, auth_code=None):
        """Authenticates with the given code or existing token."""
        creds = None
        if os.path.exists(self.token_path):
            with open(self.token_path, 'rb') as token:
                try:
                    creds = pickle.load(token)
                except Exception as e:
                    print(f"Error loading token: {e}")
                    creds = None
        
        # 1. Load from DB first
        from database import db
        db_token = db.get_setting("gdrive_token")
        if db_token and not os.path.exists(self.token_path):
            try:
                with open(self.token_path, 'wb') as f:
                    f.write(base64.b64decode(db_token))
                print("Loaded token.pickle from Database.")
            except Exception as e:
                print(f"Error loading token from DB: {e}")

        # If there are no (valid) credentials available, let the user log in.
        try:
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(Request())
                    except Exception as refresh_error:
                        print(f"Token refresh failed: {refresh_error}")
                        # Cleanup invalid token
                        if os.path.exists(self.token_path):
                            os.remove(self.token_path)
                        db.set_setting("gdrive_token", None)
                        return False
                elif auth_code:
                    flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                    flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
                    flow.fetch_token(code=auth_code)
                    creds = flow.credentials
                else:
                    return False

                # Save the credentials for the next run
                with open(self.token_path, 'wb') as token:
                    pickle.dump(creds, token)
                
                # Also save to DB for Heroku persistence
                with open(self.token_path, 'rb') as token:
                    db.set_setting("gdrive_token", base64.b64encode(token.read()).decode('utf-8'))

            # Optimization: Use a higher cache discovery level if needed, but build is usually fine
            self.service = build('drive', 'v3', credentials=creds, cache_discovery=False)
            return True
        except Exception as e:
            print(f"Authentication error: {e}")
            # Specific handling for RefreshError or invalid_grant
            if "invalid_grant" in str(e).lower() or "expired" in str(e).lower():
                if os.path.exists(self.token_path):
                    os.remove(self.token_path)
                db.set_setting("gdrive_token", None)
                return False
            raise e # Raise to surface other actual errors (e.g., SSL issues)

    def is_authenticated(self):
        if self.service:
            return True
        return self.authenticate()

    def search_files(self, query):
        """Searches for files in Google Drive by name, restricted to a specific folder."""
        service = self.get_service()
        if not service:
            return []

        from config import FOLDER_ID
        
        # Escape single quotes in query
        safe_query = query.replace("'", "\\'")
        
        # query: name contains '...' and not mimeType = 'application/vnd.google-apps.folder'
        # Also restricted to the specific folder ID if provided
        q = f"name contains '{safe_query}' and mimeType != 'application/vnd.google-apps.folder' and trashed = false"
        if FOLDER_ID:
            q += f" and '{FOLDER_ID}' in parents"
            
        try:
            results = service.files().list(
                q=q,
                pageSize=100,
                fields="files(id, name, size, mimeType)",
                orderBy="name_natural",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
            return results.get('files', [])
        except Exception as e:
            print(f"Search error: {e}")
            return []

    def download_file(self, file_id, file_name):
        """Downloads a file from Google Drive and returns the path."""
        service = self.get_service()
        if not service:
            raise Exception("Drive service not initialized")

        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        
        # Use a temporary file path
        if not os.path.exists('downloads'):
            os.makedirs('downloads')
        
        file_path = os.path.join('downloads', file_name)
        
        with io.FileIO(file_path, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=1024*1024*5) # 5MB chunks for better speed
            done = False
            while done is False:
                status, done = downloader.next_chunk()
                if status:
                    print(f"Download {int(status.progress() * 100)}%.")
        
        return file_path

    def delete_file(self, file_id):
        """Permanently deletes a file from Google Drive."""
        service = self.get_service()
        if not service:
            raise Exception("Drive service not initialized")
        
        try:
            # Change from delete (permanent) to update (trash) for better permission compatibility
            service.files().update(fileId=file_id, body={'trashed': True}, supportsAllDrives=True).execute()
            return True
        except Exception as e:
            print(f"🔴 Delete (trash) error for {file_id}: {e}")
            raise e

    def get_all_files(self):
        """Fetches all files from the configured folder using pagination."""
        service = self.get_service()
        if not service:
            return []

        from config import FOLDER_ID
        
        q = f"mimeType != 'application/vnd.google-apps.folder' and trashed = false"
        if FOLDER_ID:
            q += f" and '{FOLDER_ID}' in parents"
            
        all_files = []
        page_token = None
        
        try:
            while True:
                results = service.files().list(
                    q=q,
                    pageSize=1000,
                    fields="nextPageToken, files(id, name, size, createdTime)",
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True
                ).execute()
                
                all_files.extend(results.get('files', []))
                page_token = results.get('nextPageToken')
                if not page_token:
                    break
            return all_files
        except Exception as e:
            print(f"Get all files error: {e}")
            return []

    def get_recursive_file_count(self, folder_id):
        """Recursively count all files in a folder and its subfolders."""
        service = self.get_service()
        if not service:
            return 0
        
        total_count = 0
        folders_to_scan = [folder_id]
        
        try:
            while folders_to_scan:
                current_folder = folders_to_scan.pop(0)
                
                # Count files in current folder
                q_files = f"'{current_folder}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed = false"
                page_token = None
                while True:
                    results = service.files().list(
                        q=q_files,
                        pageSize=1000,
                        fields="nextPageToken, files(id)",
                        pageToken=page_token,
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True
                    ).execute()
                    
                    total_count += len(results.get('files', []))
                    page_token = results.get('nextPageToken')
                    if not page_token:
                        break
                
                # Find subfolders
                q_folders = f"'{current_folder}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
                page_token = None
                while True:
                    results = service.files().list(
                        q=q_folders,
                        pageSize=1000,
                        fields="nextPageToken, files(id)",
                        pageToken=page_token,
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True
                    ).execute()
                    
                    for f in results.get('files', []):
                        folders_to_scan.append(f['id'])
                    
                    page_token = results.get('nextPageToken')
                    if not page_token:
                        break
                        
            return total_count
        except Exception as e:
            print(f"Recursive count error: {e}")
            return total_count # Return what we have so far

drive_handler = GoogleDriveHandler()
