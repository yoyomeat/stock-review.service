#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比成功/失败信号板块的量化特征，找过滤规则"""
import sqlite3, pandas as pd
import numpy as np

DB = "/opt/stock-review/data/wave_analysis.db"
conn = sqlite3.connect(DB)
# 之前去重后的信号列表
signals = [
    ("20250604","冰雪产业",1),("20250618","智能穿戴",1),("20250618","智能音箱",1),
    ("20250618","无线耳机",1),("20250618","MiniLED",1),("20250618","MicroLED概念",1),
    ("20250618","AI手机",1),("20250618","AI眼镜",1),("20250619","钙钛矿电池",1),
    ("20250624","HJT电池",1),("20250625","中船系",1),("20250625","物业管理",1),
    ("20250625","电子纸",1),("20250626","成飞概念",1),("20250627","同花顺出海50",1),
    ("20250704","预制菜",0),("20250707","租售同权",0),("20250708","注册制次新股",0),
    ("20250725","短剧游戏",1),("20250806","人脸识别",0),("20250811","天津自贸区",0),
    ("20250813","拼多多概念",0),("20250813","快手概念",0),("20250814","足球概念",0),
    ("20250814","特色小镇",1),("20250901","免税店",0),("20250912","海南自贸区",1),
    ("20251024","成飞概念",1),("20251027","中船系",1),("20251027","注册制次新股",0),
    ("20251110","预制菜",0),("20251117","快手概念",1),("20251118","抖音概念(字节概念)",1),
    ("20251125","租售同权",0),("20251125","人脸识别",1),("20251201","电子纸",0),
    ("20251210","冰雪产业",0),("20260106","足球概念",0),("20260225","天津自贸区",0),
    ("20260225","特色小镇",0),("20260302","注册制次新股",0),("20260303","AI眼镜",1),
    ("20260317","摘帽",0)
]

# 读板块历史数据，计算每个板块在触发信号前的特征
concept_data = pd.read_sql("""
    SELECT c.code, n.name, c.trade_date, c.volume, c.close
    FROM concept_daily c
    JOIN concept_names n ON c.code = n.code
""", conn)
conn.close()

success_feats = []
fail_feats = []
for date, sec_name, is_hit in signals:
    g = concept_data[concept_data['name']==sec_name].sort_values('trade_date')
    g = g[g['trade_date']<=date].tail(60)
    if len(g)<30: continue
    # 特征1：近60天平均日成交额（这里用volume代替）
    avg_vol = g['volume'].mean()
    # 特征2：近60天平均日波动率（振幅）
    avg_amp = (g['close'].pct_change().abs().mean()*100)
    # 特征3：近60天成交量标准差（活跃度）
    vol_std = g['volume'].std()/g['volume'].mean()
    # 特征4：近60天累计涨幅
    ret_60d = g['close'].iloc[-1]/g['close'].iloc[0] - 1
    
    feat = {
        "name":sec_name, "avg_vol":round(avg_vol,0),
        "avg_daily_amp_pct":round(avg_amp,2),
        "vol_cv":round(vol_std,2),
        "ret_60d_pct":round(ret_60d*100,1)
    }
    if is_hit:
        success_feats.append(feat)
    else:
        fail_feats.append(feat)

print("===== 成功信号板块平均特征 =====")
succ_df = pd.DataFrame(success_feats)
print(succ_df.describe().loc[['mean','min','max']])
print("\n===== 失败信号板块平均特征 =====")
fail_df = pd.DataFrame(fail_feats)
print(fail_df.describe().loc[['mean','min','max']])

print("\n===== 对比差异 =====")
print(f"成功板块平均日成交量: {succ_df['avg_vol'].mean():.0f}")
print(f"失败板块平均日成交量: {fail_df['avg_vol'].mean():.0f}")
print(f"成功板块平均日振幅: {succ_df['avg_daily_amp_pct'].mean():.2f}%")
print(f"失败板块平均日振幅: {fail_df['avg_daily_amp_pct'].mean():.2f}%")
print(f"成功板块60日前累计涨幅: {succ_df['ret_60d_pct'].mean():.1f}%")
print(f"失败板块60日前累计涨幅: {fail_df['ret_60d_pct'].mean():.1f}%")
