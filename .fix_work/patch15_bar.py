# -*- coding: utf-8 -*-
"""patch15: 盘中分钟采样器（方案1）
背景：intraday_monitor.py 因 pytdx 缺失每天 09:25 启动即崩（迁移遗留），分钟采样从未跑起来，
      导致量能对比曲线数据稀疏。
修复：在 realtime 轮询线程中每分钟落一行轻量盘中快照（复用 fetch_full_market，不引入新依赖，
      不依赖页面是否打开）；同分钟去重。失效的 intraday_monitor cron 另行注释停用。"""
import pathlib, sys

ROOT = pathlib.Path('/opt/stock-review')
REL = 'quant/realtime_service.py'
p = ROOT / REL
s = p.read_text(encoding='utf-8')

def rep(old, new):
    global s
    n = s.count(old)
    if n != 1:
        print('!! expect 1, got %d: %r' % (n, old[:70]))
        sys.exit(1)
    s = s.replace(old, new)
    print('ok %r' % old[:55])

# 1) __init__ 增加去重标记
rep('        self._amt_buffer_date = ""  # 当天全天成交额入账日期（每天只记一笔）',
    '        self._amt_buffer_date = ""  # 当天全天成交额入账日期（每天只记一笔）\n        self._last_bar_minute = ""   # 分钟采样去重（每分钟一行）')

# 2) 新增 _save_minute_bar 方法（插到 start_polling 之前）
NEW_METHOD = '''    def _save_minute_bar(self, force: bool = False):
        """每分钟落一行轻量盘中快照（不依赖页面是否打开）

        供量能对比曲线 / 盘中图表使用；同分钟去重；字段为完整快照的子集，读取方兼容。
        """
        try:
            now = datetime.now()
            if not force and not _is_trade_time():
                return
            minute = now.strftime("%H:%M")
            if self._last_bar_minute == minute:
                return
            quotes = self.fetch_full_market()
            if not quotes:
                return
            from utils import get_limit_threshold, _limit_price
            total_amount = 0.0
            up = down = flat = zt = 0
            for q in quotes:
                total_amount += q.get("amount", 0) or 0
                pct = q.get("change_pct", 0) or 0
                if pct > 0:
                    up += 1
                elif pct < 0:
                    down += 1
                else:
                    flat += 1
                code = str(q.get("code", ""))
                name = q.get("name", "")
                price = q.get("price", 0) or 0
                lc = q.get("last_close", 0) or 0
                if price > 0 and lc > 0 and price >= _limit_price(lc, get_limit_threshold(code, name)):
                    zt += 1
            bar = {
                "time": now.strftime("%H:%M:%S"),
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "total_amount_yi": round(total_amount / 1e8, 1),
                "total_up": up,
                "total_down": down,
                "total_flat": flat,
                "total_stocks": len(quotes),
                "limit_up_count": zt,
                "minute_bar": True,
            }
            log_dir = BASE_DIR / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            fp = log_dir / ("intraday_%s.jsonl" % now.strftime("%Y%m%d"))
            with open(fp, "a", encoding="utf-8") as f:
                print(json.dumps(bar, ensure_ascii=False), file=f)
            self._last_bar_minute = minute
        except Exception as e:
            logger.warning("分钟快照落盘失败: %s" % e)

'''
rep('    def start_polling(self, interval=None):', NEW_METHOD + '    def start_polling(self, interval=None):')

# 3) 轮询循环每轮调用（分钟去重在方法内部）
rep('''                    if _is_trade_time():
                        self.get_snapshot()
                    else:''',
    '''                    if _is_trade_time():
                        self.get_snapshot()
                        self._save_minute_bar()
                    else:''')

p.write_text(s, encoding='utf-8')
print('patch15 done')
