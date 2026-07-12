import os
import hashlib
import urllib.parse
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from telethon import TelegramClient
from telethon.sessions import StringSession

app = FastAPI()

# 設定 CORS，允許您的 Vercel 前端呼叫這個 API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 從環境變數讀取機密資訊 (Hugging Face Secrets)
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")
TARGET_GROUP_ID = int(os.environ.get("TARGET_GROUP_ID", 0))

# 初始化 Telegram Client
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@app.on_event("startup")
async def startup_event():
    # 伺服器啟動時，自動連線到 Telegram
    await client.connect()

@app.get("/")
def read_root():
    return {"status": "Telegram Uploader API (Evidence Edition) is running on Hugging Face!"}

# ==========================================
# ⬆️ 錄音證據上傳端點 (保留 Hash 計算與存檔邏輯)
# ==========================================
@app.post("/upload/")
async def upload_recording(
    file: UploadFile = File(...), 
    topic_id: int = Form(...) # 接收前端傳來的主題(月份) ID
):
    if not client.is_connected():
        await client.connect()

    temp_file_path = f"/tmp/{file.filename}"
    
    try:
        # 將大檔案分塊寫入暫存檔，同時間計算 SHA256 防偽指紋
        sha256_hash = hashlib.sha256()
        with open(temp_file_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                buffer.write(chunk)
                sha256_hash.update(chunk) 
        
        file_hash = sha256_hash.hexdigest()

        # 透過 Telethon 上傳到指定的 Telegram Topic
        message = await client.send_file(
            TARGET_GROUP_ID,
            file=temp_file_path,
            reply_to=topic_id,
            caption=f"📂 錄音檔：{file.filename}\n⚖️ SHA256 指紋：`{file_hash}`\n🕒 上傳時間：備份系統自動上傳",
            force_document=True # 強制以檔案傳送，保證音質不被壓縮
        )

        chat_id_str = str(TARGET_GROUP_ID).replace("-100", "")
        tg_link = f"https://t.me/c/{chat_id_str}/{message.id}"

        return {
            "success": True,
            "filename": file.filename,
            "telegram_link": tg_link,
            "file_hash": file_hash,
            "message_id": message.id # 🌟 新增回傳 Message ID，方便前端組裝下載連結
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

# ==========================================
# ⬇️ 新增：錄音證據串流下載端點
# ==========================================
@app.get("/download/{message_id}")
async def download_file(message_id: int):
    if not client.is_connected():
        await client.connect()

    message = await client.get_messages(TARGET_GROUP_ID, ids=message_id)
    if not message or not message.file:
        raise HTTPException(status_code=404, detail="找不到該檔案")

    async def file_streamer():
        async for chunk in client.iter_download(message.media, chunk_size=1024 * 1024):
            # 🌟 加上 bytes() 轉型，解決 FastAPI 報錯
            yield bytes(chunk)

    # 🌟 將中文檔名進行 URL 安全編碼，避免伺服器防火牆切斷連線
    file_name = message.file.name or "audio_evidence"
    encoded_filename = urllib.parse.quote(file_name)

    headers = {
        "Content-Disposition": f"attachment; filename*=utf-8''{encoded_filename}"
    }
    
    return StreamingResponse(
        file_streamer(), 
        media_type="application/octet-stream", 
        headers=headers
    )