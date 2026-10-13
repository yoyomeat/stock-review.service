"""T+1 保护回归测试（KNOWN_BUGS #38）

规则：买入执行日（entry_idx == day_idx）当天不得卖出（含止损/止盈/到期/清仓/升级淘汰），
次日（day_idx > entry_idx）起才允许卖出。

本测试用"止损价高于现价 + max_hold_days=0"的极端持仓，确保若无 T+1 守卫必然触发卖出，
从而精确锁定守卫行为（非空转测试）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.bt_position_manager import (  # noqa: E402
    check_exits,
    force_close_residual,
    candidate_upgrade_check,
)

CODE = "600000"


def _pos(entry_price=10.0, stop_loss=20.0):
    """最小持仓字典：止损价高于现价、到期天数为 0，任何一天都会触发卖出"""
    return {
        "name": "测试股",
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": 99.0,
        "alloc": 10.0,
        "max_hold_days": 0,
        "fired_tiers": [],
        "tp_tiers": None,
        "strategy_tag": "other",
        "source": "",
    }


def _prices(low=9.5):
    return {"open": 10.1, "high": 10.2, "low": low, "close": 9.8}


class TestT1Protection:
    def test_check_exits_holds_on_buy_day(self):
        """买入执行日当天：止损/到期条件均已触发，但必须不可卖出"""
        pos = {CODE: _pos()}
        closed, _ = check_exits(pos, {CODE: 5}, {CODE: _prices()},
                                10000.0, 5, 1.0, True)
        assert closed == []
        assert CODE in pos

    def test_check_exits_sells_next_day(self):
        """次日起：同样条件下允许卖出（证明测试非空转）"""
        pos = {CODE: _pos()}
        closed, _ = check_exits(pos, {CODE: 5}, {CODE: _prices()},
                                10000.0, 6, 1.0, True)
        assert len(closed) == 1
        assert closed[0]["code"] == CODE
        assert CODE not in pos

    def test_force_close_residual_holds_on_buy_day(self):
        """强制清残仓路径：买入当天同样受 T+1 保护"""
        pos = {CODE: _pos()}
        result = force_close_residual(pos, {CODE: 5}, {CODE: _prices()},
                                      10000.0, 5, True)
        assert result[0] == []
        assert CODE in pos

    def test_candidate_upgrade_holds_on_buy_day(self):
        """候选升级检查路径：买入当天同样受 T+1 保护"""
        pos = {CODE: _pos()}
        result = candidate_upgrade_check(pos, {CODE: 5}, {}, {CODE: _prices()},
                                         5, True)
        assert result[0] == []
        assert CODE in pos

    def test_future_entry_also_protected(self):
        """entry_idx > day_idx（挂单未成交）：同样不可卖出"""
        pos = {CODE: _pos()}
        closed, _ = check_exits(pos, {CODE: 6}, {CODE: _prices()},
                                10000.0, 5, 1.0, True)
        assert closed == []
        assert CODE in pos
