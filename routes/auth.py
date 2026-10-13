"""API auth dependency"""
from fastapi import HTTPException, Header
from config import API_KEY


async def check_api_key(x_api_key: str = Header(None)):
    """POST endpoints require API Key. Allow all when key not configured."""
    if not API_KEY:
        return
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
