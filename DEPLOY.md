# 部署指南

## 方案 A：前端 CF Pages + 后端 Railway（推荐，省钱）

### 1️⃣ 后端部署到 Railway

1. 注册 [Railway.app](https://railway.app)（GitHub 登录即可）
2. 点击 `New Project` → `Deploy from GitHub repo` → 选择你的仓库
3. Railway 自动检测 `Dockerfile` 并构建
4. 部署成功后，Railway 会给你一个地址，如：
   ```
   https://blind-watermark-web-production-xxxx.up.railway.app
   ```
5. 记下这个地址

### 2️⃣ 前端部署到 Cloudflare Pages

1. 注册 [Cloudflare](https://dash.cloudflare.com)
2. Workers & Pages → Create → Pages → Connect to Git
3. 选择你的 GitHub 仓库
4. 构建设置：
   - **Build command**: 留空（纯静态，无需构建）
   - **Build output directory**: `frontend`
5. 部署后得到地址，如 `https://blind-watermark.pages.dev`

### 3️⃣ 连接前后端

在前端仓库中修改 `frontend/js/config.js`：

```javascript
// 改为 Railway 后端地址
window.__API_URL__ = 'https://blind-watermark-web-production-xxxx.up.railway.app';
```

提交推送，CF Pages 自动重新部署。

✅ 完成！前端全球 CDN，后端 Railway 自动扩缩容。

---

## 方案 B：全栈 Docker 一把梭

### VPS 部署

```bash
git clone https://github.com/your-repo/blind-watermark-web.git
cd blind-watermark-web
docker compose up -d
```

访问 `http://your-ip:8000`

### Railway 全栈

直接用 Dockerfile 部署，前端后端一起打包。

---

## 方案 C：Telegram Bot 部署

Bot 可以和后端一起部署，也可以单独部署。

### 环境变量

```bash
TELEGRAM_BOT_TOKEN=your_bot_token_here
```

### Docker 部署

```bash
docker build -f Dockerfile.bot -t blind-watermark-bot .
docker run -d -e TELEGRAM_BOT_TOKEN=xxx blind-watermark-bot
```

### Railway 部署

创建单独的 Railway 服务，用 `Dockerfile.bot` 构建。

---

## 注意事项

- Railway 免费额度 $5/月，个人使用足够
- CF Pages 完全免费（带宽无限）
- 后端 CORS 已配置为 `allow_origins=["*"]`，分离部署无跨域问题
- `config.js` 中 `window.__API_URL__ = ''` 时，自动使用当前域名（全栈模式）