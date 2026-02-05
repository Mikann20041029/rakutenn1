import os
import random
import requests
import datetime
import re
from xml.sax.saxutils import escape as xml_escape
from openai import OpenAI  # DeepSeek is OpenAI-compatible

# --- Config (GitHub Secrets) ---
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
RAKUTEN_ID = os.getenv("RAKUTEN_ID")  # affiliate id for hb.afl.rakuten.co.jp/hgc/<RAKUTEN_ID>/
HATENA_ID = os.getenv("HATENA_ID")
HATENA_BLOG_ID = os.getenv("HATENA_BLOG_ID")  # example.hatenablog.com
HATENA_API_KEY = os.getenv("HATENA_API_KEY")

def require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env: {name}")
    return v

# Validate required envs early (fail fast)
require_env("DEEPSEEK_API_KEY")
require_env("RAKUTEN_ID")
require_env("HATENA_ID")
require_env("HATENA_BLOG_ID")
require_env("HATENA_API_KEY")

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

# --- Helpers ---
PRODUCT_RE = re.compile(r"^\[PRODUCT\]\s*(.+?)\s*$", re.MULTILINE)
KEYWORDS_RE = re.compile(r"^\[KEYWORDS\]\s*(.+?)\s*$", re.MULTILINE)

def clamp_title(s: str, max_len: int = 60) -> str:
    s = (s or "").strip()
    if not s:
        return "おすすめ商品の紹介"
    return s[:max_len].rstrip()

def extract_product_and_keywords(text: str) -> tuple[str, str]:
    product = ""
    keywords = ""

    m = PRODUCT_RE.search(text or "")
    if m:
        product = m.group(1).strip()

    m = KEYWORDS_RE.search(text or "")
    if m:
        keywords = m.group(1).strip()

    # Fallbacks (avoid empty)
    if not product:
        # try to use first non-empty line as product-ish fallback
        lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        product = lines[0][:80] if lines else "楽天 人気 商品"

    if not keywords:
        keywords = product

    return product, keywords

def build_rakuten_search_affiliate_url(affiliate_id: str, query: str) -> str:
    # NOTE: This is still a search link (lower CVR than product page),
    # but keeps you off API limits and avoids item-ID dependency.
    q = requests.utils.quote(query)
    return (
        f"https://hb.afl.rakuten.co.jp/hgc/{affiliate_id}/"
        f"?pc=https%3A%2F%2Fsearch.rakuten.co.jp%2Fsearch%2Fmall%2F{q}%2F"
    )

# --- Core ---
def get_ai_content() -> str:
    targets = ["コスパ重視の大学生", "30代共働き主婦", "海外留学準備中の学生", "在宅勤務のガジェット好き"]
    categories = ["キッチン家電", "掃除の時短グッズ", "QOL向上アイテム", "楽天の隠れた名品"]  # Amazonは避けた方が無難

    target = random.choice(targets)
    category = random.choice(categories)

    # IMPORTANT: remove "comparison table" to reduce hallucination risk
    # Force explicit product & keywords lines at the end for reliable parsing
    prompt = f"""
あなたは凄腕のアフィリエイターです。{target}に向けて、楽天市場で買える「具体的な1商品」を1つ選んで紹介してください。

【絶対ルール（守れないなら出力し直せ）】
- 実在しない仕様・数値・レビューを捏造しない（分からないことは断定しない）
- 文章は短めでOK。ダラダラ書かない
- 最後に必ず以下の2行を“そのままの形式”で出力する
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
        # optional: keep it stable
        temperature=0.7,
    )
    return resp.choices[0].message.content or ""

def post_hatena(title: str, content: str) -> int:
    hatena_id = HATENA_ID
    blog_id = HATENA_BLOG_ID
    api_key = HATENA_API_KEY

    url = f"https://blog.hatena.ne.jp/{hatena_id}/{blog_id}/atom/entry"

    product_name, keywords = extract_product_and_keywords(content)

    # Use keywords for search (usually better than title)
    search_url = build_rakuten_search_affiliate_url(RAKUTEN_ID, keywords)

    # Append affiliate link block
    body = (
        f"{content}\n\n"
        f"---\n"
        f"【楽天で検索】\n"
        f"{search_url}\n"
    )

    # Atom XML must be escaped (otherwise &,<,> break the request)
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
        auth=(hatena_id, api_key),
        data=xml_data.encode("utf-8"),
        headers={"Content-Type": "application/atom+xml; charset=utf-8"},
        timeout=30,
    )

    if r.status_code >= 300:
        # Make failures obvious in Actions logs
        raise RuntimeError(f"Hatena post failed: {r.status_code} body={r.text[:500]}")
    return r.status_code

# --- Run ---
article_text = get_ai_content()

# Title: first non-empty line (not necessarily '# ')
lines = [ln.strip() for ln in article_text.splitlines() if ln.strip()]
raw_title = lines[0] if lines else "おすすめ商品の紹介"
raw_title = raw_title.lstrip("#").strip()

post_hatena(raw_title, article_text)
