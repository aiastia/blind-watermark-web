#!/usr/bin/env python3
"""快速验证 x+hex 编码方案的比特长度一致性"""
import sys
sys.path.insert(0, '.')

from blind_watermark import WaterMark
import numpy as np
from PIL import Image

PREFIX = "x"
PAD_CHAR = "0"

def pad_name(name, max_len=16):
    hex_name = name.encode("utf-8").hex()
    content_len = max_len - 1
    return PREFIX + hex_name.ljust(content_len, PAD_CHAR)[:content_len]

def unpad_name(text):
    hex_str = text[1:].rstrip(PAD_CHAR).strip()
    return bytes.fromhex(hex_str).decode("utf-8")

# 测试多个名字
names = ["张三", "李四", "王五", "Alice"]
for name in names:
    padded = pad_name(name, 16)
    print(f"{name} → padded: {repr(padded)}, len={len(padded)}")

# 用模板计算比特长度
template = PREFIX + "f" * 15  # 16 chars total
bwm = WaterMark(password_wm=1)
bwm.read_wm(template, mode="str")
template_len = len(bwm.wm_bit)
print(f"\n模板比特长度: {template_len}")

# 测试每个名字的比特长度
for name in names:
    padded = pad_name(name, 16)
    bwm2 = WaterMark(password_wm=1)
    bwm2.read_wm(padded, mode="str")
    actual_len = len(bwm2.wm_bit)
    match = "✅" if actual_len == template_len else "❌"
    print(f"  {name}: {actual_len} bits {match}")

# 完整嵌入+提取测试
print("\n--- 完整嵌入+提取测试 ---")
test_img = np.random.randint(0, 255, (300, 300, 3), dtype=np.uint8)
Image.fromarray(test_img).save("/tmp/test_xhex.png")

for name in names:
    padded = pad_name(name, 16)
    
    # 嵌入
    bwm_e = WaterMark(password_img=1, password_wm=1)
    bwm_e.read_img("/tmp/test_xhex.png")
    bwm_e.read_wm(padded, mode="str")
    bwm_e.embed(f"/tmp/test_xhex_{name}.png")
    
    # 提取
    bwm_d = WaterMark(password_img=1, password_wm=1)
    extracted = bwm_d.extract(f"/tmp/test_xhex_{name}.png", wm_shape=template_len, mode="str")
    
    decoded = unpad_name(extracted)
    match = "✅" if decoded == name else "❌"
    print(f"  {name}: extracted={repr(extracted[:20])} decoded={decoded} {match}")