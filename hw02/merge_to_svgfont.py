import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
import statistics

def eaw_is_fullwidth(codepoint: int) -> bool:
    """
    依據 Unicode East Asian Width 屬性判斷寬度：
      W  (Wide)      → 全形 300
      F  (Fullwidth) → 全形 300
      Na (Narrow)    → 半形 150
      H  (Halfwidth) → 半形 150
      N  (Neutral)   → 全形 300（特殊符號預設全形）
      A  (Ambiguous) → 全形 300（CJK 脈絡下視為全形）
    """
    eaw = unicodedata.east_asian_width(chr(codepoint))
    return eaw not in ('Na', 'H')

def calculate_bounding_box(tokens):
    """計算路徑的邊界框"""
    min_x = float('inf')
    max_x = float('-inf')
    min_y = float('inf')
    max_y = float('-inf')
    
    is_x = True
    for cmd, val in tokens:
        if not cmd and val:
            num = float(val)
            if is_x:
                min_x = min(min_x, num)
                max_x = max(max_x, num)
                is_x = False
            else:
                min_y = min(min_y, num)
                max_y = max(max_y, num)
                is_x = True
        elif cmd:
            is_x = True
    
    if min_x == float('inf'):
        return None, None, None, None
    return min_x, max_x, min_y, max_y

def transform_tokens(tokens, global_origin_x, global_origin_y, uniform_square, canvas_size):
    """
    用全局基準偏移，統一縮放，翻轉 Y — 所有字形共用同一個變換，保留相對位置
    """
    scale = canvas_size / uniform_square
    
    new_tokens = []
    is_x = True
    
    for cmd, val in tokens:
        if cmd:
            new_tokens.append(cmd)
            is_x = True
        elif val:
            num = float(val)
            if is_x:
                x_val = (num - global_origin_x) * scale
                new_tokens.append(format(x_val, '.2f'))
                is_x = False
            else:
                y_val = (num - global_origin_y) * scale
                flipped_y = canvas_size - y_val
                new_tokens.append(format(flipped_y, '.2f'))
                is_x = True
    
    return new_tokens

def transform_tokens_with_shift(tokens, global_origin_x, global_origin_y, uniform_square, canvas_size, shift_x, shift_y):
    """
    和 transform_tokens 相同，但額外加上偏移量，讓超出邊界的字移回來
    """
    scale = canvas_size / uniform_square
    
    new_tokens = []
    is_x = True
    
    for cmd, val in tokens:
        if cmd:
            new_tokens.append(cmd)
            is_x = True
        elif val:
            num = float(val)
            if is_x:
                x_val = (num - global_origin_x) * scale + shift_x
                new_tokens.append(format(x_val, '.2f'))
                is_x = False
            else:
                y_val = (num - global_origin_y) * scale
                flipped_y = canvas_size - y_val + shift_y
                new_tokens.append(format(flipped_y, '.2f'))
                is_x = True
    
    return new_tokens

def create_svg_font_with_flip():
    font_name = 'MyFont'
    input_folder = Path('my_output_folder')
    output_dir = Path('final_font')
    output_path = output_dir / 'fontpico_py2.svg'
    
    output_dir.mkdir(parents=True, exist_ok=True)

    svg_header = f'''<?xml version="1.0" standalone="no"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd" >
<svg xmlns="http://www.w3.org/2000/svg">
<defs>
  <font id="{font_name}" horiz-adv-x="300">
    <font-face font-family="{font_name}"
      units-per-em="300" ascent="300"
      descent="0" />
    <missing-glyph horiz-adv-x="0" />
'''
    
    svg_files = sorted(list(input_folder.glob("*.svg")))
    
    # 第一遍掃描：收集每個字形的 bounding box
    print("掃描所有 SVG...")
    all_min_x = []
    all_max_x = []
    all_min_y = []
    all_max_y = []
    
    for svg_path in svg_files:
        try:
            tree = ET.parse(svg_path)
            root = tree.getroot()
            ns = {'svg': 'http://www.w3.org/2000/svg'}
            paths = root.findall('.//svg:path', ns) or root.findall('.//path')
            raw_d = " ".join([p.attrib.get('d', '') for p in paths])
            
            if not raw_d:
                continue
            
            tokens = re.findall(r"([a-zA-Z])|([-+]?\d*\.\d+|\d+)", raw_d)
            min_x, max_x, min_y, max_y = calculate_bounding_box(tokens)
            
            if min_x is None:
                continue
            
            all_min_x.append(min_x)
            all_max_x.append(max_x)
            all_min_y.append(min_y)
            all_max_y.append(max_y)
            
        except Exception as e:
            pass
    
    # 用中位數取範圍，排除歪字的影響
    all_min_x.sort()
    all_max_x.sort()
    all_min_y.sort()
    all_max_y.sort()
    n = len(all_min_x)
    
    # 用 5th / 95th 百分位數，排除最極端的 5%
    lo = max(0, int(n * 0.05))
    hi = min(n - 1, int(n * 0.95))
    
    crop_min_x = all_min_x[lo]
    crop_max_x = all_max_x[hi]
    crop_min_y = all_min_y[lo]
    crop_max_y = all_max_y[hi]
    
    crop_width = crop_max_x - crop_min_x
    crop_height = crop_max_y - crop_min_y
    uniform_square = max(crop_width, crop_height)
    
    # 居中較短的那邊
    crop_center_x = (crop_min_x + crop_max_x) / 2
    crop_center_y = (crop_min_y + crop_max_y) / 2
    global_origin_x = crop_center_x - uniform_square / 2
    global_origin_y = crop_center_y - uniform_square / 2
    
    print(f"5%-95% 範圍: X=[{crop_min_x:.2f}, {crop_max_x:.2f}], Y=[{crop_min_y:.2f}, {crop_max_y:.2f}]")
    print(f"裁剪後寬={crop_width:.2f}, 高={crop_height:.2f}, 統一正方形邊長={uniform_square:.2f}")
    
    canvas_size = 300  # 放大到 300x300
    MARGIN = 15  # 每個字形左右各留的邊距（單位同 units-per-em）
    FULLWIDTH_ADV = 300   # 全形字（CJK、假名、注音等）推進寬度
    HALFWIDTH_ADV = 150   # 半形字（ASCII、拉丁字母等）推進寬度
    
    # 第二遍掃描：使用最小正方形處理所有 SVG
    print("處理 SVG 文件...")
    glyph_definitions = []

    for svg_path in svg_files:
        match = re.search(r'[Uu]\+([0-9A-Fa-f]+)', svg_path.name)
        if not match:
            continue
        
        hex_code = match.group(1).upper()
        codepoint = int(hex_code, 16)
        target_adv = FULLWIDTH_ADV if eaw_is_fullwidth(codepoint) else HALFWIDTH_ADV
        glyph_name = f"icon_{hex_code}"
        unicode_entity = f"&#x{hex_code};"
        
        try:
            tree = ET.parse(svg_path)
            root = tree.getroot()
            ns = {'svg': 'http://www.w3.org/2000/svg'}
            paths = root.findall('.//svg:path', ns) or root.findall('.//path')
            raw_d = " ".join([p.attrib.get('d', '') for p in paths])
            
            if not raw_d:
                continue

            tokens = re.findall(r"([a-zA-Z])|([-+]?\d*\.\d+|\d+)", raw_d)
            min_x, max_x, min_y, max_y = calculate_bounding_box(tokens)
            
            if min_x is None:
                continue
            
            # 先用全局變換計算這個字形變換後的邊界
            scale = canvas_size / uniform_square
            t_min_x = (min_x - global_origin_x) * scale
            t_max_x = (max_x - global_origin_x) * scale
            # 翻轉後 min/max 互換
            t_min_y = canvas_size - (max_y - global_origin_y) * scale
            t_max_y = canvas_size - (min_y - global_origin_y) * scale
            
            # 計算需要的偏移量，讓超出邊界的字移回來
            # 在 target_adv 寬度內水平置中（全形=300，半形=150）
            ink_width = t_max_x - t_min_x
            shift_x = (target_adv - ink_width) / 2 - t_min_x
            shift_y = 0
            if t_min_y < 0:
                shift_y = -t_min_y  # 往下推
            elif t_max_y > canvas_size:
                shift_y = canvas_size - t_max_y  # 往上推

            # 固定推進寬度（全形=300，半形=150）
            horiz_adv_x = target_adv

            transformed_tokens = transform_tokens_with_shift(
                tokens, global_origin_x, global_origin_y, uniform_square,
                canvas_size, shift_x, shift_y
            )
            transformed_d = " ".join(transformed_tokens)

            # 產出 glyph 標籤
            glyph_def = f'    <glyph glyph-name="{glyph_name}"\n' \
                        f'      unicode="{unicode_entity}"\n' \
                        f'      horiz-adv-x="{horiz_adv_x:.0f}" d="{transformed_d}" />'
            glyph_definitions.append(glyph_def)
            
        except Exception as e:
            print(f"Failed to process {svg_path.name}: {e}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg_header)
        f.write("\n".join(glyph_definitions))
        f.write('\n  </font>\n</defs>\n</svg>')

    print(f"SVG Font：{output_path}")

if __name__ == "__main__":
    create_svg_font_with_flip()