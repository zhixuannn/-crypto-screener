"""
交易日誌（/journal）。在 app.py 加兩行就能啟用：

    import journal
    journal.init_app(app, _scheduler)
"""

import os
import hashlib
import logging
import datetime

logger = logging.getLogger(__name__)


def init_app(app, scheduler=None):
    from .routes import bp
    from . import bingx_sync, paper, notify

    if not app.secret_key:
        secret = os.environ.get('FLASK_SECRET_KEY') or hashlib.sha256(
            ('journal:' + os.environ.get('JOURNAL_PASSWORD', 'dev')).encode()).hexdigest()
        app.secret_key = secret
    app.config.setdefault('PERMANENT_SESSION_LIFETIME', datetime.timedelta(days=30))
    app.config.setdefault('SESSION_COOKIE_SAMESITE', 'Lax')
    if os.environ.get('RENDER'):
        app.config.setdefault('SESSION_COOKIE_SECURE', True)
    app.config.setdefault('MAX_CONTENT_LENGTH', 25 * 1024 * 1024)

    app.register_blueprint(bp)

    if scheduler is not None and bingx_sync.has_keys():
        minutes = int(os.environ.get('JOURNAL_SYNC_MINUTES', '5'))
        scheduler.add_job(bingx_sync.run_sync, 'interval', minutes=minutes, id='journal_sync_job',
                          replace_existing=True, max_instances=1, coalesce=True)
        logger.info(f'[日誌] BingX 同步排程已啟動，每 {minutes} 分鐘一次')
        bingx_sync.sync_in_background()
    if scheduler is not None:
        scheduler.add_job(paper.settle_open, 'interval', minutes=5, id='journal_paper_settle',
                          replace_existing=True, max_instances=1, coalesce=True)
        logger.info('[日誌] 紙上驗證結算排程已啟動，每 5 分鐘一次')
        scheduler.add_job(notify.tick, 'interval', minutes=5, id='journal_notify_tick',
                          replace_existing=True, max_instances=1, coalesce=True)
