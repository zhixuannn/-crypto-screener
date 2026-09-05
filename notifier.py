"""
發送 Telegram 通知的模組。
需要在環境變數設定：
- TELEGRAM_BOT_TOKEN：你的Bot Token
- TELEGRAM_CHAT_ID：你的Chat ID
"""

import os
import requests

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')


def send_telegram_message(text: str) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        print('[notifier] 尚未設定 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID，跳過通知')
        return False

    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    try:
        resp = requests.post(url, data={
            'chat_id': CHAT_ID,
            'text': text,
            'parse_mode': 'HTML',
        }, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f'[notifier] 發送Telegram通知失敗: {e}')
        return False


def format_signal_message(symbol: str, direction: str, entry_price: float, sl_price: float, timeframe: str) -> str:
    direction_text = '📈 做多 (Long)' if direction == 'long' else '📉 做空 (Short)'
    risk = abs(entry_price - sl_price)
    risk_pct = (risk / entry_price) * 100 if entry_price else 0

    return (
        f'<b>XUAN 3+1 進場訊號</b>\n'
        f'幣種: <b>{symbol}</b>\n'
        f'週期: {timeframe}\n'
        f'方向: {direction_text}\n'
        f'進場價: {entry_price:.6g}\n'
        f'止損價: {sl_price:.6g}\n'
        f'止損距離: {risk_pct:.2f}%'
    )
