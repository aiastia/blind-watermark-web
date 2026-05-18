"""
Blind Watermark Telegram Bot
支持在 Telegram 中嵌入和提取图片盲水印
支持固定档位模式，提取时无需记住长度数字
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

# 复用后端的编码函数和档位配置
from app import _pad_name, _unpad_name, _get_fixed_wm_length, _ensure_min_size, WM_LENGTH_TIERS

# 日志
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# 临时目录
TEMP_DIR = Path("./temp_bot")
TEMP_DIR.mkdir(exist_ok=True)

# Telegram Bot API 文件大小限制
TG_PHOTO_MAX_SIZE = 10 * 1024 * 1024   # 10MB (sendPhoto)
TG_DOWNLOAD_MAX_SIZE = 20 * 1024 * 1024  # 20MB (getFile)

# 对话状态
(
    STATE_MENU,
    STATE_EMBED_WAIT_IMAGE,
    STATE_EMBED_WAIT_TEXT,
    STATE_EMBED_WAIT_TIER,
    STATE_EMBED_WAIT_PASSWORD,
    STATE_EXTRACT_WAIT_IMAGE,
    STATE_EXTRACT_WAIT_MODE,
    STATE_EXTRACT_WAIT_TIER,
    STATE_EXTRACT_WAIT_WMLEN,
    STATE_EXTRACT_WAIT_PASSWORD,
) = range(10)

# 用户会话数据
user_sessions = {}

# 档位显示
TIER_LABELS = {
    "s": "🔷 S (≤5中文)",
    "l": "🔮 L (≤15中文)",
    "xl": "🌟 XL (≤20中文)",
}


def get_keyboard():
    """主菜单键盘"""
    return ReplyKeyboardMarkup(
        [["🔐 嵌入水印", "🔍 提取水印"]],
        resize_keyboard=True,
    )


def get_tier_keyboard():
    """档位选择键盘"""
    keys = [[TIER_LABELS[k] for k in WM_LENGTH_TIERS.keys()]]
    return ReplyKeyboardMarkup(keys, resize_keyboard=True)


def get_extract_mode_keyboard():
    """提取模式选择键盘"""
    return ReplyKeyboardMarkup(
        [["🎯 按档位提取", "📏 按长度提取"]],
        resize_keyboard=True,
    )


def tier_from_label(label: str) -> str:
    """从键盘标签提取档位 key"""
    for k, v in TIER_LABELS.items():
        if v == label:
            return k
    return "s"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始命令"""
    await update.message.reply_text(
        "👋 *盲水印 Bot*\n\n"
        "我可以帮你在图片中嵌入看不见的水印，或者从图片中提取隐藏的水印。\n\n"
        "水印是*不可见*的，图片看起来和原图完全一样，"
        "即使图片被裁剪、旋转、压缩，水印仍然可以提取。\n\n"
        "支持*固定档位模式*，提取时无需记住长度数字！\n\n"
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


# ============ 嵌入流程 ============

async def embed_receive_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收嵌入水印的图片"""
    user_id = update.effective_user.id

    if not update.message.photo:
        await update.message.reply_text("请发送一张图片。")
        return STATE_EMBED_WAIT_IMAGE

    photo = update.message.photo[-1]
    file = await photo.get_file()

    # 检查文件大小
    file_size = file.file_size or 0
    if file_size > TG_DOWNLOAD_MAX_SIZE:
        await update.message.reply_text(
            f"⚠️ 图片太大（{file_size // 1024 // 1024}MB），超过 Bot 下载限制（20MB）\n\n"
            "💡 请使用网页版处理大文件：\n"
            "📸 嵌入水印 / 🔍 提取水印\n\n"
            "发送 /start 重新开始"
        )
        return ConversationHandler.END

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
        "📏 请选择水印长度档位：\n\n"
        "• S  — ≤5个中文 / 15个数字\n"
        "• L  — ≤15个中文 / 47个数字\n"
        "• XL — ≤20个中文 / 63个数字\n\n"
        "💡 推荐选 S，提取时只需选同档位",
        reply_markup=get_tier_keyboard(),
    )
    return STATE_EMBED_WAIT_TIER


async def embed_receive_tier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收档位选择"""
    user_id = update.effective_user.id
    session = user_sessions.get(user_id, {})

    if not session:
        await update.message.reply_text("会话过期，请重新开始 /start")
        return ConversationHandler.END

    tier = tier_from_label(update.message.text)
    session["tier"] = tier
    user_sessions[user_id] = session

    await update.message.reply_text(
        "🔑 请输入密码（数字），直接发送数字即可。\n"
        "默认密码为 1，直接发送 1 即可：",
        reply_markup=ReplyKeyboardRemove(),
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
    tier = session.get("tier", "s")
    task_id = session["task_id"]
    out_path = TEMP_DIR / f"tg_embed_{user_id}_{task_id}.png"

    try:
        await update.message.reply_text("⏳ 正在嵌入水印，请稍候...")

        # 固定长度模式
        padded_name = _pad_name(wm_text, tier)

        # 读取并确保图片够大
        img = Image.open(ori_path)
        if img.mode != "RGB":
            img = img.convert("RGB")
        img = _ensure_min_size(img, 300)
        img.save(ori_path, "PNG")

        bwm = WaterMark(password_img=password, password_wm=password)
        bwm.read_img(ori_path)
        bwm.read_wm(padded_name, mode="str")
        bwm.embed(str(out_path))

        wm_len = len(bwm.wm_bit)

        # 检查输出文件大小
        out_size = out_path.stat().st_size
        if out_size > TG_PHOTO_MAX_SIZE:
            await update.message.reply_text(
                f"⚠️ 嵌入成功，但图片太大（{out_size // 1024 // 1024}MB）超过 Bot 发送限制（10MB）\n\n"
                "💡 请使用网页版下载带水印的图片\n\n"
                f"📝 记录信息：\n"
                f"• 水印文字: `{wm_text}`\n"
                f"• 档位: {TIER_LABELS.get(tier, tier)}\n"
                f"• 密码: `{password}`\n"
                f"• 比特长度: `{wm_len}`",
                parse_mode="Markdown",
            )
        else:
            with open(str(out_path), "rb") as f:
                await update.message.reply_photo(
                    photo=f,
                    caption=(
                        f"✅ 水印嵌入成功！\n\n"
                        f"📝 水印文字: `{wm_text}`\n"
                        f"📏 档位: {TIER_LABELS.get(tier, tier)}\n"
                        f"🔑 密码: `{password}`\n"
                        f"📏 比特长度: `{wm_len}`\n\n"
                        f"💡 提取时选择「按档位提取」→ 选 `{TIER_LABELS.get(tier, tier)}` → 输入密码 `{password}` 即可"
                    ),
                    parse_mode="Markdown",
                )

        logger.info(f"TG嵌入成功: user={user_id}, task={task_id}, tier={tier}, out_size={out_size}")

    except ValueError as e:
        logger.error(f"TG嵌入失败(名字太长): {str(e)}")
        await update.message.reply_text(f"❌ 嵌入失败: {str(e)}\n\n请缩短文字或选择更高档位 /start")
    except Exception as e:
        logger.error(f"TG嵌入失败: {str(e)}")
        await update.message.reply_text(f"❌ 嵌入失败: {str(e)}")

    finally:
        Path(ori_path).unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)

    return ConversationHandler.END


# ============ 提取流程 ============

async def extract_receive_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收提取水印的图片"""
    user_id = update.effective_user.id

    if not update.message.photo:
        await update.message.reply_text("请发送一张图片。")
        return STATE_EXTRACT_WAIT_IMAGE

    photo = update.message.photo[-1]
    file = await photo.get_file()

    # 检查文件大小
    file_size = file.file_size or 0
    if file_size > TG_DOWNLOAD_MAX_SIZE:
        await update.message.reply_text(
            f"⚠️ 图片太大（{file_size // 1024 // 1024}MB），超过 Bot 下载限制（20MB）\n\n"
            "💡 请使用网页版提取水印\n\n"
            "发送 /start 重新开始"
        )
        return ConversationHandler.END

    task_id = uuid.uuid4().hex[:12]
    img_path = TEMP_DIR / f"tg_extract_{user_id}_{task_id}.jpg"
    await file.download_to_drive(str(img_path))

    user_sessions[user_id] = {
        "action": "extract",
        "img_path": str(img_path),
        "task_id": task_id,
    }

    await update.message.reply_text(
        "请选择提取方式：\n\n"
        "🎯 *按档位提取* — 推荐，无需记长度数字\n"
        "📏 *按长度提取* — 输入嵌入时返回的比特长度",
        parse_mode="Markdown",
        reply_markup=get_extract_mode_keyboard(),
    )
    return STATE_EXTRACT_WAIT_MODE


async def extract_receive_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收提取模式选择"""
    user_id = update.effective_user.id
    session = user_sessions.get(user_id, {})

    if not session:
        await update.message.reply_text("会话过期，请重新开始 /start")
        return ConversationHandler.END

    text = update.message.text

    if text == "🎯 按档位提取":
        await update.message.reply_text(
            "📏 请选择嵌入时的档位：",
            reply_markup=get_tier_keyboard(),
        )
        return STATE_EXTRACT_WAIT_TIER

    elif text == "📏 按长度提取":
        await update.message.reply_text(
            "📏 请输入水印比特长度（嵌入时返回的数字）：",
            reply_markup=ReplyKeyboardRemove(),
        )
        return STATE_EXTRACT_WAIT_WMLEN

    return STATE_EXTRACT_WAIT_MODE


async def extract_receive_tier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收档位并执行提取"""
    user_id = update.effective_user.id
    session = user_sessions.pop(user_id, {})

    if not session:
        await update.message.reply_text("会话过期，请重新开始 /start")
        return ConversationHandler.END

    tier = tier_from_label(update.message.text)
    img_path = session["img_path"]

    try:
        await update.message.reply_text("⏳ 正在提取水印，请稍候...")

        # 自动遍历：先试选定档位，不行就全部
        tiers_to_try = [tier]
        best_name = ""

        for t in tiers_to_try:
            try:
                wm_len = _get_fixed_wm_length(t)
                bwm = WaterMark(password_img=1, password_wm=1)
                extracted = bwm.extract(img_path, wm_shape=wm_len, mode="str")
                name = _unpad_name(extracted)
                if name and any(c.isalnum() or '\u4e00' <= c <= '\u9fff' for c in name):
                    best_name = name
                    break
            except Exception:
                pass

        # 如果选定档位没结果，自动遍历其他档位
        if not best_name:
            for t in WM_LENGTH_TIERS.keys():
                if t == tier:
                    continue
                try:
                    wm_len = _get_fixed_wm_length(t)
                    bwm = WaterMark(password_img=1, password_wm=1)
                    extracted = bwm.extract(img_path, wm_shape=wm_len, mode="str")
                    name = _unpad_name(extracted)
                    if name and any(c.isalnum() or '\u4e00' <= c <= '\u9fff' for c in name):
                        best_name = name
                        break
                except Exception:
                    pass

        if best_name:
            await update.message.reply_text(
                f"✅ 水印提取成功！\n\n"
                f"📝 提取的水印文字:\n\n`{best_name}`",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                "🤷 未检测到有效水印\n\n"
                "可能原因：\n"
                "• 图片不含盲水印\n"
                "• 密码不匹配（默认密码为 1）\n"
                "• 图片被严重裁剪或压缩"
            )

        logger.info(f"TG提取(档位): user={user_id}, name='{best_name}'")

    except Exception as e:
        logger.error(f"TG提取失败: {str(e)}")
        await update.message.reply_text(f"❌ 提取失败: {str(e)}")

    finally:
        Path(img_path).unlink(missing_ok=True)

    return ConversationHandler.END


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
    """接收密码并执行提取（传统模式）"""
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

        logger.info(f"TG提取成功: user={user_id}, result='{wm_extract[:50]}...'")

    except Exception as e:
        logger.error(f"TG提取失败: {str(e)}")
        await update.message.reply_text(f"❌ 提取失败: {str(e)}")

    finally:
        Path(img_path).unlink(missing_ok=True)

    return ConversationHandler.END


# ============ 通用 ============

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消操作"""
    user_id = update.effective_user.id
    session = user_sessions.pop(user_id, {})

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
        "4. 选择长度档位（S/L/XL）\n"
        "5. 输入密码\n"
        "6. 获得带水印的图片\n\n"
        "🔍 *提取水印（推荐按档位）*:\n"
        "1. 选择「提取水印」\n"
        "2. 发送带水印的图片\n"
        "3. 选择「按档位提取」→ 选嵌入时的档位\n"
        "4. 自动提取出水印文字\n\n"
        "📏 *提取水印（按长度）*:\n"
        "1. 选择「提取水印」\n"
        "2. 发送带水印的图片\n"
        "3. 选择「按长度提取」→ 输入水印比特长度\n"
        "4. 输入密码\n\n"
        "💡 *档位说明*:\n"
        "• S  — ≤5个中文 / 15个数字\n"
        "• L  — ≤15个中文 / 47个数字\n"
        "• XL — ≤20个中文 / 63个数字\n\n"
        "⚠️ *注意*: 嵌入和提取时的密码必须相同",
        parse_mode="Markdown",
    )


def main():
    """启动 Bot"""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")

    if not token:
        print("错误: 请设置 TELEGRAM_BOT_TOKEN 环境变量")
        print("获取 Token: 在 Telegram 中搜索 @BotFather 创建 Bot")
        sys.exit(1)

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
            STATE_EMBED_WAIT_TIER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, embed_receive_tier),
            ],
            STATE_EMBED_WAIT_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, embed_receive_password),
            ],
            STATE_EXTRACT_WAIT_IMAGE: [
                MessageHandler(filters.PHOTO, extract_receive_image),
            ],
            STATE_EXTRACT_WAIT_MODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, extract_receive_mode),
            ],
            STATE_EXTRACT_WAIT_TIER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, extract_receive_tier),
            ],
            STATE_EXTRACT_WAIT_WMLEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, extract_receive_wmlen),
            ],
            STATE_EXTRACT_WAIT_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, extract_receive_password),
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