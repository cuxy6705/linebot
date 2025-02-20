import os
import datetime
from linebot import LineBotApi
from linebot.models import TextSendMessage
from supabase import create_client, Client

CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_ANON_KEY = os.getenv('SUPABASE_ANON_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

def handler(event, context):
    # 1. 查詢到期的提醒
    now = datetime.datetime.utcnow()  # 使用 UTC 或依你資料庫時區設定
    # 假設 reminders.notify_time 是 timestamptz，且以 UTC 儲存
    resp = supabase.table("reminders") \
        .select("*") \
        .lte("notify_time", now.isoformat()) \
        .eq("is_sent", False) \
        .execute()

    rows = resp.data

    if not rows:
        return {
            "statusCode": 200,
            "body": "No reminders"
        }

    for row in rows:
        user_id = row['user_id']
        desc = row['text']
        notify_time = row['notify_time']  # ISO8601 字串
        try:
            # 2. 發送提醒
            line_bot_api.push_message(user_id, TextSendMessage(text=f"提醒：{desc}\n(原設定時間: {notify_time})"))

            # 3. 更新狀態為已發送
            supabase.table("reminders") \
                .update({"is_sent": True}) \
                .eq("id", row['id']) \
                .execute()

        except Exception as e:
            print("推播失敗:", e)

    return {
        "statusCode": 200,
        "body": f"Processed {len(rows)} reminders"
    }
