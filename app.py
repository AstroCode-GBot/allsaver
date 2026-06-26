import asyncio
import logging
import os
import sys
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

# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger("AllSaverPro")

# --- ENV CONFIG ---
class Settings(BaseSettings):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
    SECRET_KEY: str = os.getenv("SECRET_KEY", "all-saver-pro-secret-12345")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    ALGORITHM: str = "HS256"

config = Settings()

# CRITICAL: Auto-fix Database URL for AsyncPG
if config.DATABASE_URL.startswith("postgres://"):
    config.DATABASE_URL = config.DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

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
engine = create_async_engine(config.DATABASE_URL, pool_pre_ping=True) if config.DATABASE_URL else None
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False) if engine else None
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

async def init_db():
    if not engine:
        logger.error("DATABASE_URL is missing. Skipping DB initialization.")
        return
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Migration check
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE;"))
        
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(AdminUser).where(AdminUser.username == "admin"))
            if not res.scalar_one_or_none():
                session.add(AdminUser(username="admin", password=pwd_context.hash("admin123")))
                await session.commit()
                logger.info("Default Admin 'admin/admin123' created.")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

# --- DOWNLOADER ENGINE ---
class Downloader:
    @staticmethod
    async def get_media(url: str):
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            try:
                if "tiktok.com" in url:
                    r = await client.get(f"https://www.tikwm.com/api/?url={url}")
                    d = r.json().get('data')
                    if d: return {"type": "video", "url": d['play'], "caption": d.get('title')}
                if "facebook.com" in url or "fb.watch" in url:
                    r = await client.get(f"https://serverless-tooly-gateway-6n4h522y.ue.gateway.dev/facebook/video?url={url}")
                    d = r.json().get('videos')
                    if d: return {"type": "video", "url": d.get('hd') or d.get('sd')}
                if "instagram.com" in url:
                    r = await client.get(f"https://igram.site/api/instagram?url={url}")
                    d = r.json()
                    if d: return {"type": "insta", "items": d}
            except Exception as e:
                logger.error(f"Downloader error: {e}")
        return None

# --- BOT LOGIC ---
bot = Bot(token=config.BOT_TOKEN) if config.BOT_TOKEN else None
dp = Dispatcher()

@dp.message(Command("start"))
async def start(m: types.Message):
    if not AsyncSessionLocal: return
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
    if not data: return await wait.edit_text("❌ Media not found or private link.")

    if AsyncSessionLocal:
        async with AsyncSessionLocal() as session:
            await session.execute(update(User).where(User.telegram_id == m.from_user.id).values(download_count=User.download_count + 1))
            session.add(Download(user_id=m.from_user.id, platform="auto", url=m.text))
            await session.commit()

    try:
        if data['type'] == "video":
            await m.answer_video(data['url'], caption="✅ @AllSaverPro_bot")
        elif data['type'] == "insta":
            for i in data['items'][:3]:
                if i['type'] == 'video': await m.answer_video(i['url'])
                else: await m.answer_photo(i['url'])
        await wait.delete()
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        await wait.edit_text("⚠️ Error uploading file to Telegram.")

# --- FASTAPI WEB ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialize Database
    await init_db()
    
    # 2. Start Bot in Background only if token exists
    bot_task = None
    if config.BOT_TOKEN:
        try:
            logger.info("Starting Telegram Bot Polling...")
            bot_task = asyncio.create_task(dp.start_polling(bot))
        except Exception as e:
            logger.error(f"Could not start bot: {e}")
    else:
        logger.warning("BOT_TOKEN is missing. Bot functionality is disabled.")

    yield
    
    if bot_task:
        bot_task.cancel()
        logger.info("Bot task cancelled.")

app = FastAPI(lifespan=lifespan)

# Templates (Embedded for single-file requirement)
LOGIN_UI = """
<html><head><script src="https://cdn.tailwindcss.com"></script><title>Admin Login</title></head>
<body class="bg-slate-900 text-white flex items-center justify-center h-screen">
    <form action="/admin/login" method="post" class="bg-slate-800 p-10 rounded-3xl w-96 border border-slate-700 shadow-2xl">
        <h1 class="text-3xl font-bold mb-6 text-center text-blue-500">All Saver Pro</h1>
        <input name="username" placeholder="Username" required class="w-full bg-slate-900 p-4 rounded-xl mb-4 outline-none border border-slate-700">
        <input name="password" type="password" placeholder="Password" required class="w-full bg-slate-900 p-4 rounded-xl mb-6 outline-none border border-slate-700">
        <button class="w-full bg-blue-600 hover:bg-blue-700 p-4 rounded-xl font-bold transition">Sign In</button>
    </form>
</body></html>
"""

DASH_UI = """
<html><head><script src="https://cdn.tailwindcss.com"></script><title>Dashboard</title></head>
<body class="bg-slate-900 text-white p-10">
    <div class="max-w-4xl mx-auto">
        <div class="flex justify-between items-center mb-10">
            <h1 class="text-4xl font-bold">Admin Dashboard</h1>
            <a href="/admin/logout" class="bg-red-600/20 text-red-500 px-6 py-2 rounded-xl font-bold hover:bg-red-600 hover:text-white transition">Logout</a>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div class="bg-slate-800 p-10 rounded-3xl border border-slate-700 shadow-lg">
                <p class="text-slate-400 font-bold uppercase text-xs tracking-widest mb-2">Registered Users</p>
                <h2 class="text-6xl font-black">{{users}}</h2>
            </div>
            <div class="bg-slate-800 p-10 rounded-3xl border border-slate-700 shadow-lg">
                <p class="text-slate-400 font-bold uppercase text-xs tracking-widest mb-2">Total Downloads</p>
                <h2 class="text-6xl font-black text-blue-500">{{dls}}</h2>
            </div>
        </div>
        <div class="mt-10 bg-slate-800 p-8 rounded-3xl border border-slate-700">
            <h3 class="text-xl font-bold mb-4">System Status</h3>
            <p class="text-slate-400">Database: <span class="text-green-500">Connected</span></p>
            <p class="text-slate-400">Bot Service: <span class="text-green-500">Active</span></p>
        </div>
    </div>
</body></html>
"""

jinja_env = Environment(loader=FunctionLoader(lambda name: LOGIN_UI if name == "login" else DASH_UI))

@app.get("/")
async def index():
    return RedirectResponse("/admin/login")

@app.get("/admin/login")
async def login_pg():
    return HTMLResponse(jinja_env.get_template("login").render())

@app.post("/admin/login")
async def login_post(username: str = Form(...), password: str = Form(...)):
    if not AsyncSessionLocal: raise HTTPException(500, "Database not configured")
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(AdminUser).where(AdminUser.username == username))
        admin = res.scalar_one_or_none()
        if admin and pwd_context.verify(password, admin.password):
            token = jwt.encode({"sub": username, "exp": datetime.utcnow() + timedelta(hours=24)}, config.SECRET_KEY, algorithm=config.ALGORITHM)
            r = RedirectResponse("/admin/dashboard", status_code=302)
            r.set_cookie("access_token", token, httponly=True)
            return r
    return RedirectResponse("/admin/login?error=invalid")

@app.get("/admin/dashboard")
async def dash(request: Request):
    token = request.cookies.get("access_token")
    if not token: return RedirectResponse("/admin/login")
    try:
        jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
    except:
        return RedirectResponse("/admin/login")

    u_count, d_count = 0, 0
    if AsyncSessionLocal:
        async with AsyncSessionLocal() as session:
            u_count = (await session.execute(select(func.count(User.id)))).scalar() or 0
            d_count = (await session.execute(select(func.count(Download.id)))).scalar() or 0
    
    return HTMLResponse(jinja_env.get_template("dash").render(users=u_count, dls=d_count))

@app.get("/admin/logout")
async def logout():
    r = RedirectResponse("/admin/login")
    r.delete_cookie("access_token")
    return r

@app.get("/health")
async def health():
    return {"status": "online", "timestamp": datetime.utcnow().isoformat()}

if __name__ == "__main__":
    # This block is used for local development. 
    # On Render, Gunicorn will run 'app:app'
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
