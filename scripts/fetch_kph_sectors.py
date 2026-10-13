#!/usr/bin/env python3
"""获取开盘啦精选板块（KPH50）数据 + 成分股明细

每日cron（16:30）做两件事：
1. 实时：获取今天的板块排行（amount/change_pct/净流入等），供当天review
2. 历史：补全昨天的成分股数据（龙一龙二龙三），供review展示龙头
"""
import sys, os, json, time
from datetime import datetime, timedelta, date as date_type
sys.path.insert(0, '/opt/levistock')
import levistock as lk

OUTPUT_DIR = '/opt/stock-review/data/kph_sectors'
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _date_fmt(date_str):
    """20260702 -> 2026-07-02"""
    return f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}'


def _prev_trading_day(date_str):
    """获取前一个交易日（简单回退，跳过周末）"""
    dt = datetime.strptime(date_str, '%Y%m%d')
    for _ in range(5):
        dt -= timedelta(days=1)
        if dt.weekday() < 5:
            return dt.strftime('%Y%m%d')
    return None


def fetch_today_ranking(date_str):
    """步骤1：获取今天的板块排行（实时接口）"""
    d = _date_fmt(date_str)
    try:
        sectors = lk.sector_ranking_kph(date=d, zs_type=lk.SECTOR_SELECTED)
        if not sectors:
            print(f'  {date_str}: 无板块数据')
            return None
        print(f'  {date_str}: 实时板块排行 {len(sectors)} 个')
        return sectors
    except Exception as e:
        print(f'  {date_str}: 板块排行失败 {e}')
        return None


def enrich_with_stocks(sectors, target_date):
    """步骤2：补全成分股数据（历史接口，用target_date）"""
    d = _date_fmt(target_date)
    enriched = 0
    for s in sectors:
        plate_id = s.get('plate_id', '')
        if not plate_id:
            continue
        # 如果已有stocks（非空），跳过
        if s.get('stocks'):
            enriched += 1
            continue
        try:
            stocks = lk.sector_stocks_his_kph(plate_id=plate_id, date=d)
            s['stocks'] = stocks if stocks else []
            if stocks:
                enriched += 1
        except Exception:
            s['stocks'] = []
        time.sleep(0.3)
    return enriched


def fetch_kph50(date_str):
    """获取指定日期的KPH50精选板块数据，含个股明细"""
    # 步骤1：获取今天的板块排行
    sectors = fetch_today_ranking(date_str)
    if not sectors:
        return

    # 步骤2：补全成分股（用昨天的数据，因为当天接口不支持）
    prev_date = _prev_trading_day(date_str)
    if prev_date:
        enriched = enrich_with_stocks(sectors, prev_date)
        total = len([s for s in sectors if s.get('plate_id')])
        print(f'  {date_str}: 成分股补全 {enriched}/{total} (用{prev_date}数据)')

    result = {
        'date': date_str,
        'fetch_time': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'sectors': sectors,
    }

    out_path = os.path.join(OUTPUT_DIR, f'{date_str}.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f'  {date_str}: {len(sectors)} 个板块 -> {out_path}')


def main():
    dates = sys.argv[1:] if len(sys.argv) > 1 else None

    if not dates:
        # 默认模式：获取今天 + 补全昨天成分股
        today = date_type.today().strftime('%Y%m%d')
        yesterday = _prev_trading_day(today)
        dates = [today]
        # 如果今天的KPH已存在，只补全昨天成分股
        today_path = os.path.join(OUTPUT_DIR, f'{today}.json')
        if os.path.exists(today_path):
            # 检查是否需要补全昨天成分股
            data = json.load(open(today_path, encoding='utf-8'))
            sectors = data.get('sectors', [])
            needs_enrich = any(not s.get('stocks') for s in sectors if s.get('plate_id'))
            if needs_enrich and yesterday:
                print(f'补全 {today} 的成分股 (用{yesterday}数据)')
                enriched = enrich_with_stocks(sectors, yesterday)
                total = len([s for s in sectors if s.get('plate_id')])
                print(f'  成分股补全 {enriched}/{total}')
                with open(today_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            else:
                print(f'{today}: 已存在且成分股完整，跳过')
            return
        print(f'获取今日KPH: {today}')

    missing = [d for d in dates if not os.path.exists(os.path.join(OUTPUT_DIR, f'{d}.json'))]
    print(f'需要获取: {len(missing)} 天 (已跳过 {len(dates) - len(missing)} 天)')

    for d in missing:
        fetch_kph50(d)
        time.sleep(0.5)


if __name__ == '__main__':
    main()
