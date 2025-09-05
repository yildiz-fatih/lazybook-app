from datetime import datetime
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query, Request, WebSocket, WebSocketException, status, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from .database import AsyncSessionLocal, engine, get_db_async
from .models import Base, User, Follow, Post, Message
from .auth import hash_password, verify_password, generate_access_token, get_current_user_dep, get_current_user_ws

# Create tables on startup (async engine + sync-bridge)
async def init_models():
    async with engine.begin() as conn:
        # run_sync lets us call the synchronous create_all() using this async connection
        await conn.run_sync(Base.metadata.create_all)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_models()
    yield

app = FastAPI(lifespan=lifespan)

# CORS configuration (for HTTP only, WS uses explicit Origin check)
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

# Chat stuff
class MessageIn(BaseModel):
    recipient_id: int
    contents: str

class MessageOut(BaseModel):
    id: int
    sender_id: int
    recipient_id: int
    contents: str
    created_at: str

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, set[WebSocket]] = {}
    
    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()

        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)
    
    def disconnect(self, websocket: WebSocket):
        # Scan through all users, remove this websocket wherever it appears
        # Keep track of emptied out entries, remove them to keep the dict tidy
        user_id_to_remove = None
        for user_id, connections in self.active_connections.items():
            if websocket in connections:
                connections.discard(websocket)
                if not connections:
                    user_id_to_remove = user_id
                break  # each ws belongs to exactly one user set
        
        if user_id_to_remove is not None:
            self.active_connections.pop(user_id_to_remove)


connection_manager = ConnectionManager()

'''
Known issues:
    - Long-lived connections will not be forced to re-auth mid-connection
'''
@app.websocket("/chatting")
async def chat(websocket: WebSocket, token: str = Query(...)):
    # Ensure only WebSockets coming from the expected origins are allowed
    if websocket.headers.get("origin") != FRONTEND_ORIGIN:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    # Authenticate the user using the JWT passed as query params
    async with AsyncSessionLocal() as db:
        me = await get_current_user_ws(token, db)
    # Accept and 'register' the user
    await connection_manager.connect(me.id, websocket)

    try:
        while True:
            # Parse JSON
            try:
                data = await websocket.receive_json()
            except Exception:
                await websocket.send_json({"type": "error", "code": "bad_json"})
                continue

            # Validate payload shape
            try:
                incoming = MessageIn.model_validate(data)
            except ValidationError:
                await websocket.send_json({"type": "error", "code": "validation_error"})
                continue
            
            # Persist message (short-lived async session per message)
            async with AsyncSessionLocal() as db:
                recipient = await db.get(User, incoming.recipient_id)
                if not recipient:
                    await websocket.send_json({"type": "error", "code": "recipient_not_found"})
                    continue

                message = Message(
                    sender_id=me.id,
                    recipient_id=incoming.recipient_id,
                    contents=incoming.contents,
                )
                db.add(message)

                try:
                    await db.commit()
                except Exception:
                    await db.rollback()
                    await websocket.send_json({"type": "error", "code": "db_error"})
                    continue

                await db.refresh(message)
            
            outgoing = {
                "sender_id": me.id,
                "contents": message.contents,
                "created_at": message.created_at.isoformat()
            }
            # NOTE: Why do we catch per-recipient send errors and prune sockets here?
            #   This block writes to other users’ sockets.
            #   If a recipient socket is stale/closed, ws.send_json(...) raises.
            #   There’s nobody to notify on that dead socket, and if we let
            #   the exception escape this try/except, it would propagate out of our handler and close
            #   the sender’s WebSocket --> disconnecting them even though only the recipient was at fault.
            #   This solution tries to prevent repeated failures and leaking dead connections, while keeping the sender connected.
            targets = connection_manager.active_connections.get(incoming.recipient_id)
            if targets:
                stale = []
                for ws in list(targets):
                    try:
                        await ws.send_json(outgoing)
                    except Exception:
                        stale.append(ws) # websocket is stale/closed, mark it for removal
                for ws in stale:
                    connection_manager.disconnect(ws)

    except WebSocketDisconnect:
        connection_manager.disconnect(websocket)

@app.get("/messages", response_model=list[MessageOut], status_code=200)
async def get_messages(peer_id: int = Query(...), db: AsyncSession = Depends(get_db_async), me: User = Depends(get_current_user_dep)):
    # verify peer exists
    peer_row = await db.execute(
        text("SELECT id FROM users WHERE id = :peer_id"),
        {"peer_id": peer_id},
    )
    if peer_row.mappings().first() is None:
        raise HTTPException(status_code=404, detail="user not found")

    result = await db.execute(
        text("""
            SELECT id, sender_id, recipient_id, contents, created_at
            FROM messages
            WHERE (sender_id = :me_id   AND recipient_id = :peer_id)
               OR (sender_id = :peer_id AND recipient_id = :me_id)
            ORDER BY created_at ASC, id ASC
        """),
        {"me_id": me.id, "peer_id": peer_id},
    )
    rows = result.mappings().all()

    return [
        MessageOut(
            id=r["id"],
            sender_id=r["sender_id"],
            recipient_id=r["recipient_id"],
            contents=r["contents"],
            created_at=r["created_at"].isoformat(),
        )
        for r in rows
    ]

# --- Auth routes ---
@app.post("/auth/register", status_code=201)
async def register(payload: RegisterIn, db: AsyncSession = Depends(get_db_async)):
    username = payload.username.strip().lower()

    existing = await db.scalar(select(User).where(User.username == username))
    if existing:
        raise HTTPException(status_code=409, detail="username already taken")

    u = User(
        username=username,
        password_hash=hash_password(payload.password)
        )
    db.add(u)
    await db.commit()
    return {"success": True, "data": {"username": u.username}}

@app.post("/auth/login")
async def login(payload: LoginIn, db: AsyncSession = Depends(get_db_async)):
    u = await db.scalar(select(User).where(User.username == payload.username.strip().lower()))
    if not u or not verify_password(payload.password, u.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")

    token = generate_access_token(user_id=u.id, username=u.username)
    return {"access_token": token, "token_type": "Bearer"}

# ---- Routes ----
@app.get("/users")
async def get_all_users(db: AsyncSession = Depends(get_db_async)):
    rows = (await db.scalars(select(User).order_by(User.id.asc()))).all()
    return [{"id": u.id, "username": u.username} for u in rows]

@app.get("/whoami")
async def whoami(me: User = Depends(get_current_user_dep)):
    return UserOut(id=me.id, username=me.username)

@app.get("/users/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_db_async), me: User = Depends(get_current_user_dep)):
    u = await db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="user not found")

    i_follow = (await db.scalars(
        select(Follow)
        .where(Follow.follower_id == me.id, Follow.followee_id == user_id)
        .limit(1)
        )).first() is not None

    follows_me = (await db.scalars(select(Follow).where(Follow.follower_id == user_id, Follow.followee_id == me.id).limit(1))).first() is not None

    return UserOutDetailed(
        id=u.id,
        username=u.username,
        status=u.status or "",
        iFollow=i_follow,
        follows=follows_me,
    )

@app.get("/users/{user_id}/followers")
async def followers(user_id: int, db: AsyncSession = Depends(get_db_async), me: User = Depends(get_current_user_dep)):
    users = (await db.scalars(
        select(User)
        .join(Follow, Follow.follower_id == User.id)
        .where(Follow.followee_id == user_id)
        .order_by(User.id.desc())
        )).all()
    return [UserOut(id=u.id, username=u.username) for u in users]

@app.get("/users/{user_id}/following")
async def following(user_id: int, db: AsyncSession = Depends(get_db_async), me: User = Depends(get_current_user_dep)):
    users = (await db.scalars(
        select(User)
        .join(Follow, Follow.followee_id == User.id)
        .where(Follow.follower_id == user_id)
        .order_by(User.id.desc())
    )).all()
    return [UserOut(id=u.id, username=u.username) for u in users]

@app.post("/users/status")
async def update_status(request: Request, db: AsyncSession = Depends(get_db_async), me: User = Depends(get_current_user_dep)):
    data = await request.json()
    me.status = (data.get("status") or "").strip()
    await db.commit()
    return {"success": True}

@app.post("/follow")
async def follow_action(payload: FollowIn, db: AsyncSession = Depends(get_db_async), me: User = Depends(get_current_user_dep)):
    if payload.whom == me.id:
        raise HTTPException(status_code=400, detail="can not follow yourself")

    target_user = await db.get(User, payload.whom)
    if not target_user:
        raise HTTPException(status_code=404, detail="user not found")

    existing_follow = await db.scalar(
        select(Follow).where(Follow.follower_id == me.id, Follow.followee_id == target_user.id).limit(1)
    )
    if payload.action is True: # follow
        if existing_follow:
            raise HTTPException(status_code=409, detail="already following")
        db.add(Follow(follower_id=me.id, followee_id=target_user.id))
        await db.commit()
        return {"success": True, "detail": "successfully followed"}
    else: # unfollow
        if not existing_follow:
            raise HTTPException(status_code=409, detail="not following")
        await db.delete(existing_follow)
        await db.commit()
        return {"success": True, "detail": "successfully unfollowed"}

@app.post("/posts")
async def create_post(payload: PostCreate, db: AsyncSession = Depends(get_db_async), me: User = Depends(get_current_user_dep)):
    contents = payload.contents.strip()
    if len(contents) == 0 or len(contents) > 1024:
        raise HTTPException(status_code=400, detail="content must be 1-1024 characters")
    
    p = Post(user_id=me.id, contents=contents)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return PostOut(
        id=p.id,
        user_id=p.user_id,
        username=me.username,
        contents=p.contents,
        created_at=p.created_at.isoformat(),
    )

@app.get("/users/{user_id}/posts")
async def user_posts(user_id: int, db: AsyncSession = Depends(get_db_async), me: User = Depends(get_current_user_dep)):
    result = await db.execute(
        text("""
            SELECT
              p.id,
              p.user_id,
              u.username,
              p.contents,
              p.created_at
            FROM posts AS p
            JOIN users AS u ON u.id = p.user_id
            WHERE p.user_id = :user_id
            ORDER BY p.created_at DESC, p.id DESC
        """),
        {"user_id": user_id},
    )
    rows = result.mappings().all()  # dict-like rows

    return [
        PostOut(
            id=row["id"],
            user_id=row["user_id"],
            username=row["username"],
            contents=row["contents"],
            created_at=row["created_at"].isoformat(),
        )
        for row in rows
    ]

@app.get("/feed")
async def get_the_feed(db: AsyncSession = Depends(get_db_async), me: User = Depends(get_current_user_dep)):
    result = await db.execute(
        text("""
            SELECT
              p.id,
              p.user_id,
              u.username,
              p.contents,
              p.created_at
            FROM follows AS f
            JOIN posts   AS p ON p.user_id = f.followee_id
            JOIN users   AS u ON u.id      = p.user_id
            WHERE f.follower_id = :me_id
            ORDER BY p.created_at DESC, p.id DESC
        """),
        {"me_id": me.id},
    )
    rows = result.mappings().all()

    return [
        PostOut(
            id=row["id"],
            user_id=row["user_id"],
            username=row["username"],
            contents=row["contents"],
            created_at=row["created_at"].isoformat(),
        )
        for row in rows
    ]
