import urllib.request
import ssl
import sys

def test_connection():
    url = "https://oauth2.googleapis.com/.well-known/openid-configuration"
    print(f"Testing connection to: {url}")
    print(f"Python Version: {sys.version}")
    print(f"SSL Version: {ssl.OPENSSL_VERSION}")
    
    try:
        response = urllib.request.urlopen(url, timeout=10)
        print(f"Successfully connected! Status: {response.status}")
        return True
    except Exception as e:
        print(f"Connection Failed: {e}")
        return False

if __name__ == "__main__":
    test_connection()
