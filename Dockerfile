# 使用官方 Python 3.9 映像檔
FROM python:3.9

# 設定工作目錄
WORKDIR /app

# 將 requirements.txt 複製到容器內並安裝依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 將專案的所有檔案複製到容器內
COPY . .

# 🌟 核心修改：移除寫死的 7860，改用 Render 動態分配的 $PORT (預設 10000)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}"]