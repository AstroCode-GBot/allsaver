import asyncio
import logging
import os
import sys
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

# --- THIRD PARTY ---
import httpx
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Response, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic_settings import BaseSettings
from jinja2 import Environment, FunctionLoader

# --- BOT & DB ---
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReactionTypeEmoji
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, BigInteger, DateTime, Integer, Boolean, Text, select, func, update, text

# --- ENV CONFIG ---
class Settings(BaseSettings):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "8930218512:AAGF429l1ofoeW7HrRpM7_DKdqn-mdxAwqM")
    ADMIN_ID: int = int(os.getenv("ADMIN_ID", "6434652846"))
    SECRET_KEY: str = os.getenv("SECRET_KEY", "AAGF429l1ofoeW7HrRpM7_DKdqn-mdxAwqM")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://neondb_owner:npg_DFY1rh8nPxQA@ep-lucky-mode-aoxoorn5.c-2.ap-southeast-1.aws.neon.tech/neondb")
    ALGORITHM: str = "HS256"

config = Settings()

# AUTO-FIX DB URL
if config.DATABASE_URL.startswith("postgres://"):
    config.DATABASE_URL = config.DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AllSaverPro")

# --- DB MODELS ---
class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255))
    first_name: Mapped[Optional[str]] = mapped_column(String(255))
    join_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    download_count: Mapped[int] = mapped_column(Integer, default=0)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)

class Download(Base):
    __tablename__ = "downloads"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    platform: Mapped[str] = mapped_column(String(50))
    url: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class AdminUser(Base):
    __tablename__ = "admins"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password: Mapped[str] = mapped_column(String(255))

# --- DATABASE ENGINE ---
engine = create_async_engine(config.DATABASE_URL, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Self-healing: Add missing columns if they don't exist
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE;"))
    
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(AdminUser).where(AdminUser.username == "admin"))
        if not res.scalar_one_or_none():
            session.add(AdminUser(username="admin", password=pwd_context.hash("admin123")))
            await session.commit()

# --- DOWNLOADER ENGINE ---
class Downloader:
    @staticmethod
    async def get_media(url: str):
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            try:
                if "tiktok.com" in url:
                    r = await client.get(f"https://www.tikwm.com/api/?url={url}")
                    d = r.json()['data']
                    return {"type": "video", "url": d['play'], "caption": d.get('title')}
                if "facebook.com" in url or "fb.watch" in url:
                    r = await client.get(f"https://serverless-tooly-gateway-6n4h522y.ue.gateway.dev/facebook/video?url={url}")
                    d = r.json()['videos']
                    return {"type": "video", "url": d.get('hd') or d.get('sd')}
                if "instagram.com" in url:
                    r = await client.get(f"https://igram.site/api/instagram?url={url}")
                    d = r.json()
                    return {"type": "insta", "items": d}
            except: return None

# --- BOT LOGIC ---
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start(m: types.Message):
    async with AsyncSessionLocal() as session:
        u = await session.execute(select(User).where(User.telegram_id == m.from_user.id))
        if not u.scalar_one_or_none():
            session.add(User(telegram_id=m.from_user.id, username=m.from_user.username, first_name=m.from_user.first_name))
            await session.commit()
    await m.answer("🔥 **All Saver Pro Ready!**\nSend me a link from TikTok, Instagram, or Facebook.")

@dp.message(F.text.regexp(r'http'))
async def handle_dl(m: types.Message):
    wait = await m.answer("⏳ **Processing...**")
    try: await bot.set_message_reaction(m.chat.id, m.message_id, [ReactionTypeEmoji(emoji="👀")])
    except: pass
    
    data = await Downloader.get_media(m.text)
    if not data: return await wait.edit_text("❌ Media not found or private.")

    async with AsyncSessionLocal() as session:
        await session.execute(update(User).where(User.telegram_id == m.from_user.id).values(download_count=User.download_count + 1))
        session.add(Download(user_id=m.from_user.id, platform="auto", url=m.text))
        await session.commit()

    if data['type'] == "video":
        await m.answer_video(data['url'], caption="✅ @AllSaverPro_bot")
    elif data['type'] == "insta":
        for i in data['items'][:3]:
            if i['type'] == 'video': await m.answer_video(i['url'])
            else: await m.answer_photo(i['url'])
    await wait.delete()

# --- WEB ADMIN ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    bot_task = asyncio.create_task(dp.start_polling(bot))
    yield
    bot_task.cancel()

app = FastAPI(lifespan=lifespan)

# Templates
LOGIN_UI = """
<html><head><script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-slate-900 text-white flex items-center justify-center h-screen">
    <form action="/admin/login" method="post" class="bg-slate-800 p-10 rounded-3xl w-96 border border-slate-700">
        <h1 class="text-3xl font-bold mb-6 text-center">Admin Login</h1>
        <input name="username" placeholder="User" class="w-full bg-slate-900 p-4 rounded-xl mb-4 outline-none">
        <input name="password" type="password" placeholder="Pass" class="w-full bg-slate-900 p-4 rounded-xl mb-6 outline-none">
        <button class="w-full bg-blue-600 p-4 rounded-xl font-bold">Login</button>
    </form>
</body></html>
"""

DASH_UI = """
<html><head><script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-slate-900 text-white p-10">
    <div class="max-w-4xl mx-auto">
        <h1 class="text-4xl font-bold mb-10">Dashboard</h1>
        <div class="grid grid-cols-2 gap-6">
            <div class="bg-slate-800 p-10 rounded-3xl">
                <p class="text-slate-400">Total Users</p>
                <h2 class="text-6xl font-bold">{{users}}</h2>
            </div>
            <div class="bg-slate-800 p-10 rounded-3xl">
                <p class="text-slate-400">Downloads</p>
                <h2 class="text-6xl font-bold text-blue-500">{{dls}}</h2>
            </div>
        </div>
        <a href="/admin/logout" class="block mt-10 text-red-500">Logout</a>
    </div>
</body></html>
"""

jinja_env = Environment(loader=FunctionLoader(lambda name: LOGIN_UI if name == "login" else DASH_UI))

@app.get("/")
async def index(): return RedirectResponse("/admin/login")

@app.get("/admin/login")
async def login_pg(): return HTMLResponse(jinja_env.get_template("login").render())

@app.post("/admin/login")
async def login_post(u: str = Form(...), p: str = Form(...)):
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(AdminUser).where(AdminUser.username == u))
        admin = res.scalar_one_or_none()
        if admin and pwd_context.verify(p, admin.password):
            token = jwt.encode({"sub": u, "exp": datetime.utcnow() + timedelta(hours=24)}, config.SECRET_KEY)
            r = RedirectResponse("/admin/dashboard", status_code=302)
            r.set_cookie("access_token", token)
            return r
    return RedirectResponse("/admin/login")

@app.get("/admin/dashboard")
async def dash(request: Request):
    token = request.cookies.get("access_token")
    if not token: return RedirectResponse("/admin/login")
    async with AsyncSessionLocal() as session:
        u_count = (await session.execute(select(func.count(User.id)))).scalar()
        d_count = (await session.execute(select(func.count(Download.id)))).scalar()
    return HTMLResponse(jinja_env.get_template("dash").render(users=u_count, dls=d_count))

@app.get("/admin/logout")
async def logout():
    r = RedirectResponse("/admin/login")
    r.delete_cookie("access_token")
    return r

@app.get("/health")
async def health(): return {"status": "online"}
