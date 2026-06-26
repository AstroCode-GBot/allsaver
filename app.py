# app.py
# All Saver Pro
# Single File Version
# FastAPI + Aiogram 3 + PostgreSQL
# Redis Removed

import os
import asyncio
import logging
from datetime import datetime, timedelta

import httpx
import jwt

from dotenv import load_dotenv

from fastapi import (
    FastAPI,
    Request,
    Depends,
    Form,
    HTTPException
)

from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    JSONResponse
)

from fastapi.middleware.cors import CORSMiddleware


from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    Text,
    DateTime,
    ForeignKey,
    select,
    func
)

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker
)

from sqlalchemy.orm import declarative_base


from passlib.context import CryptContext


from aiogram import (
    Bot,
    Dispatcher,
    types
)

from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties


# ============================
# CONFIG
# ============================

load_dotenv()


BOT_TOKEN = os.getenv("BOT_TOKEN")





ADMIN_ID = int(

    os.getenv(

        "ADMIN_ID",

        "6434652846"

    )

)





SECRET_KEY = os.getenv("SECRET_KEY")





DATABASE_URL = os.getenv(

    "DATABASE_URL",

    "postgresql+asyncpg://neondb_owner:npg_DFY1rh8nPxQA@ep-lucky-mode-aoxoorn5.c-2.ap-southeast-1.aws.neon.tech/neondb"

)



logging.basicConfig(
    level=logging.INFO
)


logger=logging.getLogger(
    "ALL_SAVER_PRO"
)



# ============================
# DATABASE
# ============================


Base=declarative_base()


engine=create_async_engine(
    DATABASE_URL,
    echo=False
)


SessionLocal=async_sessionmaker(
    engine,
    expire_on_commit=False
)



async def get_db():

    async with SessionLocal() as session:

        yield session




# ============================
# MODELS
# ============================


class User(Base):

    __tablename__="users"


    id=Column(
        Integer,
        primary_key=True
    )


    telegram_id=Column(
        String,
        unique=True
    )


    username=Column(
        String,
        nullable=True
    )


    first_name=Column(
        String,
        nullable=True
    )


    last_name=Column(
        String,
        nullable=True
    )


    photo=Column(
        Text,
        nullable=True
    )


    download_count=Column(
        Integer,
        default=0
    )


    is_banned=Column(
        Boolean,
        default=False
    )


    join_date=Column(
        DateTime,
        default=datetime.utcnow
    )


    last_activity=Column(
        DateTime,
        default=datetime.utcnow
    )




class Download(Base):

    __tablename__="downloads"


    id=Column(
        Integer,
        primary_key=True
    )


    user_id=Column(
        Integer
    )


    platform=Column(
        String
    )


    url=Column(
        Text
    )


    filename=Column(
        String,
        nullable=True
    )


    size=Column(
        String,
        nullable=True
    )


    status=Column(
        String,
        default="pending"
    )


    created_at=Column(
        DateTime,
        default=datetime.utcnow
    )




class APIModel(Base):

    __tablename__="apis"


    id=Column(
        Integer,
        primary_key=True
    )


    name=Column(
        String
    )


    platform=Column(
        String
    )


    endpoint=Column(
        Text
    )


    priority=Column(
        Integer,
        default=1
    )


    status=Column(
        Boolean,
        default=True
    )




class Promotion(Base):

    __tablename__="promotions"


    id=Column(
        Integer,
        primary_key=True
    )


    title=Column(
        String,
        nullable=True
    )


    sponsor_username=Column(
        String,
        nullable=True
    )


    image_file_id=Column(
        Text,
        nullable=True
    )


    description=Column(
        Text,
        nullable=True
    )


    message=Column(
        Text,
        nullable=True
    )


    button_text=Column(
        String,
        nullable=True
    )


    button_url=Column(
        Text,
        nullable=True
    )


    status=Column(
        Boolean,
        default=True
    )



# ============================
# FASTAPI
# ============================


app=FastAPI(
    title="All Saver Pro"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)




# ============================
# TELEGRAM BOT
# ============================


bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)


dp=Dispatcher()




# ============================
# INIT DB
# ============================


async def init_database():

    async with engine.begin() as conn:

        await conn.run_sync(
            Base.metadata.create_all
        )




# ============================
# PLATFORM DETECTOR
# ============================


def detect_platform(url):

    url=url.lower()


    if "tiktok" in url:
        return "TikTok"

    if "instagram" in url:
        return "Instagram"

    if "facebook" in url or "fb.watch" in url:
        return "Facebook"

    if "pinterest" in url:
        return "Pinterest"

    if "spotify" in url:
        return "Spotify"

    if "terabox" in url:
        return "Terabox"


    return None




# ============================
# DOWNLOADER ENGINE
# ============================


class Downloader:


    async def call(self,url):

        try:

            async with httpx.AsyncClient(
                timeout=30
            ) as client:

                response=await client.get(
                    url
                )

                return response.json()


        except Exception as e:

            return {
                "error":True,
                "message":str(e)
            }



    async def download(
        self,
        platform,
        link
    ):


        if platform=="TikTok":

            return await self.call(
                "https://www.tikwm.com/api/?url="+link
            )


        elif platform=="Instagram":

            return await self.call(
                "https://igram.site/api/instagram?url="+link
            )


        elif platform=="Facebook":

            return await self.call(
                "https://serverless-tooly-gateway-6n4h522y.ue.gateway.dev/facebook/video?url="+link
            )


        elif platform=="Pinterest":

            return await self.call(
                "https://api.pinssaver.com/pin?url="+link
            )


        elif platform=="Spotify":

            return await self.call(
                "https://spotyloader.com/api/spotify/info?url="+link
            )


        elif platform=="Terabox":

            return await self.call(
                "https://teradown-dzv3.onrender.com/api?url="+link
            )


        return {
            "error":True
        }



downloader=Downloader()
