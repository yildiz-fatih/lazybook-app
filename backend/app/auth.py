import os
import time
import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from .database import get_db
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
    issued_at_seconds = int(time.time())
    expiration_seconds = issued_at_seconds + (15 * 60) # expires in 15 mins
    payload = {
        "sub": str(user_id),
        "name": username,
        "iat": issued_at_seconds,
        "exp": expiration_seconds,
        "typ": "access"
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

# Extracts and verifies JWT from Authorization header, returns the authenticated user
def get_current_user(creds: HTTPAuthorizationCredentials = Depends(bearer_scheme), db: Session = Depends(get_db),) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    
    data = jwt.decode(creds.credentials, JWT_SECRET, algorithms=["HS256"])
    user_id = int(data.get("sub"))
    
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")
    
    return user
