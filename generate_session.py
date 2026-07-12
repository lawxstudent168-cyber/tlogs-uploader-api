from telethon.sync import TelegramClient
from telethon.sessions import StringSession

# ==========================================
# ⚠️ 請在這裡填入您的 Telegram API 資訊
# ==========================================
API_ID = 20614967  # 請換成您的 API ID (數字，不需要引號)
API_HASH = "b5b7152936c09de5e26513d1cae73fd2"  # 請換成您的 API HASH (字串，需要引號)

print("🚀 啟動 Telegram 登入程序...")
print("（第一次執行時，系統會要求您輸入手機號碼與 Telegram 收到的驗證碼）\n")

# 使用空白的 StringSession 來啟動客戶端
with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    print("\n✅ 登入成功！")
    print("👇 這是您的全新 SESSION_STRING，請將下面這整串亂碼複製起來：\n")
    
    # 產生存檔並印出
    session_string = client.session.save()
    print(session_string)
    
    print("\n⚠️ 安全警告：這串文字就等於您 Telegram 帳號的「免死金牌 (最高權限密碼)」，請絕對不要外洩給任何人！")