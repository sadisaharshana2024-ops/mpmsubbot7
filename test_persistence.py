from database import db
import os
import base64

def test_persistence():
    print("Testing Setting Persistence...")
    
    test_key = "test_token_persistence"
    test_value = base64.b64encode(b"dummy_token_data").decode('utf-8')
    
    # Save setting
    db.set_setting(test_key, test_value)
    print(f"Set {test_key} to {test_value}")
    
    # Retrieve setting
    retrieved = db.get_setting(test_key)
    print(f"Retrieved: {retrieved}")
    
    if retrieved == test_value:
        print("✅ SUCCESS: Setting persisted correctly.")
    else:
        print("❌ FAILURE: Setting did not match.")

if __name__ == "__main__":
    test_persistence()
