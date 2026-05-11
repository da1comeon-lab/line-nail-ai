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
ピンクベージュネイル

【本文】
ピンクベージュ系でまとめたデザインです。
肌なじみが良く、手元がきれいに見えるカラーです。
シンプルだけど少し可愛さも欲しい方におすすめです。

ご予約お待ちしております。

【タイトル】
マグネットネイル

【本文】
マグネットを使ったシンプルなデザインです。
角度によって見え方が変わるので、派手すぎず少し変化も楽しめます。
普段使いにも合わせやすいネイルです。

ご予約お待ちしております。

【タイトル】
フレンチネイル

【本文】
シンプルなフレンチネイルです。
カラーを変えるだけでも雰囲気が変わるので、きれいめが好きな方にも人気です。
手元をすっきり見せたい方にもおすすめです。

ご予約お待ちしております。
"""

NG_REPLACE = {
    "個性的": "少し雰囲気のある",
    "個性": "雰囲気",
    "洗練された": "すっきりした",
    "洗練": "すっきり",
    "演出": "仕上がり",
    "魅力": "良さ",
    "アクセントが効いた": "ポイントを入れた",
    "アクセント": "ポイント",
    "存在感": "ほどよいポイント感",
    "ワンランク": "",
    "映える": "写真でもきれいに見える",
    "ポツポツ": "少し",
    "散らして": "合わせて",
    "シンプルながら": "シンプルですが",
    "上品": "きれいめ",
    "華やか": "明るい印象",
}

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
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return "Invalid signature", 400
    except Exception as e:
        print("callback error:", e)
        return "OK"

    return "OK"

def crop_square(img):
    w, h = img.size
    size = min(w, h)
    left = (w - size) // 2
    top = int((h - size) * 0.25)
    top = max(0, min(top, h - size))
    return img.crop((left, top, left + size, top + size))

def improve_nail_image(filepath):
    img = Image.open(filepath).convert("RGB")
    img = ImageOps.exif_transpose(img)

    img = crop_square(img)
    img = img.resize((1080, 1080), Image.LANCZOS)

    # 自然補正：白飛びさせず、暗さだけ少し取る
    img = ImageEnhance.Brightness(img).enhance(1.06)
    img = ImageEnhance.Contrast(img).enhance(1.04)

    # 黄ばみと赤みをほんの少しだけ補正
    r, g, b = img.split()
    r = r.point(lambda i: min(255, int(i * 0.990)))
    g = g.point(lambda i: min(255, int(i * 1.002)))
    b = b.point(lambda i: min(255, int(i * 1.010)))
    img = Image.merge("RGB", (r, g, b))

    # 色味は飛ばさない
    img = ImageEnhance.Color(img).enhance(1.02)

    # 肌だけでなく全体をほんの少しなめらかに
    soft = img.filter(ImageFilter.GaussianBlur(radius=0.35))
    img = Image.blend(img, soft, 0.08)

    # 爪の輪郭とツヤ感を軽く戻す
    img = ImageEnhance.Sharpness(img).enhance(1.18)

    img.save(filepath, "JPEG", quality=95, optimize=True)

def clean_text(text):
    for old, new in NG_REPLACE.items():
        text = text.replace(old, new)
    return text.strip()

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

    try:
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
変にラフにせず、丁寧で読みやすい文章にしてください。

参考文章：
{GOOD_EXAMPLES}

絶対ルール：
・絵文字は禁止
・変にオシャレに言いすぎない
・説明しすぎない
・短めで読みやすく
・本文は普通のサロン文
・「おすすめです」は1回まで
・「個性」「個性的」は使わない
・「洗練」「演出」「魅力」「ワンランク」「映える」「存在感」「ポツポツ」は使わない
・無理に季節感を入れない
・画像に写っている内容から外れたことを書かない

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
"""

        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            temperature=0.32,
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
        text = clean_text(text)

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

    except Exception as e:
        print("image error:", e)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="エラーが出ました。もう一度画像を送ってください。")
        )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
