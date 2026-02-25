import io
import json
import os
import random
import re
import time
import difflib
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st
from PIL import Image
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

# ============================================================
# Page config + Minimal Japanese aesthetic
# ============================================================
st.set_page_config(
    page_title="Nimble Camp Trip Planner",
    page_icon="🔥",
    layout="wide",
)

st.markdown(
    """
<style>
/* overall page padding */
.block-container { padding-top: 1.6rem; padding-bottom: 2.5rem; }

/* reduce Streamlit vertical gaps */
div[data-testid="stVerticalBlock"] { gap: 0.75rem; }

/* soften widgets */
.stTextInput > div > div, .stTextArea > div > div, .stMultiSelect > div > div,
.stSelectbox > div > div, .stNumberInput > div > div {
  border-radius: 10px;
}

/* buttons: minimal pill */
.stButton>button {
  border-radius: 999px;
  padding: 0.55rem 1rem;
  font-weight: 600;
}

/* headings: calmer */
h1, h2, h3 { letter-spacing: 0.2px; }

/* soften dataframe edges */
div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] { border-radius: 12px; overflow: hidden; }

/* tighten caption spacing */
[data-testid="stCaptionContainer"] { margin-top: -0.25rem; }
</style>
""",
    unsafe_allow_html=True,
)

st.markdown("### Nimble Camp")
st.markdown("# Trip Planner")
st.caption("Build a personalised Japanese-style camp cookbook based on the tools you pack.")
st.divider()

# ============================================================
# Nimble Camp product links (update these to real URLs anytime)
# ============================================================
PRODUCT_LINKS = {
    "Messtin": "https://nimblecamp.com",
    "Frying pan": "https://nimblecamp.com",
    "Skillet": "https://nimblecamp.com",
    "Sierra Cup": "https://nimblecamp.com",
    "Hot sandwich maker": "https://nimblecamp.com",
    "Smoker": "https://nimblecamp.com",
    "Dutch oven": "https://nimblecamp.com",
}

# ============================================================
# Defaults
# ============================================================
DEFAULT_DAYS = 5
DEFAULT_MEAL_TAGS = ["Breakfast", "Lunch", "Dinner"]

DEFAULT_MEALS_PER_DAY = 2
DEFAULT_FIXED_SLOTS_2 = ["Lunch", "Dinner"]
DEFAULT_FIXED_SLOTS_1 = ["Dinner"]
DEFAULT_FIXED_SLOTS_3 = ["Breakfast", "Lunch", "Dinner"]

ALL_TOOLS_EXCEPT_DUTCH = ["Messtin", "Frying pan", "Skillet", "Sierra Cup", "Hot sandwich maker", "Smoker"]
DEFAULT_PREFER = ["Chicken", "Fish"]
DEFAULT_AVOID: List[str] = []

MASTER_JSON_DEFAULT = "sotorecipe_verbatim_JP_EN_ALL_V4.json"
IMG_CACHE_DIR = "img_cache"
os.makedirs(IMG_CACHE_DIR, exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NimbleCampTripApp/1.0)"}
TIMEOUT = 25

FONT = "Helvetica"
FONT_B = "Helvetica-Bold"

# A5 layout
PAGE_W, PAGE_H = A5
MARGIN = 10 * mm
FOOTER_H = 8 * mm
GAP = 3 * mm
TITLE_SIZE = 14
H_SIZE = 10.5
BODY_SIZE = 9.5
SMALL_SIZE = 8.5
IMAGE_MAX_H = 45 * mm
IMAGE_MAX_W = PAGE_W - 2 * MARGIN

MEAL_BUCKETS = ["Breakfast", "Lunch", "Dinner"]
TOOL_BUCKETS = ["Messtin", "Frying pan", "Skillet", "Dutch oven", "Sierra Cup", "Hot sandwich maker", "Smoker"]
MAIN_BUCKETS = ["Vegetarian", "Chicken", "Fish", "Meat", "Other"]

JP_MEAL_MAP = {
    "朝ごはん": "Breakfast",
    "朝ご飯": "Breakfast",
    "昼ごはん": "Lunch",
    "昼ご飯": "Lunch",
    "ランチ": "Lunch",
    "夜ごはん": "Dinner",
    "夜ご飯": "Dinner",
    "晩ごはん": "Dinner",
    "夕食": "Dinner",
    "ディナー": "Dinner",
}
JP_TOOL_MAP = {
    "メスティン": "Messtin",
    "フライパン": "Frying pan",
    "スキレット": "Skillet",
    "ダッチオーブン": "Dutch oven",
    "ダッチオープン": "Dutch oven",
    "シェラカップ": "Sierra Cup",
    "ホットサンドメーカー": "Hot sandwich maker",
    "スモーカー": "Smoker",
}

# ============================================================
# Helpers
# ============================================================
def clean(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x.strip()
    return str(x).strip()

def safe_list(x: Any) -> List[str]:
    if x is None:
        return []
    if isinstance(x, list):
        return [clean(i) for i in x if clean(i)]
    if isinstance(x, str):
        s = x.strip()
        return [s] if s else []
    return [clean(x)]

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()

def normalize_for_search(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[’'`]", "", s)
    s = re.sub(r"[^a-z0-9\u3040-\u30ff\u4e00-\u9fff\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def tokenize(s: str) -> List[str]:
    s = normalize_for_search(s)
    toks = [t for t in s.split(" ") if t]
    out = []
    for t in toks:
        if len(t) > 3 and t.endswith("s"):
            out.append(t[:-1])
        out.append(t)
    seen = set()
    final = []
    for t in out:
        if t not in seen:
            seen.add(t)
            final.append(t)
    return final

def did_you_mean(query: str, candidates: List[str], n: int = 8) -> List[str]:
    q = normalize_for_search(query)
    if not q:
        return []
    return difflib.get_close_matches(q, candidates, n=n, cutoff=0.55)

def build_search_blob(r: Dict[str, Any]) -> str:
    parts = [
        clean(r.get("title_en")),
        clean(r.get("title_jp")),
        " ".join(safe_list(r.get("tags_en"))),
        " ".join(safe_list(r.get("tags_jp"))),
        " ".join(safe_list(r.get("kitchenwares_en"))),
        " ".join(safe_list(r.get("kitchenwares_jp"))),
        clean(r.get("tool")),
        clean(r.get("main_ing")),
    ]
    return normalize_for_search(" ".join([p for p in parts if p]))

# ============================================================
# Classification
# ============================================================
def classify_meal(r: Dict[str, Any]) -> str:
    m = clean(r.get("meal"))
    if m in MEAL_BUCKETS:
        return m
    tags_jp = safe_list(r.get("tags_jp"))
    tags_en = safe_list(r.get("tags_en"))
    for t in tags_jp:
        if t in JP_MEAL_MAP:
            return JP_MEAL_MAP[t]
    blob = norm(" ".join(tags_en + [clean(r.get("title_en"))]))
    if "breakfast" in blob:
        return "Breakfast"
    if "lunch" in blob:
        return "Lunch"
    if "dinner" in blob:
        return "Dinner"
    return "Dinner"

def classify_tool(r: Dict[str, Any]) -> str:
    t = clean(r.get("tool"))
    if t in TOOL_BUCKETS:
        return t
    tags_jp = safe_list(r.get("tags_jp")) + safe_list(r.get("kitchenwares_jp"))
    for x in tags_jp:
        if x in JP_TOOL_MAP:
            return JP_TOOL_MAP[x]
    blob = norm(" ".join(safe_list(r.get("kitchenwares_en")) + safe_list(r.get("tags_en"))))
    if "messtin" in blob or "mess tin" in blob:
        return "Messtin"
    if "frying pan" in blob:
        return "Frying pan"
    if "skillet" in blob:
        return "Skillet"
    if "dutch oven" in blob:
        return "Dutch oven"
    if "sierra" in blob and "cup" in blob:
        return "Sierra Cup"
    if "hot sandwich" in blob:
        return "Hot sandwich maker"
    if "smoker" in blob:
        return "Smoker"
    return "Other"

def classify_main(r: Dict[str, Any]) -> str:
    mi = clean(r.get("main_ing"))
    if mi:
        return mi
    blob = norm(" ".join(safe_list(r.get("ingredients_en")) + safe_list(r.get("tags_en"))))
    if "chicken" in blob:
        return "Chicken"
    if any(x in blob for x in ["fish", "salmon", "tuna", "shrimp", "octopus", "squid"]):
        return "Fish"
    if any(x in blob for x in ["beef", "pork", "lamb", "bacon", "sausage", "venison", "meat"]):
        return "Meat"
    veg_hit = any(x in blob for x in ["tofu", "mushroom", "eggplant", "vegetable", "veggie"])
    animal_hit = any(x in blob for x in ["beef", "pork", "chicken", "fish", "salmon", "tuna", "shrimp", "bacon", "sausage", "meat"])
    if veg_hit and not animal_hit:
        return "Vegetarian"
    return "Other"

# ============================================================
# Shopping list helpers
# ============================================================
def ingredient_key(line: str) -> str:
    s = norm(line)
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\b(g|kg|ml|l|tbsp|tsp|cup|cups|pcs|pc)\b", "", s)
    s = re.sub(r"\b\d+(\.\d+)?\b", "", s)
    s = re.sub(r"[^a-z0-9\s/+-]", "", s)
    return re.sub(r"\s+", " ", s).strip()

def bucket_shopping_list(recipes: List[Dict[str, Any]]) -> List[Tuple[str, List[str]]]:
    agg: Dict[str, List[str]] = {}
    raw_lines: List[str] = []
    for r in recipes:
        raw_lines.extend(safe_list(r.get("ingredients_en")))

    for line in raw_lines:
        k = ingredient_key(line)
        if not k:
            continue
        agg.setdefault(k, []).append(line)

    merged = [max(lines, key=len) for lines in agg.values()]

    buckets = {"Proteins": [], "Vegetables & Herbs": [], "Sauces, Oils & Spices": [], "Staples": [], "Other": []}
    for line in merged:
        s = norm(line)
        if any(x in s for x in ["chicken", "beef", "pork", "fish", "tuna", "salmon", "egg", "bacon", "sausage", "tofu", "venison", "lamb"]):
            buckets["Proteins"].append(line)
        elif any(x in s for x in ["onion","garlic","ginger","tomato","mushroom","pepper","carrot","cabbage","lettuce","spinach","spring onion","scallion","chive","herb","lemon","lime"]):
            buckets["Vegetables & Herbs"].append(line)
        elif any(x in s for x in ["soy","miso","sauce","oil","vinegar","salt","pepper","spice","seasoning","sesame","chili","sugar","mirin","sake","ketchup","mayo"]):
            buckets["Sauces, Oils & Spices"].append(line)
        elif any(x in s for x in ["rice","noodle","bread","tortilla","pasta","flour","starch"]):
            buckets["Staples"].append(line)
        else:
            buckets["Other"].append(line)

    out: List[Tuple[str, List[str]]] = []
    for b in ["Proteins", "Vegetables & Herbs", "Sauces, Oils & Spices", "Staples", "Other"]:
        lines = sorted(buckets[b], key=lambda x: norm(x))
        if lines:
            out.append((b, lines))
    return out

# ============================================================
# PDF helpers
# ============================================================
def cache_path_for_url(url: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9]+", "_", url)[-90:]
    return os.path.join(IMG_CACHE_DIR, f"{name}.jpg")

def fetch_image(url: str) -> Optional[ImageReader]:
    if not url:
        return None
    cp = cache_path_for_url(url)
    try:
        if os.path.exists(cp) and os.path.getsize(cp) > 5000:
            return ImageReader(cp)
    except Exception:
        pass
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        img.save(cp, format="JPEG", quality=82, optimize=True)
        return ImageReader(cp)
    except Exception:
        return None

def scale_to_fit(iw: float, ih: float, max_w: float, max_h: float) -> Tuple[float, float]:
    if iw <= 0 or ih <= 0:
        return (0.0, 0.0)
    s = min(max_w / iw, max_h / ih, 1.0)
    return (iw * s, ih * s)

def wrap(text: str, font: str, size: float, max_w: float) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    words = text.split(" ")
    out, cur = [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if pdfmetrics.stringWidth(t, font, size) <= max_w:
            cur = t
        else:
            if cur:
                out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    return out

def draw_lines(c: canvas.Canvas, x: float, y: float, lines: List[str], font: str, size: float, leading: float) -> float:
    c.setFont(font, size)
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y

def draw_footer(c: canvas.Canvas, page_num: int):
    c.setFont(FONT, 7.5)
    c.drawCentredString(PAGE_W / 2, MARGIN / 2 + 3, "nimblecamp.com")
    c.drawCentredString(PAGE_W / 2, MARGIN / 2 - 6, str(page_num))

def build_a5_pdf(menu_full: List[Dict[str, Any]], title: str, subtitle: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A5)
    page_num = 1

    # Cover
    c.setFont(FONT_B, 24)
    c.drawCentredString(PAGE_W / 2, PAGE_H * 0.73, "Nimble Camp")
    c.setFont(FONT_B, 18)
    c.drawCentredString(PAGE_W / 2, PAGE_H * 0.66, title)
    if subtitle:
        c.setFont(FONT, 11)
        c.drawCentredString(PAGE_W / 2, PAGE_H * 0.61, subtitle)
    c.setFont(FONT, 9)
    c.drawCentredString(PAGE_W / 2, PAGE_H * 0.55, time.strftime("%Y-%m-%d"))
    c.showPage()
    page_num += 1

    # Shopping list
    shopping = bucket_shopping_list(menu_full)
    c.setFont(FONT_B, 16)
    c.drawString(MARGIN, PAGE_H - MARGIN, "Master Shopping List")
    y = PAGE_H - MARGIN - 22
    for bucket, lines in shopping:
        if y < MARGIN + FOOTER_H + 40:
            draw_footer(c, page_num)
            c.showPage()
            page_num += 1
            y = PAGE_H - MARGIN
        c.setFont(FONT_B, 11)
        c.drawString(MARGIN, y, bucket)
        y -= 14
        c.setFont(FONT, 10)
        for ln in lines:
            if y < MARGIN + FOOTER_H + 18:
                draw_footer(c, page_num)
                c.showPage()
                page_num += 1
                y = PAGE_H - MARGIN
                c.setFont(FONT, 10)
            c.drawString(MARGIN + 6, y, "• " + ln)
            y -= 12
        y -= 6
    draw_footer(c, page_num)
    c.showPage()
    page_num += 1

    # Recipes (one per page)
    for r in menu_full:
        day = int(r.get("day", 0))
        meal = clean(r.get("meal"))
        title_r = clean(r.get("title_en")) or clean(r.get("title_jp")) or "Untitled"
        url = clean(r.get("url"))
        tool = clean(r.get("tool")) or classify_tool(r)
        main_ing = clean(r.get("main_ing")) or classify_main(r)

        y = PAGE_H - MARGIN
        c.setFont(FONT_B, TITLE_SIZE)
        header = f"DAY {day} — {meal}: {title_r}"
        y = draw_lines(
            c,
            MARGIN,
            y,
            wrap(header, FONT_B, TITLE_SIZE, PAGE_W - 2 * MARGIN),
            FONT_B,
            TITLE_SIZE,
            TITLE_SIZE * 1.15,
        ) - GAP

        meta = " • ".join([x for x in [tool, main_ing, url] if x])
        c.setFont(FONT, 8.5)
        y = draw_lines(c, MARGIN, y, wrap(meta, FONT, 8.5, PAGE_W - 2 * MARGIN), FONT, 8.5, 10) - GAP

        img = fetch_image(clean(r.get("image_url")))
        if img:
            iw, ih = img.getSize()
            dw, dh = scale_to_fit(iw, ih, IMAGE_MAX_W, IMAGE_MAX_H)
            if dw > 0 and dh > 0 and (y - dh) > (MARGIN + FOOTER_H + 20):
                c.drawImage(img, MARGIN, y - dh, width=dw, height=dh, preserveAspectRatio=True, mask="auto")
                y -= (dh + GAP)

        # Ingredients
        c.setFont(FONT_B, H_SIZE)
        c.drawString(MARGIN, y, "Ingredients")
        y -= (H_SIZE * 1.5)
        c.setFont(FONT, BODY_SIZE)
        for line in safe_list(r.get("ingredients_en")):
            y = draw_lines(
                c,
                MARGIN,
                y,
                wrap("• " + line, FONT, BODY_SIZE, PAGE_W - 2 * MARGIN),
                FONT,
                BODY_SIZE,
                BODY_SIZE * 1.25,
            )
            if y < (MARGIN + FOOTER_H + 55):
                break

        y -= GAP

        # Method
        c.setFont(FONT_B, H_SIZE)
        c.drawString(MARGIN, y, "Method")
        y -= (H_SIZE * 1.5)
        c.setFont(FONT, BODY_SIZE)
        for i, step in enumerate(safe_list(r.get("method_en")), start=1):
            y = draw_lines(
                c,
                MARGIN,
                y,
                wrap(f"{i}. {step}", FONT, BODY_SIZE, PAGE_W - 2 * MARGIN),
                FONT,
                BODY_SIZE,
                BODY_SIZE * 1.25,
            )
            y -= 1
            if y < (MARGIN + FOOTER_H + 30):
                break

        draw_footer(c, page_num)
        c.showPage()
        page_num += 1

    c.save()
    buf.seek(0)
    return buf.read()

# ============================================================
# Data load / pool ops
# ============================================================
@st.cache_data(show_spinner=False)
def load_master(path: str) -> List[Dict[str, Any]]:
    d = json.load(open(path, "r", encoding="utf-8"))
    pool = [r for r in d.get("recipes", []) if not r.get("error") and r.get("url")]
    for r in pool:
        r["meal"] = classify_meal(r)
        r["tool"] = classify_tool(r)
        r["main_ing"] = classify_main(r)
    return pool

def filter_pool(pool: List[Dict[str, Any]], meal_tags: List[str], tools: List[str], prefer: List[str], avoid: List[str]) -> List[Dict[str, Any]]:
    out = []
    for r in pool:
        if meal_tags and r.get("meal") not in meal_tags:
            continue
        if tools and r.get("tool") not in tools:
            continue
        if avoid and r.get("main_ing") in avoid:
            continue
        out.append(r)

    if prefer:
        out.sort(key=lambda r: (0 if r.get("main_ing") in prefer else 1, norm(r.get("title_en") or r.get("title_jp"))))
    return out

def build_daily_slots(days: int, meal_tags: List[str], meals_per_day: int, schedule_mode: str, fixed_slots: List[str]) -> List[Tuple[int, str]]:
    """
    IMPORTANT: total slots = days * meals_per_day always.
    meal_tags only influences which meal labels appear in those slots (not how many).
    """
    slots: List[Tuple[int, str]] = []
    meal_tags = [m for m in (meal_tags or []) if m in MEAL_BUCKETS]
    if not meal_tags:
        meal_tags = ["Dinner"]

    meals_per_day = max(1, min(3, int(meals_per_day)))

    if schedule_mode.startswith("Fixed"):
        chosen = [m for m in (fixed_slots or []) if m in MEAL_BUCKETS]
        if not chosen:
            chosen = ["Dinner"]
        chosen = chosen[:meals_per_day]
        for d in range(1, days + 1):
            for m in chosen:
                slots.append((d, m))
        return slots

    idx = 0
    for d in range(1, days + 1):
        for _ in range(meals_per_day):
            slots.append((d, meal_tags[idx % len(meal_tags)]))
            idx += 1
    return slots

def propose_menu(
    pool_filtered: List[Dict[str, Any]],
    days: int,
    meal_tags: List[str],
    meals_per_day: int,
    schedule_mode: str,
    fixed_meal_slots: List[str],
    prefer: List[str],
    seed: int,
    locked_urls: List[str],
    mode: str,
) -> List[Dict[str, Any]]:
    need = int(days) * int(meals_per_day)
    random.seed(int(seed))

    by_url = {r["url"]: r for r in pool_filtered if r.get("url")}
    locked_urls = [u for u in (locked_urls or []) if u in by_url]
    locked_recipes = [by_url[u] for u in locked_urls]

    def score(r: Dict[str, Any]) -> float:
        s = 0.0
        if mode == "weighted" and prefer and r.get("main_ing") in prefer:
            s += 5.0
        s += random.random()
        return s

    candidates = [r for r in pool_filtered if r.get("url") and r["url"] not in set(locked_urls)]
    candidates.sort(key=score, reverse=True)

    picked: List[Dict[str, Any]] = []
    used = set()

    for r in locked_recipes:
        if r["url"] not in used:
            picked.append(r)
            used.add(r["url"])

    for r in candidates:
        if len(picked) >= need:
            break
        if r["url"] in used:
            continue
        picked.append(r)
        used.add(r["url"])

    if len(picked) < need:
        raise ValueError(f"Not enough recipes matched filters. Needed {need}, got {len(picked)}. Relax filters.")

    daily_slots = build_daily_slots(
        days=int(days),
        meal_tags=meal_tags,
        meals_per_day=int(meals_per_day),
        schedule_mode=schedule_mode,
        fixed_slots=fixed_meal_slots,
    )

    ordered: List[Dict[str, Any]] = []
    for i, (d, m) in enumerate(daily_slots):
        r = picked[i]
        ordered.append({
            "day": d,
            "meal": m,
            "url": r.get("url"),
            "title_en": r.get("title_en", ""),
            "title_jp": r.get("title_jp", ""),
            "tool": r.get("tool", ""),
            "main_ing": r.get("main_ing", ""),
            "image_url": r.get("image_url", ""),
            "ingredients_en": r.get("ingredients_en", []) or [],
            "method_en": r.get("method_en", []) or [],
        })
    return ordered

def hydrate_from_pool(url: str, fallback: Dict[str, Any], pool_by_url: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    base = pool_by_url.get(url)
    out = dict(fallback)
    out["url"] = url

    if not base:
        out["ingredients_en"] = out.get("ingredients_en", []) or []
        out["method_en"] = out.get("method_en", []) or []
        return out

    out["title_en"] = base.get("title_en", "") or base.get("title_jp", "")
    out["title_jp"] = base.get("title_jp", "")
    out["tool"] = base.get("tool", "") or classify_tool(base)
    out["main_ing"] = base.get("main_ing", "") or classify_main(base)
    out["image_url"] = base.get("image_url", "")
    out["ingredients_en"] = base.get("ingredients_en", []) or []
    out["method_en"] = base.get("method_en", []) or []
    return out

# ============================================================
# Sidebar (Plan)
# ============================================================
with st.sidebar:
    st.header("Master DB")
    master_path = st.text_input("Master JSON path", MASTER_JSON_DEFAULT)
    load_btn = st.button("Load / Reload DB")
    clear_cache_btn = st.button("Clear cache (if DB updated)")

    st.divider()
    st.header("Trip Settings")

    days = st.number_input("Days", min_value=1, max_value=30, value=DEFAULT_DAYS, step=1)
    meal_tags = st.multiselect("Meal tags to pull from (filter)", MEAL_BUCKETS, default=DEFAULT_MEAL_TAGS)

    meals_per_day = st.number_input("Meals per day to generate", min_value=1, max_value=3, value=DEFAULT_MEALS_PER_DAY, step=1)

    schedule_mode = st.selectbox(
        "Meal schedule",
        ["Fixed (pick exact meals)", "Auto (rotate through selected meal tags)"],
        index=0,
    )

    if meals_per_day == 1:
        default_fixed = DEFAULT_FIXED_SLOTS_1
    elif meals_per_day == 3:
        default_fixed = DEFAULT_FIXED_SLOTS_3
    else:
        default_fixed = DEFAULT_FIXED_SLOTS_2

    fixed_meal_slots = default_fixed
    if schedule_mode.startswith("Fixed"):
        fixed_meal_slots = st.multiselect(
            "Meals to use each day (must match Meals per day)",
            MEAL_BUCKETS,
            default=default_fixed,
        )
        if len(fixed_meal_slots) != int(meals_per_day):
            st.warning("Fixed schedule: pick exactly the same number of meals as 'Meals per day'.")

    tools = st.multiselect("Tools you have", TOOL_BUCKETS, default=ALL_TOOLS_EXCEPT_DUTCH)
    tools = [t for t in tools if t != "Dutch oven"]

    prefer = st.multiselect("Prefer main ingredient", MAIN_BUCKETS, default=DEFAULT_PREFER)
    avoid = st.multiselect("Avoid main ingredient", MAIN_BUCKETS, default=DEFAULT_AVOID)

    mode = st.selectbox("Random mode", ["weighted", "random"], index=0)
    seed = st.number_input("Random seed (same seed = same menu)", min_value=1, max_value=999999, value=42, step=1)

    st.divider()
    st.header("PDF Output")
    pdf_title = st.text_input("PDF Title", value=f"{int(days)}-Day Camp Cookbook")
    pdf_subtitle = st.text_input(
        "PDF Subtitle",
        value=f"Meals/day: {int(meals_per_day)} | Tags: {', '.join(meal_tags) if meal_tags else 'Any'} | Tools: {', '.join(tools) if tools else 'Any'} | Mode: {mode} | Seed: {seed}",
    )

    st.divider()
    st.header("Actions")
    generate_btn = st.button("Generate / Refresh Proposed Menu")
    pdf_btn = st.button("Generate A5 PDF from Approved Menu")

# ============================================================
# Session init
# ============================================================
if "pool" not in st.session_state:
    st.session_state.pool = []
if "menu" not in st.session_state:
    st.session_state.menu = []
if "locked_urls" not in st.session_state:
    st.session_state.locked_urls = []

if clear_cache_btn:
    st.cache_data.clear()
    st.success("Cache cleared. Click Load / Reload DB.")
    st.stop()

# ============================================================
# Load DB
# ============================================================
if load_btn or (not st.session_state.pool):
    try:
        st.session_state.pool = load_master(master_path)
        st.success(f"Loaded {len(st.session_state.pool)} recipes from {master_path}")
    except Exception as e:
        st.error(f"Failed to load JSON: {e}")

pool = st.session_state.pool
if not pool:
    st.warning("Load your master JSON first (sidebar).")
    st.stop()

POOL_BY_URL = {r.get("url"): r for r in pool if r.get("url")}

filtered = filter_pool(pool, meal_tags=meal_tags, tools=tools, prefer=prefer, avoid=avoid)
st.caption(f"Eligible recipes after filters: **{len(filtered)}**")

colA, colB = st.columns([2, 1])

# ============================================================
# Locked picks (Right)
# ============================================================
with colB:
    st.subheader("Locked picks")
    st.write("Lock favourites so they stay in the menu when you randomize.")

    locked_text = st.text_area(
        "Locked recipe URLs (one per line)",
        value="\n".join(st.session_state.locked_urls),
        height=220,
    )
    st.session_state.locked_urls = sorted(set([ln.strip() for ln in locked_text.splitlines() if ln.strip()]))

    st.caption(f"Locked URLs: **{len(st.session_state.locked_urls)}**")

    if st.button("Clear all locks"):
        st.session_state.locked_urls = []
        st.success("Cleared all locked recipes.")
        st.rerun()

# ============================================================
# Browse & lock (Left) - upgraded table + drop-in apply button
# ============================================================
with colA:
    st.subheader("Browse & lock recipes")

    browse_df = pd.DataFrame([{
        "lock": False,
        "title": (r.get("title_en") or r.get("title_jp") or "")[:220],
        "meal": r.get("meal"),
        "tool": r.get("tool"),
        "main": r.get("main_ing"),
        "url": r.get("url"),
        "_blob": build_search_blob(r),
        "_title_norm": normalize_for_search(r.get("title_en") or r.get("title_jp") or ""),
    } for r in filtered])

    left_s, right_s = st.columns([2, 1])
    with left_s:
        q = st.text_input("Search (title/tags/tool/main) — JP + EN", "")
    with right_s:
        fuzzy = st.checkbox("Fuzzy (typo-tolerant)", value=True)

    locked_set = set(st.session_state.locked_urls or [])
    if not browse_df.empty:
        browse_df.loc[browse_df["url"].isin(locked_set), "lock"] = True

    if q.strip() and not browse_df.empty:
        toks = tokenize(q)
        if toks:
            mask = pd.Series([True] * len(browse_df))
            for t in toks:
                mask &= browse_df["_blob"].str.contains(re.escape(t), na=False)
            results = browse_df[mask]

            if results.empty and fuzzy:
                title_norms = browse_df["_title_norm"].fillna("").tolist()
                suggestions = did_you_mean(q, title_norms, n=12)
                if suggestions:
                    sug_tokens = set()
                    for s in suggestions[:6]:
                        for t in tokenize(s):
                            sug_tokens.add(t)
                    if sug_tokens:
                        mask2 = pd.Series([False] * len(browse_df))
                        for t in sug_tokens:
                            mask2 |= browse_df["_blob"].str.contains(re.escape(t), na=False)
                        results = browse_df[mask2]
                    st.info("No exact matches. Showing closest results. Try fewer keywords for best results.")
                else:
                    st.warning("No matches. Try fewer words, or search JP tags like キムチ / 鍋 / メスティン.")
            browse_df = results

    display_df = browse_df.drop(columns=["_blob", "_title_norm"], errors="ignore")

    edited = st.data_editor(
        display_df,
        use_container_width=True,
        height=380,
        num_rows="fixed",
        hide_index=True,
        column_config={
            "lock": st.column_config.CheckboxColumn("Lock", help="Tick to lock/unlock this recipe"),
            "url": st.column_config.TextColumn("url", width="large"),
            "title": st.column_config.TextColumn("title", width="large"),
        },
        disabled=["title", "meal", "tool", "main", "url"],
        key="browse_editor",
    )

    # ---- Single “apply locks from this view” button (drop-in workflow)
    urls_in_view = edited["url"].dropna().tolist()
    checked_urls = edited.loc[edited["lock"] == True, "url"].dropna().tolist()

    c1, c2 = st.columns([1, 2])
    with c1:
        if st.button("Apply locks from this view"):
            current = set(st.session_state.locked_urls or [])
            current -= set(urls_in_view)           # remove any locks that were in this view
            current |= set(checked_urls)           # add checked locks
            st.session_state.locked_urls = sorted(current)
            st.success(f"Updated locks. Total locked: {len(st.session_state.locked_urls)}")
            st.rerun()

    with c2:
        st.caption("Tick recipes, click **Apply locks from this view**, then generate the menu.")

# ============================================================
# Generate menu
# ============================================================
if generate_btn:
    if schedule_mode.startswith("Fixed") and len(fixed_meal_slots) != int(meals_per_day):
        st.error("Fixed schedule mismatch: set 'Meals per day' and select the same number of meals.")
    else:
        try:
            st.session_state.menu = propose_menu(
                pool_filtered=filtered,
                days=int(days),
                meal_tags=meal_tags,
                meals_per_day=int(meals_per_day),
                schedule_mode=schedule_mode,
                fixed_meal_slots=fixed_meal_slots,
                prefer=prefer,
                seed=int(seed),
                locked_urls=st.session_state.locked_urls,
                mode=mode,
            )
            st.success(f"Proposed menu created: {len(st.session_state.menu)} meals")
        except Exception as e:
            st.error(str(e))

# ============================================================
# Proposed menu editor (rehydrate on URL changes)
# ============================================================
if st.session_state.menu:
    st.divider()
    st.subheader("Proposed menu")

    used_tools = sorted({clean(r.get("tool")) for r in st.session_state.menu if clean(r.get("tool"))})
    if used_tools:
        st.markdown("### Gear used")
        for t in used_tools:
            link = PRODUCT_LINKS.get(t)
            if link:
                st.markdown(f"• **{t}** → [Nimble Camp]({link})")
            else:
                st.markdown(f"• **{t}**")

    menu_full = st.session_state.menu
    menu_df = pd.DataFrame(menu_full)

    edited_df = st.data_editor(
        menu_df[["day", "meal", "title_en", "tool", "main_ing", "url"]],
        use_container_width=True,
        height=420,
        num_rows="fixed",
        hide_index=True,
        key="menu_editor",
    )

    new_menu: List[Dict[str, Any]] = []
    for i, row in edited_df.iterrows():
        old = menu_full[i]
        updated = dict(old)

        updated["day"] = int(row.get("day", updated.get("day", 1)))
        updated["meal"] = clean(row.get("meal", updated.get("meal", "Dinner")))

        new_url = clean(row.get("url", updated.get("url", "")))
        if new_url and new_url != updated.get("url"):
            updated = hydrate_from_pool(new_url, updated, POOL_BY_URL)
        else:
            updated["title_en"] = clean(row.get("title_en", updated.get("title_en", "")))
            updated["tool"] = clean(row.get("tool", updated.get("tool", "")))
            updated["main_ing"] = clean(row.get("main_ing", updated.get("main_ing", "")))

        updated["ingredients_en"] = updated.get("ingredients_en", []) or []
        updated["method_en"] = updated.get("method_en", []) or []
        new_menu.append(updated)

    st.session_state.menu = new_menu

    ok_ing = sum(1 for r in st.session_state.menu if (r.get("ingredients_en") or []))
    ok_meth = sum(1 for r in st.session_state.menu if (r.get("method_en") or []))
    st.caption(f"Sanity check: ingredients present in {ok_ing}/{len(st.session_state.menu)} | method present in {ok_meth}/{len(st.session_state.menu)}")

    menu_json = {
        "days": int(days),
        "meal_tags": meal_tags,
        "meals_per_day": int(meals_per_day),
        "schedule_mode": schedule_mode,
        "fixed_meal_slots": fixed_meal_slots,
        "tools": tools,
        "prefer": prefer,
        "avoid": avoid,
        "seed": int(seed),
        "mode": mode,
        "locked_urls": st.session_state.locked_urls,
        "menu": st.session_state.menu,
    }
    st.download_button(
        "Download approved menu JSON",
        data=json.dumps(menu_json, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name="trip_menu_approved.json",
        mime="application/json",
    )

# ============================================================
# PDF build
# ============================================================
if pdf_btn:
    if not st.session_state.menu:
        st.error("No proposed menu yet. Click 'Generate / Refresh Proposed Menu' first.")
    else:
        title = (pdf_title or "").strip() or f"{int(days)}-Day Camp Cookbook"
        subtitle = (pdf_subtitle or "").strip()

        with st.spinner("Generating A5 PDF (includes images + shopping list)…"):
            pdf_bytes = build_a5_pdf(st.session_state.menu, title=title, subtitle=subtitle)

        st.success("PDF generated.")
        st.download_button(
            "Download A5 PDF booklet",
            data=pdf_bytes,
            file_name=f"Trip_Cookbook_A5_{int(days)}d_{int(meals_per_day)}mpd_{mode}_seed{int(seed)}.pdf",
            mime="application/pdf",
        )
