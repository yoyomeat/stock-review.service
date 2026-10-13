"""统一推送模块 — QQ Bot 通过 OpenClaw 发送"""
import subprocess
import logging

logger = logging.getLogger('stock-review.notifier')

# QQ Bot 目标（从 send_share.sh 复用）
QQ_TARGET = "qqbot:c2c:fc845549ab913cafdb8cc7f273d5db04"


def push(title: str, body: str, level: str = 'info', image_path: str = None) -> bool:
    """统一推送入口 — 单条消息发送（文字+图片合并）"""
    prefix = {'critical': '🚨 ', 'warning': '⚠️ ', 'info': ''}.get(level, '')
    message = f"{prefix}{title}\n{body}" if body else f"{prefix}{title}"

    import shutil as _sh
    _cli = _sh.which('openclaw') or '/usr/local/bin/openclaw'  # cron 裸 PATH 兜底
    cmd = [_cli, 'message', 'send',
           '--channel', 'qqbot',
           '--target', QQ_TARGET,
           '--message', message]
    if image_path:
        cmd.extend(['--media', image_path])

    timeout = 90 if image_path else 30
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            logger.info(f'QQ推送成功: {title}')
            return True
        else:
            logger.error(f'QQ推送失败: {result.stderr}')
            return False
    except Exception as e:
        logger.error(f'QQ推送异常: {e}')
        return False
