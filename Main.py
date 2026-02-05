import os
import random
import requests
import datetime
from openai import OpenAI # DeepSeekはOpenAI互換のライブラリで動きます

# --- 設定（GitHub Secretsから読み込み） ---
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
RAKUTEN_ID = os.getenv("RAKUTEN_ID")
HATENA_ID = os.getenv("HATENA_ID")
HATENA_BLOG_ID = os.getenv("HATENA_BLOG_ID") # example.hatenablog.com
HATENA_API_KEY = os.getenv("HATENA_API_KEY")

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

def get_ai_content():
    # ターゲットを絞り、Googleが好む「専門性」を出す
    targets = ["コスパ重視の大学生", "30代共働き主婦", "海外留学準備中の学生", "在宅勤務のガジェット好き"]
    categories = ["キッチン家電", "掃除の時短グッズ", "QOL向上アイテム", "Amazon/楽天の隠れた名品"]
    
    target = random.choice(targets)
    category = random.choice(categories)

    prompt = f"""
    あなたは凄腕のアフィリエイターです。{target}に向けて、楽天市場で買える{category}の紹介記事を書いてください。
    【構成】
    1. 読者の悩みに共感するキャッチーなタイトル
    2. 商品の「意外なデメリット」と「それを上回る圧倒的メリット」
    3. 同ジャンルの他製品との比較表（Markdown形式）
    4. 最後に「商品名（正確に）」と「検索用キーワード」を出力。
    【制約】
    ・AIっぽさを消し、実体験に基づいたような熱量ある口調で。
    """

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

def post_hatena(title, content):
    url = f"https://blog.hatena.ne.jp/{HATENA_ID}/{HATENA_BLOG_ID}/atom/entry"
    
    # 楽天アフィリエイトリンクの簡易生成（商品名から検索結果へ飛ばす）
    # これならAPI制限に触れず、無限にリンクを作れます
    product_name = title # 簡易的にタイトルを商品名として扱う
    search_url = f"https://hb.afl.rakuten.co.jp/hgc/{RAKUTEN_ID}/?pc=https%3A%2F%2Fsearch.rakuten.co.jp%2Fsearch%2Fmall%2F{requests.utils.quote(product_name)}%2F"
    
    body = f"{content}\n\n[詳細・購入はこちらから]({search_url})"
    
    xml_data = f"""<?xml version="1.0" encoding="utf-8"?>
    <entry xmlns="http://www.w3.org/2005/Atom">
      <title>{title}</title>
      <content type="text/plain">{body}</content>
      <updated>{datetime.datetime.now().isoformat()}</updated>
      <app:control xmlns:app="http://www.w3.org/2007/app">
        <app:draft>no</app:draft>
      </app:control>
    </entry>"""
    
    r = requests.post(url, auth=(HATENA_ID, HATENA_API_KEY), data=xml_data.encode('utf-8'))
    return r.status_code

# 実行
article_text = get_ai_content()
title = article_text.split('\n')[0].replace('# ', '') # 1行目をタイトルにする
post_hatena(title, article_text)
