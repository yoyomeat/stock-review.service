#!/usr/bin/env python3
import sys
sys.path.insert(0, '/opt/stock-review')
from quant.anchor_monitor import _load_kph_data, compute_strong_pool, detect_concentration_signal

dates = ['20250108', '20250507', '20250623']
for d in dates:
    kph = _load_kph_data(d)
    pool = compute_strong_pool(d, '/opt/stock-review/data/csv')
    kph_sectors = kph.get('sectors', []) if kph else []
    print(f'{d}:')
    print(f'  kph: {len(kph_sectors)} sectors')
    print(f'  pool: {len(pool)} stocks')
    
    conc = detect_concentration_signal(
        pool=pool,
        kph_data=kph,
        cycle_phase='上升期第1天',
        sent=60,
        prev_state=None,
        today_date=d,
    )
    print(f'  conc.plate: {conc.plate}')
    print(f'  conc.signal: {conc.signal}')
    print(f'  conc.ratio: {conc.ratio}')
    print()
