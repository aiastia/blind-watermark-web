#!/usr/bin/env python3
"""测试盲水印中文名编码方案"""
import sys
sys.path.insert(0, '.')

from blind_watermark import WaterMark
import numpy as np
from PIL import Image

def test_encoding(name, padded_text, img_size=(400, 400)):
    """测试某种编码方案的嵌入+提取"""
    print(f"\n{'='*60}")
    print(f"测试: name={name}, padded_len={len(padded_text)}, img={img_size}")
    print(f"padded repr: {repr(padded_text[:40])}...")
    
    # 创建测试图片
    test_img = np.random.randint(0, 255, (*img_size, 3), dtype=np.uint8)
    ori_path = f'/tmp/test_ori_{img_size[0]}.png'
    wm_path = '/tmp/test_wm.png'
    Image.fromarray(test_img).save(ori_path)
    
    try:
        # 嵌入
        bwm1 = WaterMark(password_img=1, password_wm=1)
        bwm1.read_img(ori_path)
        bwm1.read_wm(padded_text, mode='str')
        wm_len = len(bwm1.wm_bit)
        print(f"嵌入比特长度: {wm_len}")
        bwm1.embed(wm_path)
        
        # 提取
        bwm2 = WaterMark(password_img=1, password_wm=1)
        extracted = bwm2.extract(wm_path, wm_shape=wm_len, mode='str')
        print(f"提取原始: {repr(extracted[:40])}...")
        
        # 比较
        match = extracted == padded_text
        print(f"完全匹配: {match}")
        
        if not match:
            # 看看哪里不同
            for i, (a, b) in enumerate(zip(padded_text, extracted)):
                if a != b:
                    print(f"  位置{i}: 期望={repr(a)} 实际={repr(b)}")
                    if i > 5:
                        print(f"  ... 共有差异位置过多")
                        break
        
        return match, wm_len
    except Exception as e:
        print(f"错误: {e}")
        return False, 0


# 方案1: 原始中文 + 空格补齐
name = "张三"
padded = name.ljust(32)  # 空格补齐到32字符
test_encoding("方案1: 中文+空格", padded)

# 方案2: hex 编码
hex_name = name.encode('utf-8').hex()  # e5bca0e4b889 = 12 chars
padded_hex = hex_name.ljust(32, '0')[:32]
test_encoding("方案2: hex编码", padded_hex)

# 方案3: 用数字ID代替名字（最简单）
test_encoding("方案3: 纯ASCII", "zhang_san_______________00001", (400, 400))

# 方案4: 中文 + 空格，大图
padded_cn = name.ljust(32)
test_encoding("方案4: 中文+空格+大图", padded_cn, (800, 800))

# 方案5: hex 编码 + 更短的长度
hex_name = name.encode('utf-8').hex()
padded_hex_short = hex_name.ljust(16, '0')[:16]
test_encoding("方案5: hex短", padded_hex_short, (400, 400))

# 方案6: 用 mode='bytes' 方式直接传 bits
print(f"\n{'='*60}")
print("方案6: 手动 bits")
name = "张三"
name_bytes = name.encode('utf-8')
# 转为 bits
bits = []
for byte in name_bytes:
    for bit_pos in range(7, -1, -1):
        bits.append((byte >> bit_pos) & 1)
# 补齐到固定长度
target_bits = 256  # 32 bytes = 256 bits
while len(bits) < target_bits:
    bits.append(0)
bits = bits[:target_bits]

print(f"name bytes: {name_bytes.hex()}, {len(name_bytes)} bytes → {len(bits)} bits")

test_img = np.random.randint(0, 255, (400, 400, 3), dtype=np.uint8)
ori_path = '/tmp/test_ori_400.png'
wm_path = '/tmp/test_wm6.png'
Image.fromarray(test_img).save(ori_path)

bwm1 = WaterMark(password_img=1, password_wm=1)
bwm1.read_img(ori_path)
bwm1.read_wm(bits)  # 不用 mode='str'
print(f"wm_bit len: {len(bwm1.wm_bit)}")
bwm1.embed(wm_path)

bwm2 = WaterMark(password_img=1, password_wm=1)
extracted_bits = bwm2.extract(wm_path, wm_shape=len(bits), mode='bit')
print(f"extracted bits len: {len(extracted_bits)}")
# 转回 bytes
result_bytes = bytearray()
for i in range(0, len(extracted_bits), 8):
    byte = 0
    for j in range(8):
        if i + j < len(extracted_bits):
            byte = (byte << 1) | int(extracted_bits[i + j])
        else:
            byte = byte << 1
    result_bytes.append(byte)
result = bytes(result_bytes).rstrip(b'\x00').decode('utf-8', errors='replace')
print(f"解码结果: {result}")
print(f"匹配: {result == name}")