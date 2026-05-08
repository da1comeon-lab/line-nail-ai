from flask import Flask, request, send_from_directory
from linebot import LineBotApi, WebhookHandler
from linebot.models import *
from linebot.exceptions import InvalidSignatureError
from PIL import Image, ImageEnhance, ImageFilter
from openai import OpenAI
import os
import uuid
import base64

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
        "style": "親しみやすく自然、大人可愛い雰囲気"
    },
    "住道店": {
        "name": "ネイルサロン スマイリー住道店",
        "info": "〒574-0046 大阪府大東市赤井1丁目15-27 ポップタウン住道5番館 2F\nTEL 072-870-0585",
        "style": "ナチュラルで女性らしい雰囲気"
    },
    "心斎橋店": {
        "name": "ネイルサロン スマイリー心斎橋店",
        "info": "〒542-0086 大阪府大阪市中央区西心斎橋1丁目8-22 4階\nTEL 06-4708-7318",
        "style": "大人っぽく上品、高級感ある雰囲気"
    },
    "マカナ": {
        "name": "ネイルサロン マカナ河内山本店",
        "info": "〒581-0013 大阪府八尾市山本町南4丁目1-3 岩田ビル506号\nTEL 070-9009-1440",
        "style": "韓国っぽさとトレンド感を意識"
    }
}

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
    top = int((h - size) * 0.35)

    if top < 0:
        top = 0

    return img.crop((left, top, left + size, top + size))

def enhance_image(filepath):
    img = Image.open(filepath).convert("RGB")

    img = crop_square(img)

    img = img.resize((1080, 1080))

    # 明るさ
    img = ImageEnhance.Brightness(img).enhance(1.12)

    # コントラスト
    img = ImageEnhance.Contrast(img).enhance(1.06)

    # 彩度
    img = ImageEnhance.Color(img).enhance(0.96)

    # シャープ
    img = ImageEnhance.Sharpness(img).enhance(1.12)

    # 少しだけぼかし→肌自然化
    img = img.filter(ImageFilter.SMOOTH_MORE)

    # 軽くシャープ戻し
    img = img.filter(ImageFilter.SHARPEN)

    img.save(filepath, quality=95)

def shop_message():
    return """店舗名を送信してください。

・八尾店
・住道店
・心斎橋店
・マカナ

設定後にネイル画像を送ると、
画像加工＋ブログ文章を自動作成します。"""

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    if text in SHOPS:
        user_shop[user_id] = text

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=f"{SHOPS[text]['name']}で設定しました。\nネイル画像を送ってください。"
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

    enhance_image(filepath)

    image_url = f"{BASE_URL}/static/images/{filename}"

    with open(filepath, "rb") as image_file:
        base64_image = base64.b64encode(image_file.read()).decode("utf-8")

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": f"""
あなたは人気ネイルサロンのスタッフです。

画像を見て、
Hot Pepper Beauty向けのブログ文章を書いてください。

重要：

・説明しすぎない
・人が書いた自然感
・少しカジュアル
・絵文字禁止
・女性誌っぽい空気感
・押し売りしない
・大人っぽい
・実際のサロンスタッフ感
・120〜220文字程度
・タイトル付き
・最後に自然な予約誘導
・最後にハッシュタグ5個
・店舗情報を最後に載せる

店舗の雰囲気：
{shop['style']}

最後に必ず以下を記載：

{shop['name']}
{shop['info']}
"""
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
        ],
        temperature=1.0
    )

    blog_text = response.choices[0].message.content

    line_bot_api.reply_message(
        event.reply_token,
        [
            ImageSendMessage(
                original_content_url=image_url,
                preview_image_url=image_url
            ),
            TextSendMessage(text=blog_text)
        ]
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
