import os
import requests
from dotenv import load_dotenv, set_key
from fastapi import HTTPException, status

load_dotenv()

APP_ID = os.getenv("META_APP_ID")
APP_SECRET = os.getenv("META_APP_SECRET")
BASE_URL = os.getenv("BASE_URL")
ZING_ACCESS_TOKEN = os.getenv("ZING_ACCESS_TOKEN")
ZING_INSTAGRAM_ACCOUNT_ID = os.getenv("ZING_INSTAGRAM_ACCOUNT_ID")
LONG_LIVED_TOKEN = os.getenv("LONG_LIVED_TOKEN")

def refresh_access_token(app_id: str, app_secret: str, long_lived_token: str):
    """
    Refresh the long-lived access token using Meta's Graph API.
    """
    url = "https://graph.facebook.com/v21.0/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": long_lived_token,
    }
    response = requests.get(url, params=params)

    if response.status_code != 200:
        raise Exception(f"Failed to refresh token: {response.text}")
    
    data = response.json()
    return data.get("access_token")

def is_access_token_expired(access_token: str) -> bool:
    """
    Check if the access token has expired by making a test request to the Instagram API.
    Returns True if expired, False if valid.
    """
    test_url = f"{BASE_URL}{ZING_INSTAGRAM_ACCOUNT_ID}?fields=id&access_token={ZING_ACCESS_TOKEN}"
    response = requests.get(test_url)
   # Check for 401 Unauthorized (token expired)
    if response.status_code == 401:
        return True
    
    # Check for 400 Bad Request with expired token message
    if response.status_code == 400:
        try:
            error_data = response.json()
            error_message = error_data.get("error", {}).get("message", "")
            # If the error message indicates token expiration
            if "expired" in error_message.lower():
                return True
        except ValueError:
            pass  # In case response is not in JSON format or doesn't contain error info
    
    return False

def generate_new_long_lived_token() -> str:
    """
    Generate a new long-lived token using the current short-lived token.
    Returns the new long-lived token.
    """
    try:
        load_dotenv()
        short_lived_token = os.getenv("ZING_ACCESS_TOKEN")

        if not short_lived_token:
            raise Exception("Short-lived token not found in .env file.")
        
        url = f"https://graph.facebook.com/v21.0/oauth/access_token"
        params = {
            'grant_type': 'fb_exchange_token',
            'client_id': APP_ID,
            'client_secret': APP_SECRET,
            'fb_exchange_token': short_lived_token,  # The old short lived access token
        }

        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            new_token_data = response.json()
            new_long_lived_token = new_token_data.get("access_token")
            
            if new_long_lived_token:
                # Update the .env file with the new token
                set_key('.env', 'LONG_LIVED_TOKEN', new_long_lived_token)
                load_dotenv()  # Reload the environment after updating
                return new_long_lived_token
            else:
                raise Exception("Failed to generate a new long-lived token.")
        else:
            raise Exception(f"Error generating new long-lived token: {response.text}")
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate new long-lived token: {str(e)}"
        )