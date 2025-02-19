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



app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
line_handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))

# 建立背景排程器
scheduler = BackgroundScheduler()
scheduler.start()

def parse_date(date_str):
    """
    解析不帶年份的日期字串，支援「5/30」或「5月30」格式，預設年份為今年，
    同時也支援完整格式「YYYY-MM-DD」。
    """
    current_year = datetime.datetime.now().year
    # 嘗試不帶年份的格式
    formats = ['%m/%d', '%m月%d']
    for fmt in formats:
        try:
            dt = datetime.datetime.strptime(date_str, fmt)
            # 用今年取代解析後的年份
            dt = dt.replace(year=current_year)
            return dt
        except ValueError:
            continue
    # 如果前面格式皆無法解析，嘗試完整格式
    try:
        return datetime.datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        raise ValueError("日期格式錯誤，請使用例如 MM/DD、MM月DD 或 YYYY-MM-DD 的格式。")

def send_reminder(user_id, reminder_text):
    """
    在指定時間發送提醒訊息給 user_id
    """
    try:
        line_bot_api.push_message(user_id, TextSendMessage(text=f"提醒：{reminder_text}"))
    except Exception as e:
        print("發送提醒失敗：", e)


@line_handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    received_text = event.message.text.strip()

    # 預期格式：日期 時間 事件描述
    # 日期部分可使用 MM/DD、MM月DD 或 YYYY-MM-DD 格式，時間部分格式為 HH:MM
    try:
        # 以空白分割，最多切三個部分
        parts = received_text.split(' ', 2)
        if len(parts) != 3:
            raise ValueError("格式錯誤")
        date_str, time_str, event_desc = parts

        # 解析日期部分
        scheduled_date = parse_date(date_str)
        # 解析時間部分，格式為 HH:MM
        try:
            time_obj = datetime.datetime.strptime(time_str, '%H:%M')
        except ValueError:
            raise ValueError("時間格式錯誤，請使用 HH:MM 格式（例如 23:00）")

        # 將日期與時間合併
        scheduled_time = scheduled_date.replace(hour=time_obj.hour, minute=time_obj.minute, second=0)

        # 依據需求，提醒時間提前一小時
        notify_time = scheduled_time - datetime.timedelta(hours=1)

        now = datetime.datetime.now()
        if notify_time <= now:
            reply_text = "指定的提醒時間已過，請選擇未來的日期與時間。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        # 加入排程工作，於 notify_time 發送提醒訊息
        mixText = scheduled_time.strftime('%m/%d %H:%M') + event_desc
        scheduler.add_job(
            send_reminder,
            trigger='date',
            run_date=notify_time,
            args=[user_id, mixText]
        )

        # reply_text = (f"好的，將在 {notify_time.strftime('%Y-%m-%d %H:%M')} 提醒你：{event_desc}\n"
        #               f"(原定事件時間：{scheduled_time.strftime('%Y-%m-%d %H:%M')})")
        # line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

    except Exception as e:
        print("解析或排程錯誤：", e)
        reply_text = ("請依照格式輸入：日期 時間 事件描述\n"
                      "日期部分可使用 MM/DD、MM月DD 或 YYYY-MM-DD 格式，\n"
                      "時間請使用 24 小時制 HH:MM 格式\n"
                      "例如：2/19 23:00 開會")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        line_handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'

if __name__ == "__main__":
    app.run()
