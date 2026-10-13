#!/usr/bin/env python3
"""
Plotly 交互式图表模块 — 零侵入 HTML 片段生成
生成独立的 HTML 片段，可直接嵌入现有报告，不影响 Flutter 前端。

功能：
1. 交互式 K 线图（悬停详情、缩放、导出）
2. 板块热力图（资金流向可视化）
3. 连板梯队金字塔（情绪温度计）
4. Plotly 仪表盘（替换 SVG gauge）
5. Plotly 柱状图（替换 sparkline）

用法：
    from plotly_charts import (
        plotly_gauge,      # 替换 _svg_gauge
        plotly_bar,        # 替换 _sparkline
        plotly_candlestick,# K 线图
        plotly_heatmap,    # 板块热力图
        plotly_pyramid,    # 连板金字塔
    )
"""

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False
    print("Warning: plotly not installed, interactive charts disabled")


# ════════════════════════════════════════════════════════
# 通用配置
# ════════════════════════════════════════════════════════
LAYOUT_CONFIG = dict(
    paper_bgcolor='rgba(0,0,0,0)',
    plot_bgcolor='rgba(0,0,0,0)',
    font=dict(color='#e8eaf0', size=12),
    margin=dict(l=20, r=20, t=40, b=20),
    hoverlabel=dict(
        bgcolor='#1e2235',
        bordercolor='#4e7cff',
        font_size=13,
        font_family='monospace'
    ),
)


def _to_html(fig, height=400, include_plotlyjs=False):
    """生成独立 HTML 片段（不包含 plotly.js，需在主页面引入一次）"""
    config = dict(
        displayModeBar=True,
        modeBarButtonsToAdd=['toggleSpikelines', 'hoverCompareCartesian'],
        displaylogo=False,
        responsive=True,
    )
    return fig.to_html(
        full_html=False,
        include_plotlyjs=include_plotlyjs,
        config=config,
        default_height=height,
    )


def get_plotlyjs_cdn():
    """获取 plotly.js CDN 引用（在主 HTML 中引入一次即可）"""
    return '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>'


# ════════════════════════════════════════════════════════
# 1. Plotly 仪表盘 — 替换 _svg_gauge
# ════════════════════════════════════════════════════════
def plotly_gauge(score, max_score=100, title='', subtitle=''):
    """
    交互式仪表盘，替换 _svg_gauge
    支持悬停查看详细分数、颜色渐变
    """
    if not HAS_PLOTLY:
        return f'<div style="text-align:center"><span style="font-size:48px;color:#4e7cff">{score}</span><br><small>{title}</small></div>'
    
    pct = min(100, max(0, score / max_score * 100))
    
    # 颜色渐变
    if pct >= 80:
        bar_color = '#34d399'
    elif pct >= 60:
        bar_color = '#4e7cff'
    elif pct >= 40:
        bar_color = '#fbbf24'
    else:
        bar_color = '#f87171'
    
    fig = go.Figure(go.Indicator(
        mode='gauge+number+delta',
        value=score,
        number=dict(
            font=dict(size=48, color='#e8eaf0'),
            suffix=f'/{max_score}'
        ),
        title=dict(
            text=f'{title}<br><span style="font-size:12px;color:#8b90a0">{subtitle}</span>',
            font=dict(size=16, color='#e8eaf0')
        ),
        gauge=dict(
            axis=dict(
                range=[0, max_score],
                tickwidth=2,
                tickcolor='#565b6e',
                tickfont=dict(size=11, color='#8b90a0')
            ),
            bar=dict(color=bar_color, thickness=0.3),
            bgcolor='rgba(30,34,53,0.8)',
            borderwidth=0,
            steps=[
                dict(range=[0, max_score*0.4], color='rgba(248,113,113,0.15)'),
                dict(range=[max_score*0.4, max_score*0.6], color='rgba(251,191,36,0.15)'),
                dict(range=[max_score*0.6, max_score*0.8], color='rgba(78,124,255,0.15)'),
                dict(range=[max_score*0.8, max_score], color='rgba(52,211,153,0.15)'),
            ],
            threshold=dict(
                line=dict(color='white', width=3),
                thickness=0.8,
                value=score
            )
        )
    ))
    
    fig.update_layout(
        **LAYOUT_CONFIG,
        height=250,
        width=280,
    )
    
    return _to_html(fig, height=250)


# ════════════════════════════════════════════════════════
# 2. Plotly 柱状图 — 替换 _sparkline
# ════════════════════════════════════════════════════════
def plotly_bar(values, labels=None, title='', height=120):
    """
    交互式柱状图，替换 _sparkline
    支持悬停查看数值、点击高亮
    """
    if not HAS_PLOTLY or not values:
        return ''
    
    if labels is None:
        labels = [f'D{i+1}' for i in range(len(values))]
    
    colors = ['#34d399' if v > 0 else '#f87171' if v < 0 else '#565b6e' for v in values]
    
    fig = go.Figure(go.Bar(
        x=labels,
        y=values,
        marker_color=colors,
        marker_line_width=0,
        hovertemplate='<b>%{x}</b><br>数值: %{y:+.1f}<extra></extra>',
        text=[f'{v:+.0f}' for v in values],
        textposition='outside',
        textfont=dict(size=10, color='#8b90a0'),
    ))
    
    fig.update_layout(
        **LAYOUT_CONFIG,
        height=height,
        showlegend=False,
        xaxis=dict(
            showgrid=False,
            tickfont=dict(size=10, color='#8b90a0'),
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor='rgba(255,255,255,0.04)',
            tickfont=dict(size=10, color='#8b90a0'),
            zeroline=True,
            zerolinecolor='rgba(255,255,255,0.1)',
        ),
        bargap=0.3,
    )
    
    return _to_html(fig, height=height)


# ════════════════════════════════════════════════════════
# 3. K 线图 — 全新交互式图表
# ════════════════════════════════════════════════════════
def plotly_candlestick(df, title='', show_ma=True, show_volume=True, height=500):
    """
    交互式 K 线图
    支持：悬停 OHLCV、缩放、十字光标、导出 PNG
    
    参数：
        df: DataFrame，必须包含 date, open, high, low, close, volume 列
        title: 图表标题
        show_ma: 是否显示均线（MA5, MA10, MA20）
        show_volume: 是否显示成交量
        height: 图表高度
    """
    if not HAS_PLOTLY:
        return '<p>Plotly not available</p>'
    
    required_cols = ['date', 'open', 'high', 'low', 'close']
    if not all(c in df.columns for c in required_cols):
        return '<p>Missing required columns</p>'
    
    has_vol = 'volume' in df.columns and show_volume
    
    if has_vol:
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.75, 0.25],
        )
    else:
        fig = go.Figure()
    
    # K 线
    candle = go.Candlestick(
        x=df['date'],
        open=df['open'],
        high=df['high'],
        low=df['low'],
        close=df['close'],
        increasing_line_color='#34d399',
        decreasing_line_color='#f87171',
        increasing_fillcolor='rgba(52,211,153,0.5)',
        decreasing_fillcolor='rgba(248,113,113,0.5)',
        name='K线',
        hoverinfo='text',
        hovertext=[
            f'<b>{d}</b><br>O:{o:.2f} H:{h:.2f}<br>L:{l:.2f} C:{c:.2f}<br>涨跌:{(c/o-1)*100:+.2f}%'
            for d, o, h, l, c in zip(df['date'], df['open'], df['high'], df['low'], df['close'])
        ],
    )
    
    if has_vol:
        fig.add_trace(candle, row=1, col=1)
    else:
        fig.add_trace(candle)
    
    # 均线
    if show_ma and len(df) >= 5:
        for period, color, name in [(5, '#fbbf24', 'MA5'), (10, '#4e7cff', 'MA10'), (20, '#a855f7', 'MA20')]:
            if len(df) >= period:
                ma = df['close'].rolling(period).mean()
                ma_trace = go.Scatter(
                    x=df['date'], y=ma,
                    mode='lines',
                    line=dict(color=color, width=1.5),
                    name=name,
                    hovertemplate=f'{name}: %{{y:.2f}}<extra></extra>',
                )
                if has_vol:
                    fig.add_trace(ma_trace, row=1, col=1)
                else:
                    fig.add_trace(ma_trace)
    
    # 成交量
    if has_vol:
        vol_colors = ['#34d399' if c >= o else '#f87171' 
                      for c, o in zip(df['close'], df['open'])]
        vol_bar = go.Bar(
            x=df['date'], y=df['volume'],
            marker_color=vol_colors,
            marker_line_width=0,
            name='成交量',
            hovertemplate='<b>%{x}</b><br>成交量: %{y:,.0f}<extra></extra>',
            showlegend=False,
        )
        fig.add_trace(vol_bar, row=2, col=1)
    
    # 布局
    fig.update_layout(
        **LAYOUT_CONFIG,
        height=height,
        title=dict(text=title, font=dict(size=16)),
        xaxis_rangeslider_visible=False,
        hovermode='x unified',
        spikedash='dot',
        spikecolor='#565b6e',
        spikethickness=1,
    )
    
    # 十字光标
    fig.update_xaxes(
        showspikes=True,
        spikecolor='#565b6e',
        spikethickness=1,
        spikedash='dot',
        spikemode='across',
    )
    fig.update_yaxes(
        showspikes=True,
        spikecolor='#565b6e',
        spikethickness=1,
        spikedash='dot',
        spikemode='across',
    )
    
    if has_vol:
        fig.update_xaxes(showgrid=False, row=2, col=1)
        fig.update_yaxes(title_text='成交量', row=2, col=1, tickfont=dict(size=10))
        fig.update_yaxes(title_text='价格', row=1, col=1, tickfont=dict(size=10))
    
    return _to_html(fig, height=height)


# ════════════════════════════════════════════════════════
# 4. 板块热力图 — 全新交互式图表
# ════════════════════════════════════════════════════════
def plotly_heatmap(sectors, title='板块热力图', height=500):
    """
    板块热力图（气泡图风格）
    悬停显示：板块名称、涨跌幅、成交额、领涨股
    
    参数：
        sectors: list of dict，每个 dict 包含:
            - name: 板块名称
            - change_pct: 涨跌幅 (%)
            - volume: 成交额 (亿)
            - leader: 领涨股
            - leader_change: 领涨股涨幅
        title: 图表标题
    """
    if not HAS_PLOTLY or not sectors:
        return '<p>No data</p>'
    
    # 准备数据
    names = [s['name'] for s in sectors]
    changes = [s['change_pct'] for s in sectors]
    volumes = [s.get('volume', 0) for s in sectors]
    leaders = [s.get('leader', '') for s in sectors]
    leader_changes = [s.get('leader_change', 0) for s in sectors]
    
    # 气泡大小（基于成交额）
    max_vol = max(volumes) if volumes and max(volumes) > 0 else 1
    sizes = [max(20, v / max_vol * 80) for v in volumes]
    
    fig = go.Figure(go.Scatter(
        x=list(range(len(names))),
        y=changes,
        mode='markers+text',
        marker=dict(
            size=sizes,
            color=changes,
            colorscale=[
                [0, '#991b1b'],
                [0.25, '#f87171'],
                [0.5, '#565b6e'],
                [0.75, '#22c55e'],
                [1, '#166534'],
            ],
            cmin=-5,
            cmax=5,
            line=dict(width=1, color='rgba(255,255,255,0.2)'),
            colorbar=dict(
                title='涨跌幅(%)',
                tickfont=dict(size=12),
                len=0.6,
            ),
        ),
        text=names,
        textposition='middle center',
        textfont=dict(size=10, color='white'),
        hovertemplate=(
            '<b>%{text}</b><br>'
            '涨跌幅: %{y:+.2f}%<br>'
            '成交额: %{customdata[0]:.1f}亿<br>'
            '领涨股: %{customdata[1]} (%{customdata[2]:+.1f}%)'
            '<extra></extra>'
        ),
        customdata=list(zip(volumes, leaders, leader_changes)),
    ))
    
    fig.update_layout(
        **LAYOUT_CONFIG,
        height=height,
        title=dict(text=title, font=dict(size=16)),
        xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        yaxis=dict(
            title='涨跌幅(%)',
            gridcolor='rgba(255,255,255,0.04)',
            zeroline=True,
            zerolinecolor='rgba(255,255,255,0.15)',
            ticksuffix='%',
        ),
        showlegend=False,
    )
    
    # 添加零线注释
    fig.add_hline(y=0, line_dash='dash', line_color='rgba(255,255,255,0.2)', line_width=1)
    
    return _to_html(fig, height=height)


def plotly_heatmap_treemap(sectors, title='板块热力图', height=500):
    """
    TreeMap 风格热力图（更适合展示层级关系）
    """
    if not HAS_PLOTLY or not sectors:
        return '<p>No data</p>'
    
    # 准备数据
    labels = [s['name'] for s in sectors]
    parents = ['' for _ in sectors]  # 扁平结构
    values = [abs(s.get('volume', 1)) for s in sectors]
    changes = [s['change_pct'] for s in sectors]
    
    # 文本标签
    texts = [
        f'{name}<br>{change:+.2f}%'
        for name, change in zip(labels, changes)
    ]
    
    fig = go.Figure(go.Treemap(
        labels=labels,
        parents=parents,
        values=values,
        text=texts,
        textinfo='text',
        hovertemplate='<b>%{label}</b><br>涨跌幅: %{customdata:+.2f}%<br>成交额: %{value:.1f}亿<extra></extra>',
        customdata=changes,
        marker=dict(
            colors=changes,
            colorscale=[
                [0, '#991b1b'],
                [0.25, '#f87171'],
                [0.5, '#565b6e'],
                [0.75, '#22c55e'],
                [1, '#166534'],
            ],
            cmin=-5,
            cmax=5,
            line=dict(width=2, color='rgba(15,17,23,0.8)'),
        ),
        textfont=dict(size=13, color='white'),
    ))
    
    fig.update_layout(
        **LAYOUT_CONFIG,
        height=height,
        title=dict(text=title, font=dict(size=16)),
    )
    
    return _to_html(fig, height=height)


# ════════════════════════════════════════════════════════
# 5. 连板梯队金字塔 — 全新交互式图表
# ════════════════════════════════════════════════════════
def plotly_pyramid(ladder_data, title='连板梯队金字塔', height=400):
    """
    连板梯队金字塔图
    展示各连板层级的股票数量，悬停查看具体股票
    
    参数：
        ladder_data: list of dict，每个 dict 包含:
            - level: 连板层级 (如 '7板', '6板', ...)
            - count: 股票数量
            - stocks: 股票列表 (如 ['圣龙股份', '真视通'])
            - avg_change: 平均涨幅
    """
    if not HAS_PLOTLY or not ladder_data:
        return '<p>No data</p>'
    
    # 按连板层级排序（从高到低）
    sorted_data = sorted(ladder_data, key=lambda x: x['level'], reverse=True)
    
    levels = [d['level'] for d in sorted_data]
    counts = [d['count'] for d in sorted_data]
    stocks_list = [d.get('stocks', []) for d in sorted_data]
    avg_changes = [d.get('avg_change', 0) for d in sorted_data]
    
    # 颜色渐变（从高到低连板，颜色从金到红）
    colors = []
    for i, level in enumerate(levels):
        ratio = i / max(1, len(levels) - 1)
        if ratio < 0.3:
            colors.append('#fbbf24')  # 金色（高位板）
        elif ratio < 0.6:
            colors.append('#f97316')  # 橙色
        else:
            colors.append('#f87171')  # 红色（低位板）
    
    # 金字塔效果：左右对称
    fig = go.Figure()
    
    # 左侧（负值）
    fig.add_trace(go.Bar(
        y=levels,
        x=[-c for c in counts],
        orientation='h',
        marker_color=colors,
        marker_line_width=0,
        name='左侧',
        hovertemplate=(
            '<b>%{y}</b><br>'
            '数量: %{customdata[0]}<br>'
            '平均涨幅: %{customdata[1]:+.2f}%<br>'
            '股票: %{customdata[2]}'
            '<extra></extra>'
        ),
        customdata=list(zip(counts, avg_changes, [', '.join(s) for s in stocks_list])),
        showlegend=False,
    ))
    
    # 右侧（正值）
    fig.add_trace(go.Bar(
        y=levels,
        x=counts,
        orientation='h',
        marker_color=colors,
        marker_line_width=0,
        name='右侧',
        hovertemplate=(
            '<b>%{y}</b><br>'
            '数量: %{customdata[0]}<br>'
            '平均涨幅: %{customdata[1]:+.2f}%<br>'
            '股票: %{customdata[2]}'
            '<extra></extra>'
        ),
        customdata=list(zip(counts, avg_changes, [', '.join(s) for s in stocks_list])),
        showlegend=False,
    ))
    
    # 添加数量标签
    for i, (level, count) in enumerate(zip(levels, counts)):
        fig.add_annotation(
            x=count + 0.3,
            y=level,
            text=str(count),
            showarrow=False,
            font=dict(size=14, color='#e8eaf0', family='monospace'),
            xanchor='left',
        )
    
    fig.update_layout(
        **LAYOUT_CONFIG,
        height=height,
        title=dict(text=title, font=dict(size=16)),
        barmode='overlay',
        bargap=0.15,
        xaxis=dict(
            showgrid=False,
            showticklabels=False,
            range=[-max(counts)*1.5, max(counts)*1.5],
        ),
        yaxis=dict(
            categoryorder='array',
            categoryarray=levels,
            tickfont=dict(size=13, color='#e8eaf0'),
        ),
    )
    
    # 添加中线
    fig.add_vline(x=0, line_color='rgba(255,255,255,0.3)', line_width=2)
    
    return _to_html(fig, height=height)


# ════════════════════════════════════════════════════════
# 6. 资金流向图
# ════════════════════════════════════════════════════════
def plotly_money_flow(flows, title='资金流向', height=350):
    """
    资金流向瀑布图
    
    参数：
        flows: list of dict，包含:
            - name: 名称
            - inflow: 流入 (亿)
            - outflow: 流出 (亿)
    """
    if not HAS_PLOTLY or not flows:
        return '<p>No data</p>'
    
    names = [f['name'] for f in flows]
    inflows = [f['inflow'] for f in flows]
    outflows = [-f['outflow'] for f in flows]
    nets = [f['inflow'] - f['outflow'] for f in flows]
    
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        x=names, y=inflows,
        name='流入',
        marker_color='#34d399',
        marker_line_width=0,
        hovertemplate='<b>%{x}</b><br>流入: %{y:.2f}亿<extra></extra>',
    ))
    
    fig.add_trace(go.Bar(
        x=names, y=outflows,
        name='流出',
        marker_color='#f87171',
        marker_line_width=0,
        hovertemplate='<b>%{x}</b><br>流出: %{customdata:.2f}亿<extra></extra>',
        customdata=[abs(o) for o in outflows],
    ))
    
    fig.add_trace(go.Scatter(
        x=names, y=nets,
        name='净流入',
        mode='lines+markers+text',
        line=dict(color='#4e7cff', width=2),
        marker=dict(size=8),
        text=[f'{n:+.1f}' for n in nets],
        textposition='top center',
        textfont=dict(size=10, color='#4e7cff'),
        hovertemplate='<b>%{x}</b><br>净流入: %{y:+.2f}亿<extra></extra>',
    ))
    
    fig.update_layout(
        **LAYOUT_CONFIG,
        height=height,
        title=dict(text=title, font=dict(size=16)),
        barmode='relative',
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.02,
            xanchor='right',
            x=1,
            font=dict(size=11),
        ),
        yaxis=dict(
            title='金额(亿)',
            gridcolor='rgba(255,255,255,0.04)',
            ticksuffix='亿',
        ),
    )
    
    fig.add_hline(y=0, line_dash='dash', line_color='rgba(255,255,255,0.15)')
    
    return _to_html(fig, height=height)


# ════════════════════════════════════════════════════════
# 7. 情绪指标组合图
# ════════════════════════════════════════════════════════
def plotly_sentiment_dashboard(data, title='情绪指标面板', height=400):
    """
    情绪指标组合图：涨跌比 + 涨停数 + 跌停数 + 连板高度
    """
    if not HAS_PLOTLY:
        return '<p>No data</p>'
    
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=('涨跌比', '涨停/跌停', '连板高度', '成交量'),
        vertical_spacing=0.15,
        horizontal_spacing=0.1,
    )
    
    # 涨跌比
    if 'up_down_ratio' in data:
        ratios = data['up_down_ratio']
        fig.add_trace(go.Bar(
            x=[f'D{i+1}' for i in range(len(ratios))],
            y=ratios,
            marker_color=['#34d399' if r > 1 else '#f87171' for r in ratios],
            name='涨跌比',
            hovertemplate='%{x}: %{y:.2f}<extra></extra>',
        ), row=1, col=1)
        fig.add_hline(y=1, line_dash='dash', line_color='rgba(255,255,255,0.2)', row=1, col=1)
    
    # 涨停/跌停
    if 'limit_up' in data and 'limit_down' in data:
        fig.add_trace(go.Bar(
            x=[f'D{i+1}' for i in range(len(data['limit_up']))],
            y=data['limit_up'],
            marker_color='#34d399',
            name='涨停',
        ), row=1, col=2)
        fig.add_trace(go.Bar(
            x=[f'D{i+1}' for i in range(len(data['limit_down']))],
            y=[-d for d in data['limit_down']],
            marker_color='#f87171',
            name='跌停',
        ), row=1, col=2)
    
    # 连板高度
    if 'max_limit_streak' in data:
        streaks = data['max_limit_streak']
        fig.add_trace(go.Scatter(
            x=[f'D{i+1}' for i in range(len(streaks))],
            y=streaks,
            mode='lines+markers',
            line=dict(color='#fbbf24', width=2),
            marker=dict(size=8),
            name='连板高度',
        ), row=2, col=1)
    
    # 成交量
    if 'volume' in data:
        vols = data['volume']
        fig.add_trace(go.Bar(
            x=[f'D{i+1}' for i in range(len(vols))],
            y=vols,
            marker_color='#4e7cff',
            marker_line_width=0,
            name='成交量',
        ), row=2, col=2)
    
    fig.update_layout(
        **LAYOUT_CONFIG,
        height=height,
        title=dict(text=title, font=dict(size=16)),
        showlegend=False,
    )
    
    return _to_html(fig, height=height)


# ════════════════════════════════════════════════════════
# 辅助函数：生成完整 HTML 页面
# ════════════════════════════════════════════════════════
def generate_interactive_report(charts_dict, title='交互式复盘报告'):
    """
    将多个图表组合成完整 HTML 页面
    
    参数：
        charts_dict: dict，key 为图表标题，value 为 HTML 片段
    """
    html_parts = [get_plotlyjs_cdn()]
    html_parts.append(f'<h1 style="color:#e8eaf0;text-align:center;padding:20px">{title}</h1>')
    
    for chart_title, chart_html in charts_dict.items():
        html_parts.append(f'''
        <div style="margin:20px;padding:15px;background:rgba(22,25,34,0.8);border-radius:12px;border:1px solid rgba(255,255,255,0.06)">
            {chart_html}
        </div>
        ''')
    
    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
        body {{ background: #0f1117; color: #e8eaf0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 20px; }}
    </style>
</head>
<body>
    {''.join(html_parts)}
</body>
</html>'''


# ════════════════════════════════════════════════════════
# 测试
# ════════════════════════════════════════════════════════
if __name__ == '__main__':
    print('Plotly Charts Module v1.0')
    print(f'Plotly available: {HAS_PLOTLY}')
    
    if HAS_PLOTLY:
        # 测试仪表盘
        gauge_html = plotly_gauge(75, title='情绪综合分', subtitle='测试')
        print(f'Gauge HTML length: {len(gauge_html)}')
        
        # 测试柱状图
        bar_html = plotly_bar([10, -5, 8, -3, 12, -8, 6], title='近7日涨跌')
        print(f'Bar HTML length: {len(bar_html)}')
        
        print('All tests passed!')
