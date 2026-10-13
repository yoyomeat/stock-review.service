#!/usr/bin/env python3
"""共享数据加载 — 板块层级 + 概念映射（被 review/cycle/position/plan 多模块引用）"""
import os
import json

# 模块级缓存
_CONCEPT_MAP = None
_SECTOR_HIERARCHY = None


def _load_sector_hierarchy():
    """加载板块层级数据。优先从 concept_match.csv + industry_skel.csv (v2)，回退旧 JSON。

    返回结构:
      concept_to_category: {概念名: (lv1, lv2, lv3)}  — 3级元组
      concept_to_theme: {概念名 → 主题key}  — 概念直接映射到主题
      name_to_parent: {板块名 → 一级行业}  (含三级行业+概念)
    """
    global _SECTOR_HIERARCHY
    if _SECTOR_HIERARCHY is not None:
        return _SECTOR_HIERARCHY
    _quant_dir = os.path.dirname(os.path.abspath(__file__))
    _data_dir = os.path.join(_quant_dir, '..', 'data')
    _data_dir = os.path.normpath(_data_dir)
    concept_match = os.path.join(_data_dir, 'concept_match.csv')
    industry_skel = os.path.join(_data_dir, 'industry_skel.csv')
    if os.path.isfile(concept_match) and os.path.isfile(industry_skel):
        import csv
        # 1) industry_skel: 一级行业,二级行业,三级行业  — 496个三级行业
        cat3_to_parent = {}  # lv3 → (lv1, lv2)
        with open(industry_skel, encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                keys = list(row.keys())
                lv1 = row[keys[0]].strip()
                lv2 = row[keys[1]].strip()
                lv3 = row[keys[2]].strip()
                cat3_to_parent[lv3] = (lv1, lv2)
        # 2) concept_match: 概念名称,一级行业,二级行业,三级行业,匹配方式  — 452个概念
        c2c = {}
        c2t = {}  # concept_name → theme_key
        n2p = {}  # any_name → lv1
        with open(concept_match, encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                keys = list(row.keys())
                concept = row[keys[0]].strip()
                lv1 = row[keys[1]].strip()
                lv2 = row[keys[2]].strip()
                lv3 = row[keys[3]].strip()
                if not concept:
                    continue
                c2c[concept] = (lv1, lv2, lv3)
                n2p[concept] = lv1
                # 读取主题列（第6列，可能不存在）
                theme = ''
                if len(keys) > 5:
                    theme = row[keys[5]].strip()
                if theme:
                    c2t[concept] = theme
        # 补充三级行业→一级映射
        for lv3, (lv1, _lv2) in cat3_to_parent.items():
            n2p[lv3] = lv1
            n2p[_lv2] = lv1
        _SECTOR_HIERARCHY = {
            'concept_to_category': c2c,
            'concept_to_theme': c2t,
            'name_to_parent': n2p,
        }
        return _SECTOR_HIERARCHY
    # 回退旧 JSON
    json_path = os.path.join(_data_dir, 'sector_hierarchy_v2.json')
    if os.path.isfile(json_path):
        with open(json_path, encoding='utf-8') as f:
            raw = json.load(f)
        _SECTOR_HIERARCHY = raw
        return raw
    _SECTOR_HIERARCHY = {'concept_to_category': {}, 'name_to_parent': {}}
    return _SECTOR_HIERARCHY


def _load_concept_map():
    """加载同花顺 个股→板块 映射（从JSON缓存）"""
    global _CONCEPT_MAP
    if _CONCEPT_MAP is not None:
        return _CONCEPT_MAP
    _quant_dir = os.path.dirname(os.path.abspath(__file__))
    _data_dir = os.path.join(_quant_dir, '..', 'data')
    _data_dir = os.path.normpath(_data_dir)
    concept_json = os.path.join(_data_dir, 'stock_concept_map.json')
    if os.path.isfile(concept_json):
        with open(concept_json, encoding='utf-8') as f:
            _CONCEPT_MAP = json.load(f)
        return _CONCEPT_MAP
    _CONCEPT_MAP = {}
    return _CONCEPT_MAP
