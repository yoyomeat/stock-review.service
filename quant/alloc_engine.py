"""
仓位分配引擎

支持两种模式：
  1. 普通分配：无单票上限，余量补到首选
  2. 身位分流：等权分配（次日按开盘涨幅决定买谁）
"""


class AllocEngine:
    """仓位分配引擎"""

    @staticmethod
    def allocate(total_position: int, n_picks: int,
                 board_race: bool = False) -> list[int]:
        """
        分配仓位。

        Args:
            total_position: 总仓位百分比（如 75）
            n_picks: 标的数量
            board_race: 是否身位分流模式

        Returns:
            各标的仓位百分比列表，如 [45, 30]
        """
        if total_position <= 0 or n_picks <= 0:
            return []

        # 身位分流：等权分配
        if board_race:
            per = total_position // n_picks
            allocs = [per] * n_picks
            remainder = total_position - per * n_picks
            for i in range(remainder):
                allocs[i] += 1
            return allocs

        # 普通分配：等权分配，余量补到首选
        per = total_position // n_picks
        allocs = [per] * n_picks
        remainder = total_position - per * n_picks
        if remainder > 0 and allocs:
            allocs[0] += remainder

        return allocs
