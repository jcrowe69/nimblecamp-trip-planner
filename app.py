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

# =========================================================
# Page config (ONLY ONCE)
# =========================================================
st.set_page_config(
    page_title="Nimble Camp Trip Planner",
    page_icon="🔥",
    layout="wide",
)

# =========================================================
# Minimal Japanese aesthetic CSS + remove header anchor icons
# =========================================================
st.markdown(
    """
<style>
/* --- overall --- */
html, body, [class*="css"]  {
  font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji","Segoe UI Emoji";
}
.block-container { padding-top: 1.2rem; padding-bottom: 2.0rem; max-width: 1200px; }

/* remove Streamlit header anchor icons (chain/link) */
h1 a, h2 a, h3 a, h4 a, h5 a, h6 a { display: none !important; }

/* soften widgets */
.stTextInput > div > div, .stTextArea > div > div, .stMultiSelect > div > div,
.stSelectbox > div > div, .stNumberInput > div > div {
  border-radius: 12px;
}

/* buttons */
.stButton>button {
  border-radius: 999px;
  padding: 0.55rem 1rem;
  font-weight: 650;
}

/* subtle separators */
.hr-soft {
  height: 1px;
  background: rgba(0,0,0,0.08);
  margin: 1rem 0;
}

/* Card styles */
.nc-card {
  border: 1px solid rgba(0,0,0,0.10);
  border-radius: 16px;
  padding: 14px 14px 10px 14px;
  background: rgba(255,255,255,0.75);
  box-shadow: 0 6px 24px rgba(0,0,0,0.05);
  margin-bottom: 12px;
}
.nc-card h4 {
  margin: 0 0 6px 0;
  font-size: 1.05rem;
  letter-spacing: 0.2px;
}
/* Card image */
.nc-card-img {
  width: 100%;
  border-radius: 14px;
  margin: 10px 0 10px 0;
  display: block;
}

.nc-pill {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid rgba(0,0,0,0.10);
  background: rgba(0,0,0,0.02);
  margin-right: 6px;
  margin-bottom: 6px;
  font-size: 0.85rem;
}
.nc-muted { color: rgba(0,0,0,0.62); }
.nc-small { font-size: 0.90rem; }
</style>
""",
    unsafe_allow_html=True,
)

# =========================================================
# Brand header (headings removed)
# =========================================================
st.caption("Build a personalised Japanese-style camp cookbook based on the tools you pack.")
st.markdown('<div class="hr-soft"></div>', unsafe_allow_html=True)

# =========================================================
# Defaults
# =========================================================
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

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SOTOTripApp/2.0)"}
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

# =========================================================
# Basic helpers
# =========================================================
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

def merge_unique(existing: List[str], new_items: List[str]) -> List[str]:
    seen = set(existing)
    out = list(existing)
    for x in new_items:
        if x and x not in seen:
            out.append(x)
            seen.add(x)
    return out

# =========================================================
# Search upgrades
# =========================================================
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
        clean(r.get("meal")),
    ]
    return normalize_for_search(" ".join([p for p in parts if p]))

def did_you_mean(query: str, candidates: List[str], n: int = 8) -> List[str]:
    q = normalize_for_search(query)
    if not q:
        return []
    return difflib.get_close_matches(q, candidates, n=n, cutoff=0.55)

# =========================================================
# Classification
# =========================================================
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
    animal_hit = any(
        x in blob for x in ["beef", "pork", "chicken", "fish", "salmon", "tuna", "shrimp", "bacon", "sausage", "meat"]
    )
    if veg_hit and not animal_hit:
        return "Vegetarian"
    return "Other"

# =========================================================
# Shopping list helpers
# =========================================================
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

    merged = []
    for _k, lines in agg.items():
        merged.append(max(lines, key=len))

    buckets = {"Proteins": [], "Vegetables & Herbs": [], "Sauces, Oils & Spices": [], "Staples": [], "Other": []}
    for line in merged:
        s = norm(line)
        if any(x in s for x in ["chicken", "beef", "pork", "fish", "tuna", "salmon", "egg", "bacon", "sausage", "tofu", "venison", "lamb"]):
            buckets["Proteins"].append(line)
        elif any(
            x in s
            for x in [
                "onion","garlic","ginger","tomato","mushroom","pepper","carrot","cabbage","lettuce","spinach",
                "spring onion","scallion","chive","herb","lemon","lime",
            ]
        ):
            buckets["Vegetables & Herbs"].append(line)
        elif any(
            x in s
            for x in [
                "soy","miso","sauce","oil","vinegar","salt","pepper","spice","seasoning","sesame","chili","sugar","mirin","sake","ketchup","mayo",
            ]
        ):
            buckets["Sauces, Oils & Spices"].append(line)
        elif any(x in s for x in ["rice", "noodle", "bread", "tortilla", "pasta", "flour", "starch"]):
            buckets["Staples"].append(line)
        else:
            buckets["Other"].append(line)

    out = []
    for b in ["Proteins", "Vegetables & Herbs", "Sauces, Oils & Spices", "Staples", "Other"]:
        lines = sorted(buckets[b], key=lambda x: norm(x))
        if lines:
            out.append((b, lines))
    return out

# =========================================================
# PDF helpers
# =========================================================
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
    c.setFont(FONT, SMALL_SIZE)
    c.drawCentredString(PAGE_W / 2, MARGIN / 2, str(page_num))

def build_a5_pdf(menu_full: List[Dict[str, Any]], title: str, subtitle: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A5)
    page_num = 1

    # Cover
    c.setFont(FONT_B, 22)
    c.drawCentredString(PAGE_W / 2, PAGE_H * 0.70, title)
    c.setFont(FONT, 11)
    if subtitle:
        c.drawCentredString(PAGE_W / 2, PAGE_H * 0.64, subtitle)
    c.setFont(FONT, 9)
    c.drawCentredString(PAGE_W / 2, PAGE_H * 0.58, time.strftime("%Y-%m-%d"))
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

        meta = " • ".join([x for x in [tool, main_ing] if x])  # NO URL in PDF header
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

# =========================================================
# Data load / pool ops
# =========================================================
@st.cache_data(show_spinner=False)
def load_master(path: str) -> List[Dict[str, Any]]:
    d = json.load(open(path, "r", encoding="utf-8"))
    pool = [r for r in d.get("recipes", []) if not r.get("error") and r.get("url")]
    for r in pool:
        r["meal"] = classify_meal(r)
        r["tool"] = classify_tool(r)
        r["main_ing"] = classify_main(r)
        r["_search_blob"] = build_search_blob(r)
        r["_title_norm"] = normalize_for_search(r.get("title_en") or r.get("title_jp") or "")
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
    random.seed(seed)

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
    daily_slots = daily_slots[:need]

    ordered: List[Dict[str, Any]] = []
    idx = 0
    for d, m in daily_slots:
        r = picked[idx]
        idx += 1
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

# =========================================================
# Sidebar controls
# =========================================================
with st.sidebar:
    st.subheader("Master DB")
    master_path = st.text_input("Master JSON path", MASTER_JSON_DEFAULT)
    load_btn = st.button("Load / Reload DB")
    clear_cache_btn = st.button("Clear cache")

    st.markdown("---")
    st.subheader("Trip settings")
    days = st.number_input("Days", min_value=1, max_value=30, value=DEFAULT_DAYS, step=1)

    meal_tags = st.multiselect("Meal tags to pull from", MEAL_BUCKETS, default=DEFAULT_MEAL_TAGS)
    meals_per_day = st.number_input("Meals per day", min_value=1, max_value=3, value=DEFAULT_MEALS_PER_DAY, step=1)

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
            "Meals used each day",
            MEAL_BUCKETS,
            default=default_fixed,
        )
        if len(fixed_meal_slots) != int(meals_per_day):
            st.warning("Fixed schedule: pick exactly the same number of meals as Meals/day.")

    tools = st.multiselect("Tools you have", TOOL_BUCKETS, default=ALL_TOOLS_EXCEPT_DUTCH)
    tools = [t for t in tools if t != "Dutch oven"]  # you normally don't bring it

    prefer = st.multiselect("Prefer main ingredient", MAIN_BUCKETS, default=DEFAULT_PREFER)
    avoid = st.multiselect("Avoid main ingredient", MAIN_BUCKETS, default=DEFAULT_AVOID)

    mode = st.selectbox("Random mode", ["weighted", "random"], index=0)
    seed = st.number_input("Random seed", min_value=1, max_value=999999, value=42, step=1)

    st.markdown("---")
    st.subheader("PDF")
    pdf_title = st.text_input("PDF Title", value=f"{int(days)}-Day Camp Cookbook")
    pdf_subtitle = st.text_input("PDF Subtitle (optional)", value="")

    st.markdown("---")
    generate_btn = st.button("Generate / Refresh Menu")
    pdf_btn = st.button("Generate A5 PDF")

# =========================================================
# Session init
# =========================================================
if "pool" not in st.session_state:
    st.session_state.pool = []
if "menu" not in st.session_state:
    st.session_state.menu = []
if "locked_urls" not in st.session_state:
    st.session_state.locked_urls = []

if clear_cache_btn:
    st.cache_data.clear()
    st.success("Cache cleared. Now reload DB.")
    st.stop()

# =========================================================
# Load DB
# =========================================================
if load_btn or (not st.session_state.pool):
    try:
        st.session_state.pool = load_master(master_path)
        st.success(f"Loaded {len(st.session_state.pool)} recipes.")
    except Exception as e:
        st.error(f"Failed to load JSON: {e}")

pool = st.session_state.pool
if not pool:
    st.warning("Load your master JSON first (sidebar).")
    st.stop()

POOL_BY_URL = {r.get("url"): r for r in pool if r.get("url")}

filtered = filter_pool(pool, meal_tags=meal_tags, tools=tools, prefer=prefer, avoid=avoid)
st.caption(f"Eligible recipes after filters: **{len(filtered)}**")

# =========================================================
# Browse & lock + Locked panel
# =========================================================
colA, colB = st.columns([2, 1])

with colB:
    st.subheader("Locked picks")
    st.write("Lock favourites so they stay in the menu when you randomize.")
    locked_text = st.text_area(
        "Locked recipe URLs (one per line)",
        value="\n".join(st.session_state.locked_urls),
        height=240,
    )
    st.session_state.locked_urls = sorted(set([ln.strip() for ln in locked_text.splitlines() if ln.strip()]))
    st.write(f"Locked URLs: **{len(st.session_state.locked_urls)}**")

with colA:
    st.subheader("Browse & lock recipes")

    browse_df = pd.DataFrame([{
        "lock": False,
        "title": (r.get("title_en") or r.get("title_jp") or "")[:220],
        "meal": r.get("meal"),
        "tool": r.get("tool"),
        "main": r.get("main_ing"),
        "url": r.get("url"),
        "search_blob": r.get("_search_blob", ""),
        "title_norm": r.get("_title_norm", ""),
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
                mask &= browse_df["search_blob"].str.contains(re.escape(t), na=False)
            results = browse_df[mask]

            if results.empty and fuzzy:
                title_norms = browse_df["title_norm"].fillna("").tolist()
                suggestions = did_you_mean(q, title_norms, n=12)
                if suggestions:
                    sug_tokens = set()
                    for s in suggestions[:6]:
                        for t in tokenize(s):
                            sug_tokens.add(t)
                    if sug_tokens:
                        mask2 = pd.Series([False] * len(browse_df))
                        for t in sug_tokens:
                            mask2 |= browse_df["search_blob"].str.contains(re.escape(t), na=False)
                        results = browse_df[mask2]
                    st.info("No exact matches. Showing closest results.")
                else:
                    st.warning("No matches. Try fewer words, or JP tags like キムチ / 鍋 / メスティン.")

            browse_df = results

    display_df = browse_df.drop(columns=["search_blob", "title_norm"])

    edited_browse = st.data_editor(
        display_df,
        use_container_width=True,
        height=360,
        num_rows="fixed",
        column_config={
            "lock": st.column_config.CheckboxColumn("Lock"),
            "url": st.column_config.TextColumn("url", width="large"),
            "title": st.column_config.TextColumn("title", width="large"),
        },
        disabled=["title", "meal", "tool", "main", "url"],
        key="browse_editor",
    )

    selected_urls = edited_browse.loc[edited_browse["lock"] == True, "url"].dropna().tolist()
    unselected_urls = edited_browse.loc[edited_browse["lock"] == False, "url"].dropna().tolist()

    b1, b2, b3 = st.columns([1, 1, 1])
    with b1:
        if st.button("Lock selected"):
            st.session_state.locked_urls = sorted(set(merge_unique(st.session_state.locked_urls, selected_urls)))
            st.success(f"Locked {len(selected_urls)} recipes in this view.")
    with b2:
        if st.button("Unlock selected"):
            cur = set(st.session_state.locked_urls or [])
            cur_minus = cur - set(unselected_urls)
            st.session_state.locked_urls = sorted(cur_minus)
            st.success("Unlocked unchecked recipes from this view.")
    with b3:
        if st.button("Clear locks"):
            st.session_state.locked_urls = []
            st.success("Cleared all locked recipes.")

    st.caption("Search, tick recipes, click **Lock selected**, then generate the menu.")

st.markdown('<div class="hr-soft"></div>', unsafe_allow_html=True)

# =========================================================
# Generate menu
# =========================================================
if generate_btn:
    if schedule_mode.startswith("Fixed") and len(fixed_meal_slots) != int(meals_per_day):
        st.error("Fixed schedule mismatch: set Meals/day and select the same number of meals.")
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
            st.success(f"Menu created: {len(st.session_state.menu)} meals")
        except Exception as e:
            st.error(str(e))

# =========================================================
# Proposed Menu — CARD LAYOUT (NO TABLE, NO URL DISPLAY)
# =========================================================
def group_by_day(menu: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    days_map: Dict[int, List[Dict[str, Any]]] = {}
    for r in menu:
        d = int(r.get("day", 0))
        days_map.setdefault(d, []).append(r)
    # keep stable order within day
    for d in days_map:
        days_map[d] = sorted(days_map[d], key=lambda x: (MEAL_BUCKETS.index(x.get("meal")) if x.get("meal") in MEAL_BUCKETS else 99))
    return dict(sorted(days_map.items(), key=lambda kv: kv[0]))

def card_html(title: str, meal: str, tool: str, main_ing: str, jp_title: str = "", img_src: str = "") -> str:
    pills = []
    if meal: pills.append(f'<span class="nc-pill">{meal}</span>')
    if tool: pills.append(f'<span class="nc-pill">{tool}</span>')
    if main_ing: pills.append(f'<span class="nc-pill">{main_ing}</span>')
    pills_html = "".join(pills)

    jp_line = f'<div class="nc-muted nc-small">{jp_title}</div>' if jp_title else ""
    img_html = f'<img class="nc-card-img" src="{img_src}" />' if img_src else ""

    return f"""
<div class="nc-card">
  <h4>{title}</h4>
  {jp_line}
  {img_html}
  <div style="margin-top:8px;">{pills_html}</div>
</div>
"""

if st.session_state.menu:
    st.subheader("Your trip plan")
    st.caption("Cards are your final plan. (We hide URLs here — PDF still uses the right recipes.)")

    # sanity
    ok_ing = sum(1 for r in st.session_state.menu if (r.get("ingredients_en") or []))
    ok_meth = sum(1 for r in st.session_state.menu if (r.get("method_en") or []))
    st.caption(f"Sanity check: ingredients {ok_ing}/{len(st.session_state.menu)} | method {ok_meth}/{len(st.session_state.menu)}")

    day_map = group_by_day(st.session_state.menu)

    for d, items in day_map.items():
        st.markdown(f"### Day {d}")
        for r in items:
            title_r = clean(r.get("title_en")) or clean(r.get("title_jp")) or "Untitled"
            meal = clean(r.get("meal"))
            tool = clean(r.get("tool")) or classify_tool(r)
            main_ing = clean(r.get("main_ing")) or classify_main(r)
            jp_title = clean(r.get("title_jp"))
            img_url = clean(r.get("image_url"))

            st.markdown(
                card_html(title_r, meal, tool, main_ing, jp_title=jp_title, img_src=img_url),
                unsafe_allow_html=True
            )

        st.markdown('<div class="hr-soft"></div>', unsafe_allow_html=True)

    # allow download menu json (keeps URLs internally, but user doesn't see them in the cards)
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

# =========================================================
# PDF build
# =========================================================
if pdf_btn:
    if not st.session_state.menu:
        st.error("No menu yet. Click Generate / Refresh Menu first.")
    else:
        title = (pdf_title or "").strip() or f"{int(days)}-Day Camp Cookbook"
        subtitle = (pdf_subtitle or "").strip()
        with st.spinner("Generating A5 PDF (images + shopping list)…"):
            pdf_bytes = build_a5_pdf(st.session_state.menu, title=title, subtitle=subtitle)

        st.success("PDF generated.")
        st.download_button(
            "Download A5 PDF booklet",
            data=pdf_bytes,
            file_name=f"Trip_Cookbook_A5_{int(days)}d_{int(meals_per_day)}mpd_{mode}_seed{int(seed)}.pdf",
            mime="application/pdf",
        )
