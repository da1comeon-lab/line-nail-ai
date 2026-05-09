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
        "style": "親しみやすく、少しだけカジュアル。普段使いしやすい文章。"
    },
    "住道店": {
        "name": "ネイルサロン スマイリー住道店",
        "info": "〒574-0046 大阪府大東市赤井1丁目15-27 ポップタウン住道5番館 2F\nTEL 072-870-0585",
        "area_tag": "#住道ネイル",
        "style": "ナチュラルで女性らしい。やわらかい文章。"
    },
    "心斎橋店": {
        "name": "ネイルサロン スマイリー心斎橋店",
        "info": "〒542-0086 大阪府大阪市中央区西心斎橋1丁目8-22 4階\nTEL 06-4708-7318",
        "area_tag": "#心斎橋ネイル",
        "style": "大人っぽく落ち着いた文章。"
    },
    "マカナ": {
        "name": "ネイルサロン マカナ河内山本店",
        "info": "〒581-0013 大阪府八尾市山本町南4丁目1-3 岩田ビル506号\nTEL 070-9009-1440",
        "area_tag": "#河内山本ネイル",
        "style": "透明感、トレンド感、韓国っぽさを少し意識。"
    }
}

GOOD_EXAMPLES = """
【タイトル】
ブラックフレンチ×パールネイル

【本文】
黒フレンチにパールを合わせたデザインです。
片手は黒ベースにして、シンプルすぎない雰囲気に仕上げています。
落ち着いたカラーでも少しポイントが欲しい方におすすめです。

ご予約お待ちしております。

【タイトル】
ベージュ系シンプルネイル

【本文】
肌なじみの良いベージュ系でまとめたデザインです。
少しラメ感も入れているので、シンプルすぎず手元がきれいに見えます。
オフィスネイルにも人気です。

ご予約お待ちしております。

【タイトル】
ちゅるんマグネットネイル

【本文】
ちゅるんとしたカラーにマグネットを合わせたデザインです。
派手すぎない仕上がりなので、普段使いにも合わせやすいです。
さりげなくきらっとさせたい方にもおすすめです。

気になる方ぜひお試しください。

【タイトル】
シンプルフレンチネイル

【本文】
シンプルなフレンチにポイントを入れたデザインです。
派手すぎないので、きれいめが好きな方にも合わせやすいです。
手元をすっきり見せたい方にも人気です。

ご予約お待ちしております。

【タイトル】
ピンクベージュネイル

【本文】
ピンクベージュ系でまとめたデザインです。
ほんのりツヤ感があって、肌なじみも良いカラーです。
シンプルだけど少し可愛さも欲しい方におすすめです。

ご予約お待ちしております。
"""

NG_WORDS = """
洗練、演出、魅力、映える、ワンランク、個性的、華やかさをプラス、アクセントが効いた、
散らしてみました、ポツポツ、上品な印象、女性らしさを演出、存在感抜群、指先を彩る、
トレンド感たっぷり、こなれ感、目を惹く、オシャレ度アップ、格上げ、魅力的
"""

ENDINGS = [
    "ご予約お待ちしております。",
    "気になる方ぜひお試しください。",
    "ご来店お待ちしております。"
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
    top = int((h - size) * 0.23)
    top = max(0, min(top, h - size))
    return img.crop((left, top, left + size, top + size))

def improve_nail_image(filepath):
    img = Image.open(filepath).convert("RGB")
    img = ImageOps.exif_transpose(img)

    img = crop_square(img)
    img = img.resize((1080, 1080), Image.LANCZOS)

    img = ImageEnhance.Brightness(img).enhance(1.15)
    img = ImageEnhance.Contrast(img).enhance(1.05)

    r, g, b = img.split()
    r = r.point(lambda i: min(255, int(i * 0.975)))
    g = g.point(lambda i: min(255, int(i * 1.006)))
    b = b.point(lambda i: min(255, int(i * 1.025)))
    img = Image.merge("RGB", (r, g, b))

    img = ImageEnhance.Color(img).enhance(0.98)

    soft = img.filter(ImageFilter.GaussianBlur(radius=0.7))
    img = Image.blend(img, soft, 0.16)

    img = ImageEnhance.Sharpness(img).enhance(1.38)
    img = ImageEnhance.Brightness(img).enhance(1.02)
    img = ImageEnhance.Contrast(img).enhance(1.03)

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

    improve_nail_image(filepath)

    image_url = f"{BASE_URL}/static/images/{filename}"

    with open(filepath, "rb") as img:
        base64_image = base64.b64encode(img.read()).decode("utf-8")

    ending = random.choice(ENDINGS)

    prompt = f"""
あなたは実際のネイルサロンスタッフです。
Hot Pepper Beautyに投稿するブログ文を作成してください。

目標：
普通のネイリストが書いたような、自然で無難なサロンブログ文。

参考にする文章の雰囲気：
{GOOD_EXAMPLES}

絶対ルール：
・絵文字は禁止
・AIっぽい文章は禁止
・変にラフにしすぎない
・オシャレに言いすぎない
・説明しすぎない
・本文は丁寧で普通のサロン文
・短めで読みやすく
・「おすすめです」は使ってもいいが1回まで
・下記のNGワードは使わない

NGワード：
{NG_WORDS}

出力形式は必ずこれ：

【タイトル】
20文字前後の自然なタイトル

【本文】
2〜4文。
画像のデザインを自然に説明。
最後は「{ending}」で締める。

ハッシュタグ5個。
必ず地域タグ {shop['area_tag']} を1個入れる。

{shop['name']}
{shop['info']}

店舗の文体：
{shop['style']}
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        temperature=0.45,
        messages=[
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "このネイル画像のHot Pepper Beauty用ブログ文を作成してください。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
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
