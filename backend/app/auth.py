import os
import time
import bcrypt
import jwt
from fastapi import Depends, HTTPException, WebSocketException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from .database import get_db_async
from .models import User

# Loads .env
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET is not set")

bearer_scheme = HTTPBearer(auto_error=False)

# Hashes a raw (plain-text) password with bcrypt and returns the hash
def hash_password(raw_password: str) -> str:
    password_bytes = raw_password.encode("utf-8") # convert the password string to bytes
    salt = bcrypt.gensalt() # generate a random salt
    hashed_bytes = bcrypt.hashpw(password_bytes, salt) # hash the password
    hashed_string = hashed_bytes.decode("utf-8") # convert the hashed bytes to a string
    return hashed_string

# Verifies a raw password against a stored bcrypt hash
def verify_password(raw_password: str, hashed: str) -> bool:
    return bcrypt.checkpw(raw_password.encode("utf-8"), hashed.encode("utf-8"))

# Creates and returns a JWT containing the user’s ID, username, and expiration details
def generate_access_token(user_id: int, username: str) -> str:
    now = int(time.time())

    payload = {
        "sub": str(user_id),
        "name": username,
        "iat": now,
        "exp": now + (15 * 60), # expires in 15 mins
        "typ": "access"
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

# --- Used by HTTP endpoints ---
# Verifies JWT (given as a string), returns the authenticated user
async def get_current_user_dep(creds: HTTPAuthorizationCredentials = Depends(bearer_scheme), db: AsyncSession = Depends(get_db_async)) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    
    try:
        data = jwt.decode(creds.credentials, JWT_SECRET, algorithms=["HS256"])
        user_id = int(data.get("sub"))
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")
    
    return user

# --- Used by WebSockets endpoints ---
# Verifies JWT (given as a string), returns the authenticated user
async def get_current_user_ws(token: str, db: AsyncSession) -> User: # since this function is not a FastAPI dependency, 'db' is passed by the client of the function
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = int(data.get("sub"))
    except jwt.InvalidTokenError:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    user = await db.get(User, user_id)
    if not user:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    
    return user
