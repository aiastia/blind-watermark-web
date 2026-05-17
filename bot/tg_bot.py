"""
Blind Watermark Telegram Bot
支持在 Telegram 中嵌入和提取图片盲水印
"""
import os
import io
import sys
import uuid
import logging
from pathlib import Path

from PIL import Image
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# 添加后端目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from blind_watermark import WaterMark

# 日志
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# 临时目录
TEMP_DIR = Path("./temp_bot")
TEMP_DIR.mkdir(exist_ok=True)

# 对话状态
(
    STATE_MENU,
    STATE_EMBED_WAIT_IMAGE,
    STATE_EMBED_WAIT_TEXT,
    STATE_EMBED_WAIT_PASSWORD,
    STATE_EXTRACT_WAIT_IMAGE,
    STATE_EXTRACT_WAIT_WMLEN,
    STATE_EXTRACT_WAIT_PASSWORD,
) = range(7)

# 用户会话数据
user_sessions = {}


def get_keyboard():
    """主菜单键盘"""
    return ReplyKeyboardMarkup(
        [["🔐 嵌入水印", "🔍 提取水印"]],
        resize_keyboard=True,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始命令"""
    await update.message.reply_text(
        "👋 *盲水印 Bot*\n\n"
        "我可以帮你在图片中嵌入看不见的水印，或者从图片中提取隐藏的水印。\n\n"
        "水印是*不可见*的，图片看起来和原图完全一样，"
        "但包含了隐藏信息。即使图片被裁剪、旋转、压缩，"
        "水印仍然可以提取出来。\n\n"
        "请选择操作：",
        reply_markup=get_keyboard(),
        parse_mode="Markdown",
    )
    return STATE_MENU


async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理菜单选择"""
    text = update.message.text

    if text == "🔐 嵌入水印":
        await update.message.reply_text(
            "📷 请发送要嵌入水印的图片：",
            reply_markup=ReplyKeyboardRemove(),
        )
        return STATE_EMBED_WAIT_IMAGE

    elif text == "🔍 提取水印":
        await update.message.reply_text(
            "📷 请发送要提取水印的图片：",
            reply_markup=ReplyKeyboardRemove(),
        )
        return STATE_EXTRACT_WAIT_IMAGE

    return STATE_MENU


async def embed_receive_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收嵌入水印的图片"""
    user_id = update.effective_user.id

    if not update.message.photo:
        await update.message.reply_text("请发送一张图片。")
        return STATE_EMBED_WAIT_IMAGE

    # 下载最高质量的图片
    photo = update.message.photo[-1]
    file = await photo.get_file()

    task_id = uuid.uuid4().hex[:12]
    img_path = TEMP_DIR / f"tg_ori_{user_id}_{task_id}.jpg"
    await file.download_to_drive(str(img_path))

    user_sessions[user_id] = {
        "action": "embed",
        "ori_path": str(img_path),
        "task_id": task_id,
    }

    await update.message.reply_text("✅ 图片已收到！\n\n📝 请输入要嵌入的水印文字：")
    return STATE_EMBED_WAIT_TEXT


async def embed_receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收水印文字"""
    user_id = update.effective_user.id
    session = user_sessions.get(user_id, {})

    if not session:
        await update.message.reply_text("会话过期，请重新开始 /start")
        return ConversationHandler.END

    session["watermark_text"] = update.message.text
    user_sessions[user_id] = session

    await update.message.reply_text(
        "🔑 请输入密码（数字），直接发送数字即可。\n"
        "默认密码为 1，直接发送 1 即可："
    )
    return STATE_EMBED_WAIT_PASSWORD


async def embed_receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收密码并执行嵌入"""
    user_id = update.effective_user.id
    session = user_sessions.pop(user_id, {})

    if not session:
        await update.message.reply_text("会话过期，请重新开始 /start")
        return ConversationHandler.END

    try:
        password = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("密码必须是数字，请重新开始 /start")
        return ConversationHandler.END

    ori_path = session["ori_path"]
    wm_text = session["watermark_text"]
    task_id = session["task_id"]
    out_path = TEMP_DIR / f"tg_embed_{user_id}_{task_id}.png"

    try:
        await update.message.reply_text("⏳ 正在嵌入水印，请稍候...")

        bwm = WaterMark(password_img=password, password_wm=password)
        bwm.read_img(ori_path)
        bwm.read_wm(wm_text, mode="str")
        bwm.embed(str(out_path))

        wm_len = len(bwm.wm_bit)

        with open(str(out_path), "rb") as f:
            await update.message.reply_photo(
                photo=f,
                caption=(
                    f"✅ 水印嵌入成功！\n\n"
                    f"📝 水印文字: `{wm_text}`\n"
                    f"🔑 密码: `{password}`\n"
                    f"📏 水印长度: `{wm_len}`\n\n"
                    f"⚠️ 请保存以下信息，提取水印时需要：\n"
                    f"• 水印长度: `{wm_len}`\n"
                    f"• 密码: `{password}`"
                ),
                parse_mode="Markdown",
            )

        logger.info(f"TG嵌入成功: user={user_id}, task={task_id}, wm_len={wm_len}")

    except Exception as e:
        logger.error(f"TG嵌入失败: {str(e)}")
        await update.message.reply_text(f"❌ 嵌入失败: {str(e)}")

    finally:
        Path(ori_path).unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)

    return ConversationHandler.END


async def extract_receive_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收提取水印的图片"""
    user_id = update.effective_user.id

    if not update.message.photo:
        await update.message.reply_text("请发送一张图片。")
        return STATE_EXTRACT_WAIT_IMAGE

    photo = update.message.photo[-1]
    file = await photo.get_file()

    task_id = uuid.uuid4().hex[:12]
    img_path = TEMP_DIR / f"tg_extract_{user_id}_{task_id}.jpg"
    await file.download_to_drive(str(img_path))

    user_sessions[user_id] = {
        "action": "extract",
        "img_path": str(img_path),
        "task_id": task_id,
    }

    await update.message.reply_text(
        "📏 请输入水印长度（嵌入时返回的数字）："
    )
    return STATE_EXTRACT_WAIT_WMLEN


async def extract_receive_wmlen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收水印长度"""
    user_id = update.effective_user.id

    try:
        wm_len = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("水印长度必须是数字，请重新输入：")
        return STATE_EXTRACT_WAIT_WMLEN

    session = user_sessions.get(user_id, {})
    session["wm_length"] = wm_len
    user_sessions[user_id] = session

    await update.message.reply_text(
        "🔑 请输入密码（嵌入时使用的密码）："
    )
    return STATE_EXTRACT_WAIT_PASSWORD


async def extract_receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收密码并执行提取"""
    user_id = update.effective_user.id
    session = user_sessions.pop(user_id, {})

    if not session:
        await update.message.reply_text("会话过期，请重新开始 /start")
        return ConversationHandler.END

    try:
        password = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("密码必须是数字，请重新开始 /start")
        return ConversationHandler.END

    img_path = session["img_path"]
    wm_len = session["wm_length"]

    try:
        await update.message.reply_text("⏳ 正在提取水印，请稍候...")

        bwm = WaterMark(password_img=password, password_wm=password)
        wm_extract = bwm.extract(img_path, wm_shape=wm_len, mode="str")

        await update.message.reply_text(
            f"✅ 水印提取成功！\n\n"
            f"📝 提取的水印文字:\n\n`{wm_extract}`",
            parse_mode="Markdown",
        )

        logger.info(
            f"TG提取成功: user={user_id}, result='{wm_extract[:50]}...'"
        )

    except Exception as e:
        logger.error(f"TG提取失败: {str(e)}")
        await update.message.reply_text(f"❌ 提取失败: {str(e)}")

    finally:
        Path(img_path).unlink(missing_ok=True)

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消操作"""
    user_id = update.effective_user.id
    session = user_sessions.pop(user_id, {})

    # 清理临时文件
    for key in ["ori_path", "img_path"]:
        if key in session:
            Path(session[key]).unlink(missing_ok=True)

    await update.message.reply_text(
        "❌ 操作已取消。\n发送 /start 重新开始。",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """帮助命令"""
    await update.message.reply_text(
        "📖 *盲水印 Bot 使用帮助*\n\n"
        "🔐 *嵌入水印*:\n"
        "1. 选择「嵌入水印」\n"
        "2. 发送原始图片\n"
        "3. 输入水印文字\n"
        "4. 输入密码\n"
        "5. 获得带水印的图片和提取码\n\n"
        "🔍 *提取水印*:\n"
        "1. 选择「提取水印」\n"
        "2. 发送带水印的图片\n"
        "3. 输入水印长度（嵌入时返回的数字）\n"
        "4. 输入密码\n"
        "5. 获得提取的水印文字\n\n"
        "💡 *提示*: 盲水印是不可见的，图片看起来和原图完全一样。"
        "即使图片被裁剪、旋转、压缩，水印仍然可以提取。\n\n"
        "⚠️ *注意*: 请务必保存好水印长度和密码，丢失后无法提取。",
        parse_mode="Markdown",
    )


def main():
    """启动 Bot"""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")

    if not token:
        print("错误: 请设置 TELEGRAM_BOT_TOKEN 环境变量")
        print("获取 Token: 在 Telegram 中搜索 @BotFather 创建 Bot")
        sys.exit(1)

    # 创建对话处理器
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            STATE_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler),
            ],
            STATE_EMBED_WAIT_IMAGE: [
                MessageHandler(filters.PHOTO, embed_receive_image),
            ],
            STATE_EMBED_WAIT_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, embed_receive_text),
            ],
            STATE_EMBED_WAIT_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, embed_receive_password),
            ],
            STATE_EXTRACT_WAIT_IMAGE: [
                MessageHandler(filters.PHOTO, extract_receive_image),
            ],
            STATE_EXTRACT_WAIT_WMLEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, extract_receive_wmlen),
            ],
            STATE_EXTRACT_WAIT_PASSWORD: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, extract_receive_password
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app = Application.builder().token(token).build()

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("help", help_command))

    logger.info("Bot 启动中...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()