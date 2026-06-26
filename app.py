import os
import asyncio
import logging
import json
import secrets
import time
import sys
import re
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Any, Dict, Union

# --- THIRD PARTY IMPORTS ---
import uvicorn
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Cookie, Response, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr
from pydantic_settings import BaseSettings

from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile, 
    InputMediaPhoto, InputMediaVideo, ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import (
    String, BigInteger, DateTime, Integer, Boolean, Text, 
    ForeignKey, select, func, update, delete, desc, and_
)

import aiohttp
from jose import JWTError, jwt
from passlib.context import CryptContext
from dotenv import load_dotenv

# --- CONFIGURATION & ENV ---
load_dotenv()

class Settings(BaseSettings):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "8930218512:AAGF429l1ofoeW7HrRpM7_DKdqn-mdxAwqM")
    ADMIN_ID: int = int(os.getenv("ADMIN_ID", "6434652846"))
    SECRET_KEY: str = os.getenv("SECRET_KEY", "AAGF429l1ofoeW7HrRpM7_DKdqn-mdxAwqM")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://neondb_owner:npg_DFY1rh8nPxQA@ep-lucky-mode-aoxoorn5.c-2.ap-southeast-1.aws.neon.tech/neondb")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 1 Week

config = Settings()

# --- LOGGING SETUP ---
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
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)

class Download(Base):
    __tablename__ = "downloads"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    platform: Mapped[str] = mapped_column(String(50))
    url: Mapped[str] = mapped_column(Text)
    filename: Mapped[Optional[str]] = mapped_column(String(500))
    size: Mapped[Optional[str]] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50)) # success, failed, processing
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
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="admin") # superadmin, editor
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

class PromotionClick(Base):
    __tablename__ = "promotion_clicks"
    id: Mapped[int] = mapped_column(primary_key=True)
    promotion_id: Mapped[int] = mapped_column(Integer, ForeignKey("promotions.id"))
    user_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class SystemSetting(Base):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    value: Mapped[str] = mapped_column(Text)

class SystemLog(Base):
    __tablename__ = "logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

# --- DB ENGINE & SESSION ---
engine = create_async_engine(config.DATABASE_URL, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with AsyncSessionLocal() as session:
        # Check Admin
        admin_check = await session.execute(select(AdminUser).where(AdminUser.username == "admin"))
        if not admin_check.scalar_one_or_none():
            pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
            new_admin = AdminUser(
                telegram_id=config.ADMIN_ID,
                username="admin",
                password=pwd_context.hash("admin123"),
                role="superadmin"
            )
            session.add(new_admin)
            logger.info("Default Admin Created: admin / admin123")
        
        # Default Settings
        default_settings = {
            "maintenance_mode": "false",
            "bot_enabled": "true",
            "welcome_text": "<b>Welcome to All Saver Pro!</b>\n\nI can download videos and music from TikTok, Instagram, Facebook, Pinterest, Spotify, and Terabox.\n\nJust send me a link!",
            "broadcast_lock": "false"
        }
        for k, v in default_settings.items():
            s_check = await session.execute(select(SystemSetting).where(SystemSetting.key == k))
            if not s_check.scalar_one_or_none():
                session.add(SystemSetting(key=k, value=v))
        
        # Default APIs
        apis = [
            ("TikWM", "tiktok", "https://www.tikwm.com/api/?url="),
            ("iGram", "instagram", "https://igram.site/api/instagram?url="),
            ("ToolyFB", "facebook", "https://serverless-tooly-gateway-6n4h522y.ue.gateway.dev/facebook/video?url="),
            ("SpotyLoader", "spotify", "https://spotyloader.com/api/spotify/info?url="),
            ("TeraDown", "terabox", "https://teradown-dzv3.onrender.com/api?url="),
            ("PinsSaver", "pinterest", "https://api.pinssaver.com/pin?url=")
        ]
        for name, plat, end in apis:
            a_check = await session.execute(select(ApiSource).where(ApiSource.name == name))
            if not a_check.scalar_one_or_none():
                session.add(ApiSource(name=name, platform=plat, endpoint=end, status=True, priority=1))

        await session.commit()

# --- MEDIA DOWNLOAD ENGINE ---
class DownloadEngine:
    @staticmethod
    async def get_json(url: str, params: dict = None, headers: dict = None):
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params, headers=headers, timeout=20) as r:
                    if r.status == 200:
                        return await r.json()
            except Exception as e:
                logger.error(f"Engine Fetch Error: {e}")
            return None

    @classmethod
    async def tiktok(cls, url: str):
        data = await cls.get_json(f"https://www.tikwm.com/api/?url={url}")
        if data and data.get("code") == 0:
            d = data["data"]
            return {
                "type": "video",
                "url": d.get("play"),
                "music": d.get("music"),
                "cover": d.get("cover"),
                "title": d.get("title", "TikTok Video"),
                "author": d.get("author", {}).get("nickname", "Unknown")
            }
        return None

    @classmethod
    async def instagram(cls, url: str):
        data = await cls.get_json(f"https://igram.site/api/instagram?url={url}")
        if data and isinstance(data, list) and len(data) > 0:
            return {"type": "mixed", "items": data}
        return None

    @classmethod
    async def facebook(cls, url: str):
        data = await cls.get_json(f"https://serverless-tooly-gateway-6n4h522y.ue.gateway.dev/facebook/video?url={url}")
        if data and "videos" in data:
            v = data["videos"]
            best = v.get("hd") or v.get("sd")
            if best: return {"type": "video", "url": best["url"]}
        return None

    @classmethod
    async def spotify(cls, url: str):
        data = await cls.get_json(f"https://spotyloader.com/api/spotify/info?url={url}")
        if data and "post" in data:
            p = data["post"]
            return {
                "type": "audio",
                "url": p.get("preview_url"),
                "title": p.get("name"),
                "artist": p.get("artist"),
                "image": p.get("image")
            }
        return None

    @classmethod
    async def terabox(cls, url: str):
        # Specific API as per requirements
        api = f"https://teradown-dzv3.onrender.com/api?url={url}&ndus=Y2t6_i7teHuiX-uHDssg3XhTPleotTOyL1Jf5tPV"
        data = await cls.get_json(api)
        if data and "download" in data:
            return {
                "type": "file",
                "url": data.get("download"),
                "name": data.get("name", "TeraBox_File"),
                "size": data.get("size", "Unknown"),
                "thumb": data.get("thumbnail")
            }
        return None

    @classmethod
    async def pinterest(cls, url: str):
        data = await cls.get_json(f"https://api.pinssaver.com/pin?url={url}")
        if data and "data" in data:
            return {"type": "photo", "url": data["data"].get("src", {}).get("orig")}
        return None

# --- TELEGRAM BOT (AIOGRAM 3) ---
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

async def track_user(message: types.Message):
    async with AsyncSessionLocal() as session:
        stmt = select(User).where(User.telegram_id == message.from_user.id)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()
        
        if not user:
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name
            )
            session.add(user)
        else:
            user.last_activity = datetime.utcnow()
            user.username = message.from_user.username
        
        await session.commit()
        return user

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await track_user(message)
    async with AsyncSessionLocal() as session:
        txt = await session.execute(select(SystemSetting).where(SystemSetting.key == "welcome_text"))
        welcome = txt.scalar_one().value
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🔥 Support", url="https://t.me/AllSaverPro_Support")
    kb.button(text="⭐ Rate Us", url=f"https://t.me/BotFather?start=rate")
    kb.adjust(2)
    
    await message.answer(welcome, parse_mode="HTML", reply_markup=kb.as_markup())

@dp.message(F.text.regexp(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'))
async def handle_media_link(message: types.Message):
    user = await track_user(message)
    if user.is_banned:
        return await message.answer("🚫 You are banned from using this bot.")
    
    url = message.text.strip()
    processing_msg = await message.answer("👀 <b>Checking your link...</b>", parse_mode="HTML")
    
    # Visual Reaction
    try:
        await bot.set_message_reaction(message.chat.id, message.message_id, reaction=[types.ReactionTypeEmoji(emoji="👀")])
    except: pass

    await asyncio.sleep(0.8)
    await processing_msg.edit_text("⏳ <b>Processing download...</b>", parse_mode="HTML")
    
    platform = None
    result = None

    try:
        if "tiktok.com" in url:
            platform = "tiktok"
            result = await DownloadEngine.tiktok(url)
        elif "instagram.com" in url:
            platform = "instagram"
            result = await DownloadEngine.instagram(url)
        elif "facebook.com" in url or "fb.watch" in url:
            platform = "facebook"
            result = await DownloadEngine.facebook(url)
        elif "spotify.com" in url:
            platform = "spotify"
            result = await DownloadEngine.spotify(url)
        elif "terabox.com" in url or "1024tera" in url:
            platform = "terabox"
            result = await DownloadEngine.terabox(url)
        elif "pinterest.com" in url or "pin.it" in url:
            platform = "pinterest"
            result = await DownloadEngine.pinterest(url)

        if not result:
            await processing_msg.edit_text("❌ <b>Unsupported URL or Media not found.</b>\nPlease make sure the link is public.", parse_mode="HTML")
            return

        # Log Download
        async with AsyncSessionLocal() as session:
            dl = Download(user_id=user.telegram_id, platform=platform, url=url, status="success")
            session.add(dl)
            await session.execute(update(User).where(User.id == user.id).values(download_count=User.download_count + 1))
            
            # Check for promotion
            promo_res = await session.execute(select(Promotion).where(Promotion.status == True).order_by(func.random()).limit(1))
            promo = promo_res.scalar_one_or_none()
            await session.commit()

        # Send Media
        await processing_msg.edit_text("✅ <b>Download completed!</b> Sending now...", parse_mode="HTML")
        await asyncio.sleep(0.5)
        await processing_msg.delete()

        caption = f"✅ <b>Downloaded via @AllSaverPro_bot</b>"
        
        # Promotion Logic
        promo_kb = None
        if promo and promo.button_text and promo.button_url:
            p_kb = InlineKeyboardBuilder()
            p_kb.button(text=f"🎁 {promo.button_text}", url=promo.button_url)
            promo_kb = p_kb.as_markup()
            caption += f"\n\n<i>Sponsor: {promo.title}</i>"

        if platform == "tiktok":
            await message.answer_video(result['url'], caption=f"🎬 <b>{result['title']}</b>\n👤 {result['author']}\n\n{caption}", parse_mode="HTML", reply_markup=promo_kb)
        elif platform == "instagram":
            items = result['items']
            if len(items) == 1:
                if items[0]['type'] == 'video': await message.answer_video(items[0]['url'], caption=caption, parse_mode="HTML", reply_markup=promo_kb)
                else: await message.answer_photo(items[0]['url'], caption=caption, parse_mode="HTML", reply_markup=promo_kb)
            else:
                media_group = []
                for i in items[:10]:
                    if i['type'] == 'video': media_group.append(InputMediaVideo(media=i['url']))
                    else: media_group.append(InputMediaPhoto(media=i['url']))
                await message.answer_media_group(media_group)
                if promo_kb: await message.answer("Check out our sponsor:", reply_markup=promo_kb)
        elif platform == "facebook":
            await message.answer_video(result['url'], caption=caption, parse_mode="HTML", reply_markup=promo_kb)
        elif platform == "spotify":
            await message.answer_audio(result['url'], caption=f"🎵 <b>{result['title']}</b>\n👤 {result['artist']}\n\n{caption}", parse_mode="HTML", reply_markup=promo_kb)
        elif platform == "pinterest":
            await message.answer_photo(result['url'], caption=caption, parse_mode="HTML", reply_markup=promo_kb)
        elif platform == "terabox":
            txt = f"📦 <b>{result['name']}</b>\n📏 Size: {result['size']}\n\n{caption}"
            kb = InlineKeyboardBuilder()
            kb.button(text="📥 Download Link", url=result['url'])
            if promo_kb: kb.button(text=f"🎁 {promo.button_text}", url=promo.button_url)
            kb.adjust(1)
            await message.answer(txt, parse_mode="HTML", reply_markup=kb.as_markup())

    except Exception as e:
        logger.error(f"Bot Logic Error: {e}")
        await message.answer("⚠️ <b>Something went wrong.</b> The server might be busy, please try again in a few seconds.", parse_mode="HTML")

# --- FASTAPI ADMIN BACKEND ---
app = FastAPI(title="All Saver Pro CMS")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- ADMIN UI TEMPLATES (STRING BLOCKS) ---

CSS_LIB = """
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
    body { font-family: 'Plus Jakarta Sans', sans-serif; background-color: #0f172a; color: #f8fafc; }
    .glass { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.1); }
    .sidebar-link { transition: all 0.3s; border-radius: 12px; margin-bottom: 4px; }
    .sidebar-link:hover { background: rgba(59, 130, 246, 0.15); color: #60a5fa; transform: translateX(5px); }
    .sidebar-active { background: linear-gradient(90deg, rgba(37, 99, 235, 0.2), transparent); border-left: 4px solid #3b82f6; color: #3b82f6; }
    .stat-card { border-radius: 24px; transition: transform 0.3s; }
    .stat-card:hover { transform: translateY(-5px); }
    .custom-scroll::-webkit-scrollbar { width: 6px; }
    .custom-scroll::-webkit-scrollbar-track { background: #1e293b; }
    .custom-scroll::-webkit-scrollbar-thumb { background: #334155; border-radius: 10px; }
    input, select, textarea { background: #1e293b !important; border: 1px solid #334155 !important; color: white !important; }
    .btn-primary { background: linear-gradient(135deg, #3b82f6, #2563eb); }
</style>
"""

NAV_SIDEBAR = """
<div class="fixed inset-y-0 left-0 w-72 glass border-r border-slate-800 flex flex-col z-50">
    <div class="p-8 flex items-center gap-3">
        <div class="w-10 h-10 bg-blue-600 rounded-xl flex items-center justify-center shadow-lg shadow-blue-500/20">
            <i class="fa fa-bolt text-white"></i>
        </div>
        <span class="text-xl font-bold bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent">All Saver Pro</span>
    </div>
    
    <nav class="flex-1 px-6 custom-scroll overflow-y-auto">
        <div class="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-4 px-2">Main Menu</div>
        <a href="/admin/dashboard" class="sidebar-link flex items-center gap-3 p-3.5"><i class="fa fa-th-large w-5"></i> Dashboard</a>
        <a href="/admin/users" class="sidebar-link flex items-center gap-3 p-3.5"><i class="fa fa-users w-5"></i> User Management</a>
        <a href="/admin/downloads" class="sidebar-link flex items-center gap-3 p-3.5"><i class="fa fa-cloud-download-alt w-5"></i> Downloads History</a>
        
        <div class="text-xs font-semibold text-slate-500 uppercase tracking-wider mt-8 mb-4 px-2">System</div>
        <a href="/admin/apis" class="sidebar-link flex items-center gap-3 p-3.5"><i class="fa fa-server w-5"></i> API Sources</a>
        <a href="/admin/promotions" class="sidebar-link flex items-center gap-3 p-3.5"><i class="fa fa-ad w-5"></i> Promotions CMS</a>
        <a href="/admin/settings" class="sidebar-link flex items-center gap-3 p-3.5"><i class="fa fa-sliders-h w-5"></i> Bot Settings</a>
        
        <div class="text-xs font-semibold text-slate-500 uppercase tracking-wider mt-8 mb-4 px-2">Utility</div>
        <a href="/admin/logs" class="sidebar-link flex items-center gap-3 p-3.5"><i class="fa fa-terminal w-5"></i> System Logs</a>
    </nav>
    
    <div class="p-6 border-t border-slate-800">
        <a href="/admin/logout" class="flex items-center gap-3 p-3.5 text-red-400 hover:bg-red-400/10 rounded-xl transition">
            <i class="fa fa-sign-out-alt w-5"></i> Sign Out
        </a>
    </div>
</div>
"""

# --- AUTH LOGIC ---
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, config.SECRET_KEY, algorithm=config.ALGORITHM)

async def get_current_admin(request: Request):
    token = request.cookies.get("access_token")
    if not token: return None
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
        uname = payload.get("sub")
        if uname is None: return None
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(AdminUser).where(AdminUser.username == uname))
            return res.scalar_one_or_none()
    except: return None

# --- ADMIN ROUTES ---
@app.get("/admin/login")
async def login_page(error: str = None):
    return HTMLResponse(f"""
    <html>
    <head><title>Login | All Saver Pro</title>{CSS_LIB}</head>
    <body class="flex items-center justify-center min-h-screen bg-[#020617]">
        <div class="w-full max-w-md p-8 glass rounded-[32px] shadow-2xl">
            <div class="text-center mb-8">
                <div class="w-16 h-16 bg-blue-600 rounded-2xl flex items-center justify-center mx-auto mb-4">
                    <i class="fa fa-shield-alt text-2xl text-white"></i>
                </div>
                <h1 class="text-3xl font-bold">Admin Portal</h1>
                <p class="text-slate-400 mt-2">Sign in to manage All Saver Pro</p>
            </div>
            {f'<div class="bg-red-500/10 text-red-400 p-4 rounded-xl text-center mb-6">{error}</div>' if error else ''}
            <form action="/admin/login" method="POST" class="space-y-6">
                <div>
                    <label class="block text-sm font-medium text-slate-400 mb-2">Username</label>
                    <input type="text" name="username" required class="w-full px-4 py-3 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none transition">
                </div>
                <div>
                    <label class="block text-sm font-medium text-slate-400 mb-2">Password</label>
                    <input type="password" name="password" required class="w-full px-4 py-3 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none transition">
                </div>
                <button type="submit" class="w-full btn-primary py-4 rounded-xl font-bold text-white shadow-lg shadow-blue-500/20 hover:scale-[1.02] active:scale-95 transition">
                    Access Dashboard
                </button>
            </form>
        </div>
    </body>
    </html>
    """)

@app.post("/admin/login")
async def process_login(response: Response, username: str = Form(...), password: str = Form(...)):
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(AdminUser).where(AdminUser.username == username))
        admin = res.scalar_one_or_none()
        if admin and pwd_context.verify(password, admin.password):
            token = create_access_token({"sub": admin.username})
            resp = RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_302_FOUND)
            resp.set_cookie(key="access_token", value=token, httponly=True)
            return resp
    return RedirectResponse(url="/admin/login?error=Invalid Credentials", status_code=status.HTTP_302_FOUND)

@app.get("/admin/logout")
async def logout():
    resp = RedirectResponse(url="/admin/login")
    resp.delete_cookie("access_token")
    return resp

@app.get("/admin/dashboard")
async def admin_dashboard(request: Request):
    admin = await get_current_admin(request)
    if not admin: return RedirectResponse("/admin/login")
    
    async with AsyncSessionLocal() as session:
        total_users = (await session.execute(select(func.count(User.id)))).scalar()
        total_dl = (await session.execute(select(func.count(Download.id)))).scalar()
        today_dl = (await session.execute(select(func.count(Download.id)).where(Download.created_at >= datetime.utcnow().date()))).scalar()
        active_24h = (await session.execute(select(func.count(User.id)).where(User.last_activity >= datetime.utcnow() - timedelta(days=1)))).scalar()
        
        recent_dl = (await session.execute(select(Download).order_by(Download.created_at.desc()).limit(5))).scalars().all()

    content = f"""
    <div class="ml-72 p-10">
        <header class="flex justify-between items-center mb-10">
            <div>
                <h1 class="text-4xl font-bold">Analytics Overview</h1>
                <p class="text-slate-400 mt-1">Welcome back, {admin.username}!</p>
            </div>
            <div class="flex gap-4">
                <div class="glass px-6 py-3 rounded-2xl flex items-center gap-3">
                    <div class="w-2 h-2 bg-emerald-500 rounded-full animate-pulse"></div>
                    <span class="text-sm font-medium">Server Online</span>
                </div>
            </div>
        </header>

        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-10">
            <div class="glass p-8 stat-card">
                <div class="flex justify-between items-start mb-4">
                    <div class="w-12 h-12 bg-blue-500/10 rounded-2xl flex items-center justify-center text-blue-500"><i class="fa fa-users text-xl"></i></div>
                </div>
                <div class="text-slate-400 text-sm font-medium uppercase tracking-wider">Total Users</div>
                <div class="text-3xl font-bold mt-1">{total_users:,}</div>
            </div>
            <div class="glass p-8 stat-card">
                <div class="flex justify-between items-start mb-4">
                    <div class="w-12 h-12 bg-emerald-500/10 rounded-2xl flex items-center justify-center text-emerald-500"><i class="fa fa-download text-xl"></i></div>
                </div>
                <div class="text-slate-400 text-sm font-medium uppercase tracking-wider">Total Downloads</div>
                <div class="text-3xl font-bold mt-1">{total_dl:,}</div>
            </div>
            <div class="glass p-8 stat-card">
                <div class="flex justify-between items-start mb-4">
                    <div class="w-12 h-12 bg-amber-500/10 rounded-2xl flex items-center justify-center text-amber-500"><i class="fa fa-chart-line text-xl"></i></div>
                </div>
                <div class="text-slate-400 text-sm font-medium uppercase tracking-wider">Today's Usage</div>
                <div class="text-3xl font-bold mt-1">{today_dl:,}</div>
            </div>
            <div class="glass p-8 stat-card">
                <div class="flex justify-between items-start mb-4">
                    <div class="w-12 h-12 bg-purple-500/10 rounded-2xl flex items-center justify-center text-purple-500"><i class="fa fa-user-check text-xl"></i></div>
                </div>
                <div class="text-slate-400 text-sm font-medium uppercase tracking-wider">Active (24h)</div>
                <div class="text-3xl font-bold mt-1">{active_24h:,}</div>
            </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
            <div class="lg:col-span-2 glass p-8 rounded-[32px]">
                <h3 class="text-xl font-bold mb-6">Traffic Analysis</h3>
                <canvas id="mainChart" height="300"></canvas>
            </div>
            <div class="glass p-8 rounded-[32px]">
                <h3 class="text-xl font-bold mb-6">Recent Downloads</h3>
                <div class="space-y-6">
                    {"".join([f'''
                    <div class="flex items-center gap-4">
                        <div class="w-10 h-10 bg-slate-800 rounded-lg flex items-center justify-center text-slate-400 uppercase font-bold text-xs">{d.platform[:2]}</div>
                        <div class="flex-1 min-w-0">
                            <p class="text-sm font-medium truncate">{d.url}</p>
                            <p class="text-xs text-slate-500">{d.created_at.strftime('%H:%M:%S')}</p>
                        </div>
                    </div>''' for d in recent_dl])}
                </div>
                <a href="/admin/downloads" class="block text-center mt-8 text-blue-500 text-sm font-medium hover:underline">View All History</a>
            </div>
        </div>
    </div>
    <script>
        const ctx = document.getElementById('mainChart').getContext('2d');
        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
                datasets: [{{
                    label: 'Downloads',
                    data: [65, 59, 80, 81, 56, 55, 40],
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    fill: true,
                    tension: 0.4,
                    borderWidth: 3,
                    pointRadius: 0
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    y: {{ grid: {{ color: 'rgba(255,255,255,0.05)' }}, ticks: {{ color: '#64748b' }} }},
                    x: {{ grid: {{ display: false }}, ticks: {{ color: '#64748b' }} }}
                }}
            }}
        }});
    </script>
    """
    
    return HTMLResponse(f"<html><head>{CSS_LIB}</head><body>{NAV_SIDEBAR}{content}</body></html>")

@app.get("/admin/users")
async def manage_users(request: Request, page: int = 1):
    admin = await get_current_admin(request)
    if not admin: return RedirectResponse("/admin/login")
    
    async with AsyncSessionLocal() as session:
        offset = (page-1) * 20
        res = await session.execute(select(User).order_by(desc(User.join_date)).offset(offset).limit(20))
        users = res.scalars().all()
    
    user_rows = "".join([f"""
    <tr class="border-b border-slate-800/50 hover:bg-slate-800/30 transition">
        <td class="p-4">
            <div class="flex items-center gap-3">
                <div class="w-10 h-10 bg-slate-800 rounded-full flex items-center justify-center text-slate-500 font-bold">
                    {u.first_name[0] if u.first_name else 'U'}
                </div>
                <div>
                    <p class="font-medium">{u.first_name} {u.last_name or ''}</p>
                    <p class="text-xs text-slate-500">@{u.username or 'NoUsername'}</p>
                </div>
            </div>
        </td>
        <td class="p-4 text-slate-400 font-mono text-sm">{u.telegram_id}</td>
        <td class="p-4">
            <span class="px-3 py-1 bg-blue-500/10 text-blue-400 rounded-full text-xs font-bold">{u.download_count} DLs</span>
        </td>
        <td class="p-4 text-slate-500 text-sm">{u.join_date.strftime('%Y-%m-%d')}</td>
        <td class="p-4">
            <div class="flex gap-2">
                <button class="p-2 hover:bg-red-500/20 text-red-400 rounded-lg transition"><i class="fa fa-ban"></i></button>
                <button class="p-2 hover:bg-blue-500/20 text-blue-400 rounded-lg transition"><i class="fa fa-envelope"></i></button>
            </div>
        </td>
    </tr>""" for u in users])

    content = f"""
    <div class="ml-72 p-10">
        <div class="flex justify-between items-center mb-10">
            <h1 class="text-3xl font-bold">User Management</h1>
            <div class="flex gap-4">
                <input type="text" placeholder="Search by ID or Username..." class="px-4 py-2 rounded-xl glass outline-none w-64">
            </div>
        </div>
        
        <div class="glass rounded-3xl overflow-hidden">
            <table class="w-full text-left border-collapse">
                <thead class="bg-slate-800/50 text-slate-400 text-xs uppercase tracking-wider">
                    <tr>
                        <th class="p-5">Profile</th>
                        <th class="p-5">Telegram ID</th>
                        <th class="p-5">Usage</th>
                        <th class="p-5">Joined</th>
                        <th class="p-5">Actions</th>
                    </tr>
                </thead>
                <tbody class="text-sm">
                    {user_rows}
                </tbody>
            </table>
        </div>
    </div>
    """
    return HTMLResponse(f"<html><head>{CSS_LIB}</head><body>{NAV_SIDEBAR}{content}</body></html>")

@app.get("/admin/settings")
async def bot_settings(request: Request):
    admin = await get_current_admin(request)
    if not admin: return RedirectResponse("/admin/login")
    
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(SystemSetting))
        settings = {s.key: s.value for s in res.scalars().all()}

    content = f"""
    <div class="ml-72 p-10">
        <h1 class="text-3xl font-bold mb-10">System Configuration</h1>
        
        <div class="max-w-3xl space-y-8">
            <form action="/admin/settings" method="POST" class="glass p-8 rounded-[32px] space-y-6">
                <div>
                    <label class="block text-sm font-semibold text-slate-400 mb-2">Bot Status</label>
                    <select name="bot_enabled" class="w-full p-3.5 rounded-xl outline-none">
                        <option value="true" {'selected' if settings.get('bot_enabled') == 'true' else ''}>Online (Active)</option>
                        <option value="false" {'selected' if settings.get('bot_enabled') == 'false' else ''}>Offline (Disabled)</option>
                    </select>
                </div>
                
                <div>
                    <label class="block text-sm font-semibold text-slate-400 mb-2">Welcome Message (HTML Supported)</label>
                    <textarea name="welcome_text" rows="5" class="w-full p-3.5 rounded-xl outline-none">{settings.get('welcome_text')}</textarea>
                </div>
                
                <div class="flex items-center gap-4 p-4 bg-blue-500/5 border border-blue-500/20 rounded-2xl">
                    <i class="fa fa-info-circle text-blue-500"></i>
                    <p class="text-sm text-slate-400">Maintenance mode will block all bot interactions except for admins.</p>
                </div>

                <button type="submit" class="w-full btn-primary py-4 rounded-xl font-bold text-white shadow-lg">Save Changes</button>
            </form>
        </div>
    </div>
    """
    return HTMLResponse(f"<html><head>{CSS_LIB}</head><body>{NAV_SIDEBAR}{content}</body></html>")

@app.post("/admin/settings")
async def update_settings(request: Request):
    admin = await get_current_admin(request)
    if not admin: return RedirectResponse("/admin/login")
    
    form = await request.form()
    async with AsyncSessionLocal() as session:
        for key in form.keys():
            await session.execute(update(SystemSetting).where(SystemSetting.key == key).values(value=form[key]))
        await session.commit()
    return RedirectResponse("/admin/settings", status_code=302)

# --- BROADCAST SYSTEM ---
@app.get("/admin/broadcast")
async def broadcast_page(request: Request):
    admin = await get_current_admin(request)
    if not admin: return RedirectResponse("/admin/login")
    return HTMLResponse(f"<html><head>{CSS_LIB}</head><body>{NAV_SIDEBAR}<div class='ml-72 p-10'><h1 class='text-3xl font-bold mb-8'>Global Broadcast</h1><div class='glass p-8 rounded-3xl max-w-2xl'><form action='/admin/broadcast' method='POST' class='space-y-6'><div><label class='block mb-2 text-sm'>Message Content (HTML)</label><textarea name='msg' rows='8' class='w-full p-4 rounded-xl outline-none'></textarea></div><button class='btn-primary w-full py-4 rounded-xl font-bold'>Send to All Users</button></form></div></div></body></html>")

# --- PROMOTION CMS ---
@app.get("/admin/promotions")
async def promotions_list(request: Request):
    admin = await get_current_admin(request)
    if not admin: return RedirectResponse("/admin/login")
    
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(Promotion))
        promos = res.scalars().all()

    promo_list = "".join([f"""
    <div class="glass p-6 rounded-2xl flex items-center justify-between">
        <div>
            <h4 class="font-bold">{p.title}</h4>
            <p class="text-sm text-slate-400">{p.button_url}</p>
        </div>
        <div class="flex gap-2">
            <button class="px-4 py-2 bg-slate-800 rounded-lg hover:bg-slate-700 transition">Edit</button>
            <button class="px-4 py-2 bg-red-500/20 text-red-400 rounded-lg hover:bg-red-500/30 transition">Delete</button>
        </div>
    </div>""" for p in promos])

    content = f"""
    <div class="ml-72 p-10">
        <div class="flex justify-between items-center mb-10">
            <h1 class="text-3xl font-bold">Promotions CMS</h1>
            <button class="btn-primary px-6 py-3 rounded-xl font-bold text-sm">+ Create Promo</button>
        </div>
        <div class="grid grid-cols-1 gap-4">
            {promo_list or '<div class="text-center p-20 text-slate-500">No promotions active</div>'}
        </div>
    </div>
    """
    return HTMLResponse(f"<html><head>{CSS_LIB}</head><body>{NAV_SIDEBAR}{content}</body></html>")

# --- MAIN EXECUTION HANDLER ---
async def run_bot():
    await init_db()
    logger.info("Starting Aiogram 3.x Bot Worker...")
    await dp.start_polling(bot)

@app.on_event("startup")
async def startup_event():
    await init_db()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "bot":
        # Run Bot Worker Mode
        asyncio.run(run_bot())
    else:
        # Run FastAPI Server Mode
        port = int(os.environ.get("PORT", 10000))
        uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
