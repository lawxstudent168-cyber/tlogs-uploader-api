import os
import uuid
import shutil
from fastapi import FastAPI, File, UploadFile, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pyrogram import Client

# ==========================================
# 1. 讀取環境變數 (Render 的 Environment Variables)
# ==========================================
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
# 找到原本的這行：
# SESSION_STRING = os.environ.get("SESSION_STRING", "")

# 🌟 加上 .strip() 改成這樣：
SESSION_STRING = os.environ.get("SESSION_STRING", "").strip()
TARGET_GROUP_ID = int(os.environ.get("TARGET_GROUP_ID", 0))

# ==========================================
# 2. 初始化 FastAPI 與設定 CORS
# ==========================================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 3. 初始化 Pyrogram (Telegram 客戶端)
# ==========================================
tg_client = Client(
    "render_session",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

# 在 FastAPI 啟動與關閉時，連動啟動/關閉 Telegram 客戶端
@app.on_event("startup")
async def startup_event():
    await tg_client.start()
    print("✅ Telegram 客戶端已連線")

@app.on_event("shutdown")
async def shutdown_event():
    await tg_client.stop()
    print("🛑 Telegram 客戶端已離線")

# ==========================================
# 4. 狀態暫存區 (記憶體字典)
# ==========================================
upload_tasks = {}

# ==========================================
# 5. 背景上傳邏輯
# ==========================================
async def process_and_upload_to_tg(task_id: str, file_path: str, filename: str):
    """
    這是在背景執行的任務，不會卡住前端的 100 秒連線限制。
    """
    upload_tasks[task_id]["status"] = "processing"
    
    try:
        # 將檔案傳送至指定的 Telegram 群組/頻道
        message = await tg_client.send_document(
            chat_id=TARGET_GROUP_ID,
            document=file_path,
            file_name=filename
        )
        
        # 組合 Telegram 的跳轉連結 (支援私人頻道的 -100 格式轉換)
        chat_id_str = str(TARGET_GROUP_ID).replace("-100", "")
        tg_link = f"https://t.me/c/{chat_id_str}/{message.id}"
        
        # 更新任務狀態為成功，並附上回傳資料
        upload_tasks[task_id]["telegram_link"] = tg_link
        upload_tasks[task_id]["message_id"] = message.id
        upload_tasks[task_id]["status"] = "completed"
        
    except Exception as e:
        print(f"[{task_id}] 上傳 Telegram 失敗: {e}")
        upload_tasks[task_id]["status"] = "failed"
        
    finally:
        # 🌟 核心清理：無論成功或失敗，務必刪除 /tmp 下的暫存檔，避免 Render 硬碟被塞爆
        if os.path.exists(file_path):
            os.remove(file_path)

# ==========================================
# 6. API 端點 (Routes)
# ==========================================

@app.get("/")
async def root():
    return {"status": "ok", "message": "API 伺服器運作中"}

@app.post("/upload/")
async def upload_file(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """
    接收前端檔案，寫入暫存區後立刻回傳 task_id，並將上傳任務丟到背景。
    """
    task_id = str(uuid.uuid4())
    upload_tasks[task_id] = {
        "status": "pending",
        "telegram_link": None,
        "message_id": None
    }
    
    # 🌟 核心防護：將檔案一邊接收一邊寫入 /tmp，而不是全部讀進記憶體，避免 180MB 檔案撐爆 512MB RAM
    temp_file_path = f"/tmp/{task_id}_{file.filename}"
    with open(temp_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # 加入背景任務佇列
    background_tasks.add_task(process_and_upload_to_tg, task_id, temp_file_path, file.filename)
    
    # 立即切斷與前端的連線，回傳 task_id 供後續輪詢
    return {"success": True, "task_id": task_id}


@app.get("/status/{task_id}")
async def get_status(task_id: str):
    """
    供前端輪詢上傳進度的端點。
    """
    task = upload_tasks.get(task_id)
    if not task:
        return {"status": "not_found"}
    return task


@app.get("/download/{message_id}")
async def stream_download(message_id: int):
    """
    透過 message_id，直接從 Telegram 串流取得原始檔案 (供前端綠色按鈕使用)。
    """
    try:
        # 先抓取該則訊息
        message = await tg_client.get_messages(TARGET_GROUP_ID, message_id)
        
        # 檢查該訊息是否包含可下載的媒體
        if not message.document and not message.audio and not message.video:
            raise HTTPException(status_code=404, detail="找不到附加檔案")

        # 取得真實檔名
        file_name = "downloaded_evidence"
        if message.document:
            file_name = message.document.file_name
        elif message.audio:
            file_name = message.audio.file_name or "audio.mp3"
        elif message.video:
            file_name = message.video.file_name or "video.mp4"

        # 建立位元組串流生成器
        async def file_streamer():
            async for chunk in tg_client.stream_media(message):
                yield chunk

        # 回傳 StreamingResponse，讓瀏覽器可以直接開始下載或播放
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
