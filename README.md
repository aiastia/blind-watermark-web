# 🔐 盲水印工具 - Blind Watermark

基于 [blind_watermark](https://github.com/guofei9987/blind_watermark) (DWT-DCT-SVD) 的图片盲水印 Web 版和 Telegram Bot。

水印**不可见**，图片看起来和原图完全一样，但包含了隐藏信息。即使图片被裁剪、旋转、压缩，水印仍然可以提取。

## ✨ 功能

- 🌐 **Web 页面**: 现代化 UI，拖拽上传，一键嵌入/提取水印
- 🤖 **Telegram Bot**: 在 TG 中直接使用，发送图片即可操作
- 📝 **文字水印**: 嵌入任意文字信息
- 🖼️ **图片水印**: 嵌入图片作为水印（API 支持）
- 🔒 **双密码保护**: 图片密码 + 水印密码
- 🐳 **Docker 部署**: 一键启动

## 📁 项目结构

```
├── backend/
│   ├── app.py              # FastAPI 后端服务
│   └── requirements.txt    # Python 依赖
├── bot/
│   └── tg_bot.py           # Telegram Bot
├── frontend/
│   └── index.html          # Web 前端（Vue 3）
├── docker-compose.yml      # Docker Compose 配置
├── Dockerfile              # Web 服务 Dockerfile
├── Dockerfile.bot          # Bot Dockerfile
└── .env.example            # 环境变量示例
```

## 🚀 快速开始

### 方式一：本地运行

```bash
# 1. 安装依赖
cd backend
pip install -r requirements.txt

# 2. 启动 Web 服务
cd ..
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload

# 3. 打开浏览器
open http://localhost:8000
```

### 方式二：启动 Telegram Bot

```bash
# 1. 设置 Bot Token（从 @BotFather 获取）
export TELEGRAM_BOT_TOKEN="your_bot_token_here"

# 2. 启动 Bot
cd bot
python tg_bot.py
```

### 方式三：Docker 部署

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的 Telegram Bot Token（可选）

# 2. 构建并启动
docker-compose up -d

# 3. 访问
open http://localhost:8000
```

## 📖 使用方法

### Web 页面

**嵌入水印：**
1. 上传原始图片
2. 输入要隐藏的水印文字
3. 设置密码（默认为 1）
4. 点击「嵌入水印」
5. 下载带水印的图片
6. **保存好返回的「水印长度」和密码**

**提取水印：**
1. 上传带水印的图片
2. 输入嵌入时返回的「水印长度」
3. 输入嵌入时使用的密码
4. 点击「提取水印」
5. 查看提取的水印文字

### Telegram Bot

1. 发送 `/start` 开始
2. 选择「嵌入水印」或「提取水印」
3. 按提示发送图片和输入信息

## 🔧 API 接口

### 嵌入文字水印

```bash
curl -X POST http://localhost:8000/api/embed \
  -F "image=@original.jpg" \
  -F "watermark_text=Hello 盲水印" \
  -F "password_img=1" \
  -F "password_wm=1" \
  --output watermarked.png
```

返回的 Header 中包含 `X-WM-Length`，提取时需要。

### 提取文字水印

```bash
curl -X POST http://localhost:8000/api/extract \
  -F "image=@watermarked.png" \
  -F "wm_length=xxx" \
  -F "password_img=1" \
  -F "password_wm=1"
```

### 嵌入图片水印

```bash
curl -X POST http://localhost:8000/api/embed_image \
  -F "image=@original.jpg" \
  -F "watermark_image=@watermark.png" \
  -F "password_img=1" \
  -F "password_wm=1" \
  --output watermarked.png
```

## ⚠️ 注意事项

- 请务必保存好**水印长度**和**密码**，丢失后无法提取水印
- 建议水印文字不超过 100 字，过长可能导致鲁棒性下降
- 图片大小限制 20MB
- 临时文件会在 1 小时后自动清理

## 📄 开源协议

MIT License

基于 [blind_watermark](https://github.com/guofei9987/blind_watermark) by [@guofei9987](https://github.com/guofei9987)