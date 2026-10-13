"""在 style.css 末尾追加 wave 模块样式"""
fp = "/opt/stock-review/static/css/style.css"
with open(fp, encoding="utf-8") as f:
    css = f.read()

wave_css = """

/* ============================================================
   Wave Analysis DB — 板块数据模块
   ============================================================ */

.wave-db-info {
  font-size: 13px; color: var(--gray-500); margin-bottom: 12px;
}

.wave-overview-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px; margin-bottom: 20px;
}

.wave-stat-card {
  background: var(--bg-card, #fff); border: 1px solid var(--border, #e5e7eb);
  border-radius: var(--radius-sm, 8px); padding: 14px 16px; cursor: pointer;
  transition: all 0.2s;
}
.wave-stat-card:hover { border-color: var(--primary, #4f46e5); box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.wave-stat-card.has-data { border-left: 3px solid var(--primary, #4f46e5); }
.wave-stat-card.empty { opacity: 0.5; }
.wave-stat-label { font-size: 12px; color: var(--gray-500); margin-bottom: 4px; }
.wave-stat-value { font-size: 20px; font-weight: 700; color: var(--gray-900, #111); }
.wave-stat-detail { font-size: 11px; color: var(--gray-400); margin-top: 2px; }

.wave-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 16px; gap: 12px; flex-wrap: wrap;
}

.wave-table-tabs {
  display: flex; gap: 4px; flex-wrap: wrap;
}

.wave-table-tab {
  padding: 6px 14px; border: 1px solid var(--border, #e5e7eb);
  border-radius: 6px; background: var(--bg-card, #fff); cursor: pointer;
  font-size: 13px; color: var(--gray-600); transition: all 0.15s;
}
.wave-table-tab:hover { border-color: var(--primary, #4f46e5); color: var(--primary); }
.wave-table-tab.active {
  background: var(--primary, #4f46e5); color: #fff; border-color: var(--primary);
}

.wave-filter select {
  padding: 6px 10px; border: 1px solid var(--border, #e5e7eb);
  border-radius: 6px; font-size: 13px; min-width: 150px;
}

.wave-table-wrap { overflow-x: auto; margin-bottom: 12px; }

.wave-table {
  width: 100%; border-collapse: collapse; font-size: 13px;
}
.wave-table th {
  position: sticky; top: 0; background: var(--gray-50, #f9fafb);
  padding: 8px 10px; text-align: left; font-weight: 600;
  border-bottom: 2px solid var(--border, #e5e7eb); cursor: pointer;
  white-space: nowrap; color: var(--gray-700);
}
.wave-table th:hover { background: var(--gray-100, #f3f4f6); }
.wave-table th.sorted { color: var(--primary, #4f46e5); }
.wave-table td {
  padding: 6px 10px; border-bottom: 1px solid var(--border, #e5e7eb);
  white-space: nowrap; color: var(--gray-800);
}
.wave-table tr:hover td { background: var(--gray-50, #f9fafb); }
.wave-table .null { color: var(--gray-300); font-style: italic; }

.wave-pagination {
  display: flex; align-items: center; gap: 8px; padding: 12px 0;
}
.wave-pagination button {
  padding: 5px 12px; border: 1px solid var(--border, #e5e7eb);
  border-radius: 6px; background: var(--bg-card, #fff); cursor: pointer;
  font-size: 13px; color: var(--gray-600);
}
.wave-pagination button:hover:not(:disabled) { border-color: var(--primary); color: var(--primary); }
.wave-pagination button:disabled { opacity: 0.4; cursor: default; }
.wave-pagination .page-info { font-size: 13px; color: var(--gray-500); }
.wave-pagination select {
  padding: 5px 8px; border: 1px solid var(--border, #e5e7eb);
  border-radius: 6px; font-size: 13px;
}

.wave-sql-section {
  margin-top: 24px; padding: 20px; background: var(--bg-card, #fff);
  border: 1px solid var(--border, #e5e7eb); border-radius: var(--radius-sm, 8px);
}
.wave-sql-title { font-size: 15px; font-weight: 600; margin-bottom: 12px; color: var(--gray-800); }
.wave-sql-row { display: flex; gap: 8px; margin-bottom: 12px; }
.wave-sql-row input {
  flex: 1; padding: 8px 12px; border: 1px solid var(--border, #e5e7eb);
  border-radius: 6px; font-size: 13px; font-family: 'SF Mono', 'Fira Code', monospace;
}
.wave-sql-row button {
  padding: 8px 20px; background: var(--primary, #4f46e5); color: #fff;
  border: none; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600;
}
.wave-sql-row button:hover { opacity: 0.9; }
.wave-query-info { font-size: 13px; color: var(--gray-500); margin-bottom: 8px; }
"""

if ".wave-overview-grid" not in css:
    css += wave_css
    with open(fp, "w", encoding="utf-8") as f:
        f.write(css)
    print("style.css updated")
else:
    print("style.css already has wave styles")
