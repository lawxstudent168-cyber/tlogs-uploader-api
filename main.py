import hashlib
import os
import tempfile
import urllib.parse

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import DocumentAttributeFilename, InputMessagesFilterDocument


API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "").strip()
SESSION_STRING = os.environ.get("SESSION_STRING", "").strip()
TARGET_GROUP_ID = int(os.environ.get("TARGET_GROUP_ID", "0"))

app = FastAPI(title="SHJHS Telegram Evidence API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = (
    TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    if API_ID and API_HASH and SESSION_STRING
    else None
)


async def ensure_connected() -> None:
    if client is None or not TARGET_GROUP_ID:
        raise HTTPException(status_code=503, detail="Telegram 環境變數尚未完整設定")
    if not client.is_connected():
        await client.connect()
    if not await client.is_user_authorized():
        raise HTTPException(status_code=503, detail="Telegram Session 無效或已過期")


@app.on_event("startup")
async def startup_event() -> None:
    try:
        await ensure_connected()
        print("Telegram client connected")
    except HTTPException as exc:
        print(f"Telegram client unavailable: {exc.detail}")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if client is not None and client.is_connected():
        await client.disconnect()


@app.get("/")
async def read_root():
    return {"status": "ok", "service": "SHJHS Telegram Evidence API"}


@app.get("/health")
async def health():
    await ensure_connected()
    return {"status": "healthy", "telegram_connected": True}


@app.post("/upload/")
async def upload_recording(
    file: UploadFile = File(...),
    topic_id: int = Form(...),
    caption: str | None = Form(None),
):
    await ensure_connected()

    original_name = file.filename or "recording"
    suffix = os.path.splitext(original_name)[1]
    temp_path = ""

    try:
        sha256_hash = hashlib.sha256()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as buffer:
            temp_path = buffer.name
            while chunk := await file.read(1024 * 1024):
                buffer.write(chunk)
                sha256_hash.update(chunk)

        message = await client.send_file(
            TARGET_GROUP_ID,
            file=temp_path,
            reply_to=topic_id,
            caption=caption or f"📂 證據檔案：{original_name}",
            force_document=True,
            attributes=[DocumentAttributeFilename(original_name)],
        )

        chat_id = str(TARGET_GROUP_ID).removeprefix("-100")
        return {
            "success": True,
            "filename": original_name,
            "telegram_link": f"https://t.me/c/{chat_id}/{message.id}",
            "file_hash": sha256_hash.hexdigest(),
            "message_id": message.id,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        await file.close()
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


@app.get("/search")
async def search_group_files(query: str = "", limit: int = 20):
    await ensure_connected()
    safe_limit = min(max(limit, 1), 100)

    try:
        results = []
        async for message in client.iter_messages(
            TARGET_GROUP_ID,
            search=query,
            filter=InputMessagesFilterDocument,
            limit=safe_limit,
        ):
            if not message.document:
                continue

            filename = "未知檔案"
            for attribute in message.document.attributes:
                if isinstance(attribute, DocumentAttributeFilename):
                    filename = attribute.file_name
                    break

            results.append(
                {
                    "id": message.id,
                    "filename": filename,
                    "size_mb": round(message.document.size / (1024 * 1024), 2),
                    "caption": message.text or "",
                    "date": message.date.strftime("%Y/%m/%d %H:%M"),
                }
            )

        return {"success": True, "data": results}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/download/{message_id}")
async def download_file(message_id: int):
    await ensure_connected()
    message = await client.get_messages(TARGET_GROUP_ID, ids=message_id)
    if not message or not message.file:
        raise HTTPException(status_code=404, detail="找不到該檔案")

    async def file_streamer():
        async for chunk in client.iter_download(message.media, chunk_size=1024 * 1024):
            yield bytes(chunk)

    filename = message.file.name or "telegram_evidence"
    encoded_filename = urllib.parse.quote(filename)
    return StreamingResponse(
        file_streamer(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{encoded_filename}"},
    )
