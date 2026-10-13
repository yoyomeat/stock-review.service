"""测试量化画像核心函数"""
import sys
sys.path.insert(0, '.')

from quant.quant_profile import (
    _percentile_rank, _safe_float, _parse_change_pct,
    _calc_shape_score, _pearson_r, _iqr,
)

def test_percentile_rank():
    assert _percentile_rank([1,2,3,4,5], 3) == 40.0
    assert _percentile_rank([1,2,3,4,5], 1) == 0.0
    assert _percentile_rank([1,2,3,4,5], 5) == 80.0
    assert _percentile_rank([], 3) == 50.0
    print('test_percentile_rank OK')

def test_safe_float():
    assert _safe_float(None) == 0
    assert _safe_float('-') == 0
    assert _safe_float(3.14) == 3.14
    assert _safe_float('abc', -1) == -1
    print('test_safe_float OK')

def test_parse_change_pct():
    r = _parse_change_pct('1234567,5.5,1.2,34567890')
    assert r['amount'] == 1234567
    assert r['pct'] == 5.5
    assert r['vol_ratio'] == 1.2
    assert r['turnover'] == 34567890
    print('test_parse_change_pct OK')

def test_calc_shape_score():
    # U型: high-low-high
    u_shape = []
    for i in range(242):
        t = i / 241
        u_val = t ** 2 * 0.5 + abs(t - 0.5) ** 2 * 0.5
        u_shape.append(u_val)
    score = _calc_shape_score(u_shape)
    assert score > 0.5, 'U-shape should match well'
    print('test_calc_shape_score: U=%.3f' % score)

    # Flat: should not match U
    flat = [1.0] * 242
    score_flat = _calc_shape_score(flat)
    assert score_flat < 0.3, 'Flat should not match U'
    print('test_calc_shape_score: flat=%.3f' % score_flat)

def test_iqr():
    assert _iqr([1,2,3,4,5,6,7,8,9,10]) == 5
    assert _iqr([]) == 0
    print('test_iqr OK')

def test_pearson():
    x = [1,2,3,4,5]
    y = [2,4,6,8,10]
    r = _pearson_r(x, y)
    assert abs(r - 1.0) < 0.001
    print('test_pearson OK')

if __name__ == '__main__':
    test_percentile_rank()
    test_safe_float()
    test_parse_change_pct()
    test_calc_shape_score()
    test_iqr()
    test_pearson()
    print('\nAll tests passed!')
