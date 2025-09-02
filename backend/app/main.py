# backend/app/main.py
import os
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .database import engine, get_db
from .models import Base, User

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
class UserCreate(BaseModel):
    username: str

class UserOut(BaseModel):
    id: int
    username: str

# ---- Routes ----
@app.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    rows = db.query(User).order_by(User.id.asc()).all()
    return [UserOut(id=u.id, username=u.username) for u in rows]

@app.post("/users", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    username = payload.username.strip()

    # check uniqueness
    exists = db.query(User).filter(User.username == username).first()
    if exists:
        raise HTTPException(status_code=409, detail="username already taken")

    u = User(username=username)
    db.add(u)
    db.commit()
    db.refresh(u)
    return UserOut(id=u.id, username=u.username)
