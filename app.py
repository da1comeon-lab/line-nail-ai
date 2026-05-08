from flask import Flask, request, send_from_directory
from linebot import LineBotApi, WebhookHandler
from linebot.models import *
from linebot.exceptions import InvalidSignatureError
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
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
        "style": "親しみやすく、少しラフ。お客様目線でわかりやすい文章。"
    },
    "住道店": {
        "name": "ネイルサロン スマイリー住道店",
        "info": "〒574-0046 大阪府大東市赤井1丁目15-27 ポップタウン住道5番館 2F\nTEL 072-870-0585",
        "style": "ナチュラルで女性らしく、普段使いしやすい文章。"
    },
    "心斎橋店": {
        "name": "ネイルサロン スマイリー心斎橋店",
        "info": "〒542-0086 大阪府大阪市中央区西心斎橋1丁目8-22 4階\nTEL 06-4708-7318",
        "style": "大人っぽく、落ち着いた上品な文章。"
    },
    "マカナ": {
        "name": "ネイルサロン マカナ河内山本店",
        "info": "〒581-0013 大阪府八尾市山本町南4丁目1-3 岩田ビル506号\nTEL 070-9009-1440",
        "style": "韓国っぽさ、透明感、トレンド感のある文章。"
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

def crop_square_nail_focus(img):
    w, h = img.size
    size = min(w, h)

    left = (w - size) // 2
    top = int((h - size) * 0.25)
    top = max(0, min(top, h - size))

    return img.crop((left, top, left + size, top + size))

def nail_salon_retouch(filepath):
    img = Image.open(filepath).convert("RGB")
    img = ImageOps.exif_transpose(img)

    # 額縁なしで正方形化
    img = crop_square_nail_focus(img)
    img = img.resize((1080, 1080), Image.LANCZOS)

    # 全体を明るく
    img = ImageEnhance.Brightness(img).enhance(1.13)
    img = ImageEnhance.Contrast(img).enhance(1.05)

    # 赤み・黄ばみを軽減
    r, g, b = img.split()
    r = r.point(lambda i: min(255, int(i * 0.970)))
    g = g.point(lambda i: min(255, int(i * 1.006)))
    b = b.point(lambda i: min(255, int(i * 1.022)))
    img = Image.merge("RGB", (r, g, b))

    # 高級感寄せで彩度を少し抑える
    img = ImageEnhance.Color(img).enhance(0.95)

    # 肌の質感を少しだけなめらかに
    soft = img.filter(ImageFilter.GaussianBlur(radius=0.65))
    img = Image.blend(img, soft, 0.20)

    # 爪のツヤ感・輪郭を戻す
    img = ImageEnhance.Sharpness(img).enhance(1.35)

    # 最終調整
    img = ImageEnhance.Brightness(img).enhance(1.03)
    img = ImageEnhance.Contrast(img).enhance(1.04)

    img.save(filepath, "JPEG", quality=95, optimize=True)

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
            TextSendMessage(text=f"{SHOPS[text]['name']}で設定しました。\nネイル画像を送ってください。")
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

    nail_salon_retouch(filepath)

    image_url = f"{BASE_URL}/static/images/{filename}"

    with open(filepath, "rb") as image_file:
        base64_image = base64.b64encode(image_file.read()).decode("utf-8")

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        temperature=0.55,
        messages=[
            {
                "role": "system",
                "content": f"""
あなたは実際のネイルサロンスタッフです。
Hot Pepper Beautyに投稿するブログ文を自然に作成してください。

絶対ルール：
・絵文字禁止
・AIっぽい文章禁止
・「タイトル」「本文」「ハッシュタグ」「店舗情報」という見出しは禁止
・「洗練」「演出」「魅力」「上品」「ぴったり」「効いた」は使わない
・説明しすぎない
・短め
・自然
・少しラフ
・営業感を出しすぎない
・同じ言葉を繰り返さない
・季節感を無理に入れない
・ネイリスト本人が軽く投稿した雰囲気

出力形式：
1行目：タイトル風に短く。15〜22文字くらい。
空行
本文：2〜3文。80〜140文字程度。
最後は自然に「ご予約お待ちしております。」または「気になる方ぜひお試しください。」で締める。
空行
ハッシュタグ5個。地域名タグを1個入れる。
空行
{shop['name']}
{shop['info']}

店舗の雰囲気：
{shop['style']}

文章例：
黒フレンチにパール合わせました。

片手だけ黒ベースにして少し雰囲気変えてます。
シンプルすぎない黒ネイルが好きな方におすすめです。
ご予約お待ちしております。

#黒ネイル #フレンチネイル #パールネイル #大人ネイル #八尾ネイル
"""
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "このネイル画像のHot Pepper Beauty用ブログ文を作成してください。"
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
