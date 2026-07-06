"""向后兼容 shim — 实现已迁至 investbrief.core.scoring。

现有 risk 模块仍 import 本模块的符号, 全部重导出, 行为零变化。
阶段4 收尾时若 risk 内已全部改 import core.scoring, 可删除本文件。
"""
from investbrief.core.scoring import (  # noqa: F401
    moving_average,
    exponential_moving_average,
    calculate_macd,
    percentile_rank,
    normalize_score,
    consecutive_count,
    safe_divide,
)
