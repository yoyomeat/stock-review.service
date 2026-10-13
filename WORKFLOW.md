# WORKFLOW.md — Git 工作流规程

> 适用：本地 `/opt/stock-review` ↔ GitHub `yoyomeat/stock-review.service`（private）
> 生效：2026-10-13　|　配套：`AGENTS.md`（AI 协作约定）、`COMMIT_INSTRUCTIONS.md`（2026-06 一次性示例，已过时，仅存档参考）

---

## 1. 权威源

**服务器工作区 `/opt/stock-review` 是唯一权威源（single source of truth）。**

- 提交前后的判断一律以磁盘上的当前文件为准，不以任何历史提交为准。
- 禁止从 GitHub 反向"恢复"文件覆盖服务器工作区；如确需取回，必须人工确认后再落地（见 §7）。
- 本地与远程分歧时，先 `git fetch`，再人工比对，**不盲目 `git pull` 覆盖**。

---

## 2. 仓库内容边界

### 2.1 必须入库

| 类别 | 路径 |
| --- | --- |
| 业务代码 | `*.py`、`routes/`、`quant/`、`scripts/`、`config/` |
| 前端资源 | `templates/`、`static/` |
| 测试 | `tests/` |
| 文档 | `README.md`、`AGENTS.md`、`ARCHITECTURE.md`、`CHANGELOG.md`、`KNOWN_BUGS.md`、`WORKFLOW.md`、`docs/` |
| 依赖清单 | `requirements.txt` |
| 输入数据 | `data/` 下**非数据库**的 csv / json / json.gz（行情、板块、映射表等静态输入） |

### 2.2 严禁入库

| 类别 | 规则 | 说明 |
| --- | --- | --- |
| **数据库** | `*.db`、`*.db-wal`、`*.db-shm` | 共 7 个库，最大 1.07 GB，远超 GitHub 100 MB 硬限制 |
| 第三方依赖 | `.pylibs/` | 可由 `requirements.txt` 重建 |
| 密钥环境 | `.env`、`.api_key`、`.mimo_key`、`*.pem`、`id_*`、`*token*` | 见 §5 |
| 运行产物 | `reports/`、`logs/`、`__pycache__/`、`*.pyc`、`*.log` | |
| 备份回收 | `backups/`、`.trash_*/`、`*.bak*` | |
| 临时文件 | `static/tmp_deploy_/`、`_tmp_*.py`、`_*.py`、`*.txt`（白名单 `requirements.txt`） | |

> 已在 `.gitignore` 落地。改动边界时**先改 `.gitignore` 再提交**，不要靠"记得不 add"。

### 2.3 单文件体积红线

- **100 MB 是 GitHub 硬限制**，超过直接 push 失败，且写进历史后极难清除。
- 新增任何 > 10 MB 的文件前，先在本文件 §6 清单里跑一遍自检。

---

## 3. 数据库规程

数据库**完全不进 git**，因此它的更新不体现在提交历史里：

1. `git status` 里出现 `*.db` 属于**正常**，不要 `git add -f`。
2. 确认被忽略：`git check-ignore -v data/xxx.db`。
3. 数据库备份走 `backups/`（已忽略）或异地，与代码发布解耦。
4. 若某天数据库确需版本化，**先开会讨论**：走 Git LFS 或独立数据仓库，不要直接 `git add`。

---

## 4. 提交规程

### 4.1 粒度

一个逻辑改动 / 一个工作会话 = 一个提交。不攒大提交，也不把一次改动拆成十几个碎提交。

### 4.2 格式

沿用仓库既有风格：

```
<type>(<scope>): <中文描述> — <关键结论/影响>
```

- `type`：`feat` `fix` `docs` `chore` `refactor` `test` `perf` `data`
- `scope`：模块名，如 `web` `m1` `m2` `m3` `audit` `data`
- 关联 issue 用 `#N`，例：`feat(m3): #58/59/60 出场结构化三连 — 低吸加仓全胜`
- 正文写"为什么"和"结论"，不写流水账。

### 4.3 提交步骤

```bash
cd /opt/stock-review
git status                      # 1. 看清改了什么
git add <明确的路径>             # 2. 指定路径，不用 -A 盲加
git diff --cached --stat        # 3. 复核暂存内容
python -m pytest tests/ -q      # 4. 跑测试（见 AGENTS.md）
git commit -m "fix(scope): ..."
```

### 4.4 禁止事项

- 禁止提交 `.env` / `.api_key` / 任何 token 明文。
- 禁止 `git add -f` 强制加入被忽略的数据库或密钥。
- 禁止 `git commit --no-verify` 绕过检查。
- 禁止把 `__pycache__`、`.pylibs/`、`.trash_*/` 加回索引。

---

## 5. 认证与密钥

- **remote 使用 SSH**，格式 `git@github.com:yoyomeat/stock-review.service.git`。
- **禁止在 remote URL 里嵌 PAT/token**（2026-10-13 前曾明文存过一个 GitHub PAT，已失效并清除）。
- SSH 私钥位于服务器 `~/.ssh/id_ed25519`，**永不入库、永不外传**；公钥注册在 GitHub 仓库的 Deploy keys。
- 环境里的 `GH_TOKEN` 属临时集成令牌，可读可推但**不可作为长期方案**，不得写进任何文件。

---

## 6. 推送前自检清单

逐条执行，全绿再 push：

```bash
cd /opt/stock-review

# ① 无大文件（>100MB 必失败，>10MB 需人工确认）
git diff --cached --name-only -z | xargs -0 -r stat -c '%s %n' | sort -rn | head
git ls-files -z | xargs -0 -r stat -c '%s %n' | sort -rn | head

# ② 无数据库混入
git ls-files | grep -E '\.db(-wal|-shm)?$' && echo "!! 有数据库被跟踪" || echo "OK 无数据库"

# ③ 无密钥泄露
git diff --cached | grep -nEi 'ghp_[A-Za-z0-9]{20,}|github_pat_|sk-[A-Za-z0-9]{20,}|BEGIN [A-Z ]*PRIVATE KEY' && echo "!! 疑似密钥" || echo "OK 无密钥"

# ④ 测试通过
python -m pytest tests/ -q

# ⑤ 同步
git fetch origin && git status
```

推送：

```bash
git push origin master          # 常规
git push --force-with-lease origin master   # 仅在历史重建时（见 §7）
```

---

## 7. 异常处理

### 7.1 本地与远程分歧

```bash
git fetch origin
git log --oneline --left-right HEAD...origin/master   # 左=本地独有 右=远程独有
git diff --stat HEAD origin/master                    # 看内容差异
```

- 远程独有的文件，先确认是否是本地已搬迁/已压缩（如 `data/kph_sectors/*.json` → `*.json.gz`、根目录 `PROGRESS_*.md` → `docs/progress/`），**确认无独有内容后**再合并或重建。
- 不确定就先问，不做破坏性操作。

### 7.2 历史重建（force push）

**仅在"以服务器当前版本为准、整体重录"时使用**，且必须满足：

1. 先打存档分支留住旧历史：`git branch archive/<原因>-<日期>`
2. `git fetch origin && git branch archive/remote-<日期> origin/master`
3. 按 §6 全绿
4. 用 `git push --force-with-lease`
5. 在 commit message 里写明重建原因与日期

### 7.3 误提交了不该提交的文件

```bash
git rm --cached <文件>          # 只从索引移除，不动磁盘
# 若是大文件已进历史：
git filter-repo --path <文件> --invert-paths   # 需安装 git-filter-repo，之后必须 force push
```

---

## 8. 本次基线说明

- 2026-10-13：按"以服务器当前版本为准"重建历史，旧的分叉历史（本地 45 / 远程 39 提交）保留在本地存档分支 `archive/*`，不再推送。
- 7 个数据库（1.9 GB）与历史遗留的 587 MB blob 一并移出版本库。
- 从旧远程抢救回 10 篇 `docs/progress/PROGRESS_*.md` 与 `tests/test_quant_profile.py`。
