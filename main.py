import os
import uuid
import shutil
from fastapi import FastAPI, File, UploadFile, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

# 🌟 改用 Telethon 核心
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "").strip()
TARGET_GROUP_ID = int(os.environ.get("TARGET_GROUP_ID", 0))

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 初始化 Telethon 客戶端 (吃您的原本 Session)
# ==========================================
tg_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@app.on_event("startup")
async def startup_event():
    await tg_client.connect()
    # 檢查 session 是否有效
    if not await tg_client.is_user_authorized():
        print("🛑 警告：Telegram Session 無效或已過期")
    else:
        print("✅ Telegram 客戶端已連線 (Telethon)")

@app.on_event("shutdown")
async def shutdown_event():
    await tg_client.disconnect()
    print("🛑 Telegram 客戶端已離線")

upload_tasks = {}

# ==========================================
# Telethon 背景上傳邏輯
# ==========================================
async def process_and_upload_to_tg(task_id: str, file_path: str, filename: str):
    upload_tasks[task_id]["status"] = "processing"
    try:
        # 使用 Telethon 發送檔案
        message = await tg_client.send_file(
            TARGET_GROUP_ID,
            file_path,
            caption=filename
        )
        
        # 組合 Telegram 跳轉連結
        chat_id_str = str(TARGET_GROUP_ID).replace("-100", "")
        tg_link = f"https://t.me/c/{chat_id_str}/{message.id}"
        
        upload_tasks[task_id]["telegram_link"] = tg_link
        upload_tasks[task_id]["message_id"] = message.id
        upload_tasks[task_id]["status"] = "completed"
        
    except Exception as e:
        print(f"[{task_id}] 上傳 Telegram 失敗: {e}")
        upload_tasks[task_id]["status"] = "failed"
        
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

@app.get("/")
async def root():
    return {"status": "ok", "message": "API 伺服器運作中"}

@app.post("/upload/")
async def upload_file(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    task_id = str(uuid.uuid4())
    upload_tasks[task_id] = {
        "status": "pending",
        "telegram_link": None,
        "message_id": None
    }
    
    temp_file_path = f"/tmp/{task_id}_{file.filename}"
    with open(temp_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    background_tasks.add_task(process_and_upload_to_tg, task_id, temp_file_path, file.filename)
    return {"success": True, "task_id": task_id}

@app.get("/status/{task_id}")
async def get_status(task_id: str):
    task = upload_tasks.get(task_id)
    if not task:
        return {"status": "not_found"}
    return task

# ==========================================
# Telethon 串流下載邏輯
# ==========================================
@app.get("/download/{message_id}")
async def stream_download(message_id: int):
    try:
        # Telethon 抓取單一訊息
        message = await tg_client.get_messages(TARGET_GROUP_ID, ids=message_id)
        
        if not message or not message.media:
            raise HTTPException(status_code=404, detail="找不到附加檔案")

        # 嘗試解析原始檔名
        file_name = "downloaded_evidence"
        if hasattr(message.media, 'document'):
            for attr in message.media.document.attributes:
                if hasattr(attr, 'file_name'):
                    file_name = attr.file_name
                    break

        async def file_streamer():
            # Telethon 的分塊下載產生器
            async for chunk in tg_client.iter_download(message.media):
                yield chunk

        return StreamingResponse(
            file_streamer(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{file_name}"'
            }
        )
        
    except Exception as e:
        print(f"串流下載失敗: {e}")
        raise HTTPException(status_code=500, detail="無法取得串流資源")
