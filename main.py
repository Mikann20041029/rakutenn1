import os
import random
import requests
import datetime
import re
from xml.sax.saxutils import escape as xml_escape
from openai import OpenAI  # DeepSeek is OpenAI-compatible

# =========================
# Config (GitHub Secrets)
# =========================
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
RAKUTEN_ID = os.getenv("RAKUTEN_ID")  # hb.afl.rakuten.co.jp/hgc/<RAKUTEN_ID>/
HATENA_ID = os.getenv("HATENA_ID")
HATENA_BLOG_ID = os.getenv("HATENA_BLOG_ID")  # example.hatenablog.com (NO https://)
HATENA_API_KEY = os.getenv("HATENA_API_KEY")

def require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"[FATAL] Missing required env: {name}")
    return v

# Fail fast
require_env("DEEPSEEK_API_KEY")
require_env("RAKUTEN_ID")
require_env("HATENA_ID")
require_env("HATENA_BLOG_ID")
require_env("HATENA_API_KEY")

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

# =========================
# Regex helpers
# =========================
PRODUCT_RE = re.compile(r"^\[PRODUCT\]\s*(.+?)\s*$", re.MULTILINE)
KEYWORDS_RE = re.compile(r"^\[KEYWORDS\]\s*(.+?)\s*$", re.MULTILINE)

PRODUCT_LINE_RE = re.compile(r"^\[PRODUCT\].*$", re.MULTILINE)
KEYWORDS_LINE_RE = re.compile(r"^\[KEYWORDS\].*$", re.MULTILINE)

def clamp_title(s: str, max_len: int = 60) -> str:
    s = (s or "").strip()
    if not s:
        return "おすすめ商品の紹介"
    return s[:max_len].rstrip()

def extract_product_and_keywords(text: str) -> tuple[str, str]:
    """
    Pull [PRODUCT] and [KEYWORDS] from model output.
    If missing, fall back safely.
    """
    product = ""
    keywords = ""

    m = PRODUCT_RE.search(text or "")
    if m:
        product = m.group(1).strip()

    m = KEYWORDS_RE.search(text or "")
    if m:
        keywords = m.group(1).strip()

    if not product:
        # Fallback: use first non-empty line as pseudo product keyword
        lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        product = lines[0][:80] if lines else "楽天 人気 商品"

    if not keywords:
        keywords = product

    return product, keywords

def strip_internal_lines(text: str) -> str:
    """
    Remove [PRODUCT]/[KEYWORDS] lines from the public body.
    """
    t = PRODUCT_LINE_RE.sub("", text or "")
    t = KEYWORDS_LINE_RE.sub("", t)
    # normalize excessive blank lines
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t

def build_rakuten_search_affiliate_url(affiliate_id: str, query: str) -> str:
    """
    Affiliate search link. Not the best CVR, but zero cost and no API dependency.
    """
    q = requests.utils.quote(query)
    return (
        f"https://hb.afl.rakuten.co.jp/hgc/{affiliate_id}/"
        f"?pc=https%3A%2F%2Fsearch.rakuten.co.jp%2Fsearch%2Fmall%2F{q}%2F"
    )

def make_hatena_autolink(url: str, title: str = "楽天で検索") -> str:
    """
    Hatena notation tends to autolink better even in text/plain.
    Format: [URL:title=...]
    """
    # Hatena wants raw URL (not escaped); we will XML-escape later.
    safe_title = title.replace("]", "").replace("[", "")
    return f"[{url}:title={safe_title}]"

# =========================
# AI generation
# =========================
def get_ai_content() -> str:
    targets = [
        "コスパ重視の大学生",
        "30代共働き主婦",
        "海外留学準備中の学生",
        "在宅勤務のガジェット好き",
    ]
    categories = [
        "キッチン家電",
        "掃除の時短グッズ",
        "QOL向上アイテム",
        "楽天の隠れた名品",
    ]

    target = random.choice(targets)
    category = random.choice(categories)

    # IMPORTANT:
    # - No fake numeric specs/reviews
    # - No comparison table (hallucination hotspot)
    # - Force [PRODUCT]/[KEYWORDS] for reliable linking
    prompt = f"""
あなたは凄腕のアフィリエイターです。{target}に向けて、楽天市場で買える「具体的な1商品」を1つ選んで紹介してください。

【絶対ルール（守れないなら出力し直せ）】
- 実在しない仕様・数値・レビューを捏造しない（分からないことは断定しない）
- 文章は短めでOK。ダラダラ書かない
- 最後に必ず以下の2行を“そのままの形式”で出力する（改行・表記を変えない）
  [PRODUCT] 商品名（検索で一意に絞れそうな名称）
  [KEYWORDS] 検索用キーワード（複数語OK）

【構成】
1) タイトル（1行）
2) 読者の悩み（具体例を2つ）→共感（2〜4行）
3) この商品を選ぶ理由（メリット3つ）
4) 注意点・デメリット（2つ）※誇張しない
5) 選び方チェックリスト（箇条書き5つ）※比較表は禁止
6) さいごに背中を押す一言（1〜2行）
7) [PRODUCT] ...
8) [KEYWORDS] ...
ジャンル: {category}
"""

    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return resp.choices[0].message.content or ""

# =========================
# Hatena posting
# =========================
def post_hatena(title: str, content: str) -> int:
    url = f"https://blog.hatena.ne.jp/{HATENA_ID}/{HATENA_BLOG_ID}/atom/entry"

    # 1) Extract internal fields (for linking)
    product_name, keywords = extract_product_and_keywords(content)

    # 2) Build affiliate link using KEYWORDS (better than title)
    search_url = build_rakuten_search_affiliate_url(RAKUTEN_ID, keywords)

    # 3) Remove internal lines from public body
    public_body = strip_internal_lines(content)

    # 4) Append clickable link (Hatena notation)
    link_line = make_hatena_autolink(search_url, title="楽天で検索")
    body = (
        f"{public_body}\n\n"
        f"---\n"
        f"【今回の商品（検索用）】{product_name}\n"
        f"{link_line}\n"
    )

    # 5) XML escape title/body to avoid broken Atom XML
    safe_title = xml_escape(clamp_title(title))
    safe_body = xml_escape(body)

    updated = datetime.datetime.now(datetime.timezone.utc).isoformat()

    xml_data = f"""<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom" xmlns:app="http://www.w3.org/2007/app">
  <title>{safe_title}</title>
  <content type="text/plain">{safe_body}</content>
  <updated>{updated}</updated>
  <app:control>
    <app:draft>no</app:draft>
  </app:control>
</entry>"""

    r = requests.post(
        url,
        auth=(HATENA_ID, HATENA_API_KEY),
        data=xml_data.encode("utf-8"),
        headers={"Content-Type": "application/atom+xml; charset=utf-8"},
        timeout=30,
    )

    if r.status_code >= 300:
        # show response snippet so you can debug secrets/blog-id quickly
        raise RuntimeError(
            f"[FATAL] Hatena post failed: status={r.status_code} resp={r.text[:800]}"
        )

    return r.status_code

# =========================
# Run
# =========================
article_text = get_ai_content()

# Title = first non-empty line (strip leading '#')
lines = [ln.strip() for ln in article_text.splitlines() if ln.strip()]
raw_title = lines[0] if lines else "おすすめ商品の紹介"
raw_title = raw_title.lstrip("#").strip()

status = post_hatena(raw_title, article_text)
print(f"[OK] Posted to Hatena: status={status}")
