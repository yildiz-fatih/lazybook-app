import os
from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from .database import engine, get_db
from .models import Base, User, Follow, Post
from .auth import hash_password, verify_password, generate_access_token, get_current_user
from sqlalchemy import desc

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

class FollowIn(BaseModel):
    whom: int
    action: bool  # true=follow, false=unfollow

class UserOut(BaseModel):
    id: int
    username: str

class UserOutDetailed(BaseModel):
    id: int
    username: str
    status: str = ""
    iFollow: bool
    follows: bool

class PostCreate(BaseModel):
    contents: str = Field(..., max_length=1024)

class PostOut(BaseModel):
    id: int
    user_id: int
    username: str
    contents: str
    created_at: str

# --- Auth routes ---
@app.post("/auth/register", status_code=201)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    username = payload.username.strip().lower()

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
    u = db.query(User).filter(User.username == payload.username.strip().lower()).first()
    if not u or not verify_password(payload.password, u.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")

    token = generate_access_token(user_id=u.id, username=u.username)
    return {"access_token": token, "token_type": "Bearer"}

# ---- Routes ----
@app.get("/users")
def get_all_users(db: Session = Depends(get_db)):
    rows = db.query(User).order_by(User.id.asc()).all()
    return [{"id": u.id, "username": u.username} for u in rows]

@app.get("/whoami")
def whoami(me: User = Depends(get_current_user)):
    return UserOut(id=me.id, username=me.username)

@app.get("/users/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="user not found")

    i_follow = db.query(Follow).filter(
        Follow.follower_id == me.id, Follow.followee_id == user_id
    ).first() is not None

    follows_me = db.query(Follow).filter(
        Follow.follower_id == user_id, Follow.followee_id == me.id
    ).first() is not None

    return UserOutDetailed(
        id=u.id,
        username=u.username,
        status=u.status or "",
        iFollow=i_follow,
        follows=follows_me,
    )

@app.get("/users/{user_id}/followers")
def followers(user_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    users = (
        db.query(User)
        .join(Follow, Follow.follower_id == User.id)
        .filter(Follow.followee_id == user_id)
        .order_by(User.id.desc())
        .all()
    )
    return [UserOut(id=u.id, username=u.username) for u in users]

@app.get("/users/{user_id}/following")
def following(user_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    users = (
        db.query(User)
        .join(Follow, Follow.followee_id == User.id)
        .filter(Follow.follower_id == user_id)
        .order_by(User.id.desc())
        .all()
    )
    return [UserOut(id=u.id, username=u.username) for u in users]

@app.post("/users/status")
async def update_status(request: Request, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    data = await request.json()
    me.status = (data.get("status") or "").strip()
    db.commit()
    return {"success": True}

@app.post("/follow")
def follow_action(payload: FollowIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    if payload.whom == me.id:
        raise HTTPException(status_code=400, detail="can not follow yourself")

    target_user = db.get(User, payload.whom)
    if not target_user:
        raise HTTPException(status_code=404, detail="user not found")

    existing_follow = db.query(Follow).filter(
            Follow.follower_id == me.id, Follow.followee_id == target_user.id
        ).one_or_none()
    if payload.action is True: # follow
        if existing_follow:
            raise HTTPException(status_code=409, detail="already following")
        db.add(Follow(follower_id=me.id, followee_id=target_user.id))
        db.commit()
        return {"success": True, "detail": "successfully followed"}
    else: # unfollow
        if not existing_follow:
            raise HTTPException(status_code=409, detail="not following")
        db.delete(existing_follow)
        db.commit()
        return {"success": True, "detail": "successfully unfollowed"}

@app.post("/posts")
def create_post(payload: PostCreate, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    contents = payload.contents.strip()
    if len(contents) == 0 or len(contents) > 1024:
        raise HTTPException(status_code=400, detail="content must be 1-1024 characters")
    
    p = Post(user_id=me.id, contents=contents)
    db.add(p)
    db.commit()
    db.refresh(p)
    return PostOut(
        id=p.id,
        user_id=p.user_id,
        username=me.username,
        contents=p.contents,
        created_at=p.created_at.isoformat(),
    )

@app.get("/users/{user_id}/posts")
def user_posts(user_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    q = (
        db.query(Post, User.username)
        .join(User, User.id == Post.user_id)
        .filter(Post.user_id == user_id)
        .order_by(desc(Post.created_at))
        .all()
    )
    return [
        PostOut(
            id=p.id,
            user_id=p.user_id,
            username=username,
            contents=p.contents,
            created_at=p.created_at.isoformat(),
        )
        for (p, username) in q
    ]

@app.get("/feed")
def get_the_feed(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    q = (
        db.query(Post, User.username)
        .join(User, User.id == Post.user_id)
        .join(Follow, Follow.followee_id == Post.user_id)
        .filter(Follow.follower_id == me.id)
        .order_by(desc(Post.created_at))
        .all()
    )

    return [
        PostOut(
            id=p.id,
            user_id=p.user_id,
            username=username,
            contents=p.contents,
            created_at=p.created_at.isoformat(),
        )
        for (p, username) in q
    ]
