import base64
import os

def generate():
    token_path = 'token.pickle'
    if not os.path.exists(token_path):
        print(f"Error: {token_path} not found!")
        print("Please run the bot locally first to generate the token.pickle file.")
        return

    with open(token_path, 'rb') as f:
        token_data = f.read()
        b64_token = base64.b64encode(token_data).decode('utf-8')
        
    print("\n--- YOUR GDRIVE_TOKEN_BASE64 ---")
    print(b64_token)
    print("---------------------------------\n")
    print("Copy the code above and paste it into Heroku Config Vars as 'GDRIVE_TOKEN_BASE64'.")

if __name__ == "__main__":
    generate()
