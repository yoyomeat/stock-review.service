# -*- coding: utf-8 -*-
"""patch7: 陈旧测试断言对齐现行设计（龙空龙 / 标准路由废弃 / regime 停用 / 板块结构）"""
import pathlib, sys

ROOT = pathlib.Path('/opt/stock-review')

def edit(relpath, pairs):
    p = ROOT / relpath
    s = p.read_text(encoding='utf-8')
    for old, new in pairs:
        n = s.count(old)
        if n == 0:
            print(f'!! [{relpath}] not found: {old[:70]!r}')
            sys.exit(1)
        s = s.replace(old, new)
        print(f'ok [{relpath}] x{n}: {old[:55]!r}')
    p.write_text(s, encoding='utf-8')

# ── tests/test_anchor_monitor.py：ACTION_POS_MULT['wait']=1.0（标准路由已废弃），4 处旧断言 ──
edit('tests/test_anchor_monitor.py', [
    ("        assert pos == 0.3  # 标准路由已废弃",
     "        assert pos == 1.0  # ACTION_POS_MULT['wait']（标准路由已废弃，wait 仓位系数=1.0）"),
])

# ── tests/test_pipeline_scenarios.py：regime 强制退出/调仓已禁用（2026-06-10），恒返回 normal ──
edit('tests/test_pipeline_scenarios.py', [
    ('''    def test_ice_point_exit_all(self):
        """冰点期 → exit_all"""''',
     '''    def test_ice_point_exit_all(self):
        """冰点期 → regime 强制退出已禁用（2026-06-10），恒返回 normal"""'''),
    ("        assert r[0] == 'exit_all'",
     "        assert r[0] == 'normal'  # regime 强制退出已禁用（2026-06-10）"),
    ("""        assert r[0] in ('reduce', 'exit_all')""",
     """        assert r[0] == 'normal'  # regime 调仓已禁用（龙空龙重构），恒返回 normal"""),
])

# ── tests/test_core_logic.py：sector_top5 新版结构（name/change_pct/amount/leaders） ──
edit('tests/test_core_logic.py', [
    ('''            assert "avg_pct" in s
            assert "score" in s''',
     '''            assert "change_pct" in s  # 新版板块结构（旧 avg_pct/score 已废弃）'''),
])

print('patch7 done')
