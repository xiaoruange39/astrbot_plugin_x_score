"""
图片渲染模块 - 生成 flj.info 风格的可信度报告图片
"""

import io
import os
import re
import logging
import platform
from PIL import Image, ImageDraw, ImageFont, ImageFilter

logger = logging.getLogger("X账号评分")

# ==================== 颜色常量 ====================
BG_COLOR = (10, 10, 10)           # 主背景 #0a0a0a
CARD_BG = (22, 22, 22)            # 卡片背景 #161616
CARD_BORDER = (38, 38, 38)        # 卡片边框 #262626
TEXT_WHITE = (255, 255, 255)      # 主文字
TEXT_GRAY = (156, 163, 175)       # 次要文字 #9ca3af
TEXT_MUTED = (107, 114, 128)      # 更弱的文字 #6b7280
SCORE_GREEN = (34, 197, 94)       # 高分绿色 #22c55e
SCORE_YELLOW = (234, 179, 8)      # 中分黄色 #eab308
SCORE_ORANGE = (249, 115, 22)     # 低分橙色 #f97316
SCORE_RED = (239, 68, 68)         # 极低分红色 #ef4444
TAG_BG = (30, 30, 36)             # 标签背景
TAG_BORDER = (55, 55, 65)         # 标签边框
ACCENT_BLUE = (59, 130, 246)      # 蓝色标签
WELFARE_RED = (220, 38, 38)       # 福利号红色

# ==================== 布局常量 ====================
IMG_WIDTH = 1200
PADDING = 56
CARD_PADDING = 44
CARD_RADIUS = 32
TAG_RADIUS = 16
AVATAR_SIZE = 112
SCORE_BOX_SIZE = 144

# ==================== 字体工具 ====================
_font_cache = {}

def _find_chinese_font() -> str | None:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    for file in os.listdir(current_dir):
        if file.lower().endswith(('.ttf', '.ttc', '.otf')):
            return os.path.join(current_dir, file)
            
    import subprocess
    if platform.system() != "Windows":
        try:
            result = subprocess.run(['fc-list', ':lang=zh', 'file'], capture_output=True, text=True, timeout=3)
            if result.returncode == 0 and result.stdout:
                for line in result.stdout.strip().split('\n'):
                    file_path = line.split(':')[0].strip()
                    if file_path.lower().endswith(('.ttf', '.ttc', '.otf')) and os.path.exists(file_path):
                        return file_path
        except (OSError, subprocess.SubprocessError):
            pass

    font_candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
    ]
    for path in font_candidates:
        if os.path.exists(path):
            return path
            
    for name in ["msyh.ttc", "simhei.ttf", "NotoSansCJK-Regular.ttc"]:
        try:
            ImageFont.truetype(name, 10)
            return name
        except IOError:
            continue
    return None

_global_font = _find_chinese_font()

def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """获取支持中文的字体，找不到则返回默认"""
    key = f"{size}_{bold}"
    if key in _font_cache:
        return _font_cache[key]

    if _global_font:
        index = 1 if bold and _global_font.endswith(".ttc") else 0
        try:
            font = ImageFont.truetype(_global_font, size, index=index)
        except Exception:
            font = ImageFont.truetype(_global_font, size, index=0)
    else:
        font = ImageFont.load_default()

    _font_cache[key] = font
    return font

def _get_font_list(size: int, bold: bool = False):
    """返回字体列表"""
    return [_get_font(size, bold)]


# ==================== 绘图工具 ====================


def _rounded_rect(draw: ImageDraw.ImageDraw, xy, radius, fill=None, outline=None, width=1):
    """绘制圆角矩形"""
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _draw_score_arc(img: Image.Image, center, radius, score, color):
    """绘制评分圆弧"""
    draw = ImageDraw.Draw(img)
    x, y = center
    bbox = (x - radius, y - radius, x + radius, y + radius)
    # 背景圆弧
    draw.arc(bbox, start=135, end=405, fill=(50, 50, 50), width=4)
    # 评分圆弧
    if isinstance(score, (int, float)) and score > 0:
        end_angle = 135 + (score / 100) * 270
        draw.arc(bbox, start=135, end=end_angle, fill=color, width=4)


def _get_score_color(score) -> tuple:
    """根据评分返回颜色"""
    if not isinstance(score, (int, float)):
        return TEXT_GRAY
    if score >= 80:
        return SCORE_GREEN
    elif score >= 60:
        return SCORE_YELLOW
    elif score >= 40:
        return SCORE_ORANGE
    else:
        return SCORE_RED


def _get_score_label(score) -> str:
    """根据评分返回中文标签"""
    if not isinstance(score, (int, float)):
        return "未知"
    if score >= 90:
        return "极为可信"
    elif score >= 75:
        return "较为可信"
    elif score >= 60:
        return "一般可信"
    elif score >= 40:
        return "可信度低"
    else:
        return "风险较高"


def _format_number(num) -> str:
    """格式化数字"""
    if not isinstance(num, (int, float)):
        return str(num)
    if num >= 100_000_000:
        return f"{num / 100_000_000:.1f}亿"
    elif num >= 10_000:
        return f"{num / 10_000:.1f}万"
    elif num >= 1_000:
        return f"{num / 1000:.1f}k"
    else:
        return str(int(num))



def _text_width(draw: ImageDraw.ImageDraw, text: str, fonts: list | ImageFont.FreeTypeFont) -> int:
    """获取文本宽度"""
    if isinstance(fonts, ImageFont.FreeTypeFont):
        font = fonts
    else:
        font = fonts[0]
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _draw_text_fallback(draw: ImageDraw.ImageDraw, xy, text: str, fill, fonts: list):
    """绘制文本"""
    draw.text(xy, text, fill=fill, font=fonts[0])


def _strip_emoji(text: str) -> str:
    """激进去除所有 Emoji、特殊符号和无法渲染的字符"""
    if not text: return ""
    result = []
    for char in str(text):
        cp = ord(char)
        # 跳过 SMP 平面 (大部分 emoji 在 0x10000+)
        if cp > 0xFFFF: continue
        # 跳过 Variation Selectors (FE00-FE0F)
        if 0xFE00 <= cp <= 0xFE0F: continue
        # 跳过 Arrows (2190-21FF)
        if 0x2190 <= cp <= 0x21FF: continue
        # 跳过 Misc Technical (2300-23FF) - 包含 ⌛⏰ 等
        if 0x2300 <= cp <= 0x23FF: continue
        # 跳过 Enclosed Alphanumerics (2460-24FF)
        if 0x2460 <= cp <= 0x24FF: continue
        # 跳过 Box Drawing / Block Elements (2500-259F)
        # if 0x2500 <= cp <= 0x259F: continue
        # 跳过 Misc Symbols (2600-26FF) - 包含 ☀⚠♻ 等
        if 0x2600 <= cp <= 0x26FF: continue
        # 跳过 Dingbats (2700-27BF) - 包含 ✅✓✗ 等
        if 0x2700 <= cp <= 0x27BF: continue
        # 跳过 Supplemental Arrows (27F0-27FF, 2900-297F)
        if 0x27F0 <= cp <= 0x27FF: continue
        if 0x2900 <= cp <= 0x297F: continue
        # 跳过 Misc Symbols and Arrows (2B00-2BFF)
        if 0x2B00 <= cp <= 0x2BFF: continue
        # 跳过 CJK Symbols supplement that cause issues
        # 跳过 Private Use Area
        if 0xE000 <= cp <= 0xF8FF: continue
        # 跳过 Specials
        if 0xFFF0 <= cp <= 0xFFFF: continue
        # 跳过特定的箭头和问题符号
        if char in '➝➜➤➡➔➞➝→←↑↓↔↕↗↘↙↖⇒⇐⇑⇓⇔': continue
        result.append(char)
    # 清理多余空格
    cleaned = ''.join(result)
    import re
    cleaned = re.sub(r'  +', ' ', cleaned).strip()
    return cleaned


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, fonts: list, max_width: int) -> list:
    """自动换行文本 (支持 fallback 宽度计算)"""
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        current_line = ""
        for char in paragraph:
            test_line = current_line + char
            if _text_width(draw, test_line, fonts) <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = char
        if current_line:
            lines.append(current_line)
    return lines


def _draw_tag(draw: ImageDraw.ImageDraw, x, y, text, fonts,
              bg_color=TAG_BG, text_color=TEXT_GRAY, border_color=TAG_BORDER):
    """绘制标签 (精准居中)"""
    tw = _text_width(draw, text, fonts)
    # 用实际字体度量计算文本高度
    bbox = draw.textbbox((0, 0), text, font=fonts[0])
    th = bbox[3] - bbox[1]  # 实际文本高度
    text_y_offset = bbox[1]  # 文本顶部偏移（字体 ascent 导致的偏移）
    
    tag_h = max(34, th + 12)  # 标签高度至少比文字多 12px padding
    tag_w = tw + 24
    _rounded_rect(draw, (x, y, x + tag_w, y + tag_h), TAG_RADIUS,
                  fill=bg_color, outline=border_color, width=1)
    
    # 精准居中计算：扣除字体自身的 y 偏移
    tx = x + (tag_w - tw) // 2
    ty = y + (tag_h - th) // 2 - text_y_offset
    _draw_text_fallback(draw, (tx, ty), text, text_color, fonts)
    return tag_w


def _draw_warning_banner(draw: ImageDraw.ImageDraw, x, y, width, text, fonts):
    """绘制警告横幅 (支持多行)"""
    bg_color = (40, 35, 20)
    border_color = (80, 70, 30)
    text_color = SCORE_YELLOW
    
    # 包装文本
    max_text_width = width - 48 - 24
    lines = _wrap_text(draw, text, fonts, max_text_width)
    
    line_h = 32
    banner_h = 20 + len(lines) * line_h
    _rounded_rect(draw, (x, y, x + width, y + banner_h), 12, fill=bg_color, outline=border_color, width=1)
    
    # 绘制警告图标
    _draw_text_fallback(draw, (x + 16, y + 10), "⚠", text_color, fonts)
    
    # 绘制多行文字
    for i, line in enumerate(lines):
        _draw_text_fallback(draw, (x + 52, y + 10 + i * line_h), line, text_color, fonts)
    return banner_h


# ==================== 头像和媒体处理 ====================

async def _download_image(url: str, timeout_sec: int = 30) -> Image.Image | None:
    """异步下载通用图片"""
    if not url:
        return None
    import aiohttp
    try:
        timeout = aiohttp.ClientTimeout(total=timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    return Image.open(io.BytesIO(data)).convert("RGBA")
                else:
                    logger.warning(f"图片下载失败 HTTP {resp.status}: {url}")
    except Exception as e:
        logger.debug(f"图片下载异常: {type(e).__name__}: {e}")
    return None

def _make_circle_avatar(avatar: Image.Image, size: int) -> Image.Image:
    """裁剪为圆形头像"""
    avatar = avatar.resize((size, size), Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size - 1, size - 1), fill=255)
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(avatar, (0, 0), mask)
    return result

def _calculate_score_breakdown(score: int, detail: dict, data: dict | None = None) -> list:
    """逆推并分配分数明细，确保总和等于 score"""
    if data is None:
        data = {}
    age = detail.get("account_age_years") or 0
    fols = detail.get("followers") or 0
    twts = detail.get("tweets") or 0
    eng = detail.get("engagement") or ""
    positives = detail.get("positives") or 0
    complaints = detail.get("complaints") or 0
    pinned_has_url = detail.get("pinned_tweet_has_url", False)
    
    b_age = min(25, int(age * 1.5))
    if fols > 1000000: b_fol = 20
    elif fols > 100000: b_fol = 15
    elif fols > 10000: b_fol = 10
    else: b_fol = 5
    
    if twts > 10000: b_twt = 8
    elif twts > 1000: b_twt = 5
    else: b_twt = 2
    
    b_ver = 10 if detail.get("is_verified") else 0
    b_act = 5 if detail.get("is_active") else 0
    
    if eng == "high": b_eng = 8
    elif eng == "medium": b_eng = 5
    else: b_eng = 2
    
    # 正面好评分数
    if positives >= 10: b_pos = 10
    elif positives >= 5: b_pos = 8
    elif positives >= 1: b_pos = 5
    else: b_pos = 0
    
    # 负面评价扣分
    if complaints >= 5: b_neg = -15
    elif complaints >= 3: b_neg = -10
    elif complaints >= 1: b_neg = -5
    else: b_neg = 0
    
    # 置顶推含外链扣分
    b_pin = -10 if pinned_has_url else 0
    
    # 计算差值
    allocated = 20 + b_age + b_fol + b_twt + b_ver + b_act + b_eng + b_pos + b_neg + b_pin
    diff = score - allocated
    
    # 账号寿命展示
    if age > 0:
        age_label = f"• 账号寿命（{age:.1f}年）"
    else:
        age_label = "• 账号寿命（未知）"
    
    # 互动活跃度展示等级
    eng_labels = {"high": "高", "medium": "中", "low": "低"}
    eng_level = eng_labels.get(eng, "")
    eng_text = f"• 互动活跃度（{eng_level}）" if eng_level else "• 互动活跃度"
    
    # 正面好评展示数量
    pos_text = f"• 正面好评 x{positives}" if positives > 0 else "• 正面好评"
    
    items = [
        ("• 基础分", 20),
        (age_label, b_age),
        (f"• 粉丝量（{_format_number(fols)}）", b_fol),
        (f"• 发帖量（{_format_number(twts)}）", b_twt),
        ("• 蓝V认证", b_ver),
        ("• 近期活跃发帖", b_act),
        (eng_text, b_eng),
        (pos_text, b_pos),
        ("• 负面评价", b_neg),
        ("• 置顶推含外链", b_pin),
    ]
    
    # 仅当有未分配的差值时才显示
    if diff != 0:
        items.append(("• 其它加分" if diff >= 0 else "• 风险扣分", diff))
    
    return items

# ==================== 主渲染函数 ====================

async def render_report(data: dict, blur_media: bool = False) -> bytes:
    import asyncio
    
    score = data.get("score", 0)
    display_name = _strip_emoji(str(data.get("display_name", "未知") or "未知"))
    username = str(data.get("twitter_username", "未知") or "未知")
    bio = _strip_emoji(str(data.get("bio", "") or ""))
    user_eval = _strip_emoji(str(data.get("user_eval", "暂无评价") or "暂无评价"))
    gender = data.get("gender", "")
    avatar_url = data.get("avatar_url", "")
    media_urls = (data.get("media_urls") or [])[:4]

    detail = data.get("score_detail") or {}
    followers = detail.get("followers") or 0
    following = detail.get("following") or 0
    tweets = detail.get("tweets") or 0
    account_age = detail.get("account_age_years") or 0
    is_verified = detail.get("is_verified", False)
    is_welfare = detail.get("is_welfare", False)
    is_active = detail.get("is_active", False)
    account_tags = detail.get("account_tags") or []
    location = str(detail.get("location", "") or "")
    primary_language = str(detail.get("primary_language", "") or "")

    negative_tags = [str(t) for t in (data.get("negative_tags") or [])]
    positive_tags = [str(t) for t in (data.get("positive_tags") or [])]
    is_fushi = data.get("is_fushi", False)
    has_threshold = data.get("has_threshold", False)

    pos_examples = [_strip_emoji(str(e)) for e in (data.get("positive_examples") or [])]
    neg_examples = [_strip_emoji(str(e)) for e in (data.get("complaint_examples") or [])]

    score_color = _get_score_color(score)
    score_label = _get_score_label(score)

    fl_name = _get_font_list(36, bold=True)
    fl_handle = _get_font_list(26)
    fl_body = _get_font_list(26)
    fl_small = _get_font_list(22)
    fl_score = _get_font_list(56, bold=True)
    fl_score_label = _get_font_list(22)
    fl_stat_num = _get_font_list(32, bold=True)
    fl_stat_label = _get_font_list(22)
    fl_section = _get_font_list(28, bold=True)
    fl_tag = _get_font_list(22)

    tmp_img = Image.new("RGB", (IMG_WIDTH, 200))
    tmp_draw = ImageDraw.Draw(tmp_img)
    content_w = IMG_WIDTH - 2 * PADDING
    card_content_w = content_w - 2 * CARD_PADDING

    # ==================== 下载资源 ====================
    logger.debug(f"头像: {bool(avatar_url)}, 媒体数: {len(media_urls)}")
    tasks = [_download_image(avatar_url)]
    for m_url in media_urls:
        tasks.append(_download_image(m_url))
    dl_results = await asyncio.gather(*tasks, return_exceptions=True)
    
    avatar_img = dl_results[0] if isinstance(dl_results[0], Image.Image) else None
    media_imgs = [m for m in dl_results[1:] if isinstance(m, Image.Image)]

    cx_base = PADDING + CARD_PADDING
    score_box_x_base = IMG_WIDTH - PADDING - CARD_PADDING - SCORE_BOX_SIZE

    # ==================== 计算高度 ====================
    # ==================== 计算高度 ====================
    SAFE_RIGHT_MARGIN = 40
    score_box_w_trigger = SCORE_BOX_SIZE + CARD_PADDING + 20 # 避开评分盒子的宽度
    
    header_h = CARD_PADDING + AVATAR_SIZE + 24
    tags_list = []
    if is_active: tags_list.append(("活跃", SCORE_GREEN))
    else: tags_list.append(("不活跃", SCORE_RED))
    
    if gender:
        g_icon = "♂" if gender == "male" else ("♀" if gender == "female" else "")
        g_text = {"male": "男", "female": "女"}.get(gender, gender)
        tags_list.append((f"{g_icon} {g_text}", TEXT_GRAY))
        
    if location: tags_list.append((location, TEXT_GRAY))
    if primary_language: tags_list.append((primary_language, TEXT_GRAY))
    if is_verified: tags_list.append(("✓ 已认证", ACCENT_BLUE))
    if is_welfare: tags_list.append(("福利号", WELFARE_RED))
    if is_fushi: tags_list.append(("付费", SCORE_ORANGE))
    if has_threshold: tags_list.append(("有门槛", SCORE_ORANGE))
    
    for t in account_tags: tags_list.append((str(t), TEXT_GRAY))
    for t in positive_tags: tags_list.append((str(t), SCORE_GREEN))
    for t in negative_tags: tags_list.append((str(t), SCORE_RED))

    # 重构标签布局计算，考虑避开评分盒子
    tag_x, tag_rows = 0, 1
    cy_base = CARD_PADDING # 这里的 cy 是相对于卡片的
    for tag_text, _ in tags_list:
        tw = _text_width(tmp_draw, tag_text, fl_tag) + 24 
        
        current_ty = header_h + (tag_rows - 1) * 44  # 标签行高设为 44px
        limit_w = card_content_w - SAFE_RIGHT_MARGIN
        # 如果标签行在评分盒子的垂直范围内，限制宽度
        if PADDING + current_ty < PADDING + CARD_PADDING + SCORE_BOX_SIZE:
             limit_w = score_box_x_base - cx_base - 12
             
        if tag_x + tw + 12 > limit_w and tag_x > 0:
            tag_rows += 1
            tag_x = 0
        tag_x += tw + 12
    
    tags_area_h = tag_rows * 44 + 20
    
    # 计算警告横幅高度 (动态)
    warning_h = 0
    show_warning = True  # 始终显示检测结果仅供参考
    warning_text = "检索结果仅供参考，存在漏网之鱼。建议自行查看该账号 IP 属地——若内容全为日语却使用 VPN，极有可能是诈骗账号。"
    if show_warning:
        max_text_width = card_content_w - 48 - 24
        warning_lines_count = len(_wrap_text(tmp_draw, warning_text, fl_small, max_text_width))
        warning_banner_h = 20 + warning_lines_count * 32
        warning_h = warning_banner_h + 24 # banner + gap
        
    bio_h = 0
    if bio:
        bio_lines = _wrap_text(tmp_draw, bio, fl_body, card_content_w - SAFE_RIGHT_MARGIN)[:3]
        bio_h = len(bio_lines) * 36 + 24
        
    # Stats 区域固定约 100px
    stats_h = 100 + 40 # stats + padding
    
    header_total = header_h + tags_area_h + warning_h + bio_h + stats_h + 40

    # 中部高度 (评分明细 和 近期媒体 双列)
    col_w = (content_w - 24) // 2
    grid_size = (col_w - 36*2 - 16) // 2
    media_grid_h = 100 + (2 * (grid_size + 16)) + 36 # approx
    mid_card_h = max(100 + 11*44, media_grid_h)  # 取较高者，最多11项评分明细

    # AI 评价卡片高度
    eval_lines = _wrap_text(tmp_draw, user_eval, fl_body, card_content_w - SAFE_RIGHT_MARGIN)[:12] if user_eval else []
    eval_card_h = CARD_PADDING * 2 + 56 + len(eval_lines) * 36

    # 正面/负面评价高度
    examples_h = 0
    if pos_examples:
        examples_h += 80 # title
        for ex in pos_examples[:10]:
            ex_lines = _wrap_text(tmp_draw, f"“{ex}”", fl_body, card_content_w - 40)
            examples_h += len(ex_lines) * 36 + 20
        examples_h += 40
    
    if neg_examples:
        examples_h += 80 # title
        for ex in neg_examples[:10]:
            ex_lines = _wrap_text(tmp_draw, f"“{ex}”", fl_body, card_content_w - 40)
            examples_h += len(ex_lines) * 36 + 20
        examples_h += 40

    footer_h = 80
    total_h = PADDING + header_total + 24 + mid_card_h + 24 + eval_card_h + (24 + examples_h if examples_h > 0 else 0) + 24 + footer_h + PADDING

    # ==================== 开始绘制 ====================
    img = Image.new("RGB", (IMG_WIDTH, total_h), BG_COLOR)
    draw = ImageDraw.Draw(img)
    y = PADDING

    # 1. 头部卡片
    _rounded_rect(draw, (PADDING, y, IMG_WIDTH - PADDING, y + header_total), CARD_RADIUS, fill=CARD_BG, outline=CARD_BORDER, width=2)
    cx, cy = PADDING + CARD_PADDING, y + CARD_PADDING

    draw.ellipse((cx, cy, cx + AVATAR_SIZE, cy + AVATAR_SIZE), fill=(50, 50, 50))
    if avatar_img:
        circle_avatar = _make_circle_avatar(avatar_img, AVATAR_SIZE)
        img.paste(circle_avatar, (cx, cy), circle_avatar)

    _draw_text_fallback(draw, (cx + AVATAR_SIZE + 28, cy + 8), display_name, TEXT_WHITE, fl_name)
    _draw_text_fallback(draw, (cx + AVATAR_SIZE + 28, cy + 52), f"@{username}", TEXT_GRAY, fl_handle)

    score_box_x = score_box_x_base
    _rounded_rect(draw, (score_box_x, cy, score_box_x + SCORE_BOX_SIZE, cy + SCORE_BOX_SIZE), 24, fill=BG_COLOR, outline=score_color, width=4)
    stw = _text_width(draw, str(score), fl_score)
    _draw_text_fallback(draw, (score_box_x + (SCORE_BOX_SIZE - stw) // 2, cy + 20), str(score), score_color, fl_score)
    slw = _text_width(draw, score_label, fl_score_label)
    _draw_text_fallback(draw, (score_box_x + (SCORE_BOX_SIZE - slw) // 2, cy + 92), score_label, score_color, fl_score_label)

    ty, tx = y + header_h, cx
    tag_rows_count = 1
    for tag_text, tag_color in tags_list:
        tw = _text_width(draw, tag_text, fl_tag) + 24
        
        current_ty = ty # ty 已经包含了 header_h
        limit_w = card_content_w - SAFE_RIGHT_MARGIN
        if current_ty < y + CARD_PADDING + SCORE_BOX_SIZE:
            limit_w = score_box_x - cx - 12
            
        if tx + tw + 12 > limit_w and tx > cx:
            tx = cx
            ty += 44
            tag_rows_count += 1
            
        _draw_tag(draw, tx, ty, tag_text, fl_tag, 
                  bg_color=(tag_color[0]//8+15, tag_color[1]//8+15, tag_color[2]//8+15), 
                  text_color=tag_color, 
                  border_color=(min(tag_color[0]//3+30, 255), min(tag_color[1]//3+30, 255), min(tag_color[2]//3+30, 255)))
        tx += tw + 12

    # 绘制警告横幅 (如果需要)
    current_y = y + header_h + tag_rows * 44 + 20
    if show_warning:
        warning_banner_h = _draw_warning_banner(draw, cx, current_y, card_content_w, warning_text, fl_small)
        current_y += warning_banner_h + 24
        
    # 绘制 Bio
    if bio:
        bio_y = current_y
        for i, line in enumerate(bio_lines):
            _draw_text_fallback(draw, (cx, bio_y + i * 36), line, TEXT_GRAY, fl_body)
        current_y += bio_h
        
    # 绘制分割线和统计
    sep_y = current_y + 12
    draw.line((cx, sep_y, IMG_WIDTH - PADDING - CARD_PADDING, sep_y), fill=CARD_BORDER, width=2)
    
    stat_y = sep_y + 32
    stats = [(_format_number(followers), "粉丝"), (_format_number(following), "关注"), (_format_number(tweets), "推文"), (f"{account_age:.1f}年", "账龄")]
    stat_spacing = card_content_w // len(stats)
    for i, (val, label) in enumerate(stats):
        center_x = cx + i * stat_spacing + stat_spacing // 2
        _draw_text_fallback(draw, (center_x - _text_width(draw, val, fl_stat_num) // 2, stat_y), val, TEXT_WHITE, fl_stat_num)
        _draw_text_fallback(draw, (center_x - _text_width(draw, label, fl_stat_label) // 2, stat_y + 44), label, TEXT_MUTED, fl_stat_label)

    y += header_total + 24

    # 2. 中部双列 (左侧 评分明细, 右侧 近期媒体)
    
    # 2.1 评分明细卡片
    _rounded_rect(draw, (PADDING, y, PADDING + col_w, y + int(mid_card_h)), CARD_RADIUS, fill=CARD_BG, outline=CARD_BORDER, width=2)
    _draw_text_fallback(draw, (PADDING + 36, y + 36), "评分明细", TEXT_WHITE, fl_section)
    
    breakdown = _calculate_score_breakdown(score, detail, data)
    by = y + 100
    for title, pts in breakdown:
        
        clean_title = _strip_emoji(title).strip()
        pts_str = f"+{pts}" if pts > 0 else str(pts)
        pts_color = SCORE_GREEN if pts > 0 else (SCORE_RED if pts < 0 else TEXT_GRAY)
        
        _draw_text_fallback(draw, (PADDING + 36, by), clean_title, TEXT_GRAY, fl_small)
        _draw_text_fallback(draw, (PADDING + col_w - 36 - _text_width(draw, pts_str, fl_small), by), pts_str, pts_color, fl_small)
        draw.line((PADDING + 36, by + 36, PADDING + col_w - 36, by + 36), fill=CARD_BORDER, width=1)
        by += 44

    # 2.2 近期媒体卡片
    media_x = PADDING + col_w + 24
    _rounded_rect(draw, (media_x, y, IMG_WIDTH - PADDING, y + int(mid_card_h)), CARD_RADIUS, fill=CARD_BG, outline=CARD_BORDER, width=2)
    _draw_text_fallback(draw, (media_x + 36, y + 36), "近期媒体", TEXT_WHITE, fl_section)
    
    if not media_imgs:
        empty_text = "暂无近期媒体"
        _draw_text_fallback(draw, (media_x + (col_w - _text_width(draw, empty_text, fl_body)) // 2, y + int(mid_card_h)//2 - 18), empty_text, TEXT_MUTED, fl_body)
    else:
        # 绘制网格
        for idx, m_img in enumerate(media_imgs[:4]):
            row, col = idx // 2, idx % 2
            ix = media_x + 36 + col * (grid_size + 16)
            iy = y + 100 + row * (grid_size + 16)
            
            # 裁剪并贴图
            m_img = m_img.convert("RGBA")
            w, h = m_img.size
            s = min(w, h)
            m_img = m_img.crop(((w-s)//2, (h-s)//2, (w+s)//2, (h+s)//2)).resize((grid_size, grid_size), Image.Resampling.LANCZOS)
            
            # 模糊打码处理
            if blur_media:
                m_img = m_img.filter(ImageFilter.GaussianBlur(radius=20))
            
            mask = Image.new("L", (grid_size, grid_size), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, grid_size, grid_size), radius=16, fill=255)
            rounded_m = Image.new("RGBA", (grid_size, grid_size), (0,0,0,0))
            rounded_m.paste(m_img, (0,0), mask)
            
            img.paste(rounded_m, (ix, iy), rounded_m)

    y += int(mid_card_h) + 24

    # 3. AI 评价卡片
    _rounded_rect(draw, (PADDING, y, IMG_WIDTH - PADDING, y + eval_card_h), CARD_RADIUS, fill=CARD_BG, outline=CARD_BORDER, width=2)
    _rounded_rect(draw, (PADDING + 12, y + 12, PADDING + 20, y + eval_card_h - 12), 4, fill=score_color)
    _draw_text_fallback(draw, (PADDING + CARD_PADDING, y + CARD_PADDING), "AI 可信度评价", TEXT_WHITE, fl_section)

    for i, line in enumerate(eval_lines):
        _draw_text_fallback(draw, (PADDING + CARD_PADDING + 16, y + CARD_PADDING + 56 + i * 36), line, TEXT_GRAY, fl_body)

    y += eval_card_h + 24
    
    # 4. 正面/负面评价详细 (如果存在)
    if examples_h > 0:
        _rounded_rect(draw, (PADDING, y, IMG_WIDTH - PADDING, y + examples_h), CARD_RADIUS, fill=CARD_BG, outline=CARD_BORDER, width=2)
        inner_y = y + 24
        
        if pos_examples:
            _draw_text_fallback(draw, (PADDING + CARD_PADDING, inner_y), "正面评价", SCORE_GREEN, fl_section)
            inner_y += 56
            for ex in pos_examples[:10]:
                ex_text = f"“{ex}”"
                ex_lines = _wrap_text(draw, ex_text, fl_body, card_content_w - 40)
                this_ex_h = len(ex_lines) * 36 + 12
                # 绘制小气泡背景
                _rounded_rect(draw, (PADDING + CARD_PADDING - 12, inner_y - 4, IMG_WIDTH - PADDING - CARD_PADDING + 12, inner_y + this_ex_h - 8), 12, fill=(30, 35, 30))
                for i, line in enumerate(ex_lines):
                    _draw_text_fallback(draw, (PADDING + CARD_PADDING, inner_y + i * 36), line, (200, 220, 200), fl_body)
                inner_y += this_ex_h + 8
            inner_y += 20
            
        if neg_examples:
            _draw_text_fallback(draw, (PADDING + CARD_PADDING, inner_y), "负面评价", SCORE_RED, fl_section)
            inner_y += 56
            for ex in neg_examples[:10]:
                ex_text = f"“{ex}”"
                ex_lines = _wrap_text(draw, ex_text, fl_body, card_content_w - 40)
                this_ex_h = len(ex_lines) * 36 + 12
                _rounded_rect(draw, (PADDING + CARD_PADDING - 12, inner_y - 4, IMG_WIDTH - PADDING - CARD_PADDING + 12, inner_y + this_ex_h - 8), 12, fill=(40, 30, 30))
                for i, line in enumerate(ex_lines):
                    _draw_text_fallback(draw, (PADDING + CARD_PADDING, inner_y + i * 36), line, (220, 200, 200), fl_body)
                inner_y += this_ex_h + 8
        
        y += examples_h + 24

    # 5. 底部信息
    footer_text = "X账号评分 flj.info · 数据仅供参考"
    _draw_text_fallback(draw, ((IMG_WIDTH - _text_width(draw, footer_text, fl_small)) // 2, y + 16), footer_text, TEXT_MUTED, fl_small)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
