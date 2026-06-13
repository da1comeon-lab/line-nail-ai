from flask import Flask, request, send_from_directory, redirect, session
from linebot import LineBotApi, WebhookHandler
from linebot.models import *
from linebot.exceptions import InvalidSignatureError
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials

import os
import uuid
import json
import secrets
import requests
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import cv2


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

BASE_URL = os.getenv("BASE_URL", "https://line-nail-ai.onrender.com").rstrip("/")

LOCAL_UPLOAD_DIR = "static/uploads"
os.makedirs(LOCAL_UPLOAD_DIR, exist_ok=True)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_DRIVE_REFRESH_TOKEN = os.getenv("GOOGLE_DRIVE_REFRESH_TOKEN") or os.getenv("GOOGLE_REFRESH_TOKEN")
GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI",
    "https://line-nail-ai.onrender.com/oauth2callback"
)
GOOGLE_DRIVE_ROOT_FOLDER_ID = os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_ID", "").strip()
GOOGLE_DRIVE_ROOT_FOLDER_NAME = os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_NAME", "Smily AI 投稿用")

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]

JST = ZoneInfo("Asia/Tokyo")

user_shop = {}

SHOPS = {
    "八尾店": {
        "slug": "yao",
        "folder_name": "八尾店",
        "name": "ネイルサロン スマイリー八尾店",
        "info": "〒581-0869 大阪府八尾市桜ヶ丘3丁目119 加島ビル1F\nTEL 072-920-7313",
        "area_tag": "#八尾ネイル",
    },
    "住道店": {
        "slug": "suminodo",
        "folder_name": "住道店",
        "name": "ネイルサロン スマイリー住道店",
        "info": "〒574-0046 大阪府大東市赤井1丁目15-27 ポップタウン住道5番館 2F\nTEL 072-870-0585",
        "area_tag": "#住道ネイル",
    },
    "心斎橋店": {
        "slug": "shinsaibashi",
        "folder_name": "心斎橋店",
        "name": "ネイルサロン スマイリー心斎橋店",
        "info": "〒542-0086 大阪府大阪市中央区西心斎橋1丁目8-22 4階\nTEL 06-4708-7318",
        "area_tag": "#心斎橋ネイル",
    },
    "マカナ": {
        "slug": "makana",
        "folder_name": "マカナ",
        "name": "ネイルサロン マカナ河内山本店",
        "info": "〒581-0013 大阪府八尾市山本町南4丁目1-3 岩田ビル506号\nTEL 070-9009-1440",
        "area_tag": "#河内山本ネイル",
    },
}


def now_jst():
    return datetime.now(JST)


def google_client_config():
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI],
        }
    }


def get_drive_credentials():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not GOOGLE_DRIVE_REFRESH_TOKEN:
        return None

    return Credentials(
        token=None,
        refresh_token=GOOGLE_DRIVE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=DRIVE_SCOPES,
    )


def get_drive_access_token():
    creds = get_drive_credentials()
    if not creds:
        return None

    from google.auth.transport.requests import Request

    creds.refresh(Request())
    return creds.token


def drive_headers(token):
    return {"Authorization": f"Bearer {token}"}


def drive_find_folder(token, name, parent_id=None):
    query = [
        "mimeType = 'application/vnd.google-apps.folder'",
        "trashed = false",
        f"name = '{name.replace(chr(39), chr(92) + chr(39))}'",
    ]

    if parent_id:
        query.append(f"'{parent_id}' in parents")

    res = requests.get(
        "https://www.googleapis.com/drive/v3/files",
        headers=drive_headers(token),
        params={
            "q": " and ".join(query),
            "fields": "files(id,name)",
            "pageSize": 10,
        },
        timeout=30,
    )
    res.raise_for_status()
    files = res.json().get("files", [])
    return files[0]["id"] if files else None


def drive_create_folder(token, name, parent_id=None):
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }

    if parent_id:
        metadata["parents"] = [parent_id]

    res = requests.post(
        "https://www.googleapis.com/drive/v3/files",
        headers={**drive_headers(token), "Content-Type": "application/json"},
        json=metadata,
        timeout=30,
    )
    res.raise_for_status()
    return res.json()["id"]


def drive_get_or_create_folder(token, name, parent_id=None):
    try:
        folder_id = drive_find_folder(token, name, parent_id)
    except requests.HTTPError as e:
        if e.response is None or e.response.status_code != 403:
            raise
        folder_id = None

    if folder_id:
        return folder_id
    return drive_create_folder(token, name, parent_id)


def drive_upload_file(token, filepath, filename, folder_id, mime_type):
    metadata = {"name": filename, "parents": [folder_id]}

    with open(filepath, "rb") as f:
        files = {
            "metadata": (
                "metadata",
                json.dumps(metadata, ensure_ascii=False),
                "application/json; charset=UTF-8",
            ),
            "file": (filename, f, mime_type),
        }
        res = requests.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,webViewLink",
            headers=drive_headers(token),
            files=files,
            timeout=60,
        )

    res.raise_for_status()
    return res.json()


def save_text_file(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def fit_to_square_no_cut(rgb):
    h, w, _ = rgb.shape
    size = max(w, h)
    canvas = np.ones((size, size, 3), dtype=np.uint8) * 255

    x = (size - w) // 2
    y = int((size - h) * 0.32)
    y = max(0, min(y, size - h))

    canvas[y:y + h, x:x + w] = rgb
    return canvas


def soft_highlight_control(rgb):
    img = rgb.astype(np.float32)
    threshold = 245
    mask = img > threshold
    img[mask] = threshold + (img[mask] - threshold) * 0.45
    return np.clip(img, 0, 255).astype(np.uint8)


def detect_image_type(rgb):
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h, s, v = cv2.split(hsv)

    skin_mask = ((h < 25) | (h > 165)) & (s > 25) & (s < 150) & (v > 80)
    dark_mask = (v < 70) & (s > 25)

    total = rgb.shape[0] * rgb.shape[1]
    skin_ratio = float(np.sum(skin_mask)) / total
    dark_ratio = float(np.sum(dark_mask)) / total

    return skin_ratio > 0.10, dark_ratio > 0.035


def protect_dark_tones(rgb):
    img = rgb.astype(np.float32)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    v = hsv[:, :, 2]
    dark_mask = v < 65
    img[dark_mask] = img[dark_mask] * 1.08 + 3
    return np.clip(img, 0, 255).astype(np.uint8)


def auto_light_correction(rgb, is_hand_photo, has_black_nail):
    rgb = soft_highlight_control(rgb)

    if has_black_nail:
        rgb = protect_dark_tones(rgb)

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    mean_l = float(np.mean(l))

    if is_hand_photo:
        lab = cv2.merge((l, a, b))
        bgr = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        if mean_l < 115:
            bgr = cv2.convertScaleAbs(bgr, alpha=1.015, beta=3)
        elif mean_l > 205:
            bgr = cv2.convertScaleAbs(bgr, alpha=0.99, beta=-2)
    else:
        if mean_l < 120:
            clahe = cv2.createCLAHE(clipLimit=0.8, tileGridSize=(8, 8))
            l = clahe.apply(l)
        lab = cv2.merge((l, a, b))
        bgr = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        if mean_l < 120:
            bgr = cv2.convertScaleAbs(bgr, alpha=1.025, beta=3)
        elif mean_l > 210:
            bgr = cv2.convertScaleAbs(bgr, alpha=0.99, beta=-2)

    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def natural_adjustment(rgb, is_hand_photo):
    pil = Image.fromarray(rgb).convert("RGB")

    if is_hand_photo:
        pil = ImageEnhance.Brightness(pil).enhance(1.00)
        pil = ImageEnhance.Color(pil).enhance(1.01)
        pil = ImageEnhance.Contrast(pil).enhance(0.97)
        pil = ImageEnhance.Sharpness(pil).enhance(0.94)
        soft = pil.filter(ImageFilter.GaussianBlur(radius=0.35))
        pil = Image.blend(pil, soft, 0.09)
    else:
        pil = ImageEnhance.Brightness(pil).enhance(1.00)
        pil = ImageEnhance.Color(pil).enhance(1.025)
        pil = ImageEnhance.Contrast(pil).enhance(1.015)
        pil = ImageEnhance.Sharpness(pil).enhance(1.08)
        soft = pil.filter(ImageFilter.GaussianBlur(radius=0.20))
        pil = Image.blend(pil, soft, 0.03)

    return np.array(pil)


def improve_nail_image(source_path, output_path):
    pil = Image.open(source_path).convert("RGB")
    pil = ImageOps.exif_transpose(pil)

    rgb = np.array(pil)

    is_hand_photo, has_black_nail = detect_image_type(rgb)
    rgb = auto_light_correction(rgb, is_hand_photo, has_black_nail)
    rgb = natural_adjustment(rgb, is_hand_photo)

    out = Image.fromarray(rgb).convert("RGB")
    out.save(output_path, "JPEG", quality=95, optimize=True)


def shop_message():
    return """店舗名を送信してください。

・八尾店
・住道店
・心斎橋店
・マカナ

設定後にネイル画像を送ると、
画像補正して店舗別フォルダへ保存します。"""


def build_post_text(shop):
    return f"""投稿候補文はCodexで作成します。

{shop["area_tag"]} #ネイルデザイン #ニュアンスネイル #シンプルネイル #ネイルサロン

{shop["name"]}
{shop["info"]}
"""


def save_image_workflow(message_content, shop_key):
    shop = SHOPS[shop_key]
    stamp = now_jst()
    date_folder = stamp.strftime("%Y-%m-%d")
    basename = stamp.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]

    local_dir = os.path.join(LOCAL_UPLOAD_DIR, shop["slug"], "unposted", date_folder)
    os.makedirs(local_dir, exist_ok=True)

    original_filename = f"{basename}_original.jpg"
    corrected_filename = f"{basename}_corrected.jpg"
    text_filename = f"{basename}_post_text.txt"

    original_path = os.path.join(local_dir, original_filename)
    corrected_path = os.path.join(local_dir, corrected_filename)
    text_path = os.path.join(local_dir, text_filename)

    with open(original_path, "wb") as f:
        for chunk in message_content.iter_content():
            f.write(chunk)

    improve_nail_image(original_path, corrected_path)
    post_text = build_post_text(shop)
    save_text_file(text_path, post_text)

    result = {
        "shop_key": shop_key,
        "shop": shop,
        "date_folder": date_folder,
        "original_filename": original_filename,
        "corrected_filename": corrected_filename,
        "text_filename": text_filename,
        "original_path": original_path,
        "corrected_path": corrected_path,
        "text_path": text_path,
        "original_url": f"{BASE_URL}/{original_path.replace(os.sep, '/')}",
        "corrected_url": f"{BASE_URL}/{corrected_path.replace(os.sep, '/')}",
        "drive": None,
    }

    token = get_drive_access_token()
    if token:
        root_id = GOOGLE_DRIVE_ROOT_FOLDER_ID or drive_get_or_create_folder(
            token,
            GOOGLE_DRIVE_ROOT_FOLDER_NAME,
        )
        shop_folder_id = drive_get_or_create_folder(token, shop["folder_name"], root_id)
        unposted_folder_id = drive_get_or_create_folder(token, "未投稿", shop_folder_id)
        drive_get_or_create_folder(token, "投稿済み", shop_folder_id)
        date_folder_id = drive_get_or_create_folder(token, date_folder, unposted_folder_id)

        original_drive = drive_upload_file(token, original_path, original_filename, date_folder_id, "image/jpeg")
        corrected_drive = drive_upload_file(token, corrected_path, corrected_filename, date_folder_id, "image/jpeg")
        text_drive = drive_upload_file(token, text_path, text_filename, date_folder_id, "text/plain")

        result["drive"] = {
            "root_folder_id": root_id,
            "shop_folder_id": shop_folder_id,
            "unposted_folder_id": unposted_folder_id,
            "date_folder_id": date_folder_id,
            "original": original_drive,
            "corrected": corrected_drive,
            "text": text_drive,
        }

    return result


@app.route("/")
def home():
    return """
    LINE Nail AI Running<br><br>
    確認ページ:<br>
    /drive-status<br>
    /drive-login<br>
    /latest-uploads<br>
    """


@app.route("/static/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(LOCAL_UPLOAD_DIR, filename)


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


@app.route("/drive-login")
def drive_login():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET が設定されていません。"

    flow = Flow.from_client_config(
        google_client_config(),
        scopes=DRIVE_SCOPES,
        autogenerate_code_verifier=True,
    )
    flow.redirect_uri = GOOGLE_REDIRECT_URI

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="false",
        prompt="consent",
    )

    session["oauth_state"] = state
    session["code_verifier"] = flow.code_verifier
    session["oauth_kind"] = "drive"

    return redirect(authorization_url)


@app.route("/oauth2callback")
def oauth2callback():
    try:
        state = session.get("oauth_state")
        code_verifier = session.get("code_verifier")

        if not state or not code_verifier:
            return "Google連携エラー：セッション情報が切れています。もう一度 /drive-login からやり直してください。"

        flow = Flow.from_client_config(
            google_client_config(),
            scopes=DRIVE_SCOPES,
            state=state,
        )
        flow.redirect_uri = GOOGLE_REDIRECT_URI
        flow.code_verifier = code_verifier
        flow.fetch_token(authorization_response=request.url)

        refresh_token = flow.credentials.refresh_token

        if not refresh_token:
            return "Google Drive連携は成功しましたが、refresh_token が取得できませんでした。もう一度 /drive-login を開いて許可し直してください。"

        return f"""
        Google Drive連携成功<br><br>
        RenderのEnvironmentへ追加してください。<br><br>
        KEY：GOOGLE_DRIVE_REFRESH_TOKEN<br>
        VALUE：{refresh_token}<br><br>
        この画面の内容は他人に見せないでください。
        """

    except Exception as e:
        print("oauth error:", e)
        print(traceback.format_exc())
        return f"Google Drive連携エラー：{e}"


@app.route("/drive-status")
def drive_status():
    html = """
    <h1>Google Drive 連携状態確認</h1>
    <h2>環境変数</h2>
    <ul>
    """
    checks = {
        "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID,
        "GOOGLE_CLIENT_SECRET": GOOGLE_CLIENT_SECRET,
        "GOOGLE_DRIVE_REFRESH_TOKEN or GOOGLE_REFRESH_TOKEN": GOOGLE_DRIVE_REFRESH_TOKEN,
        "GOOGLE_REDIRECT_URI": GOOGLE_REDIRECT_URI,
        "GOOGLE_DRIVE_ROOT_FOLDER_ID": GOOGLE_DRIVE_ROOT_FOLDER_ID,
    }
    for key, value in checks.items():
        html += f"<li>{key}: {'設定あり' if value else '未設定'}</li>"
    html += "</ul>"

    try:
        token = get_drive_access_token()
        if not token:
            html += "<p>Driveトークンがありません。/drive-login を開いてください。</p>"
            return html

        root_id = GOOGLE_DRIVE_ROOT_FOLDER_ID or drive_get_or_create_folder(
            token,
            GOOGLE_DRIVE_ROOT_FOLDER_NAME,
        )
        html += f"<p>Drive接続OK</p><p>Root folder ID: {root_id}</p>"

    except Exception as e:
        html += f"<pre>Drive確認エラー: {e}</pre>"

    return html


@app.route("/latest-uploads")
def latest_uploads():
    html = "<h1>保存済み画像</h1>"

    for shop_key, shop in SHOPS.items():
        shop_dir = os.path.join(LOCAL_UPLOAD_DIR, shop["slug"])
        html += f"<h2>{shop_key}</h2>"

        if not os.path.exists(shop_dir):
            html += "<p>まだ保存なし</p>"
            continue

        files = []
        for root, _, filenames in os.walk(shop_dir):
            for filename in filenames:
                if filename.lower().endswith((".jpg", ".jpeg", ".png", ".txt")):
                    path = os.path.join(root, filename)
                    files.append(path)

        files = sorted(files, key=lambda p: os.path.getmtime(p), reverse=True)[:20]

        if not files:
            html += "<p>まだ保存なし</p>"
            continue

        html += "<ul>"
        for path in files:
            url = "/" + path.replace(os.sep, "/")
            html += f'<li><a href="{url}" target="_blank">{os.path.basename(path)}</a></li>'
        html += "</ul>"

    return html


@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    if text in SHOPS:
        user_shop[user_id] = text
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=f"{text}に設定しました。\nネイル画像を送ってください。"
            ),
        )
        return

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=shop_message()))


@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id

    if user_id not in user_shop:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=shop_message()))
        return

    shop_key = user_shop[user_id]

    try:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="画像を受け取りました。\n保存が完了したらお知らせします。"),
        )

        message_content = line_bot_api.get_message_content(event.message.id)
        result = save_image_workflow(message_content, shop_key)

        if result["drive"]:
            drive_text = (
                "保存完了しました。\n\n"
                f"店舗：{shop_key}\n"
                f"日付：{result['date_folder']}\n"
                "状態：未投稿\n\n"
                "投稿用の画像として保存しました。"
            )
        else:
            drive_text = (
                "画像は保存しました。\n\n"
                f"店舗：{shop_key}\n"
                f"日付：{result['date_folder']}\n"
                "状態：未投稿\n\n"
                "管理側の保存設定を確認してください。"
            )

        line_bot_api.push_message(user_id, TextSendMessage(text=drive_text))

    except Exception as e:
        print("image error:", e)
        print(traceback.format_exc())
        try:
            line_bot_api.push_message(
                user_id,
                TextSendMessage(text=f"保存エラーが出ました。\n場所：画像保存処理\n内容：{e}"),
            )
        except Exception as push_error:
            print("push error:", push_error)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
