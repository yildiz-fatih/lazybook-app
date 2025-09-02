import os
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from .database import engine, get_db
from .models import Base, User
from .auth import hash_password, verify_password, generate_access_token

app = FastAPI()

# Create tables on startup
Base.metadata.create_all(bind=engine)

# CORS configuration (allow only the frontend app's origin to make cross-origin requests)
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN")
if not FRONTEND_ORIGIN:
    raise RuntimeError("FRONTEND_ORIGIN is not set in environment variables.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Pydantic models ----
class RegisterIn(BaseModel):
    username: str = Field(..., min_length=3, max_length=16)
    password: str = Field(..., min_length=10, max_length=30)

class LoginIn(BaseModel):
    username: str
    password: str

# --- Auth routes ---
@app.post("/auth/register", status_code=201)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    username = payload.username.strip()

    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=409, detail="username already taken")

    u = User(
        username=username,
        password_hash=hash_password(payload.password)
        )
    db.add(u)
    db.commit()
    return {"success": True, "data": {"username": u.username}}

@app.post("/auth/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.username == payload.username.strip()).first()
    if not u or not verify_password(payload.password, u.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")

    token = generate_access_token(user_id=u.id, username=u.username)
    return {"access_token": token, "token_type": "Bearer"}

# ---- Routes ----
@app.get("/users")
def list_users(db: Session = Depends(get_db)):
    rows = db.query(User).order_by(User.id.asc()).all()
    return [{"id": u.id, "username": u.username} for u in rows]