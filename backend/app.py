
"""
Blind Watermark Web & Telegram Bot - Backend Service
基于 DWT-DCT-SVD 的图片盲水印服务
"""
import os
import io
import json
import uuid
import logging
from pathlib import Path

import numpy as np
from PIL import Image
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from blind_watermark import WaterMark

# 日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 临时文件目录
TEMP_DIR = Path("./temp")
TEMP_DIR.mkdir(exist_ok=True)

app = FastAPI(
    title="Blind Watermark API",
    description="图片盲水印 - 嵌入与提取服务",
    version="1.0.0",
)

# 跨域支持
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def cleanup_old_files():
    """清理超过 1 小时的临时文件"""
    import time
    now = time.time()
    for f in TEMP_DIR.iterdir():
        if f.is_file() and (now - f.stat().st_mtime) > 3600:
            f.unlink(missing_ok=True)


@app.post("/api/embed")
async def embed_watermark(
    image: UploadFile = File(..., description="原始图片"),
    watermark_text: str = Form("", description="水印文字"),
    password_img: int = Form(1, description="图片密码"),
    password_wm: int = Form(1, description="水印密码"),
    tier: str = Form("", description="长度档位: short/medium/long，留空则用原始长度"),
):
    """
    嵌入文字盲水印到图片中。
    - tier 为空时：使用原始文字长度（提取时需提供 wm_length）
    - tier 指定时：自动编码补齐到固定长度（提取时无需 wm_length）
    """
    cleanup_old_files()

    if not watermark_text:
        raise HTTPException(status_code=400, detail="水印文字不能为空")

    image_bytes = await image.read()
    if len(image_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片大小不能超过 20MB")

    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"图片格式错误: {str(e)}")

    task_id = uuid.uuid4().hex[:12]
    ori_path = TEMP_DIR / f"ori_{task_id}.png"
    out_path = TEMP_DIR / f"embed_{task_id}.png"

    try:
        img.save(ori_path, "PNG")

        use_fixed = bool(tier and tier in WM_LENGTH_TIERS)
        if use_fixed:
            # 固定长度模式：x + hex 编码
            wm_text = _pad_name(watermark_text, tier)
            # 确保图片够大
            img2 = _ensure_min_size(img, 300)
            if img2.size != img.size:
                img2.save(ori_path, "PNG")
        else:
            wm_text = watermark_text

        bwm = WaterMark(password_img=password_img, password_wm=password_wm)
        bwm.read_img(str(ori_path))
        bwm.read_wm(wm_text, mode="str")
        bwm.embed(str(out_path))

        wm_len = len(bwm.wm_bit)

        logger.info(
            f"嵌入成功: task={task_id}, wm_len={wm_len}, "
            f"text='{watermark_text[:20]}...', fixed={use_fixed}, tier={tier}"
        )

        headers = {
            "X-WM-Length": str(wm_len),
            "X-Task-ID": task_id,
        }
        if use_fixed:
            headers["X-Fixed-Tier"] = tier

        return FileResponse(
            str(out_path),
            media_type="image/png",
            filename=f"watermarked_{task_id}.png",
            headers=headers,
        )

    except Exception as e:
        logger.error(f"嵌入失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"嵌入水印失败: {str(e)}")
    finally:
        ori_path.unlink(missing_ok=True)


@app.post("/api/extract")
async def extract_watermark(
    image: UploadFile = File(..., description="带水印的图片"),
    wm_length: int = Form(0, description="水印比特长度（档位模式时为0）"),
    tier: str = Form("", description="长度档位: short/medium/long/auto，留空用 wm_length"),
    password_img: int = Form(1, description="图片密码"),
    password_wm: int = Form(1, description="水印密码"),
):
    """
    从图片中提取文字盲水印。
    - 指定 tier 时：按档位提取（支持 auto 自动遍历），自动解码 hex 编码
    - 指定 wm_length 时：按传统模式提取原始文字
    """
    cleanup_old_files()

    image_bytes = await image.read()
    if len(image_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片大小不能超过 20MB")

    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"图片格式错误: {str(e)}")

    task_id = uuid.uuid4().hex[:12]
    img_path = TEMP_DIR / f"extract_input_{task_id}.png"

    try:
        img.save(img_path, "PNG")

        # 档位模式
        use_tier = bool(tier and tier in WM_LENGTH_TIERS or tier == "auto")
        if use_tier:
            tiers_to_try = list(WM_LENGTH_TIERS.keys()) if tier == "auto" else [tier]
            best_name = ""
            best_tier = ""
            all_results = []

            for t in tiers_to_try:
                try:
                    wm_len = _get_fixed_wm_length(t, password_wm)
                    bwm = WaterMark(password_img=password_img, password_wm=password_wm)
                    extracted = bwm.extract(str(img_path), wm_shape=wm_len, mode="str")
                    name = _unpad_name(extracted)
                    has_content = bool(name and any(c.isalnum() or '\u4e00' <= c <= '\u9fff' for c in name))
                    all_results.append({"tier": t, "name": name, "valid": has_content})
                    if has_content and not best_name:
                        best_name = name
                        best_tier = t
                except Exception:
                    pass

            logger.info(f"提取成功(档位模式): task={task_id}, name='{best_name}', tier={best_tier}")
            return JSONResponse({
                "success": True,
                "watermark": best_name,
                "decoded_name": best_name,
                "tier": best_tier,
                "task_id": task_id,
            })

        # 传统模式
        if wm_length <= 0:
            raise HTTPException(status_code=400, detail="请指定 wm_length 或 tier")

        bwm = WaterMark(password_img=password_img, password_wm=password_wm)
        wm_extract = bwm.extract(str(img_path), wm_shape=wm_length, mode="str")

        logger.info(f"提取成功: task={task_id}, result='{wm_extract[:50]}...'")
        return JSONResponse({
            "success": True,
            "watermark": wm_extract,
            "task_id": task_id,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提取失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"提取水印失败: {str(e)}")
    finally:
        img_path.unlink(missing_ok=True)


@app.post("/api/embed_image")
async def embed_image_watermark(
    image: UploadFile = File(..., description="原始图片"),
    watermark_image: UploadFile = File(..., description="水印图片"),
    password_img: int = Form(1, description="图片密码"),
    password_wm: int = Form(1, description="水印密码"),
):
    """
    嵌入图片盲水印到图片中
    """
    cleanup_old_files()

    image_bytes = await image.read()
    wm_image_bytes = await watermark_image.read()

    if len(image_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片大小不能超过 20MB")

    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")

        wm_img = Image.open(io.BytesIO(wm_image_bytes))
        if wm_img.mode != "RGB":
            wm_img = wm_img.convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"图片格式错误: {str(e)}")

    task_id = uuid.uuid4().hex[:12]
    ori_path = TEMP_DIR / f"ori_{task_id}.png"
    wm_path = TEMP_DIR / f"wm_{task_id}.png"
    out_path = TEMP_DIR / f"embed_{task_id}.png"

    try:
        img.save(ori_path, "PNG")
        wm_img.save(wm_path, "PNG")

        bwm = WaterMark(password_img=password_img, password_wm=password_wm)
        bwm.read_img(str(ori_path))
        bwm.read_wm(str(wm_path))
        bwm.embed(str(out_path))

        wm_shape = f"{wm_img.height},{wm_img.width}"

        return FileResponse(
            str(out_path),
            media_type="image/png",
            filename=f"watermarked_{task_id}.png",
            headers={
                "X-WM-Shape": wm_shape,
                "X-Task-ID": task_id,
            },
        )

    except Exception as e:
        logger.error(f"图片水印嵌入失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"嵌入水印失败: {str(e)}")
    finally:
        ori_path.unlink(missing_ok=True)
        wm_path.unlink(missing_ok=True)


@app.post("/api/extract_image")
async def extract_image_watermark(
    image: UploadFile = File(..., description="带水印的图片"),
    wm_height: int = Form(..., description="水印图片高度"),
    wm_width: int = Form(..., description="水印图片宽度"),
    password_img: int = Form(1, description="图片密码"),
    password_wm: int = Form(1, description="水印密码"),
):
    """
    从图片中提取图片盲水印
    """
    cleanup_old_files()

    image_bytes = await image.read()

    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"图片格式错误: {str(e)}")

    task_id = uuid.uuid4().hex[:12]
    img_path = TEMP_DIR / f"extract_input_{task_id}.png"
    out_wm_path = TEMP_DIR / f"extracted_wm_{task_id}.png"

    try:
        img.save(img_path, "PNG")

        bwm = WaterMark(password_img=password_img, password_wm=password_wm)
        bwm.extract(
            filename=str(img_path),
            wm_shape=(wm_height, wm_width),
            out_wm_name=str(out_wm_path),
        )

        if not out_wm_path.exists():
            raise Exception("提取的水印图片未生成")

        return FileResponse(
            str(out_wm_path),
            media_type="image/png",
            filename=f"extracted_watermark_{task_id}.png",
        )

    except Exception as e:
        logger.error(f"图片水印提取失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"提取水印失败: {str(e)}")
    finally:
        img_path.unlink(missing_ok=True)


@app.post("/api/batch_embed")
async def batch_embed_watermark(
    images: list[UploadFile] = File(..., description="多张原始图片"),
    watermark_text: str = Form("", description="水印文字"),
    password_img: int = Form(1, description="图片密码"),
    password_wm: int = Form(1, description="水印密码"),
):
    """
    批量嵌入文字盲水印到多张图片
    返回 JSON 包含每张图片的下载链接和水印长度
    """
    import zipfile
    cleanup_old_files()

    if not watermark_text:
        raise HTTPException(status_code=400, detail="水印文字不能为空")

    if len(images) > 50:
        raise HTTPException(status_code=400, detail="单次最多处理 50 张图片")

    task_id = uuid.uuid4().hex[:12]
    results = []
    zip_files = []

    try:
        # 先计算水印长度（用第一张图片）
        first_bytes = await images[0].read()
        if len(first_bytes) > 20 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="图片大小不能超过 20MB")

        try:
            first_img = Image.open(io.BytesIO(first_bytes))
            if first_img.mode != "RGB":
                first_img = first_img.convert("RGB")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"图片格式错误: {str(e)}")

        # 用临时图片计算 wm_bit 长度
        tmp_path = TEMP_DIR / f"tmp_{task_id}.png"
        first_img.save(tmp_path, "PNG")
        bwm_test = WaterMark(password_img=password_img, password_wm=password_wm)
        bwm_test.read_img(str(tmp_path))
        bwm_test.read_wm(watermark_text, mode="str")
        wm_len = len(bwm_test.wm_bit)
        tmp_path.unlink(missing_ok=True)

        # 重新读取第一张图片（因为已经 read 过了）
        await images[0].seek(0)

        # 处理每张图片
        for idx, img_file in enumerate(images):
            image_bytes = await img_file.read()
            if len(image_bytes) > 20 * 1024 * 1024:
                results.append({
                    "index": idx,
                    "filename": img_file.filename,
                    "error": "图片大小超过 20MB",
                })
                continue

            try:
                img = Image.open(io.BytesIO(image_bytes))
                if img.mode != "RGB":
                    img = img.convert("RGB")

                ori_path = TEMP_DIR / f"batch_ori_{task_id}_{idx}.png"
                out_path = TEMP_DIR / f"batch_embed_{task_id}_{idx}.png"

                img.save(ori_path, "PNG")

                bwm = WaterMark(password_img=password_img, password_wm=password_wm)
                bwm.read_img(str(ori_path))
                bwm.read_wm(watermark_text, mode="str")
                bwm.embed(str(out_path))

                zip_files.append((out_path, f"watermarked_{img_file.filename}"))
                results.append({
                    "index": idx,
                    "filename": img_file.filename,
                    "status": "success",
                })

                ori_path.unlink(missing_ok=True)

            except Exception as e:
                results.append({
                    "index": idx,
                    "filename": img_file.filename,
                    "error": str(e),
                })

        # 打包为 ZIP
        zip_path = TEMP_DIR / f"batch_{task_id}.zip"
        with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path, arcname in zip_files:
                zf.write(str(file_path), arcname)
                file_path.unlink(missing_ok=True)

        return FileResponse(
            str(zip_path),
            media_type="application/zip",
            filename=f"watermarked_batch_{task_id}.zip",
            headers={
                "X-WM-Length": str(wm_len),
                "X-Total-Count": str(len(results)),
                "X-Success-Count": str(
                    sum(1 for r in results if r.get("status") == "success")
                ),
                "X-Task-ID": task_id,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量嵌入失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"批量嵌入失败: {str(e)}")


# 水印长度档位（名字补齐到此长度，提取时无需知道名字）
# 使用 'x' + hex 编码：保证所有名字的比特长度完全一致
WM_LENGTH_TIERS = {
    "short": 16,    # 短名：张三（hex后≈12字符+前缀，兼容小图）
    "medium": 32,   # 中等：邮箱、用户ID
    "long": 64,     # 长文本：句子、URL
}
DEFAULT_TIER = "short"
PREFIX = "x"       # 固定前缀，确保首字节一致，比特长度不因内容变化
PAD_CHAR = "0"     # hex 补齐字符


def _pad_name(name: str, tier: str = DEFAULT_TIER) -> str:
    """将名字编码为 hex + 固定前缀 + 补齐到固定长度（保证比特长度一致）"""
    hex_name = name.encode("utf-8").hex()
    max_len = WM_LENGTH_TIERS.get(tier, WM_LENGTH_TIERS[DEFAULT_TIER])
    # 格式: "x" + hex_name + "000...0"，总长 = max_len
    content_len = max_len - 1  # 减去前缀 'x'
    if len(hex_name) > content_len:
        raise ValueError(
            f"名字太长：编码后{len(hex_name)}字符，上限{content_len}字符。"
            f"请缩短名字或选择更高档位"
        )
    return PREFIX + hex_name.ljust(content_len, PAD_CHAR)[:content_len]


def _unpad_name(text: str) -> str:
    """去除前缀和补齐字符，解码回名字"""
    if not text or len(text) < 2:
        return ""
    hex_str = text[1:].rstrip(PAD_CHAR).strip()  # 去掉前缀 'x' 和尾部 '0'
    if not hex_str:
        return ""
    try:
        return bytes.fromhex(hex_str).decode("utf-8")
    except Exception:
        return text  # 解码失败返回原文


def _get_fixed_wm_length(tier: str = DEFAULT_TIER, password_wm: int = 1) -> int:
    """计算指定档位对应的比特长度（使用与 _pad_name 相同的模板）"""
    max_len = WM_LENGTH_TIERS.get(tier, WM_LENGTH_TIERS[DEFAULT_TIER])
    # 模板必须和实际嵌入的格式一致：'x' + hex chars
    template = PREFIX + "f" * (max_len - 1)
    bwm = WaterMark(password_wm=password_wm)
    bwm.read_wm(template, mode="str")
    return len(bwm.wm_bit)


def _ensure_min_size(img: Image.Image, min_dim: int = 300) -> Image.Image:
    """确保图片足够大以嵌入水印（太小则放大）"""
    w, h = img.size
    if w < min_dim or h < min_dim:
        scale = max(min_dim / w, min_dim / h)
        new_w, new_h = int(w * scale), int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        logger.info(f"图片太小({w}x{h})，放大到({new_w}x{new_h})")
    return img


@app.post("/api/distribute")
async def distribute_watermark(
    image: UploadFile = File(..., description="原始图片"),
    names: str = Form(..., description="接收者名字列表，逗号分隔"),
    tier: str = Form("medium", description="长度档位: short(32)/medium(128)/long(256)"),
    password_img: int = Form(1, description="图片密码"),
    password_wm: int = Form(1, description="水印密码"),
):
    """
    分发追踪模式：一张图片 + 多个名字 → 每人一份带唯一水印的图片，打包 ZIP
    名字自动补齐到固定长度，追踪时无需知道名字即可提取
    """
    import zipfile
    cleanup_old_files()

    name_list = [n.strip() for n in names.split(",") if n.strip()]
    if not name_list:
        raise HTTPException(status_code=400, detail="请输入至少一个名字")
    if len(name_list) > 100:
        raise HTTPException(status_code=400, detail="单次最多 100 个名字")

    image_bytes = await image.read()
    if len(image_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片大小不能超过 20MB")

    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"图片格式错误: {str(e)}")

    # 确保图片够大
    img = _ensure_min_size(img, 300)

    task_id = uuid.uuid4().hex[:12]
    ori_path = TEMP_DIR / f"dist_ori_{task_id}.png"
    img.save(ori_path, "PNG")

    zip_path = TEMP_DIR / f"distribute_{task_id}.zip"
    results = []

    try:
        # 先用第一个名字测试图片容量，自动降级档位
        actual_tier = tier
        for test_tier in [tier] if tier != "auto" else list(WM_LENGTH_TIERS.keys()):
            try:
                test_padded = _pad_name(name_list[0], test_tier)
                bwm_test = WaterMark(password_img=password_img, password_wm=password_wm)
                bwm_test.read_img(str(ori_path))
                bwm_test.read_wm(test_padded, mode="str")
                # 如果没报错，说明容量够
                actual_tier = test_tier
                del bwm_test
                break
            except Exception:
                continue
        logger.info(f"使用档位: {actual_tier}")

        name_map = {}  # 序号 → 名字映射
        with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, name in enumerate(name_list):
                out_path = TEMP_DIR / f"dist_{task_id}_{idx}.png"
                try:
                    # 补齐到指定档位的固定长度
                    padded_name = _pad_name(name, actual_tier)

                    bwm = WaterMark(password_img=password_img, password_wm=password_wm)
                    bwm.read_img(str(ori_path))
                    bwm.read_wm(padded_name, mode="str")
                    bwm.embed(str(out_path))

                    # ZIP内用纯 ASCII 文件名（序号），避免编码问题
                    num = idx + 1
                    arcname = f"{num:03d}.png"
                    zf.write(str(out_path), arcname)
                    name_map[arcname] = name

                    results.append({"name": name, "status": "success", "filename": arcname})
                    logger.info(f"分发嵌入成功: {name}")
                except Exception as e:
                    results.append({"name": name, "status": "error", "error": str(e)})
                    logger.error(f"分发嵌入失败: {name} - {str(e)}")
                finally:
                    out_path.unlink(missing_ok=True)

            # 写入名字映射文件（纯 ASCII + UTF-8 内容）
            map_lines = [f"{filename} -> {name}" for filename, name in name_map.items()]
            map_content = "分发追踪 - 文件名映射\n" + "=" * 30 + "\n" + "\n".join(map_lines)
            map_content += f"\n\n档位: {actual_tier}\n密码: img={password_img}, wm={password_wm}"
            zf.writestr("README.txt", map_content.encode("utf-8"))

        success_count = sum(1 for r in results if r["status"] == "success")
        return FileResponse(
            str(zip_path),
            media_type="application/zip",
            filename=f"distribute_{task_id}.zip",
            headers={
                "X-Task-ID": task_id,
                "X-Total-Count": str(len(name_list)),
                "X-Success-Count": str(success_count),
                "X-Results": json.dumps(results, ensure_ascii=True),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"分发失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"分发失败: {str(e)}")
    finally:
        ori_path.unlink(missing_ok=True)


@app.post("/api/track")
async def track_leak(
    image: UploadFile = File(..., description="泄漏的图片"),
    tier: str = Form("medium", description="长度档位: short/medium/long，不记得可填 auto 自动遍历"),
    password_img: int = Form(1, description="图片密码"),
    password_wm: int = Form(1, description="水印密码"),
):
    """
    泄漏追踪：上传图片 → 直接提取名字
    支持指定档位或 auto 自动遍历所有档位
    """
    cleanup_old_files()

    image_bytes = await image.read()
    if len(image_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片大小不能超过 20MB")

    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"图片格式错误: {str(e)}")

    task_id = uuid.uuid4().hex[:12]
    img_path = TEMP_DIR / f"track_{task_id}.png"

    try:
        img.save(img_path, "PNG")

        # 确定要尝试的档位
        if tier == "auto":
            tiers_to_try = list(WM_LENGTH_TIERS.keys())
        else:
            tiers_to_try = [tier]

        results = []
        best_name = ""
        best_tier = ""

        for t in tiers_to_try:
            try:
                wm_len = _get_fixed_wm_length(t, password_wm)
                bwm = WaterMark(password_img=password_img, password_wm=password_wm)
                extracted = bwm.extract(str(img_path), wm_shape=wm_len, mode="str")
                name = _unpad_name(extracted)

                # 判断是否有有效内容（非空且不是纯乱码）
                has_content = bool(name and any(c.isalnum() or '\u4e00' <= c <= '\u9fff' for c in name))

                results.append({
                    "tier": t,
                    "max_length": WM_LENGTH_TIERS[t],
                    "name": name,
                    "valid": has_content,
                })

                if has_content and not best_name:
                    best_name = name
                    best_tier = t

                logger.info(f"追踪: tier={t}, name='{name}', valid={has_content}")
            except Exception as e:
                results.append({"tier": t, "name": "", "valid": False, "error": str(e)})

        return JSONResponse({
            "success": True,
            "name": best_name,
            "tier": best_tier,
            "results": results,
            "task_id": task_id,
        })

    except Exception as e:
        logger.error(f"追踪失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"追踪失败: {str(e)}")
    finally:
        img_path.unlink(missing_ok=True)


@app.get("/api/wm_length")
async def get_wm_length(
    text: str,
    password_wm: int = 1,
):
    """
    根据文字计算水印比特长度（无需图片）
    相同文字 + 相同密码 → 长度固定
    """
    try:
        bwm = WaterMark(password_wm=password_wm)
        bwm.read_wm(text, mode="str")
        wm_len = len(bwm.wm_bit)
        return {"wm_length": wm_len, "text_preview": text[:20]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算失败: {str(e)}")


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "blind-watermark"}


# 挂载静态文件（前端页面）
# 支持环境变量 STATIC_DIR 指定路径（Docker 用），默认指向本地 frontend 目录
_static_path = os.environ.get("STATIC_DIR", "")
if _static_path:
    static_dir = Path(_static_path)
else:
    static_dir = Path(__file__).parent.parent / "frontend"

if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
