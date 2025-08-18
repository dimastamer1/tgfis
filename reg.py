import os
import asyncio
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
MONGO_URI = os.getenv("MONGO_URI")

# Database setup
mongo = MongoClient(MONGO_URI)
db = mongo["telegram_accounts"]
sessions_col = db["registered_sessions"]

async def register_account():
    print("=== Telegram Account Registration ===")
    
    # Get phone number
    phone = input("Enter phone number (with country code, e.g. +1234567890): ").strip()
    if not phone.startswith('+'):
        print("❌ Phone number must start with '+'")
        return
    
    # Initialize client
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    
    try:
        # Connect and send code request
        await client.connect()
        print("\n⏳ Sending verification code...")
        await client.send_code_request(phone)
        
        # Get code from user
        code = input("Enter verification code: ").strip()
        
        # First name and last name (optional)
        first_name = input("Enter first name (optional): ").strip() or "User"
        last_name = input("Enter last name (optional): ").strip() or ""
        
        # Sign in
        print("\n⏳ Registering account...")
        await client.sign_in(
            phone=phone,
            code=code,
            first_name=first_name,
            last_name=last_name
        )
        
        # Get session string
        session_string = StringSession.save(client.session)
        
        # Save to database
        account_data = {
            "phone": phone,
            "session": session_string,
            "first_name": first_name,
            "last_name": last_name,
            "registered_at": datetime.now().isoformat()
        }
        sessions_col.insert_one(account_data)
        
        print("\n✅ Account successfully registered!")
        print(f"Phone: {phone}")
        print(f"Session string: {session_string}")
        print("Saved to database.")
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
    finally:
        await client.disconnect()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(register_account())