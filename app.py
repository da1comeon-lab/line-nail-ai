from flask import Flask, request, send_from_directory, redirect, session
from linebot import LineBotApi, WebhookHandler
from linebot.models import *
from linebot.exceptions import InvalidSignatureError
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from openai import OpenAI
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials

import os
import uuid
import base64
import random
import secrets
import requests
import numpy as np
import cv2

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

BASE_URL = os.getenv("BASE_URL", "https://line-nail-ai.onrender.com")
IMAGE_DIR = "static/images"

os.makedirs(IMAGE_DIR, exist_ok=True)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN")
GOOGLE_REDIRECT_URI = "https://line-nail-ai.onrender.com/oauth2callback"

SCOPES = ["https://www.googleapis.com/auth/business.manage"]

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

ENDINGS = [
    "ご予約お待ちしております。",
    "ご来店お待ちしております。",
    "気になる方はぜひお試しください。"
]

NG_REPLACE = {
    "個性的": "少し雰囲気のある",
    "個性": "雰囲気",
    "洗練": "すっきり",
    "演出": "仕上がり",
    "魅力": "良さ",
    "存在感": "ポイント感",
    "ワンランク": "",
    "映える": "きれいに見える",
}


def google_client_config():
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI]
        }
    }


def get_google_credentials():
    if not GOOGLE_REFRESH_TOKEN:
        return None

    return Credentials(
        token=None,
        refresh_token=GOOGLE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=SCOPES
    )


def get_access_token():
    creds = get_google_credentials()

    if not creds:
        return None

    from google.auth.transport.requests import Request
    creds.refresh(Request())

    return creds.token


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


def fit_to_square_no_cut(rgb):
    h, w, _ = rgb.shape

    size = max(w, h)

    # 真っ白背景
    canvas = np.ones((size, size, 3), dtype=np.uint8) * 255

    x = (size - w) // 2
    y = (size - h) // 2

    canvas[y:y+h, x:x+w] = rgb

    return canvas


def compress_highlights(rgb):
    img = rgb.astype(np.float32)

    threshold = 240

    mask = img > threshold

    img[mask] = threshold + (img[mask] - threshold) * 0.35

    return np.clip(img, 0, 255).astype(np.uint8)


def auto_light_correction(rgb):
    rgb = compress_highlights(rgb)

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)

    l, a, b = cv2.split(lab)

    mean_l = np.mean(l)

    if mean_l < 120:
        alpha = 1.10
        beta = 10
        clip = 2.0

    elif mean_l < 150:
        alpha = 1.04
        beta = 4
        clip = 1.5

    elif mean_l > 200:
        alpha = 0.98
        beta = -2
        clip = 1.0

    else:
        alpha = 1.0
        beta = 0
        clip = 1.2

    clahe = cv2.createCLAHE(
        clipLimit=clip,
        tileGridSize=(8, 8)
    )

    l2 = clahe.apply(l)

    lab = cv2.merge((l2, a, b))

    bgr = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    bgr = cv2.convertScaleAbs(
        bgr,
        alpha=alpha,
        beta=beta
    )

    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    return rgb


def natural_adjustment(rgb):
    pil = Image.fromarray(rgb).convert("RGB")

    # 明るくしすぎない
    pil = ImageEnhance.Brightness(pil).enhance(1.01)

    # 彩度控えめ
    pil = ImageEnhance.Color(pil).enhance(1.02)

    # コントラスト弱め
    pil = ImageEnhance.Contrast(pil).enhance(1.01)

    # 軽くシャープ
    pil = ImageEnhance.Sharpness(pil).enhance(1.08)

    # なめらか
    soft = pil.filter(ImageFilter.GaussianBlur(radius=0.25))

    pil = Image.blend(pil, soft, 0.05)

    return np.array(pil)


def improve_nail_image(filepath):
    pil = Image.open(filepath).convert("RGB")

    pil = ImageOps.exif_transpose(pil)

    rgb = np.array(pil)

    # 見切れ防止
    rgb = fit_to_square_no_cut(rgb)

    pil = Image.fromarray(rgb)

    pil = pil.resize((1080, 1080), Image.LANCZOS)

    rgb = np.array(pil)

    # 白飛び防止
    rgb = auto_light_correction(rgb)

    # 自然補正
    rgb = natural_adjustment(rgb)

    out = Image.fromarray(rgb).convert("RGB")

    out.save(
        filepath,
        "JPEG",
        quality=95,
        optimize=True
    )


def clean_text(text):
    for old, new in NG_REPLACE.items():
        text = text.replace(old, new)

    text = text.replace("。。", "。")
    text = text.replace("、、", "、")

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

Hot Pepper Beauty用の
自然なネイル投稿文を作成してください。

絶対条件：

・AIっぽくしない
・短め
・絵文字禁止
・自然な言い回し
・説明しすぎない
・押し売りしない
・画像にない内容を書かない
・タイトルは短め
・本文は2〜3文
・同じ語尾を繰り返さない
・ネイリストが普通に書いた感じにする

禁止ワード：
個性的
洗練
魅力
ワンランク
存在感
映える

最後は
「{ending}」
で締める

ハッシュタグは5個。

必ず
{shop['area_tag']}
を入れる。

出力形式：

【タイトル】
タイトル

【本文】
本文

#タグ #タグ #タグ #タグ #タグ

{shop['name']}
{shop['info']}
"""

        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            temperature=0.25,
            max_tokens=600,
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
                            "text": "このネイル画像の投稿文を作成してください。"
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
            TextSendMessage(
                text="エラーが出ました。もう一度画像を送ってください。"
            )
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
