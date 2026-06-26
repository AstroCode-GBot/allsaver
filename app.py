import asyncio
import logging
import os
import secrets
import time
import uuid
import json
from datetime import datetime, timedelta
from typing import Optional, List, Any, Dict, Union

# --- THIRD PARTY IMPORTS ---
import httpx
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Response, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordBearer
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic_settings import BaseSettings
from pydantic import BaseModel

# --- BOT IMPORTS ---
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- DB IMPORTS ---
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import (
    String, BigInteger, DateTime, Integer, Boolean, Text, 
    ForeignKey, select, func, update, delete, desc
)

# --- ENVIRONMENT CONFIG ---
class Settings(BaseSettings):
    BOT_TOKEN: str = "8930218512:AAGF429l1ofoeW7HrRpM7_DKdqn-mdxAwqM"
    ADMIN_ID: int = 6434652846
    SECRET_KEY: str = "AAGF429l1ofoeW7HrRpM7_DKdqn-mdxAwqM"
    DATABASE_URL: str = "postgresql+asyncpg://neondb_owner:npg_DFY1rh8nPxQA@ep-lucky-mode-aoxoorn5.c-2.ap-southeast-1.aws.neon.tech/neondb"
    REDIS_URL: Optional[str] = None
    ENVIRONMENT: str = "production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440 # 24 Hours

    class Config:
        env_file = ".env"

config = Settings()

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
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
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    platform: Mapped[str] = mapped_column(String(50))
    url: Mapped[str] = mapped_column(Text)
    filename: Mapped[Optional[str]] = mapped_column(String(500))
    size: Mapped[Optional[str]] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50), default="completed")
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
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="admin")

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
    views: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
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

# --- DB ENGINE ---
engine = create_async_engine(config.DATABASE_URL, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with AsyncSessionLocal() as session:
        # Create default admin if not exists
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        res = await session.execute(select(AdminUser).where(AdminUser.username == "admin"))
        if not res.scalar_one_or_none():
            hashed = pwd_context.hash("admin123")
            session.add(AdminUser(username="admin", password=hashed, role="superadmin"))
            await session.commit()
            logger.info("Default admin created: admin / admin123")

# --- DOWNLOADER ENGINE ---
class DownloaderEngine:
    @staticmethod
    async def get_tiktok(url: str) -> Dict:
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"https://www.tikwm.com/api/?url={url}", timeout=15)
                data = resp.json()
                if data.get("code") == 0:
                    item = data["data"]
                    return {
                        "status": True,
                        "type": "video",
                        "url": item.get("play"),
                        "title": item.get("title"),
                        "author": item.get("author", {}).get("nickname"),
                        "cover": item.get("cover")
                    }
            except Exception as e:
                logger.error(f"TikTok error: {e}")
        return {"status": False}

    @staticmethod
    async def get_instagram(url: str) -> Dict:
        # Example using iGram style API wrapper
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"https://igram.site/api/instagram?url={url}", timeout=15)
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    return {"status": True, "type": "mixed", "medias": data}
            except Exception as e:
                logger.error(f"Instagram error: {e}")
        return {"status": False}

    @staticmethod
    async def get_facebook(url: str) -> Dict:
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"https://serverless-tooly-gateway-6n4h522y.ue.gateway.dev/facebook/video?url={url}", timeout=15)
                data = resp.json()
                if "videos" in data:
                    vids = data["videos"]
                    # Priority HD
                    link = vids.get("hd") or vids.get("sd")
                    return {"status": True, "type": "video", "url": link.get("url")}
            except Exception as e:
                logger.error(f"Facebook error: {e}")
        return {"status": False}

    @staticmethod
    async def get_spotify(url: str) -> Dict:
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"https://spotyloader.com/api/spotify/info?url={url}", timeout=15)
                data = resp.json()
                if "post" in data:
                    p = data["post"]
                    return {
                        "status": True,
                        "type": "audio",
                        "url": p.get("preview_url"),
                        "title": p.get("name"),
                        "artist": p.get("artist"),
                        "image": p.get("image")
                    }
            except Exception as e:
                logger.error(f"Spotify error: {e}")
        return {"status": False}

    @classmethod
    async def process(cls, url: str) -> Dict:
        if "tiktok.com" in url:
            return await cls.get_tiktok(url)
        elif "instagram.com" in url:
            return await cls.get_instagram(url)
        elif "facebook.com" in url or "fb.watch" in url:
            return await cls.get_facebook(url)
        elif "spotify.com" in url:
            return await cls.get_spotify(url)
        # Fallback / generic detection can be added
        return {"status": False, "message": "Platform not supported yet"}

# --- BOT HANDLERS ---
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

async def get_or_create_user(tg_user: types.User, session: AsyncSession):
    stmt = select(User).where(User.telegram_id == tg_user.id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        user = User(
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name
        )
        session.add(user)
        await session.commit()
    return user

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    async with AsyncSessionLocal() as session:
        await get_or_create_user(message.from_user, session)
    
    welcome_text = (
        "🚀 **Welcome to All Saver Pro!**\n\n"
        "I can download media from:\n"
        "• TikTok (No Watermark)\n"
        "• Instagram (Reels, Posts)\n"
        "• Facebook\n"
        "• Spotify\n"
        "• Pinterest & Terabox\n\n"
        "👉 Just **send me a link** to start!"
    )
    await message.answer(welcome_text, parse_mode="Markdown")

@dp.message(F.text.regexp(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'))
async def handle_url(message: types.Message):
    url = message.text.strip()
    
    # Check if user is banned
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(message.from_user, session)
        if user.is_banned:
            return await message.answer("🚫 You are banned from using this bot.")

    status_msg = await message.answer("👀 **Checking your link...**", parse_mode="Markdown")
    
    # Wait animation
    await asyncio.sleep(1)
    await status_msg.edit_text("⏳ **Processing download...**", parse_mode="Markdown")
    
    result = await DownloaderEngine.process(url)
    
    if not result.get("status"):
        return await status_msg.edit_text("❌ **Failed!** Could not extract media. Please check the URL or try again later.")

    # Platform determined
    platform = "Unknown"
    if "tiktok" in url: platform = "TikTok"
    elif "instagram" in url: platform = "Instagram"
    elif "facebook" in url: platform = "Facebook"
    elif "spotify" in url: platform = "Spotify"

    try:
        if result["type"] == "video":
            await message.answer_video(
                video=result["url"],
                caption=f"✅ **Download Completed**\n\n🎬 Title: {result.get('title', 'N/A')}\n🌐 Platform: {platform}\n\n@AllSaverPro_bot",
                parse_mode="Markdown"
            )
        elif result["type"] == "audio":
            await message.answer_audio(
                audio=result["url"],
                caption=f"✅ **Download Completed**\n\n🎵 Title: {result.get('title')}\n👤 Artist: {result.get('artist')}\n\n@AllSaverPro_bot",
                parse_mode="Markdown"
            )
        elif result["type"] == "mixed":
            for item in result["medias"]:
                if item["type"] == "video":
                    await message.answer_video(item["url"])
                else:
                    await message.answer_photo(item["url"])
            await message.answer(f"✅ **{platform} Bundle Completed**\n@AllSaverPro_bot")

        # Update statistics
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(User).where(User.telegram_id == message.from_user.id).values(
                    download_count=User.download_count + 1,
                    last_activity=datetime.utcnow()
                )
            )
            session.add(Download(user_id=message.from_user.id, platform=platform, url=url))
            await session.commit()

        await status_msg.delete()

    except Exception as e:
        logger.error(f"Send error: {e}")
        await status_msg.edit_text("⚠️ **Error!** Could not send the file to you. It might be too large for Telegram.")

# --- WEB ADMIN UI TEMPLATES ---
LOGIN_HTML = """
<!DOCTYPE html>
<html class="dark">
<head>
    <title>All Saver Pro | Admin Login</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-900 flex items-center justify-center h-screen">
    <div class="bg-slate-800 p-8 rounded-2xl shadow-2xl w-96 border border-slate-700">
        <h1 class="text-2xl font-bold text-white mb-6 text-center">Admin Access</h1>
        {% if error %}<p class="text-red-500 text-sm mb-4">{{ error }}</p>{% endif %}
        <form method="POST" action="/admin/login" class="space-y-4">
            <input type="text" name="username" placeholder="Username" class="w-full p-3 rounded bg-slate-700 text-white border border-slate-600 focus:outline-none">
            <input type="password" name="password" placeholder="Password" class="w-full p-3 rounded bg-slate-700 text-white border border-slate-600 focus:outline-none">
            <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-3 rounded transition">Sign In</button>
        </form>
    </div>
</body>
</html>
"""

LAYOUT_HTML = """
<!DOCTYPE html>
<html class="dark">
<head>
    <title>All Saver Pro | Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <style>
        .glass { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(10px); }
        .sidebar-link:hover { background: rgba(59, 130, 246, 0.1); }
    </style>
</head>
<body class="bg-slate-900 text-slate-200">
    <div class="flex h-screen overflow-hidden">
        <!-- Sidebar -->
        <div class="w-64 glass border-r border-slate-800 flex flex-col p-4">
            <div class="mb-10 px-2 text-2xl font-bold text-white flex items-center">
                <i class="fas fa-shield-alt mr-3 text-blue-500"></i> All Saver Pro
            </div>
            <nav class="flex-1 space-y-2">
                <a href="/admin/dashboard" class="sidebar-link flex items-center p-3 rounded-xl transition {{ 'bg-blue-600/20 text-blue-400' if active == 'dashboard' else '' }}">
                    <i class="fas fa-chart-line w-6"></i> Dashboard
                </a>
                <a href="/admin/users" class="sidebar-link flex items-center p-3 rounded-xl transition {{ 'bg-blue-600/20 text-blue-400' if active == 'users' else '' }}">
                    <i class="fas fa-users w-6"></i> Users
                </a>
                <a href="/admin/downloads" class="sidebar-link flex items-center p-3 rounded-xl transition {{ 'bg-blue-600/20 text-blue-400' if active == 'downloads' else '' }}">
                    <i class="fas fa-download w-6"></i> Downloads
                </a>
                <a href="/admin/apis" class="sidebar-link flex items-center p-3 rounded-xl transition {{ 'bg-blue-600/20 text-blue-400' if active == 'apis' else '' }}">
                    <i class="fas fa-server w-6"></i> API Engine
                </a>
                <a href="/admin/promotions" class="sidebar-link flex items-center p-3 rounded-xl transition {{ 'bg-blue-600/20 text-blue-400' if active == 'promotions' else '' }}">
                    <i class="fas fa-ad w-6"></i> Promotions
                </a>
                <a href="/admin/settings" class="sidebar-link flex items-center p-3 rounded-xl transition {{ 'bg-blue-600/20 text-blue-400' if active == 'settings' else '' }}">
                    <i class="fas fa-cog w-6"></i> Settings
                </a>
            </nav>
            <div class="mt-auto">
                <a href="/admin/logout" class="flex items-center p-3 rounded-xl text-red-400 hover:bg-red-400/10 transition">
                    <i class="fas fa-sign-out-alt w-6"></i> Logout
                </a>
            </div>
        </div>
        
        <!-- Content -->
        <main class="flex-1 overflow-y-auto p-8">
            {% block content %}{% endblock %}
        </main>
    </div>
</body>
</html>
"""

DASHBOARD_HTML = """
{% extends "layout" %}
{% block content %}
<div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
    <div class="bg-slate-800 p-6 rounded-2xl border border-slate-700">
        <p class="text-slate-400 text-sm">Total Users</p>
        <h3 class="text-3xl font-bold">{{ stats.users }}</h3>
    </div>
    <div class="bg-slate-800 p-6 rounded-2xl border border-slate-700">
        <p class="text-slate-400 text-sm">Total Downloads</p>
        <h3 class="text-3xl font-bold">{{ stats.downloads }}</h3>
    </div>
    <div class="bg-slate-800 p-6 rounded-2xl border border-slate-700">
        <p class="text-slate-400 text-sm">Active Users (24h)</p>
        <h3 class="text-3xl font-bold">{{ stats.active }}</h3>
    </div>
    <div class="bg-slate-800 p-6 rounded-2xl border border-slate-700">
        <p class="text-slate-400 text-sm">API Success Rate</p>
        <h3 class="text-3xl font-bold text-green-500">98.2%</h3>
    </div>
</div>

<div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
    <div class="bg-slate-800 p-6 rounded-2xl border border-slate-700">
        <h4 class="text-lg font-semibold mb-4">Download Growth</h4>
        <canvas id="growthChart" height="200"></canvas>
    </div>
    <div class="bg-slate-800 p-6 rounded-2xl border border-slate-700 overflow-hidden">
        <h4 class="text-lg font-semibold mb-4">Recent Activities</h4>
        <div class="space-y-4">
            {% for dl in recent %}
            <div class="flex items-center justify-between border-b border-slate-700 pb-2">
                <div>
                    <p class="text-sm font-medium">{{ dl.platform }}</p>
                    <p class="text-xs text-slate-500">{{ dl.url[:40] }}...</p>
                </div>
                <span class="text-xs text-slate-400">{{ dl.created_at.strftime('%H:%M') }}</span>
            </div>
            {% endfor %}
        </div>
    </div>
</div>

<script>
    const ctx = document.getElementById('growthChart').getContext('2d');
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
            datasets: [{
                label: 'Downloads',
                data: [120, 190, 300, 500, 200, 300, 700],
                borderColor: '#3b82f6',
                tension: 0.4
            }]
        },
        options: {
            scales: {
                y: { beginAtZero: true, grid: { color: '#334155' } },
                x: { grid: { display: false } }
            }
        }
    });
</script>
{% endblock %}
"""

USERS_HTML = """
{% extends "layout" %}
{% block content %}
<div class="bg-slate-800 rounded-2xl border border-slate-700 overflow-hidden">
    <div class="p-6 border-b border-slate-700 flex justify-between items-center">
        <h3 class="text-xl font-bold">Manage Users</h3>
        <input type="text" placeholder="Search users..." class="bg-slate-700 border border-slate-600 rounded-lg px-4 py-2 text-sm focus:outline-none">
    </div>
    <table class="w-full text-left border-collapse">
        <thead>
            <tr class="bg-slate-900/50 text-slate-400 text-xs uppercase tracking-wider">
                <th class="px-6 py-4">User</th>
                <th class="px-6 py-4">Downloads</th>
                <th class="px-6 py-4">Last Activity</th>
                <th class="px-6 py-4">Status</th>
                <th class="px-6 py-4">Action</th>
            </tr>
        </thead>
        <tbody class="text-sm">
            {% for user in users %}
            <tr class="border-b border-slate-700 hover:bg-slate-700/30 transition">
                <td class="px-6 py-4">
                    <div class="flex items-center">
                        <div class="w-8 h-8 rounded-full bg-blue-500 mr-3 flex items-center justify-center font-bold">
                            {{ user.first_name[0] }}
                        </div>
                        <div>
                            <p class="font-medium text-white">{{ user.first_name }}</p>
                            <p class="text-xs text-slate-500">@{{ user.username or 'none' }}</p>
                        </div>
                    </div>
                </td>
                <td class="px-6 py-4">{{ user.download_count }}</td>
                <td class="px-6 py-4 text-xs text-slate-400">{{ user.last_activity.strftime('%Y-%m-%d %H:%M') }}</td>
                <td class="px-6 py-4">
                    <span class="px-2 py-1 rounded text-[10px] {{ 'bg-red-500/20 text-red-500' if user.is_banned else 'bg-green-500/20 text-green-500' }}">
                        {{ 'Banned' if user.is_banned else 'Active' }}
                    </span>
                </td>
                <td class="px-6 py-4">
                    <a href="/admin/users/ban/{{ user.telegram_id }}" class="text-red-400 hover:text-red-300">
                        <i class="fas {{ 'fa-user-check' if user.is_banned else 'fa-user-slash' }}"></i>
                    </a>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
"""

# --- FASTAPI APP ---
app = FastAPI()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Template Registry
templates = Jinja2Templates(directory="templates") # We'll mock this with a Custom loader if needed, but for Render let's use strings
from jinja2 import Environment, FunctionLoader

def load_template(name):
    if name == "login": return LOGIN_HTML
    if name == "layout": return LAYOUT_HTML
    if name == "dashboard": return DASHBOARD_HTML
    if name == "users": return USERS_HTML
    return None

jinja_env = Environment(loader=FunctionLoader(load_template))

# Auth Helpers
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, config.SECRET_KEY, algorithm=config.ALGORITHM)

def get_current_admin(access_token: str = Cookie(None)):
    if not access_token:
        return None
    try:
        payload = jwt.decode(access_token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None

# Routes
@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/admin/login")

@app.get("/health")
async def health():
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(select(1))
            db_status = "connected"
        except:
            db_status = "error"
    return {"status": "online", "bot": "running", "database": db_status}

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request, error: str = None):
    template = jinja_env.get_template("login")
    return HTMLResponse(template.render(error=error))

@app.post("/admin/login")
async def admin_login_post(username: str = Form(...), password: str = Form(...)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(AdminUser).where(AdminUser.username == username))
        admin = result.scalar_one_or_none()
        if admin and pwd_context.verify(password, admin.password):
            token = create_access_token({"sub": admin.username})
            response = RedirectResponse("/admin/dashboard", status_code=status.HTTP_302_FOUND)
            response.set_cookie(key="access_token", value=token, httponly=True)
            return response
        return RedirectResponse("/admin/login?error=Invalid+Credentials", status_code=status.HTTP_302_FOUND)

@app.get("/admin/logout")
async def admin_logout():
    response = RedirectResponse("/admin/login")
    response.delete_cookie("access_token")
    return response

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, admin=Depends(get_current_admin)):
    if not admin: return RedirectResponse("/admin/login")
    
    async with AsyncSessionLocal() as session:
        user_count = (await session.execute(select(func.count(User.id)))).scalar()
        dl_count = (await session.execute(select(func.count(Download.id)))).scalar()
        active_users = (await session.execute(select(func.count(User.id)).where(User.last_activity > datetime.utcnow() - timedelta(days=1)))).scalar()
        recent_dls = (await session.execute(select(Download).order_by(desc(Download.created_at)).limit(5))).scalars().all()

    template = jinja_env.get_template("dashboard")
    return HTMLResponse(template.render(
        active="dashboard", 
        stats={"users": user_count, "downloads": dl_count, "active": active_users},
        recent=recent_dls
    ))

@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request, admin=Depends(get_current_admin)):
    if not admin: return RedirectResponse("/admin/login")
    
    async with AsyncSessionLocal() as session:
        users = (await session.execute(select(User).order_by(desc(User.join_date)).limit(100))).scalars().all()

    template = jinja_env.get_template("users")
    return HTMLResponse(template.render(active="users", users=users))

@app.get("/admin/users/ban/{tg_id}")
async def ban_user(tg_id: int, admin=Depends(get_current_admin)):
    if not admin: return RedirectResponse("/admin/login")
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.telegram_id == tg_id))).scalar_one_or_none()
        if user:
            user.is_banned = not user.is_banned
            await session.commit()
    return RedirectResponse("/admin/users")

# --- BACKGROUND TASK RUNNER ---
async def start_bot():
    await init_db()
    logger.info("Bot starting...")
    # Add a slight delay for Render to bind port
    await asyncio.sleep(2)
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Polling error: {e}")

@app.on_event("startup")
async def startup_event():
    # Start bot in background
    asyncio.create_task(start_bot())

if __name__ == "__main__":
    import uvicorn
    # Use environment port for Render compatibility
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
