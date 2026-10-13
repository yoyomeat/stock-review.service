"""
config 包 — 策略规则配置 + 重新导出根目录 config.py 全部内容

根目录 config.py = 全局配置（路径/阈值/环境变量）
本包 config/ = 策略规则（路由/过滤/止盈止损规则）

Python import config 时优先找到本包，所以这里重新导出 config.py 所有公共属性。
"""
import importlib.util
from pathlib import Path

# 动态加载根目录 config.py
_root_dir = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("_root_config", str(_root_dir / "config.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# 重新导出所有非下划线开头的属性
for _name in dir(_mod):
    if not _name.startswith('_'):
        globals()[_name] = getattr(_mod, _name)

del _root_dir, _spec, _mod, _name
