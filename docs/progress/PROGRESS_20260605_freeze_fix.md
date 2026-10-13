# 冰点守卫退出逻辑修复

日期: 2026-06-05
状态: 已完成

## 问题

`_handle_freeze()` 函数中，当 `prev_was_freeze=True` 且守卫条件 `core_sent<30 AND prof<30` 不满足时，
代码 fall-through 到反弹确认/情绪修复检查，都不满足后**默认回到冰点**。

导致 4 天 cycle_label 错误地保持为"冰点期"，而 `calc_op_v2` 已正确判断为非冰点（`freeze=False`），
造成 cycle_label 与 freeze 字段不一致。

| 日期 | 修复前 | 修复后 | core | prof |
|------|--------|--------|------|------|
| 20250113 | 冰点期 | 下降期第1天 | 28.1 | 39 |
| 20251119 | 冰点期 | 下降期第1天 | 19.4 | 36 |
| 20260304 | 冰点期 | 下降期第1天 | 25.9 | 35 |
| 20260515 | 冰点期 | 下降期第1天 | 20.4 | 31 |

## 修复方案

符合架构原则1（单一修改点）：只修改 `quant/position.py` 一个文件。

### 改动 1：`_handle_freeze` 新增 `guard_passed` 参数

```python
def _handle_freeze(prev_cycle_state, core_sent, prof, prev_sent, f3_score, gap_days, guard_passed=True):
```

### 改动 2：默认返回逻辑

```python
# 守卫失败：反弹/情绪修复都不满足 → 转下降期（不再回到冰点）
if not guard_passed:
    return '下降期第1天', 1, 0.2, 0, ['冰点守卫退出(...)']

# 守卫通过但反弹/情绪修复不满足 → 延续冰点
return '冰点期', 1, 0.0, 0, ['冰点延续(...)']
```

### 改动 3：调用处传递守卫状态

```python
if '冰点' in prev_label:
    return _handle_freeze(..., guard_passed=is_freeze)
```

## 验证

- pytest 85/85 passed
- 边界测试 7/7 passed：
  - 正常进冰点 → 冰点期 ✅
  - 守卫通过 → 冰点期 ✅
  - 守卫失败+反弹条件满足 → 反弹确认期 ✅
  - 守卫失败+情绪修复 → 下降期 ✅
  - 守卫失败+无恢复 → 下降期 ✅
  - 非守冰点场景(三通道) → 冰点期 ✅

## 影响范围

- 文件：`quant/position.py`
- 函数：`_handle_freeze()` + `determine_cycle()` 调用处
- 行数：+3行（参数+条件判断）

## 修改文件

| 文件 | 改动 |
|------|------|
| `quant/position.py` | `_handle_freeze` 新增 `guard_passed` 参数，默认返回逻辑改为守卫感知 |

---

*记录时间: 2026-06-05 10:25*
