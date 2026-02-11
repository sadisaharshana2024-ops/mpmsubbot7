import os
import base64
import json
import pickle

def generate_creds():
    print("--- Generating Heroku Config Vars ---")
    
    # 1. GDRIVE_CREDENTIALS
    if os.path.exists('credentials.json'):
        with open('credentials.json', 'r') as f:
            creds_content = f.read()
            # Verify it's valid JSON
            try:
                json.loads(creds_content)
                print("\n[GDRIVE_CREDENTIALS]")
                print("Copy the content below into Heroku Config Var 'GDRIVE_CREDENTIALS':")
                print("-" * 20)
                print(creds_content)
                print("-" * 20)
            except json.JSONDecodeError:
                print("❌ Error: credentials.json is not valid JSON.")
    else:
        print("❌ Error: credentials.json not found.")

    # 2. GDRIVE_TOKEN_BASE64
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as f:
            token_content = f.read()
            token_b64 = base64.b64encode(token_content).decode('utf-8')
            print("\n[GDRIVE_TOKEN_BASE64]")
            print("Copy the content below into Heroku Config Var 'GDRIVE_TOKEN_BASE64':")
            print("-" * 20)
            print(token_b64)
            print("-" * 20)
    else:
        print("❌ Error: token.pickle not found. Run the bot locally and authenticate first.")

if __name__ == "__main__":
    generate_creds()
