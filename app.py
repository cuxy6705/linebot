import datetime
from flask import Flask, request, abort
from apscheduler.schedulers.background import BackgroundScheduler

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
app = Flask(__name__)


scheduler = BackgroundScheduler()
scheduler.start()

import datetime
from flask import Flask, request, abort
from apscheduler.schedulers.background import BackgroundScheduler

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
# Supabase
from supabase import create_client, Client  # pip install supabase

# 請填入你的 Channel Access Token 與 Channel Secret
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN')
CHANNEL_SECRET = os.getenv('CHANNEL_SECRET')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_ANON_KEY = os.getenv('SUPABASE_ANON_KEY')

app = Flask(__name__)

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
line_handler = WebhookHandler(CHANNEL_SECRET)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# 建立背景排程器
scheduler = BackgroundScheduler()
scheduler.start()

def parse_date_time(date_str, time_str):
    """
    將日期與時間字串解析為 datetime 物件。支援:
    - date_str: 2/19 or 2月19 or YYYY-MM-DD
    - time_str: HH:MM (24小時制)
    """
    current_year = datetime.datetime.now().year
    
    # 嘗試不帶年份的格式
    date_formats = ['%m/%d', '%m月%d']
    date_obj = None
    for fmt in date_formats:
        try:
            temp = datetime.datetime.strptime(date_str, fmt)
            date_obj = temp.replace(year=current_year)
            break
        except ValueError:
            pass
    
    if not date_obj:
        # 試試完整格式
        try:
            date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            raise ValueError("日期格式錯誤")
    
    # 解析時間
    try:
        time_obj = datetime.datetime.strptime(time_str, '%H:%M')
    except ValueError:
        raise ValueError("時間格式錯誤")

    return date_obj.replace(hour=time_obj.hour, minute=time_obj.minute, second=0)


@line_handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip()
    parts = text.split(' ', 2)  # 期望: [日期, 時間, 事件描述]

    if len(parts) < 3:
        # 格式不符，回覆提示
        reply_text = ("請依照格式輸入：\n日期 時間 事件描述\n"
                      "例如：2/19 23:00 開會")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    date_str, time_str, desc = parts
    try:
        dt = parse_date_time(date_str, time_str)
    except ValueError:
        reply_text = ("日期或時間格式錯誤！\n"
                      "日期可用: MM/DD、MM月DD、YYYY-MM-DD\n"
                      "時間請用 24 小時 HH:MM")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 檢查是否是過去時間
    now = datetime.datetime.now()
    if dt <= now:
        reply_text = "指定的提醒時間已過，請輸入未來時間。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 將提醒事件寫入資料庫
    data = {
        "user_id": user_id,
        "notify_time": dt.isoformat(),  # 以 ISO8601 字串儲存
        "text": desc,
        "is_sent": False
    }
    supabase.table("reminders").insert(data).execute()

    reply_text = f"已設定提123醒：{dt.strftime('%Y-%m-%d %H:%M')} {desc}"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info(f"Request body: {body}")

    # handle webhook body
    try:
        line_handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'

if __name__ == "__main__":
    app.run()
