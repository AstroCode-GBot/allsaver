import os
import asyncio
import logging
import json
import secrets
import time
import sys
import re
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Any, Dict, Union

# --- WEB & API IMPORTS ---
import uvicorn
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Cookie, Response, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pydantic_settings import BaseSettings

# --- BOT IMPORTS ---
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile, 
    InputMediaPhoto, InputMediaVideo, ReplyKeyboardMarkup, KeyboardButton,
    WebAppInfo
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

# --- DATABASE IMPORTS ---
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import (
    String, BigInteger, DateTime, Integer, Boolean, Text, 
    ForeignKey, select, func, update, delete, desc, and_, text
)

# --- UTILS ---
import aiohttp
from jose import JWTError, jwt
from passlib.context import CryptContext
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()

class Settings(BaseSettings):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "8930218512:AAGF429l1ofoeW7HrRpM7_DKdqn-mdxAwqM")
    ADMIN_ID: int = int(os.getenv("ADMIN_ID", "6434652846"))
    SECRET_KEY: str = os.getenv("SECRET_KEY", "AAGF429l1ofoeW7HrRpM7_DKdqn-mdxAwqM")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://neondb_owner:npg_DFY1rh8nPxQA@ep-lucky-mode-aoxoorn5.c-2.ap-southeast-1.aws.neon.tech/neondb")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080 

config = Settings()

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("AllSaverPro")

# --- DATABASE MODELS ---
class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255))
    first_name: Mapped[Optional[str]] = mapped_column(String(255))
    last_name: Mapped[Optional[str]] = mapped_column(String(255))
    photo: Mapped[Optional[str]] = mapped_column(String(500))
    join_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_activity: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    download_count: Mapped[int] = mapped_column(Integer, default=0)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)

class Download(Base):
    __tablename__ = "downloads"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    platform: Mapped[str] = mapped_column(String(50))
    url: Mapped[str] = mapped_column(Text)
    filename: Mapped[Optional[str]] = mapped_column(String(500))
    size: Mapped[Optional[str]] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ApiSource(Base):
    __tablename__ = "apis"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    platform: Mapped[str] = mapped_column(String(50))
    endpoint: Mapped[str] = mapped_column(Text)
    status: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class AdminUser(Base):
    __tablename__ = "admins"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="superadmin")
    permissions: Mapped[str] = mapped_column(Text, default="all")

class Promotion(Base):
    __tablename__ = "promotions"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    sponsor_username: Mapped[Optional[str]] = mapped_column(String(100))
    image_file_id: Mapped[Optional[str]] = mapped_column(String(500))
    description: Mapped[Optional[str]] = mapped_column(Text)
    message: Mapped[Optional[str]] = mapped_column(Text)
    button_text: Mapped[Optional[str]] = mapped_column(String(100))
    button_url: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[bool] = mapped_column(Boolean, default=True)
    schedule_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Setting(Base):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    value: Mapped[str] = mapped_column(Text)

class LogEntry(Base):
    __tablename__ = "logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

# --- DB INITIALIZATION & MIGRATION ---
engine = create_async_engine(config.DATABASE_URL, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        # Create tables if not exist
        await conn.run_sync(Base.metadata.create_all)
        
        # MIGRATION: Check if 'telegram_id' exists in 'admins' table
        try:
            # We use a raw SQL approach to safely add the column if missing
            await conn.execute(text("ALTER TABLE admins ADD COLUMN IF NOT EXISTS telegram_id BIGINT UNIQUE;"))
            await conn.execute(text("ALTER TABLE admins ADD COLUMN IF NOT EXISTS permissions TEXT DEFAULT 'all';"))
            await conn.commit()
        except Exception as e:
            logger.warning(f"Migration notice: {e}")

    async with AsyncSessionLocal() as session:
        # Create Default Admin if not exists
        res = await session.execute(select(AdminUser).where(AdminUser.username == "admin"))
        if not res.scalar_one_or_none():
            pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
            new_admin = AdminUser(
                telegram_id=config.ADMIN_ID,
                username="admin",
                password=pwd_context.hash("admin123"),
                role="superadmin",
                permissions="all"
            )
            session.add(new_admin)
            logger.info("Admin user 'admin' created with password 'admin123'")
        
        # Create Default Settings
        defaults = {
            "bot_enabled": "true",
            "maintenance_mode": "false",
            "welcome_text": "<b>Welcome to All Saver Pro!</b>\n\nI am the most advanced media downloader bot. Send me any link from TikTok, Instagram, Facebook, Pinterest, Spotify, or Terabox and I will fetch it for you instantly! 🔥",
            "support_chat": "@AllSaverPro_Support"
        }
        for k, v in defaults.items():
            s_check = await session.execute(select(Setting).where(Setting.key == k))
            if not s_check.scalar_one_or_none():
                session.add(Setting(key=k, value=v))
        
        await session.commit()

# --- DOWNLOADER ENGINE ---
class DownloaderEngine:
    @staticmethod
    async def request_api(url: str, params: dict = None):
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params, timeout=25) as r:
                    if r.status == 200:
                        return await r.json()
            except Exception as e:
                logger.error(f"Engine Error ({url}): {e}")
            return None

    @classmethod
    async def get_tiktok(cls, url: str):
        data = await cls.request_api(f"https://www.tikwm.com/api/?url={url}")
        if data and data.get("code") == 0:
            d = data["data"]
            return {
                "platform": "tiktok",
                "type": "video",
                "media_url": d.get("play"),
                "music_url": d.get("music"),
                "title": d.get("title", "TikTok Video"),
                "author": d.get("author", {}).get("nickname", "Creator"),
                "thumbnail": d.get("cover")
            }
        return None

    @classmethod
    async def get_instagram(cls, url: str):
        data = await cls.request_api(f"https://igram.site/api/instagram?url={url}")
        if data and isinstance(data, list):
            return {"platform": "instagram", "items": data}
        return None

    @classmethod
    async def get_facebook(cls, url: str):
        data = await cls.request_api(f"https://serverless-tooly-gateway-6n4h522y.ue.gateway.dev/facebook/video?url={url}")
        if data and "videos" in data:
            best = data["videos"].get("hd") or data["videos"].get("sd")
            if best:
                return {"platform": "facebook", "type": "video", "media_url": best["url"]}
        return None

    @classmethod
    async def get_spotify(cls, url: str):
        data = await cls.request_api(f"https://spotyloader.com/api/spotify/info?url={url}")
        if data and "post" in data:
            p = data["post"]
            return {
                "platform": "spotify",
                "type": "audio",
                "media_url": p.get("preview_url"),
                "title": p.get("name"),
                "artist": p.get("artist"),
                "thumbnail": p.get("image")
            }
        return None

    @classmethod
    async def get_terabox(cls, url: str):
        api = f"https://teradown-dzv3.onrender.com/api?url={url}&ndus=Y2t6_i7teHuiX-uHDssg3XhTPleotTOyL1Jf5tPV"
        data = await cls.request_api(api)
        if data and "download" in data:
            return {
                "platform": "terabox",
                "type": "file",
                "media_url": data.get("download"),
                "filename": data.get("name"),
                "size": data.get("size")
            }
        return None

    @classmethod
    async def get_pinterest(cls, url: str):
        data = await cls.request_api(f"https://api.pinssaver.com/pin?url={url}")
        if data and "data" in data:
            return {"platform": "pinterest", "type": "photo", "media_url": data["data"].get("src", {}).get("orig")}
        return None

# --- TELEGRAM BOT LOGIC ---
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

async def get_or_create_user(m: types.Message):
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(User).where(User.telegram_id == m.from_user.id))
        user = res.scalar_one_or_none()
        if not user:
            user = User(
                telegram_id=m.from_user.id,
                username=m.from_user.username,
                first_name=m.from_user.first_name,
                last_name=m.from_user.last_name
            )
            session.add(user)
        else:
            user.last_activity = datetime.utcnow()
        await session.commit()
        return user

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await get_or_create_user(message)
    async with AsyncSessionLocal() as session:
        s = await session.execute(select(Setting).where(Setting.key == "welcome_text"))
        text = s.scalar_one().value
    
    kb = InlineKeyboardBuilder()
    kb.button(text="Developer", url="https://t.me/AllSaverPro_Support")
    kb.button(text="Bot Update", url="https://t.me/AllSaverPro_Support")
    kb.adjust(1)
    
    await message.answer(text, parse_mode="HTML", reply_markup=kb.as_markup())

@dp.message(F.text.regexp(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'))
async def link_processor(message: types.Message):
    user = await get_or_create_user(message)
    if user.is_banned:
        return await message.answer("❌ You are banned from using this service.")
    
    url = message.text.strip()
    wait = await message.answer("👀 <b>Checking your link...</b>", parse_mode="HTML")
    
    # Animate reaction
    try: await bot.set_message_reaction(message.chat.id, message.message_id, [types.ReactionTypeEmoji(emoji="👀")])
    except: pass

    await asyncio.sleep(1)
    await wait.edit_text("⏳ <b>Processing media...</b>", parse_mode="HTML")

    res = None
    plat = "unknown"

    try:
        if "tiktok.com" in url:
            plat, res = "tiktok", await DownloaderEngine.get_tiktok(url)
        elif "instagram.com" in url:
            plat, res = "instagram", await DownloaderEngine.get_instagram(url)
        elif "facebook.com" in url or "fb.watch" in url:
            plat, res = "facebook", await DownloaderEngine.get_facebook(url)
        elif "spotify.com" in url:
            plat, res = "spotify", await DownloaderEngine.get_spotify(url)
        elif "terabox.com" in url or "1024tera" in url:
            plat, res = "terabox", await DownloaderEngine.get_terabox(url)
        elif "pinterest.com" in url or "pin.it" in url:
            plat, res = "pinterest", await DownloaderEngine.get_pinterest(url)

        if not res:
            return await wait.edit_text("❌ <b>Media not found!</b>\nMake sure the link is public and correct.")

        # Update statistics
        async with AsyncSessionLocal() as session:
            await session.execute(update(User).where(User.id == user.id).values(download_count=User.download_count + 1))
            session.add(Download(user_id=user.telegram_id, platform=plat, url=url, status="completed"))
            # Fetch promotion
            promo_q = await session.execute(select(Promotion).where(Promotion.status == True).order_by(func.random()).limit(1))
            promo = promo_q.scalar_one_or_none()
            await session.commit()

        await wait.edit_text("✅ <b>Uploading to Telegram...</b>", parse_mode="HTML")
        
        caption = f"✅ <b>Downloaded by @AllSaverPro_bot</b>"
        pkb = None
        if promo and promo.button_text:
            p_builder = InlineKeyboardBuilder()
            p_builder.button(text=f"🎁 {promo.button_text}", url=promo.button_url)
            pkb = p_builder.as_markup()
            caption += f"\n\n<i>AD: {promo.title}</i>"

        if plat == "tiktok":
            await message.answer_video(res['media_url'], caption=f"🎬 <b>{res['title']}</b>\n👤 {res['author']}\n\n{caption}", parse_mode="HTML", reply_markup=pkb)
        elif plat == "facebook":
            await message.answer_video(res['media_url'], caption=caption, parse_mode="HTML", reply_markup=pkb)
        elif plat == "pinterest":
            await message.answer_photo(res['media_url'], caption=caption, parse_mode="HTML", reply_markup=pkb)
        elif plat == "spotify":
            await message.answer_audio(res['media_url'], caption=f"🎵 <b>{res['title']}</b> - {res['artist']}\n\n{caption}", parse_mode="HTML", reply_markup=pkb)
        elif plat == "terabox":
            await message.answer(f"📦 <b>{res['filename']}</b>\n📏 Size: {res['size']}\n\n{caption}", parse_mode="HTML", reply_markup=pkb)
        elif plat == "instagram":
            for item in res['items'][:5]:
                if item['type'] == 'video': await message.answer_video(item['url'])
                else: await message.answer_photo(item['url'])
            await message.answer("✅ Instagram media sent!", reply_markup=pkb)
        
        await wait.delete()

    except Exception as e:
        logger.error(f"Process Error: {e}")
        await wait.edit_text("⚠️ <b>Internal Error</b>\nFailed to download this link. Please try again later.")

# --- ADMIN PANEL (FASTAPI) ---
app = FastAPI(title="All Saver Pro")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# CSS / UI
UI_CSS = """
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap');
    body { font-family: 'Plus Jakarta Sans', sans-serif; background: #0f172a; color: #f8fafc; margin: 0; }
    .glass { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.1); }
    .sidebar-link { transition: 0.3s; padding: 12px 20px; border-radius: 12px; display: flex; align-items: center; gap: 12px; color: #94a3b8; text-decoration: none; }
    .sidebar-link:hover { background: rgba(59, 130, 246, 0.1); color: #3b82f6; }
    .active-link { background: #3b82f6 !important; color: white !important; box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3); }
    .stat-card { border-radius: 24px; padding: 24px; transition: 0.3s; }
    .stat-card:hover { transform: translateY(-5px); }
</style>
"""

ADMIN_LAYOUT = """
<div class="flex min-h-screen">
    <div class="w-72 glass border-r border-slate-800 p-6 fixed inset-y-0 flex flex-col">
        <div class="flex items-center gap-3 mb-10 px-2">
            <div class="w-10 h-10 bg-blue-600 rounded-xl flex items-center justify-center text-white font-bold italic">AS</div>
            <h1 class="text-xl font-bold tracking-tight">All Saver Pro</h1>
        </div>
        <nav class="flex-1 flex flex-col gap-2">
            <a href="/admin/dashboard" class="sidebar-link"><i class="fa fa-home"></i> Dashboard</a>
            <a href="/admin/users" class="sidebar-link"><i class="fa fa-users"></i> Users</a>
            <a href="/admin/downloads" class="sidebar-link"><i class="fa fa-download"></i> Downloads</a>
            <a href="/admin/promotions" class="sidebar-link"><i class="fa fa-ad"></i> Promotions</a>
            <a href="/admin/settings" class="sidebar-link"><i class="fa fa-cog"></i> Bot Settings</a>
            <a href="/admin/logs" class="sidebar-link"><i class="fa fa-terminal"></i> Logs</a>
        </nav>
        <div class="pt-6 border-t border-slate-800">
            <a href="/admin/logout" class="sidebar-link text-red-400 hover:bg-red-400/10"><i class="fa fa-sign-out-alt"></i> Logout</a>
        </div>
    </div>
    <main class="flex-1 ml-72 p-10">
        {content}
    </main>
</div>
"""

# Auth Utils
def create_token(data: dict):
    expire = datetime.utcnow() + timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    data.update({"exp": expire})
    return jwt.encode(data, config.SECRET_KEY, algorithm=config.ALGORITHM)

async def get_admin(request: Request):
    token = request.cookies.get("access_token")
    if not token: return None
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
        uname = payload.get("sub")
        async with AsyncSessionLocal() as session:
            r = await session.execute(select(AdminUser).where(AdminUser.username == uname))
            return r.scalar_one_or_none()
    except: return None

@app.get("/admin/login")
async def login_page():
    return HTMLResponse(f"""
    <html><head>{UI_CSS}</head><body class="flex items-center justify-center h-screen bg-[#020617]">
        <div class="w-full max-w-md p-8 glass rounded-[32px] shadow-2xl">
            <div class="text-center mb-8">
                <h1 class="text-3xl font-bold">Admin Login</h1>
                <p class="text-slate-500 mt-2">Manage All Saver Pro Bot</p>
            </div>
            <form action="/admin/login" method="post" class="space-y-6">
                <input name="username" placeholder="Username" class="w-full bg-slate-800 border border-slate-700 p-4 rounded-xl outline-none focus:ring-2 focus:ring-blue-500 text-white">
                <input name="password" type="password" placeholder="Password" class="w-full bg-slate-800 border border-slate-700 p-4 rounded-xl outline-none focus:ring-2 focus:ring-blue-500 text-white">
                <button class="w-full bg-blue-600 hover:bg-blue-700 py-4 rounded-xl font-bold transition">Sign In</button>
            </form>
        </div>
    </body></html>
    """)

@app.post("/admin/login")
async def handle_login(response: Response, username: str = Form(...), password: str = Form(...)):
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(AdminUser).where(AdminUser.username == username))
        admin = res.scalar_one_or_none()
        if admin and pwd_context.verify(password, admin.password):
            token = create_token({"sub": admin.username})
            resp = RedirectResponse("/admin/dashboard", status_code=302)
            resp.set_cookie("access_token", token, httponly=True)
            return resp
    return RedirectResponse("/admin/login?error=1", status_code=302)

@app.get("/admin/dashboard")
async def dashboard(request: Request):
    admin = await get_admin(request)
    if not admin: return RedirectResponse("/admin/login")
    
    async with AsyncSessionLocal() as session:
        total_u = (await session.execute(select(func.count(User.id)))).scalar()
        total_d = (await session.execute(select(func.count(Download.id)))).scalar()
        today_d = (await session.execute(select(func.count(Download.id)).where(Download.created_at >= datetime.utcnow().date()))).scalar()
        active_u = (await session.execute(select(func.count(User.id)).where(User.last_activity >= datetime.utcnow() - timedelta(hours=24)))).scalar()

    content = f"""
    <div class="mb-10 flex justify-between items-end">
        <div>
            <h2 class="text-4xl font-bold">General Insights</h2>
            <p class="text-slate-400 mt-2">Real-time system performance data.</p>
        </div>
    </div>
    
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-12">
        <div class="stat-card glass border-l-4 border-blue-500">
            <p class="text-slate-400 font-medium">Total Users</p>
            <h3 class="text-4xl font-bold mt-2">{total_u:,}</h3>
        </div>
        <div class="stat-card glass border-l-4 border-emerald-500">
            <p class="text-slate-400 font-medium">Total Downloads</p>
            <h3 class="text-4xl font-bold mt-2">{total_d:,}</h3>
        </div>
        <div class="stat-card glass border-l-4 border-purple-500">
            <p class="text-slate-400 font-medium">Today Downloads</p>
            <h3 class="text-4xl font-bold mt-2">{today_d:,}</h3>
        </div>
        <div class="stat-card glass border-l-4 border-amber-500">
            <p class="text-slate-400 font-medium">Active (24h)</p>
            <h3 class="text-4xl font-bold mt-2">{active_u:,}</h3>
        </div>
    </div>

    <div class="glass p-8 rounded-[32px] h-[400px]">
        <canvas id="growthChart"></canvas>
    </div>

    <script>
        const ctx = document.getElementById('growthChart').getContext('2d');
        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
                datasets: [{{
                    label: 'Downloads',
                    data: [120, 190, 300, 500, 200, 300, 700],
                    borderColor: '#3b82f6',
                    tension: 0.4,
                    fill: true,
                    backgroundColor: 'rgba(59, 130, 246, 0.05)'
                }}]
            }},
            options: {{ responsive: true, maintainAspectRatio: false, scales: {{ y: {{ grid: {{ color: '#1e293b' }} }}, x: {{ grid: {{ display: false }} }} }} }}
        }});
    </script>
    """
    return HTMLResponse(f"<html><head>{UI_CSS}</head><body>{ADMIN_LAYOUT.format(content=content)}</body></html>")

@app.get("/admin/users")
async def user_list(request: Request, q: str = None):
    admin = await get_admin(request)
    if not admin: return RedirectResponse("/admin/login")
    
    async with AsyncSessionLocal() as session:
        stmt = select(User).order_by(User.join_date.desc()).limit(100)
        users = (await session.execute(stmt)).scalars().all()

    rows = "".join([f"""
    <tr class="border-b border-slate-800 hover:bg-slate-800/30">
        <td class="p-4">{u.telegram_id}</td>
        <td class="p-4">{u.first_name} {u.last_name or ''}</td>
        <td class="p-4">@{u.username or '-'}</td>
        <td class="p-4"><span class="px-3 py-1 bg-blue-500/10 text-blue-400 rounded-full text-xs font-bold">{u.download_count}</span></td>
        <td class="p-4 text-slate-500 text-sm">{u.join_date.strftime('%Y-%m-%d')}</td>
        <td class="p-4">
            <button class="text-red-400 hover:underline">Ban</button>
        </td>
    </tr>""" for u in users])

    content = f"""
    <h2 class="text-3xl font-bold mb-8">User Management</h2>
    <div class="glass rounded-[32px] overflow-hidden">
        <table class="w-full text-left">
            <thead class="bg-slate-800/50 text-slate-400 uppercase text-xs font-bold">
                <tr><th class="p-5">ID</th><th class="p-5">Name</th><th class="p-5">Username</th><th class="p-5">Downloads</th><th class="p-5">Joined</th><th class="p-5">Action</th></tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
    </div>
    """
    return HTMLResponse(f"<html><head>{UI_CSS}</head><body>{ADMIN_LAYOUT.format(content=content)}</body></html>")

@app.get("/health")
async def health_check():
    return {"status": "online", "bot": "running", "database": "connected"}

# --- SYSTEM RUNNER ---
async def start_bot():
    await init_db()
    logger.info("Bot starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "bot":
        # Bot Worker Instance
        asyncio.run(start_bot())
    else:
        # Web Instance (Render looks for app:app)
        # Port 10000 is default for Render
        port = int(os.environ.get("PORT", 10000))
        uvicorn.run("app:app", host="0.0.0.0", port=port)
