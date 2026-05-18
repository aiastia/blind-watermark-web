FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（libgl1-mesa-glx 在新版 Debian 中已更名为 libgl1）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码
COPY backend/app.py ./app.py

# 复制前端文件
COPY frontend/ ./static/

# 创建临时目录
RUN mkdir -p /app/temp

# 修改 app.py 中的静态文件路径
ENV STATIC_DIR=/app/static

EXPOSE 8000

# Railway 用 PORT 环境变量，本地默认 8000
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}
