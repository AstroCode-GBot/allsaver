import os
import asyncio
import logging
import json
import time
import uuid
import sys
from datetime import datetime, timedelta
from typing import Optional, List, Any, Dict

# Web & API
import uvicorn
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Cookie, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# Bot
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Database
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, BigInteger, DateTime, Integer, Boolean, Text, ForeignKey, select, func, update, delete

# Utils
import aiohttp
from jose import JWTError, jwt
from passlib.context import CryptContext
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "8930218512:AAGF429l1ofoeW7HrRpM7_DKdqn-mdxAwqM")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6434652846"))
SECRET_KEY = os.getenv("SECRET_KEY", "AAGF429l1ofoeW7HrRpM7_DKdqn-mdxAwqM")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://neondb_owner:npg_DFY1rh8nPxQA@ep-lucky-mode-aoxoorn5.c-2.ap-southeast-1.aws.neon.tech/neondb")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week

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
    last_activity: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
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
    status: Mapped[str] = mapped_column(String(50)) # completed, failed
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
    username: Mapped[str] = mapped_column(String(100))
    password: Mapped[str] = mapped_column(String(255)) # Hashed
    role: Mapped[str] = mapped_column(String(50), default="superadmin")

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class PromotionClick(Base):
    __tablename__ = "promotion_clicks"
    id: Mapped[int] = mapped_column(primary_key=True)
    promotion_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Setting(Base):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    value: Mapped[str] = mapped_column(Text)

# --- DATABASE SETUP ---
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Create default settings
    async with AsyncSessionLocal() as session:
        # Check if default admin exists
        res = await session.execute(select(AdminUser).where(AdminUser.telegram_id == ADMIN_ID))
        if not res.scalar_one_or_none():
            pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
            admin = AdminUser(
                telegram_id=ADMIN_ID,
                username="admin",
                password=pwd_context.hash("admin123"),
                role="superadmin"
            )
            session.add(admin)
        
        # Default settings
        defaults = {
            "maintenance_mode": "false",
            "welcome_message": "Welcome to All Saver Pro! Send me any media link from TikTok, Instagram, Facebook, Pinterest, Spotify, or Terabox.",
            "bot_enabled": "true"
        }
        for k, v in defaults.items():
            s = await session.execute(select(Setting).where(Setting.key == k))
            if not s.scalar_one_or_none():
                session.add(Setting(key=k, value=v))
        
        await session.commit()

# --- DOWNLOADER ENGINE ---
class MediaDownloader:
    @staticmethod
    async def fetch_json(url: str, params: dict = None):
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params, timeout=15) as resp:
                    if resp.status == 200:
                        return await resp.json()
            except Exception as e:
                logger.error(f"Fetch error: {e}")
            return None

    @classmethod
    async def get_tiktok(cls, url: str):
        api_url = f"https://www.tikwm.com/api/?url={url}"
        data = await cls.fetch_json(api_url)
        if data and data.get("code") == 0:
            item = data["data"]
            return {
                "platform": "tiktok",
                "video": item.get("play"),
                "music": item.get("music"),
                "title": item.get("title"),
                "author": item.get("author", {}).get("nickname"),
                "cover": item.get("cover")
            }
        return None

    @classmethod
    async def get_instagram(cls, url: str):
        api_url = f"https://igram.site/api/instagram?url={url}"
        data = await cls.fetch_json(api_url)
        if data and isinstance(data, list) and len(data) > 0:
            return {
                "platform": "instagram",
                "media": [{"url": i.get("url"), "type": i.get("type")} for i in data]
            }
        return None

    @classmethod
    async def get_facebook(cls, url: str):
        api_url = f"https://serverless-tooly-gateway-6n4h522y.ue.gateway.dev/facebook/video?url={url}"
        data = await cls.fetch_json(api_url)
        if data and "videos" in data:
            vids = data["videos"]
            link = vids.get("hd") or vids.get("sd")
            if link:
                return {"platform": "facebook", "video": link.get("url")}
        return None

    @classmethod
    async def get_spotify(cls, url: str):
        api_url = f"https://spotyloader.com/api/spotify/info?url={url}"
        data = await cls.fetch_json(api_url)
        if data and "post" in data:
            p = data["post"]
            return {
                "platform": "spotify",
                "title": p.get("name"),
                "artist": p.get("artist"),
                "preview": p.get("preview_url"),
                "image": p.get("image")
            }
        return None

    @classmethod
    async def get_terabox(cls, url: str):
        # Using the provided ndus endpoint logic
        api_url = f"https://teradown-dzv3.onrender.com/api?url={url}&ndus=Y2t6_i7teHuiX-uHDssg3XhTPleotTOyL1Jf5tPV"
        data = await cls.fetch_json(api_url)
        if data and "download" in data:
            return {
                "platform": "terabox",
                "url": data.get("download"),
                "name": data.get("name"),
                "size": data.get("size")
            }
        return None

    @classmethod
    async def get_pinterest(cls, url: str):
        api_url = f"https://api.pinssaver.com/pin?url={url}"
        data = await cls.fetch_json(api_url)
        if data and "data" in data:
            return {"platform": "pinterest", "image": data["data"].get("src", {}).get("orig")}
        return None

# --- BOT LOGIC ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

async def get_user(tid, name, uname):
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(User).where(User.telegram_id == tid))
        user = res.scalar_one_or_none()
        if not user:
            user = User(telegram_id=tid, first_name=name, username=uname)
            session.add(user)
        else:
            user.last_activity = datetime.utcnow()
        await session.commit()
        return user

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = await get_user(message.from_user.id, message.from_user.first_name, message.from_user.username)
    
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(Setting).where(Setting.key == "welcome_message"))
        welcome = res.scalar_one().value
    
    await message.answer(f"👋 Hello {message.from_user.first_name}!\n\n{welcome}")

@dp.message(F.text.regexp(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'))
async def link_handler(message: types.Message):
    url = message.text
    status_msg = await message.answer("👀 Checking your link...")
    await bot.set_message_reaction(message.chat.id, message.message_id, reaction=[types.ReactionTypeEmoji(emoji="👀")])
    
    await asyncio.sleep(1)
    await status_msg.edit_text("⏳ Processing download...")
    
    result = None
    platform = "unknown"
    
    try:
        if "tiktok.com" in url:
            result = await MediaDownloader.get_tiktok(url)
            platform = "tiktok"
        elif "instagram.com" in url:
            result = await MediaDownloader.get_instagram(url)
            platform = "instagram"
        elif "facebook.com" in url or "fb.watch" in url:
            result = await MediaDownloader.get_facebook(url)
            platform = "facebook"
        elif "spotify.com" in url:
            result = await MediaDownloader.get_spotify(url)
            platform = "spotify"
        elif "terabox.com" in url or "1024tera" in url:
            result = await MediaDownloader.get_terabox(url)
            platform = "terabox"
        elif "pinterest.com" in url or "pin.it" in url:
            result = await MediaDownloader.get_pinterest(url)
            platform = "pinterest"
        
        if result:
            await status_msg.delete()
            
            # Record Download
            async with AsyncSessionLocal() as session:
                dl = Download(user_id=message.from_user.id, platform=platform, url=url, status="completed")
                session.add(dl)
                await session.execute(update(User).where(User.telegram_id == message.from_user.id).values(download_count=User.download_count + 1))
                await session.commit()

            # Handle Response based on Platform
            if platform == "tiktok":
                await message.answer_video(result['video'], caption=f"✅ **{result['title']}**\n👤 {result['author']}\n\n@AllSaverPro_bot", parse_mode="Markdown")
            elif platform == "instagram":
                for m in result['media']:
                    if m['type'] == 'video': await message.answer_video(m['url'])
                    else: await message.answer_photo(m['url'])
            elif platform == "facebook":
                await message.answer_video(result['video'], caption="✅ Facebook Video Downloaded\n\n@AllSaverPro_bot")
            elif platform == "pinterest":
                await message.answer_photo(result['image'], caption="✅ Pinterest Media Downloaded")
            elif platform == "spotify":
                caption = f"🎵 **{result['title']}**\n👤 {result['artist']}\n\n@AllSaverPro_bot"
                await message.answer_audio(result['preview'], caption=caption, parse_mode="Markdown")
            elif platform == "terabox":
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Download File", url=result['url'])]])
                await message.answer(f"📦 **{result['name']}**\n📏 Size: {result['size']}\n\nClick below to download:", reply_markup=kb, parse_mode="Markdown")
            
        else:
            await status_msg.edit_text("❌ Sorry, I couldn't extract media from this link. Try again or check the URL.")
            
    except Exception as e:
        logger.error(f"Download Error: {e}")
        await status_msg.edit_text("⚠️ An error occurred while processing your request.")

# --- WEB APP (FASTAPI) ---
app = FastAPI(title="All Saver Pro Admin")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Templates as Raw Strings (Single File Requirement)
BASE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>All Saver Pro | Admin</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        body { background: #0f172a; color: #f8fafc; font-family: 'Inter', sans-serif; }
        .glass { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.1); }
        .sidebar-link:hover { background: rgba(59, 130, 246, 0.1); color: #3b82f6; }
        .active-link { background: rgba(59, 130, 246, 0.2); color: #3b82f6; border-right: 4px solid #3b82f6; }
    </style>
</head>
<body class="flex min-h-screen">
    <!-- Sidebar -->
    <div class="w-64 glass border-r border-slate-800 flex flex-col">
        <div class="p-6 text-2xl font-bold bg-gradient-to-r from-blue-400 to-emerald-400 bg-clip-text text-transparent">
            All Saver Pro
        </div>
        <nav class="flex-1 px-4 space-y-2 mt-4">
            <a href="/admin/dashboard" class="sidebar-link flex items-center p-3 rounded-lg transition"><i class="fa fa-home w-8"></i> Dashboard</a>
            <a href="/admin/users" class="sidebar-link flex items-center p-3 rounded-lg transition"><i class="fa fa-users w-8"></i> Users</a>
            <a href="/admin/downloads" class="sidebar-link flex items-center p-3 rounded-lg transition"><i class="fa fa-download w-8"></i> Downloads</a>
            <a href="/admin/apis" class="sidebar-link flex items-center p-3 rounded-lg transition"><i class="fa fa-server w-8"></i> API Sources</a>
            <a href="/admin/promotions" class="sidebar-link flex items-center p-3 rounded-lg transition"><i class="fa fa-ad w-8"></i> Ads & Promo</a>
            <a href="/admin/settings" class="sidebar-link flex items-center p-3 rounded-lg transition"><i class="fa fa-cog w-8"></i> Settings</a>
        </nav>
        <div class="p-4 border-t border-slate-800">
            <a href="/admin/logout" class="flex items-center p-3 text-red-400 hover:bg-red-500/10 rounded-lg transition">
                <i class="fa fa-sign-out-alt w-8"></i> Logout
            </a>
        </div>
    </div>
    <!-- Main -->
    <main class="flex-1 p-8 overflow-y-auto">
        {% block content %}{% endblock %}
    </main>
</body>
</html>
"""

# Auth Helpers
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_admin(request: Request):
    token = request.cookies.get("access_token")
    if not token: return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        tid = payload.get("sub")
        if tid is None: return None
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(AdminUser).where(AdminUser.telegram_id == int(tid)))
            return res.scalar_one_or_none()
    except: return None

# Routes
@app.get("/health")
async def health():
    return {"status": "online", "bot": "running", "database": "connected"}

@app.get("/admin/login")
async def login_page():
    return HTMLResponse(content=f"""
    <html>
    <head><script src="https://cdn.tailwindcss.com"></script></head>
    <body class="bg-slate-900 flex items-center justify-center h-screen">
        <form action="/admin/login" method="post" class="bg-slate-800 p-8 rounded-xl shadow-2xl w-96 border border-slate-700">
            <h2 class="text-2xl text-white font-bold mb-6 text-center">Admin Login</h2>
            <input name="username" type="text" placeholder="Username" class="w-full p-3 mb-4 bg-slate-700 rounded text-white border border-slate-600 focus:outline-none focus:border-blue-500">
            <input name="password" type="password" placeholder="Password" class="w-full p-3 mb-6 bg-slate-700 rounded text-white border border-slate-600 focus:outline-none focus:border-blue-500">
            <button class="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-3 rounded transition">Sign In</button>
        </form>
    </body>
    </html>
    """)

@app.post("/admin/login")
async def login(response: Response, username: str = Form(...), password: str = Form(...)):
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(AdminUser).where(AdminUser.username == username))
        admin = res.scalar_one_or_none()
        if admin and pwd_context.verify(password, admin.password):
            token = create_access_token({"sub": str(admin.telegram_id)})
            response = RedirectResponse(url="/admin/dashboard", status_code=302)
            response.set_cookie(key="access_token", value=token, httponly=True)
            return response
    return RedirectResponse(url="/admin/login?error=invalid", status_code=302)

@app.get("/admin/logout")
async def logout(response: Response):
    response = RedirectResponse(url="/admin/login")
    response.delete_cookie("access_token")
    return response

@app.get("/admin/dashboard")
async def dashboard(request: Request):
    admin = await get_current_admin(request)
    if not admin: return RedirectResponse("/admin/login")
    
    async with AsyncSessionLocal() as session:
        total_users = await session.execute(select(func.count(User.id)))
        total_dl = await session.execute(select(func.count(Download.id)))
        active_24h = await session.execute(select(func.count(User.id)).where(User.last_activity >= datetime.utcnow() - timedelta(days=1)))
        
    stats = {
        "users": total_users.scalar(),
        "downloads": total_dl.scalar(),
        "active": active_24h.scalar()
    }
    
    # Return HTML via JINJA2 simulation
    from jinja2 import Template
    html = Template(BASE_HTML + """
    {% block content %}
    <h1 class="text-3xl font-bold mb-8">Dashboard Overview</h1>
    <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-10">
        <div class="glass p-6 rounded-2xl">
            <div class="text-slate-400 text-sm mb-1">Total Users</div>
            <div class="text-4xl font-bold text-blue-400">{{stats.users}}</div>
        </div>
        <div class="glass p-6 rounded-2xl">
            <div class="text-slate-400 text-sm mb-1">Total Downloads</div>
            <div class="text-4xl font-bold text-emerald-400">{{stats.downloads}}</div>
        </div>
        <div class="glass p-6 rounded-2xl">
            <div class="text-slate-400 text-sm mb-1">Active Users (24h)</div>
            <div class="text-4xl font-bold text-purple-400">{{stats.active}}</div>
        </div>
    </div>
    
    <div class="glass p-8 rounded-2xl h-96">
        <h3 class="text-xl font-bold mb-4">Download Growth</h3>
        <canvas id="growthChart"></canvas>
    </div>

    <script>
        const ctx = document.getElementById('growthChart').getContext('2d');
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
                datasets: [{
                    label: 'Downloads',
                    data: [12, 19, 3, 5, 2, 3, 7],
                    borderColor: '#3b82f6',
                    tension: 0.4,
                    fill: true,
                    backgroundColor: 'rgba(59, 130, 246, 0.1)'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: { y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.05)' } } }
            }
        });
    </script>
    {% endblock %}
    """).render(stats=stats)
    return HTMLResponse(html)

@app.get("/admin/users")
async def admin_users(request: Request):
    admin = await get_current_admin(request)
    if not admin: return RedirectResponse("/admin/login")
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(User).order_by(User.join_date.desc()).limit(100))
        users = res.scalars().all()
    
    from jinja2 import Template
    html = Template(BASE_HTML + """
    {% block content %}
    <h1 class="text-3xl font-bold mb-8">Manage Users</h1>
    <div class="glass rounded-2xl overflow-hidden">
        <table class="w-full text-left">
            <thead class="bg-slate-800/50">
                <tr>
                    <th class="p-4">User</th>
                    <th class="p-4">ID</th>
                    <th class="p-4">Downloads</th>
                    <th class="p-4">Joined</th>
                    <th class="p-4">Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for user in users %}
                <tr class="border-t border-slate-800 hover:bg-slate-800/30">
                    <td class="p-4">
                        <div class="font-bold">{{user.first_name}}</div>
                        <div class="text-sm text-slate-500">@{{user.username}}</div>
                    </td>
                    <td class="p-4 text-slate-400">{{user.telegram_id}}</td>
                    <td class="p-4">{{user.download_count}}</td>
                    <td class="p-4 text-sm text-slate-500">{{user.join_date.strftime('%Y-%m-%d')}}</td>
                    <td class="p-4">
                        <button class="text-red-400 hover:underline">Ban</button>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% endblock %}
    """).render(users=users)
    return HTMLResponse(html)

# --- EXECUTION MANAGER ---
async def start_bot():
    await init_db()
    logger.info("Bot is starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "bot":
        # Run Bot Worker
        asyncio.run(start_bot())
    else:
        # Run Web Server (Render Web Service)
        port = int(os.environ.get("PORT", 10000))
        uvicorn.run("app:app", host="0.0.0.0", port=port)
