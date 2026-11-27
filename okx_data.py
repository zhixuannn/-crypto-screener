"""
OKX 公開合約數據（不用 API 金鑰）：給「查幣」用。
  多空人數比：做多帳戶數 ÷ 做空帳戶數（15 分鐘一筆）
  CVD：OKX 主動買量 − 主動賣量（USD，15 分鐘一筆）累加
都是 OKX 市場的數字，不是 BingX 的；只用來看「大家在推哪個方向」的趨勢。
OKX 沒有上這個幣時回傳 {'ok': False, ...}，查幣照常顯示其他資料。
"""

import logging

import requests

logger = logging.getLogger(__name__)

OKX = 'https://www.okx.com'
BARS = 24          # 看最近 24 根 15 分鐘（6 小時）畫趨勢線
TREND_BARS = 4     # 趨勢＝最近 4 根（1 小時）的變化
_session = requests.Session()


def _get(path, params):
    r = _session.get(OKX + path, params=params, timeout=8)
    j = r.json()
    if str(j.get('code')) != '0':
        raise RuntimeError(j.get('msg') or f'code {j.get("code")}')
    return j.get('data') or []


def _trend(now, before, tol):
    if now is None or before is None:
        return 'flat'
    diff = now - before
    if abs(diff) <= tol:
        return 'flat'
    return 'up' if diff > 0 else 'down'


def flow(base: str) -> dict:
    inst = f'{base}-USDT-SWAP'
    out = {'ok': True, 'source': 'OKX', 'inst': inst}
    try:
        ls = _get('/api/v5/rubik/stat/contracts/long-short-account-ratio-contract',
                  {'instId': inst, 'period': '15m', 'limit': str(BARS)})
        tv = _get('/api/v5/rubik/stat/taker-volume-contract',
                  {'instId': inst, 'period': '15m', 'unit': '2', 'limit': str(BARS)})
    except Exception as e:
        msg = str(e)
        logger.info(f'[OKX] {inst} 抓不到: {msg}')
        if '51001' in msg or '不存在' in msg or 'exist' in msg.lower():
            return {'ok': False, 'error': f'OKX 沒有 {base} 的永續合約'}
        return {'ok': False, 'error': 'OKX 數據暫時抓不到'}

    # OKX 回傳是新到舊，轉成舊到新
    ls = sorted(([int(t), float(v)] for t, v in ls), key=lambda x: x[0])
    tv = sorted(([int(t), float(s), float(b)] for t, s, b in tv), key=lambda x: x[0])

    if ls:
        vals = [v for _, v in ls]
        now = vals[-1]
        before = vals[-1 - TREND_BARS] if len(vals) > TREND_BARS else vals[0]
        out['ls'] = {'now': now, 'before': before, 'series': vals,
                     'trend': _trend(now, before, tol=abs(before) * 0.01)}
    if tv:
        cvd, acc = [], 0.0
        for _, sell, buy in tv:
            acc += buy - sell
            cvd.append(acc)
        before = cvd[-1 - TREND_BARS] if len(cvd) > TREND_BARS else 0.0
        d1h = cvd[-1] - before
        vol_1h = sum(s + b for _, s, b in tv[-TREND_BARS:]) or 1.0
        out['cvd'] = {'series': cvd, 'delta_1h': d1h, 'total': cvd[-1],
                      'trend': _trend(d1h, 0.0, tol=vol_1h * 0.02)}   # 一小時淨買賣不到成交量 2% 算持平
    return out
