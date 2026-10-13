# 上升期退出条件修复（cycle_day 无限增长）

日期: 2026-05-30
状态: 已完成

## 根因

style.py 被删除后由 anchor_monitor.py 接管，但两者返回值域不同：
- 旧 style.py: 主升/低迷/抱团/散乱
- 新 anchor_monitor.py: 上升健康/上升过热/赚钱抱团/冰点反转/恐慌陷阱/...

position.py 上升期退出条件检查 `_ms == 低迷`，但 anchor_monitor 在上升期从不返回"低迷"，导致条件永远不满足，cycle_day 无限增长。

## 数据验证

- 162天上升期中，12天满足 sent<40 AND prof<35 但未触发退出
- 23个上升期段，20个直接跳到冰点期（靠冰点检测兜底），仅1个正常进入下降期
- 最长上升期达24天（20260407~20260513）

## 修改

**文件**: quant/position.py
**改动**: 上升期优先级1退出条件去掉 style 依赖

旧:
```python
if (_ms == rules.get(style_trigger, 低迷)
        and sent < rules.get(sent_max, 40)
        and prof < rules.get(prof_max, 35)):
```

新:
```python
if (sent < rules.get(sent_max, 40)
        and prof < rules.get(prof_max, 35)):
```

同步删除不再需要的 `_ms = style.get(invest_style, )` 变量。

**备份**: quant/position.py.bak_20260530_cycle_fix

## 验证

- pytest 41/41 passed
