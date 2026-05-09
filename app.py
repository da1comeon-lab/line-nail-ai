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
        "area_tag": "#八尾ネイル",
    },
    "住道店": {
        "name": "ネイルサロン スマイリー住道店",
        "info": "〒574-0046 大阪府大東市赤井1丁目15-27 ポップタウン住道5番館 2F\nTEL 072-870-0585",
        "area_tag": "#住道ネイル",
    },
    "心斎橋店": {
        "name": "ネイルサロン スマイリー心斎橋店",
        "info": "〒542-0086 大阪府大阪市中央区西心斎橋1丁目8-22 4階\nTEL 06-4708-7318",
        "area_tag": "#心斎橋ネイル",
    },
    "マカナ": {
        "name": "ネイルサロン マカナ河内山本店",
        "info": "〒581-0013 大阪府八尾市山本町南4丁目1-3 岩田ビル506号\nTEL 070-9009-1440",
        "area_tag": "#河内山本ネイル",
    }
}

GOOD_EXAMPLES = """
【タイトル】
ブラックフレンチ×パールネイル

【本文】
黒フレンチにパールを合わせたデザインです。

片手は黒ベースにして、少し雰囲気を変えています。
落ち着いた感じでまとまっていて可愛いです。

ご予約お待ちしております。

【タイトル】
シンプルベージュネイル

【本文】
肌なじみの良いベージュ系でまとめたデザインです。

ラメも少し入れているので、
シンプルすぎない感じになっています。

オフィスネイルにも人気です。

ご予約お待ちしております。

【タイトル】
マグネットネイル

【本文】
ちゅるん系カラーにマグネットを合わせたデザインです。

派手すぎないので、
普段使いにも合わせやすい感じです。

気になる方ぜひお試しください。
"""

NG_WORDS = [
    "個性",
    "個性的",
    "魅力",
    "洗練",
    "演出",
    "アクセント",
    "存在感",
    "ワンランク",
    "華やか",
    "映える",
    "ポツポツ",
    "散らして",
    "上品",
    "こなれ感",
    "指先を彩る",
    "トレンド感たっぷり",
    "シンプルながら",
]

ENDINGS = [
    "ご予約お待ちしております。",
    "ご来店お待ちしております。",
    "気になる方ぜひお試しください。"
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

    img = ImageEnhance.Brightness(img).enhance(1.12)
    img = ImageEnhance.Contrast(img).enhance(1.04)

    r, g, b = img.split()

    r = r.point(lambda i: min(255, int(i * 0.97)))
    g = g.point(lambda i: min(255, int(i * 1.01)))
    b = b.point(lambda i: min(255, int(i * 1.03)))

    img = Image.merge("RGB", (r, g, b))

    img = ImageEnhance.Color(img).enhance(0.97)

    soft = img.filter(ImageFilter.GaussianBlur(radius=0.7))
    img = Image.blend(img, soft, 0.13)

    img = ImageEnhance.Sharpness(img).enhance(1.35)

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
            TextSendMessage(
                text=f"{SHOPS[text]['name']}で設定しました。\nネイル画像を送ってください。"
            )
        )
        return

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=shop_message())
    )

def generate_blog(base64_image, shop, ending):

    prompt = f"""
あなたは実際のネイルサロンスタッフです。

Hot Pepper Beauty用の自然なブログ文を書いてください。

最重要：
AIっぽくしない。
普通のネイリストが書いたような自然な文章。

参考文章：
{GOOD_EXAMPLES}

ルール：
・短め
・説明しすぎない
・オシャレに言いすぎない
・普通のサロン文
・変に褒めすぎない
・自然な日本語
・絵文字禁止

禁止ワード：
{",".join(NG_WORDS)}

出力形式：

【タイトル】
タイトル

【本文】
本文

#ハッシュタグ

{shop['name']}
{shop['info']}

最後は必ず
「{ending}」
で締める。
"""

    response = client.chat.completions.create(
        model="gpt-4.1",
        temperature=0.38,
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
                        "text": "このネイル画像のブログ文を作成してください。"
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

    for ng in NG_WORDS:
        if ng in text:
            return None

    return text

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

    text = None

    for _ in range(5):

        ending = random.choice(ENDINGS)

        result = generate_blog(base64_image, shop, ending)

        if result:
            text = result
            break

    if not text:
        text = "文章生成に失敗しました。"

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
