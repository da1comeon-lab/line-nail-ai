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
        "style": "親しみやすく、少しカジュアル。通いやすい大人可愛い雰囲気。"
    },
    "住道店": {
        "name": "ネイルサロン スマイリー住道店",
        "info": "〒574-0046 大阪府大東市赤井1丁目15-27 ポップタウン住道5番館 2F\nTEL 072-870-0585",
        "style": "ナチュラルで女性らしい雰囲気。普段使いしやすい提案。"
    },
    "心斎橋店": {
        "name": "ネイルサロン スマイリー心斎橋店",
        "info": "〒542-0086 大阪府大阪市中央区西心斎橋1丁目8-22 4階\nTEL 06-4708-7318",
        "style": "上品で大人っぽく、高級感のある雰囲気。"
    },
    "マカナ": {
        "name": "ネイルサロン マカナ河内山本店",
        "info": "〒581-0013 大阪府八尾市山本町南4丁目1-3 岩田ビル506号\nTEL 070-9009-1440",
        "style": "韓国っぽさ、透明感、トレンド感を意識。"
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

def crop_square_with_margin(img):
    w, h = img.size
    size = min(w, h)

    left = (w - size) // 2
    top = int((h - size) * 0.35)
    top = max(0, min(top, h - size))

    return img.crop((left, top, left + size, top + size))

def salon_retouch(filepath):
    img = Image.open(filepath).convert("RGB")
    img = ImageOps.exif_transpose(img)

    # 構図：正方形化
    img = crop_square_with_margin(img)

    # 少し余白を作るために縮小して白背景へ配置
    img = img.resize((1000, 1000), Image.LANCZOS)
    canvas = Image.new("RGB", (1080, 1080), (250, 248, 245))
    canvas.paste(img, (40, 40))
    img = canvas

    # 全体を明るく、清潔感寄せ
    img = ImageEnhance.Brightness(img).enhance(1.16)
    img = ImageEnhance.Contrast(img).enhance(1.07)

    # 黄ばみ・赤みを少し抑える
    r, g, b = img.split()
    r = r.point(lambda i: min(255, int(i * 0.985)))
    g = g.point(lambda i: min(255, int(i * 1.01)))
    b = b.point(lambda i: min(255, int(i * 1.025)))
    img = Image.merge("RGB", (r, g, b))

    # 彩度は少しだけ控えめにして高級感
    img = ImageEnhance.Color(img).enhance(0.94)

    # 肌のシワ・質感を少し自然にやわらげる
    soft = img.filter(ImageFilter.SMOOTH_MORE)
    img = Image.blend(img, soft, 0.22)

    # 爪のツヤ感がぼやけすぎないように戻す
    img = ImageEnhance.Sharpness(img).enhance(1.18)

    # 最終トーン
    img = ImageEnhance.Brightness(img).enhance(1.03)
    img = ImageEnhance.Contrast(img).enhance(1.03)

    img.save(filepath, "JPEG", quality=95)

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

    salon_retouch(filepath)

    image_url = f"{BASE_URL}/static/images/{filename}"

    with open(filepath, "rb") as image_file:
        base64_image = base64.b64encode(image_file.read()).decode("utf-8")

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        temperature=0.85,
        messages=[
            {
                "role": "system",
                "content": f"""
あなたはネイルサロンの現場スタッフです。
Hot Pepper Beautyのブログ文を、人が書いたように自然に作成してください。

絶対条件：
・絵文字は禁止
・AIっぽい説明文にしない
・「〜が効いた」「〜を演出」「魅力を引き立てる」を多用しない
・同じ意味の言葉を繰り返さない
・売り込みすぎない
・サロンスタッフが自然に書いた雰囲気
・少しカジュアル
・でも安っぽくしない
・画像の特徴を拾うが、説明しすぎない
・季節感は無理に入れない
・本文は120〜200文字程度

文章構成：
【タイトル】
短めで自然。20文字前後。

本文：
2〜4文。
「こんな雰囲気が好きな方に合いそう」くらいの自然な紹介。
おすすめですを連発しない。

最後：
ご予約お待ちしております。

ハッシュタグ：
画像に合うものを5個。
地域名タグを1個入れる。

店舗情報：
{shop['name']}
{shop['info']}

店舗の文体：
{shop['style']}
"""
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "このネイル画像を見て、Hot Pepper Beauty用ブログを作成してください。"
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
