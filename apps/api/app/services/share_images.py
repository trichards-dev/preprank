"""Server-side PNG share card generation using Pillow.

All images: 1200x630px (standard OG size).
Brand: dark bg (#1A1A1E), crimson (#C22032), white text, PREP/RANK wordmark.
"""
from __future__ import annotations

import hashlib
import os
import time
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Brand colors
BG_COLOR = (26, 26, 30)  # #1A1A1E charcoal
CRIMSON = (194, 32, 50)  # #C22032
WHITE = (255, 255, 255)
GRAY = (107, 114, 128)  # #6B7280 steel-gray
DARK_GRAY = (50, 50, 55)

WIDTH = 1200
HEIGHT = 630

# Font paths — try bundled fonts, fall back to default
FONT_DIR = Path(__file__).parent / "fonts"

# Cache settings
CACHE_DIR = Path(__file__).parent.parent.parent / "share_cache"
CACHE_TTL = 3600  # 1 hour


def _get_font(bold: bool = False, size: int = 36) -> ImageFont.FreeTypeFont:
    """Get font, falling back to default if bundled fonts missing."""
    try:
        if bold:
            font_path = FONT_DIR / "BarlowCondensed-Bold.ttf"
            if font_path.exists():
                return ImageFont.truetype(str(font_path), size)
        else:
            font_path = FONT_DIR / "SourceSans3-Regular.ttf"
            if font_path.exists():
                return ImageFont.truetype(str(font_path), size)
    except Exception:
        pass
    # Fall back to default
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def _new_card() -> tuple[Image.Image, ImageDraw.Draw]:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    return img, draw


def _draw_wordmark(draw: ImageDraw.Draw, x: int = 40, y: int = 30) -> None:
    font = _get_font(bold=True, size=28)
    draw.text((x, y), "PREP", fill=WHITE, font=font)
    w = draw.textlength("PREP", font=font)
    draw.text((x + w, y), "/", fill=CRIMSON, font=font)
    w2 = draw.textlength("/", font=font)
    draw.text((x + w + w2, y), "RANK", fill=WHITE, font=font)


def _draw_rating_badge(draw: ImageDraw.Draw, x: int, y: int, rating: float, size: int = 80) -> None:
    """Draw a circular rating badge."""
    if rating >= 14:
        color = CRIMSON
    elif rating >= 12:
        color = (234, 88, 12)  # orange
    elif rating >= 10:
        color = (202, 138, 4)  # yellow
    else:
        color = GRAY

    draw.ellipse([x, y, x + size, y + size], fill=color)
    font = _get_font(bold=True, size=size // 3)
    text = f"{rating:.1f}"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((x + (size - tw) // 2, y + (size - th) // 2 - 2), text, fill=WHITE, font=font)


def _to_bytes(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _cache_key(*parts) -> str:
    return hashlib.md5(":".join(str(p) for p in parts).encode()).hexdigest()


def _get_cached(key: str) -> bytes | None:
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / f"{key}.png"
    if path.exists() and (time.time() - path.stat().st_mtime) < CACHE_TTL:
        return path.read_bytes()
    return None


def _set_cached(key: str, data: bytes) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    (CACHE_DIR / f"{key}.png").write_bytes(data)


# --- Card Generators ---

def generate_team_card(
    school_name: str,
    rating: float,
    rank: int,
    division: str,
    classification: str,
    record: str = "",
    playoff_prob: float | None = None,
) -> bytes:
    key = _cache_key("team", school_name, rating, rank)
    cached = _get_cached(key)
    if cached:
        return cached

    img, draw = _new_card()
    _draw_wordmark(draw)

    # Rating badge
    _draw_rating_badge(draw, 60, 120, rating, size=140)

    # Team name
    font_big = _get_font(bold=True, size=56)
    draw.text((230, 130), school_name, fill=WHITE, font=font_big)

    # Rank and division
    font_med = _get_font(bold=False, size=32)
    draw.text((230, 200), f"#{rank} in Division {division} ({classification})", fill=GRAY, font=font_med)

    # Record
    if record:
        draw.text((230, 245), record, fill=GRAY, font=font_med)

    # Playoff probability
    if playoff_prob is not None:
        font_prob = _get_font(bold=True, size=48)
        draw.text((60, 350), f"{playoff_prob:.1f}%", fill=CRIMSON, font=font_prob)
        font_label = _get_font(bold=False, size=24)
        draw.text((60, 410), "Playoff Probability", fill=GRAY, font=font_label)

    # Bottom bar
    draw.rectangle([0, HEIGHT - 50, WIDTH, HEIGHT], fill=CRIMSON)
    font_small = _get_font(bold=True, size=20)
    draw.text((40, HEIGHT - 40), "prep-rank.com", fill=WHITE, font=font_small)

    data = _to_bytes(img)
    _set_cached(key, data)
    return data


def generate_game_card(
    home_team: str,
    away_team: str,
    home_rating: float,
    away_rating: float,
    home_win_prob: float | None = None,
    game_date: str = "",
) -> bytes:
    key = _cache_key("game", home_team, away_team, home_rating, away_rating)
    cached = _get_cached(key)
    if cached:
        return cached

    img, draw = _new_card()
    _draw_wordmark(draw)

    font_big = _get_font(bold=True, size=48)
    font_med = _get_font(bold=False, size=28)
    font_label = _get_font(bold=True, size=22)

    # "WHAT'S AT STAKE" headline
    draw.text((40, 80), "WHAT'S AT STAKE", fill=CRIMSON, font=_get_font(bold=True, size=36))

    # Home team (left side)
    _draw_rating_badge(draw, 80, 170, home_rating, size=100)
    draw.text((200, 180), home_team, fill=WHITE, font=font_big)
    draw.text((200, 240), "HOME", fill=GRAY, font=font_label)

    # VS
    draw.text((WIDTH // 2 - 20, 310), "VS", fill=GRAY, font=_get_font(bold=True, size=36))

    # Away team (right-aligned conceptually, but left-positioned for readability)
    _draw_rating_badge(draw, 80, 360, away_rating, size=100)
    draw.text((200, 370), away_team, fill=WHITE, font=font_big)
    draw.text((200, 430), "AWAY", fill=GRAY, font=font_label)

    # Win probability
    if home_win_prob is not None:
        draw.text((700, 200), f"{home_win_prob:.0f}%", fill=WHITE, font=_get_font(bold=True, size=64))
        draw.text((700, 270), "Win Probability", fill=GRAY, font=font_med)

    # Date
    if game_date:
        draw.text((700, 400), game_date, fill=GRAY, font=font_med)

    # Bottom bar
    draw.rectangle([0, HEIGHT - 50, WIDTH, HEIGHT], fill=CRIMSON)
    draw.text((40, HEIGHT - 40), "prep-rank.com", fill=WHITE, font=_get_font(bold=True, size=20))

    data = _to_bytes(img)
    _set_cached(key, data)
    return data


def generate_pickem_results_card(
    user_name: str,
    correct: int,
    total: int,
    school_name: str | None = None,
    badge_name: str | None = None,
    week: int = 0,
) -> bytes:
    key = _cache_key("pickem", user_name, correct, total, week)
    cached = _get_cached(key)
    if cached:
        return cached

    img, draw = _new_card()
    _draw_wordmark(draw)

    font_big = _get_font(bold=True, size=64)
    font_med = _get_font(bold=True, size=36)
    font_sm = _get_font(bold=False, size=28)

    # Title
    draw.text((40, 90), f"PICK'EM WEEK {week}" if week else "PICK'EM RESULTS", fill=CRIMSON, font=font_med)

    # Score
    pct = round(correct / total * 100) if total > 0 else 0
    draw.text((40, 170), f"{correct}/{total}", fill=WHITE, font=_get_font(bold=True, size=120))
    draw.text((40, 310), f"{pct}% Accuracy", fill=GRAY, font=font_med)

    # User name
    draw.text((40, 380), user_name, fill=WHITE, font=font_med)

    # School
    if school_name:
        draw.text((40, 430), f"Representing {school_name}", fill=GRAY, font=font_sm)

    # Badge
    if badge_name:
        draw.rectangle([600, 170, 1100, 280], fill=DARK_GRAY, outline=CRIMSON, width=2)
        draw.text((630, 200), f"Badge Earned: {badge_name}", fill=CRIMSON, font=font_sm)

    # Bottom bar
    draw.rectangle([0, HEIGHT - 50, WIDTH, HEIGHT], fill=CRIMSON)
    draw.text((40, HEIGHT - 40), "prep-rank.com", fill=WHITE, font=_get_font(bold=True, size=20))

    data = _to_bytes(img)
    _set_cached(key, data)
    return data


def generate_school_leaderboard_card(
    school_name: str,
    rank: int,
    correct: int,
    total: int,
    participants: int,
) -> bytes:
    key = _cache_key("leaderboard", school_name, rank, correct)
    cached = _get_cached(key)
    if cached:
        return cached

    img, draw = _new_card()
    _draw_wordmark(draw)

    font_big = _get_font(bold=True, size=56)
    font_med = _get_font(bold=True, size=36)
    font_sm = _get_font(bold=False, size=28)

    # Headline
    draw.text((40, 100), f"#{rank} PREDICTION SCHOOL", fill=CRIMSON, font=font_med)

    # School name
    draw.text((40, 170), school_name, fill=WHITE, font=font_big)

    # Stats
    pct = round(correct / total * 100) if total > 0 else 0
    draw.text((40, 280), f"{correct}/{total} correct ({pct}%)", fill=GRAY, font=font_sm)
    draw.text((40, 330), f"{participants} participants", fill=GRAY, font=font_sm)

    # Bottom bar
    draw.rectangle([0, HEIGHT - 50, WIDTH, HEIGHT], fill=CRIMSON)
    draw.text((40, HEIGHT - 40), "prep-rank.com", fill=WHITE, font=_get_font(bold=True, size=20))

    data = _to_bytes(img)
    _set_cached(key, data)
    return data


def generate_badge_card(
    user_name: str,
    badge_name: str,
    badge_description: str,
) -> bytes:
    key = _cache_key("badge", user_name, badge_name)
    cached = _get_cached(key)
    if cached:
        return cached

    img, draw = _new_card()
    _draw_wordmark(draw)

    font_big = _get_font(bold=True, size=64)
    font_med = _get_font(bold=True, size=36)
    font_sm = _get_font(bold=False, size=28)

    # Badge icon area
    draw.ellipse([WIDTH // 2 - 60, 100, WIDTH // 2 + 60, 220], fill=CRIMSON)
    draw.text((WIDTH // 2 - 15, 135), "\u2605", fill=WHITE, font=_get_font(bold=True, size=50))

    # Badge name
    bbox = draw.textbbox((0, 0), badge_name, font=font_big)
    tw = bbox[2] - bbox[0]
    draw.text(((WIDTH - tw) // 2, 250), badge_name, fill=WHITE, font=font_big)

    # Description
    bbox2 = draw.textbbox((0, 0), badge_description, font=font_sm)
    tw2 = bbox2[2] - bbox2[0]
    draw.text(((WIDTH - tw2) // 2, 340), badge_description, fill=GRAY, font=font_sm)

    # User
    draw.text(((WIDTH - draw.textlength(user_name, font=font_med)) // 2, 420), user_name, fill=WHITE, font=font_med)

    # Bottom bar
    draw.rectangle([0, HEIGHT - 50, WIDTH, HEIGHT], fill=CRIMSON)
    draw.text((40, HEIGHT - 40), "prep-rank.com", fill=WHITE, font=_get_font(bold=True, size=20))

    data = _to_bytes(img)
    _set_cached(key, data)
    return data
