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
import traceback
import numpy as np
import cv2


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

BASE_URL = os.getenv("BASE_URL", "https://line-nail-ai.onrender.com").rstrip("/")
IMAGE_DIR = "static/images"
os.makedirs(IMAGE_DIR, exist_ok=True)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN")
GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI",
    "https://line-nail-ai.onrender.com/oauth2callback"
)

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

WRITING_STYLES = [
    "ネイリストがそのまま投稿したような、短く自然な文章。",
    "少しラフで、説明しすぎないサロンブログ風。",
    "色味と雰囲気だけをさらっと書く文章。",
    "落ち着いた言い方で、押し売り感を出さない文章。",
    "きれいにまとめすぎず、日常の投稿っぽい文章。"
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
    "上品": "",
    "ちょうどいいです": "合わせやすい仕上がりです",
    "おすすめです。おすすめです。": "おすすめです。",
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
    return """
    LINE Nail AI Running<br><br>
    確認ページ:<br>
    /google-status<br>
    /google-login<br>
    /google-locations<br>
    """


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
        print(traceback.format_exc())
        return "OK"

    return "OK"


@app.route("/google-status")
def google_status():
    html = "<h2>Google連携 状態確認</h2>"
    html += "<h3>環境変数</h3>"
    html += "<ul>"
    html += f"<li>GOOGLE_CLIENT_ID: {'設定あり' if GOOGLE_CLIENT_ID else '未設定'}</li>"
    html += f"<li>GOOGLE_CLIENT_SECRET: {'設定あり' if GOOGLE_CLIENT_SECRET else '未設定'}</li>"
    html += f"<li>GOOGLE_REFRESH_TOKEN: {'設定あり' if GOOGLE_REFRESH_TOKEN else '未設定'}</li>"
    html += f"<li>GOOGLE_REDIRECT_URI: {GOOGLE_REDIRECT_URI}</li>"
    html += f"<li>FLASK_SECRET_KEY: {'設定あり' if os.getenv('FLASK_SECRET_KEY') else '未設定'}</li>"
    html += "</ul>"

    if not GOOGLE_REFRESH_TOKEN:
        html += "<p>GOOGLE_REFRESH_TOKEN が未設定です。先に /google-login を開いて連携してください。</p>"
        return html

    try:
        token = get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }

        accounts_res = requests.get(
            "https://mybusinessaccountmanagement.googleapis.com/v1/accounts",
            headers=headers,
            timeout=30
        )

        html += "<h3>Google Business Profile API確認</h3>"
        html += f"<p>accounts API status: {accounts_res.status_code}</p>"
        html += f"<pre>{accounts_res.text}</pre>"
        return html

    except Exception as e:
        return html + f"<p>Google確認エラー: {e}</p>"


@app.route("/google-login")
def google_login():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return "Googleの環境変数 GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET が設定されていません。"

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

        query = request.query_string.decode("utf-8")
        authorization_response = GOOGLE_REDIRECT_URI
        if query:
            authorization_response += "?" + query

        flow.fetch_token(authorization_response=authorization_response)

        credentials = flow.credentials
        refresh_token = credentials.refresh_token

        if not refresh_token:
            return """
            Google連携は成功しましたが、refresh_token が取得できませんでした。<br>
            もう一度 /google-login を開いて許可し直してください。<br><br>
            それでも出ない場合は、Googleアカウント側の連携済みアプリから一度削除して再連携してください。
            """

        return f"""
        Google連携成功<br><br>
        RenderのEnvironmentへ追加してください。<br><br>
        KEY：GOOGLE_REFRESH_TOKEN<br>
        VALUE：{refresh_token}<br><br>
        この画面の内容は他人に見せないでください。
        """

    except Exception as e:
        print("Google oauth error:", e)
        print(traceback.format_exc())
        return f"Google連携エラー：{e}"


@app.route("/google-locations")
def google_locations():
    try:
        token = get_access_token()

        if not token:
            return "GOOGLE_REFRESH_TOKEN が設定されていません。先に /google-login を開いてください。"

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
            本文: <pre>{accounts_res.text}</pre>
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
        print("Google locations error:", e)
        print(traceback.format_exc())
        return f"Google店舗取得エラー：{e}"


def resize_keep_aspect(rgb, max_side=1280):
    h, w, _ = rgb.shape
    long_side = max(h, w)

    if long_side <= max_side:
        return rgb

    scale = max_side / long_side
    new_w = int(w * scale)
    new_h = int(h * scale)

    return cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)


def detect_image_type(rgb):
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h, s, v = cv2.split(hsv)

    skin_mask = (
        ((h < 25) | (h > 165)) &
        (s > 20) &
        (s < 155) &
        (v > 70)
    )

    dark_mask = (
        (v < 75) &
        (s > 20)
    )

    total = rgb.shape[0] * rgb.shape[1]
    skin_ratio = float(np.sum(skin_mask)) / total
    dark_ratio = float(np.sum(dark_mask)) / total

    is_hand_photo = skin_ratio > 0.08
    has_black_nail = dark_ratio > 0.03

    return is_hand_photo, has_black_nail


def gray_world_balance(rgb, strength=0.22):
    img = rgb.astype(np.float32)

    means = np.mean(img.reshape(-1, 3), axis=0)
    gray = np.mean(means)

    scale = gray / np.maximum(means, 1)
    scale = 1 + (scale - 1) * strength

    img = img * scale

    return np.clip(img, 0, 255).astype(np.uint8)


def soft_highlight_control(rgb):
    img = rgb.astype(np.float32)

    threshold = 238
    mask = img > threshold
    img[mask] = threshold + (img[mask] - threshold) * 0.35

    return np.clip(img, 0, 255).astype(np.uint8)


def protect_dark_tones(rgb):
    img = rgb.astype(np.float32)

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    v = hsv[:, :, 2]

    dark_mask = v < 65
    img[dark_mask] = img[dark_mask] * 1.06 + 4

    return np.clip(img, 0, 255).astype(np.uint8)


def auto_light_correction(rgb, is_hand_photo, has_black_nail):
    rgb = gray_world_balance(rgb)
    rgb = soft_highlight_control(rgb)

    if has_black_nail:
        rgb = protect_dark_tones(rgb)

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    mean_l = float(np.mean(l))

    if mean_l < 105:
        gamma = 0.92
        table = np.array([((i / 255.0) ** gamma) * 255 for i in range(256)]).astype("uint8")
        bgr = cv2.LUT(bgr, table)

        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)

        clahe = cv2.createCLAHE(clipLimit=0.55, tileGridSize=(8, 8))
        l = clahe.apply(l)

    elif mean_l > 198:
        l = cv2.convertScaleAbs(l, alpha=0.985, beta=-3)

    else:
        l = cv2.convertScaleAbs(l, alpha=1.01, beta=1)

    lab = cv2.merge((l, a, b))
    bgr = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def natural_adjustment(rgb, is_hand_photo):
    pil = Image.fromarray(rgb).convert("RGB")

    if is_hand_photo:
        pil = ImageEnhance.Brightness(pil).enhance(1.01)
        pil = ImageEnhance.Color(pil).enhance(1.045)
        pil = ImageEnhance.Contrast(pil).enhance(1.025)
        pil = ImageEnhance.Sharpness(pil).enhance(1.06)

        soft = pil.filter(ImageFilter.GaussianBlur(radius=0.25))
        pil = Image.blend(pil, soft, 0.035)

    else:
        pil = ImageEnhance.Brightness(pil).enhance(1.01)
        pil = ImageEnhance.Color(pil).enhance(1.06)
        pil = ImageEnhance.Contrast(pil).enhance(1.045)
        pil = ImageEnhance.Sharpness(pil).enhance(1.12)

        soft = pil.filter(ImageFilter.GaussianBlur(radius=0.18))
        pil = Image.blend(pil, soft, 0.02)

    return np.array(pil)


def improve_nail_image(filepath):
    pil = Image.open(filepath).convert("RGB")
    pil = ImageOps.exif_transpose(pil)

    rgb = np.array(pil)

    is_hand_photo, has_black_nail = detect_image_type(rgb)

    rgb = auto_light_correction(rgb, is_hand_photo, has_black_nail)
    rgb = natural_adjustment(rgb, is_hand_photo)

    # 正方形化しない。元画像の縦横比のまま、長辺だけ整える。
    rgb = resize_keep_aspect(rgb, max_side=1280)

    out = Image.fromarray(rgb).convert("RGB")
    out.save(
        filepath,
        "JPEG",
        quality=94,
        optimize=True
    )


def create_line_preview_image(original_path, preview_path):
    img = Image.open(original_path).convert("RGB")
    img = ImageOps.exif_transpose(img)

    # プレビューも正方形にしない。元の形のまま小さくする。
    img.thumbnail((600, 600), Image.LANCZOS)

    img.save(
        preview_path,
        "JPEG",
        quality=85,
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


def safe_push_text(user_id, text):
    try:
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text=text)
        )
        return True
    except Exception as e:
        print("push text error:", e)
        print(traceback.format_exc())
        return False


def safe_push_image(user_id, image_url, preview_url):
    try:
        line_bot_api.push_message(
            user_id,
            ImageSendMessage(
                original_content_url=image_url,
                preview_image_url=preview_url
            )
        )
        return True
    except Exception as e:
        print("push image error:", e)
        print(traceback.format_exc())
        return False


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
    stage = "開始"

    if user_id not in user_shop:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=shop_message())
        )
        return

    shop_key = user_shop[user_id]
    shop = SHOPS[shop_key]

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="画像を受け取りました。加工と文章作成をしています。少しお待ちください。")
    )

    try:
        stage = "LINE画像取得"
        message_content = line_bot_api.get_message_content(event.message.id)

        image_id = uuid.uuid4().hex
        filename = f"{image_id}.jpg"
        preview_filename = f"preview_{image_id}.jpg"

        filepath = os.path.join(IMAGE_DIR, filename)
        preview_path = os.path.join(IMAGE_DIR, preview_filename)

        stage = "画像保存"
        with open(filepath, "wb") as f:
            for chunk in message_content.iter_content():
                f.write(chunk)

        stage = "画像補正"
        improve_nail_image(filepath)

        stage = "LINEプレビュー作成"
        create_line_preview_image(filepath, preview_path)

        image_url = f"{BASE_URL}/static/images/{filename}"
        preview_url = f"{BASE_URL}/static/images/{preview_filename}"

        stage = "画像push送信"
        image_sent = safe_push_image(user_id, image_url, preview_url)

        stage = "画像読み込み"
        with open(filepath, "rb") as img:
            base64_image = base64.b64encode(img.read()).decode("utf-8")

        ending = random.choice(ENDINGS)
        writing_style = random.choice(WRITING_STYLES)

        prompt = f"""
あなたはネイルサロンのスタッフです。
Hot Pepper Beautyに載せる、自然なネイル投稿文を作ってください。

今回の文章トーン：
{writing_style}

大事な方針：
・AIっぽい説明文にしない
・実際のサロンスタッフが短く書いた感じにする
・画像に写っている内容だけを書く
・文章をきれいに整えすぎない
・一文を長くしすぎない
・「片手は」「もう片手は」をなるべく使わない
・「ちょうどいいです」を使わない
・同じ語尾を続けない
・押し売りしない
・絵文字は禁止

禁止ワード：
個性的
洗練
魅力
ワンランク
存在感
映える
上品

文章の感じ：
オレンジ系のカラーに、シルバーのきらっとしたデザインを合わせました。
左右で雰囲気を変えて、少し遊びのある仕上がりです。

淡いカラーに細めのラインを入れたデザインです。
派手すぎず、手元がすっきり見えます。

最後は
「{ending}」
で締める。

ハッシュタグは5個。
必ず {shop['area_tag']} を入れる。

出力形式：

タイトル

本文

#タグ #タグ #タグ #タグ #タグ

{shop['name']}
{shop['info']}
"""

        stage = "AI文章生成"
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            temperature=0.55,
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
                            "text": "このネイル画像を見て、自然な投稿文を作成してください。"
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

        if not image_sent:
            text = f"""画像送信だけ失敗しました。
ブログ文章は下に送ります。

{text}"""

        stage = "LINE文章push送信"
        safe_push_text(user_id, text)

    except Exception as e:
        print("image error stage:", stage)
        print("image error:", e)
        print(traceback.format_exc())

        safe_push_text(
            user_id,
            f"""エラーが出ました。

止まった場所:
{stage}

内容:
{e}

もう一度画像を送ってください。
何度も出る場合は、RenderのLogsを確認してください。"""
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
