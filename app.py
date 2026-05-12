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
    "アクセント": "ポイント",
    "上品な": "",
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


@app.route("/google-login")
def google_login():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return "Googleの環境変数が設定されていません。"

    flow = Flow.from_client_config(
        google_client_config(),
        scopes=SCOPES,
        autogenerate_code_verifier=True
    )

    flow.redirect_uri = GOOGLE_REDIRECT_URI

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )

    session["oauth_state"] = state
    session["code_verifier"] = flow.code_verifier

    return redirect(authorization_url)


@app.route("/oauth2callback")
def oauth2callback():
    try:
        state = session.get("oauth_state")
        code_verifier = session.get("code_verifier")

        if not state or not code_verifier:
            return "Google連携エラー：セッション情報が切れています。もう一度 /google-login からやり直してください。"

        flow = Flow.from_client_config(
            google_client_config(),
            scopes=SCOPES,
            state=state
        )

        flow.redirect_uri = GOOGLE_REDIRECT_URI
        flow.code_verifier = code_verifier
        flow.fetch_token(authorization_response=request.url)

        credentials = flow.credentials
        refresh_token = credentials.refresh_token

        if not refresh_token:
            return "Google連携は成功しましたが、refresh_token が取得できませんでした。もう一度 /google-login を開いて許可し直してください。"

        return f"""
        Google連携成功<br><br>
        RenderのEnvironmentへ追加してください。<br><br>
        KEY：GOOGLE_REFRESH_TOKEN<br>
        VALUE：{refresh_token}<br><br>
        この画面の内容は他人に見せないでください。
        """

    except Exception as e:
        return f"Google連携エラー：{e}"


@app.route("/google-locations")
def google_locations():
    try:
        token = get_access_token()

        if not token:
            return "GOOGLE_REFRESH_TOKEN が設定されていません。"

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }

        accounts_res = requests.get(
            "https://mybusinessaccountmanagement.googleapis.com/v1/accounts",
            headers=headers,
            timeout=30
        )

        if accounts_res.status_code != 200:
            return f"""
            Googleアカウント取得エラー<br>
            ステータス: {accounts_res.status_code}<br>
            本文: {accounts_res.text}
            """

        accounts = accounts_res.json().get("accounts", [])

        if not accounts:
            return "Googleビジネスアカウントが見つかりませんでした。"

        html = "<h2>Googleビジネス 店舗一覧</h2>"

        for account in accounts:
            account_name = account.get("name")
            account_title = account.get("accountName", "")

            html += f"<h3>{account_title}<br>{account_name}</h3>"

            locations_res = requests.get(
                f"https://mybusinessbusinessinformation.googleapis.com/v1/{account_name}/locations?readMask=name,title,storefrontAddress",
                headers=headers,
                timeout=30
            )

            html += f"<p>locations status: {locations_res.status_code}</p>"

            if locations_res.status_code != 200:
                html += f"<pre>{locations_res.text}</pre>"
                continue

            locations = locations_res.json().get("locations", [])

            if not locations:
                html += "<p>店舗なし</p>"
                continue

            html += "<ul>"

            for loc in locations:
                name = loc.get("name", "")
                title = loc.get("title", "")
                address = loc.get("storefrontAddress", {})
                lines = address.get("addressLines", [])
                postal = address.get("postalCode", "")
                admin = address.get("administrativeArea", "")
                locality = address.get("locality", "")

                html += f"""
                <li>
                    <b>{title}</b><br>
                    location_id: {name}<br>
                    {postal} {admin} {locality} {' '.join(lines)}
                </li><br>
                """

            html += "</ul>"

        return html

    except Exception as e:
        return f"Google店舗取得エラー：{e}"


def fit_to_square_no_cut(rgb):
    h, w, _ = rgb.shape
    size = max(w, h)

    canvas = np.ones((size, size, 3), dtype=np.uint8) * 255

    x = (size - w) // 2

    # 下余白が出すぎないように少し上寄せ
    y = int((size - h) * 0.35)

    y = max(0, min(y, size - h))

    canvas[y:y+h, x:x+w] = rgb

    return canvas


def soft_highlight_control(rgb):
    img = rgb.astype(np.float32)

    threshold = 245
    mask = img > threshold

    img[mask] = threshold + (img[mask] - threshold) * 0.45

    return np.clip(img, 0, 255).astype(np.uint8)


def auto_light_correction(rgb):
    rgb = soft_highlight_control(rgb)

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)

    l, a, b = cv2.split(lab)

    mean_l = float(np.mean(l))

    # シワ強調防止のためCLAHEは暗い写真だけ弱く使用
    if mean_l < 115:
        clahe = cv2.createCLAHE(clipLimit=0.7, tileGridSize=(8, 8))
        l = clahe.apply(l)

        lab = cv2.merge((l, a, b))
        bgr = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        bgr = cv2.convertScaleAbs(bgr, alpha=1.02, beta=3)

    elif mean_l < 145:
        lab = cv2.merge((l, a, b))
        bgr = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        bgr = cv2.convertScaleAbs(bgr, alpha=1.01, beta=1)

    elif mean_l > 205:
        lab = cv2.merge((l, a, b))
        bgr = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        bgr = cv2.convertScaleAbs(bgr, alpha=0.99, beta=-2)

    else:
        lab = cv2.merge((l, a, b))
        bgr = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def natural_adjustment(rgb):
    pil = Image.fromarray(rgb).convert("RGB")

    # 手のシワを強調しない自然補正
    pil = ImageEnhance.Brightness(pil).enhance(1.00)
    pil = ImageEnhance.Color(pil).enhance(1.01)
    pil = ImageEnhance.Contrast(pil).enhance(0.97)
    pil = ImageEnhance.Sharpness(pil).enhance(0.94)

    soft = pil.filter(ImageFilter.GaussianBlur(radius=0.35))
    pil = Image.blend(pil, soft, 0.09)

    return np.array(pil)


def improve_nail_image(filepath):
    pil = Image.open(filepath).convert("RGB")
    pil = ImageOps.exif_transpose(pil)

    rgb = np.array(pil)

    # 切り抜かずに正方形化。爪見切れ防止
    rgb = fit_to_square_no_cut(rgb)

    pil = Image.fromarray(rgb).resize((1080, 1080), Image.LANCZOS)
    rgb = np.array(pil)

    rgb = auto_light_correction(rgb)
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
    text = text.replace("  ", " ")

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
Hot Pepper Beauty用の自然なネイル投稿文を作成してください。

文章の方向性：
・きれいにまとめすぎない
・少しラフなサロン文章
・普通のネイリストが書いた感じ
・短くて読みやすい
・画像に写っている内容だけを書く

絶対条件：
・AIっぽくしない
・絵文字禁止
・説明しすぎない
・押し売りしない
・タイトルは短め
・本文は2〜3文
・同じ語尾を繰り返さない
・変に高級感を出しすぎない

禁止ワード：
個性的
洗練
魅力
ワンランク
存在感
映える
上品

最後は
「{ending}」
で締める。

ハッシュタグは5個。
必ず {shop['area_tag']} を入れる。

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
            temperature=0.28,
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
