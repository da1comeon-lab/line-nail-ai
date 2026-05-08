from flask import Flask, request, send_from_directory
from linebot import LineBotApi, WebhookHandler
from linebot.models import *
from linebot.exceptions import InvalidSignatureError
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from openai import OpenAI
import os
import uuid
import base64
import random

app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

BASE_URL = os.getenv("BASE_URL", "https://line-nail-ai.onrender.com")

IMAGE_DIR = "static/images"
os.makedirs(IMAGE_DIR, exist_ok=True)

user_shop = {}

SHOPS = {
    "八尾店": {
        "name": "ネイルサロン スマイリー八尾店",
        "info": "〒581-0869 大阪府八尾市桜ヶ丘3丁目119 加島ビル1F\nTEL 072-920-7313",
        "style": "親しみやすい。少しラフ。リアルなネイリスト感。"
    },
    "住道店": {
        "name": "ネイルサロン スマイリー住道店",
        "info": "〒574-0046 大阪府大東市赤井1丁目15-27 ポップタウン住道5番館 2F\nTEL 072-870-0585",
        "style": "ナチュラル。女性らしい。やわらかい雰囲気。"
    },
    "心斎橋店": {
        "name": "ネイルサロン スマイリー心斎橋店",
        "info": "〒542-0086 大阪府大阪市中央区西心斎橋1丁目8-22 4階\nTEL 06-4708-7318",
        "style": "大人っぽい。シンプル。高級感。"
    },
    "マカナ": {
        "name": "ネイルサロン マカナ河内山本店",
        "info": "〒581-0013 大阪府八尾市山本町南4丁目1-3 岩田ビル506号\nTEL 070-9009-1440",
        "style": "韓国っぽ。透明感。トレンド感。"
    }
}

ENDINGS = [
    "ご予約お待ちしております。",
    "気になる方ぜひお試しください。",
    "最近人気のデザインです。",
    "派手すぎない感じが可愛いです。",
    "大人っぽくしたい方に人気です。"
]

@app.route("/")
def home():
    return "LINE Nail AI Running"

@app.route("/static/images/<filename>")
def serve_image(filename):
    return send_from_directory(IMAGE_DIR, filename)

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return "Invalid signature", 400

    return "OK"

def crop_square(img):
    w, h = img.size
    size = min(w, h)

    left = (w - size) // 2
    top = int((h - size) * 0.22)
    top = max(0, min(top, h - size))

    return img.crop((left, top, left + size, top + size))

def improve_nail_image(filepath):
    img = Image.open(filepath).convert("RGB")
    img = ImageOps.exif_transpose(img)

    img = crop_square(img)
    img = img.resize((1080, 1080), Image.LANCZOS)

    # 明るく
    img = ImageEnhance.Brightness(img).enhance(1.18)

    # 少し白寄り
    r, g, b = img.split()

    r = r.point(lambda i: int(i * 0.97))
    g = g.point(lambda i: int(i * 1.01))
    b = b.point(lambda i: int(i * 1.04))

    img = Image.merge("RGB", (r, g, b))

    # 肌を少し綺麗に
    blur = img.filter(ImageFilter.GaussianBlur(radius=1.0))
    img = Image.blend(img, blur, 0.18)

    # 爪のツヤ感
    img = ImageEnhance.Sharpness(img).enhance(1.55)

    # コントラスト
    img = ImageEnhance.Contrast(img).enhance(1.06)

    # 彩度少しだけUP
    img = ImageEnhance.Color(img).enhance(1.04)

    img.save(filepath, quality=95)

def shop_message():
    return """店舗名を送信してください。

・八尾店
・住道店
・心斎橋店
・マカナ

設定後に画像を送ると
ブログ文章＋画像加工を自動作成します。"""

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    if text in SHOPS:
        user_shop[user_id] = text

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=f"{SHOPS[text]['name']} を設定しました。\nネイル画像を送ってください。"
            )
        )
        return

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=shop_message())
    )

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id

    if user_id not in user_shop:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=shop_message())
        )
        return

    shop_key = user_shop[user_id]
    shop = SHOPS[shop_key]

    message_content = line_bot_api.get_message_content(event.message.id)

    filename = f"{uuid.uuid4().hex}.jpg"
    filepath = os.path.join(IMAGE_DIR, filename)

    with open(filepath, "wb") as f:
        for chunk in message_content.iter_content():
            f.write(chunk)

    improve_nail_image(filepath)

    image_url = f"{BASE_URL}/static/images/{filename}"

    with open(filepath, "rb") as img:
        base64_image = base64.b64encode(img.read()).decode("utf-8")

    ending = random.choice(ENDINGS)

    prompt = f"""
あなたは実際のネイルサロンスタッフです。

Hot Pepper Beauty用の自然なブログを書いてください。

重要：
・AI感禁止
・説明しすぎ禁止
・「おすすめです」を多用しない
・「演出」「魅力」「洗練」「上品」禁止
・「散らしてみました」禁止
・人が軽く投稿した感じ
・少しラフ
・短め
・自然な日本語
・絵文字禁止
・見出し禁止
・「タイトル」「本文」など禁止

出力ルール：

1行目：
短いタイトル

空行

本文：
2〜3文
自然な会話感
ネイリスト感

最後は
「{ending}」
で終わる

空行

ハッシュタグ5個

空行

{shop['name']}
{shop['info']}

店舗イメージ：
{shop['style']}
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        temperature=0.8,
        messages=[
            {
                "role": "system",
                "content": prompt
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "このネイル画像のブログを書いて"
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ]
    )

    text = response.choices[0].message.content

    line_bot_api.reply_message(
        event.reply_token,
        [
            ImageSendMessage(
                original_content_url=image_url,
                preview_image_url=image_url
            ),
            TextSendMessage(text=text)
        ]
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
