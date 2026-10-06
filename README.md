# 企业双积分核算与交易服务

本项目是使用 Python、FastAPI 与 SQLite 实现的服务端应用，覆盖企业、车型、年度核算、订单撮合、交易结转和统计。它可在单个 Linux 应用容器内完成安装、测试、编译和接口验收，不依赖浏览器、外部数据库、缓存、消息队列或额外运行服务。

## 安装

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
```

## 测试

```bash
python3 -m pytest -q test_dual_credit_integration.py
```

## 编译

```bash
python3 -m compileall -q .
```

## 接口验收

```bash
python3 -c "from app.main import app; assert len(app.routes) > 5; print(len(app.routes))"
```

## 启动

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 集团合并申报

系统支持汽车集团统一申报多家成员企业（路由前缀 `/api/v1/group-filings`），核心规则：

- **成员生效区间**：成员关系带 `effective_from`/`effective_to`，区间不覆盖申报年度的成员不能纳入合并。
- **成员封账**：成员先对当年已确认数据封账（`/member-filings/seal`），形成不可变快照（积分记录、年度交易、跨年度结转）；更正只产生新封账版本，旧版本标记 `superseded` 并保留。
- **合并版本与抵销**：集团选择成员及其封账版本生成合并版本（`/consolidation-versions`），系统按双方封账快照识别并生成**只属于该版本**的抵销项目：
  - 内部积分转让（双方快照中都存在、同年度）→ 冲减内部买卖额（零和，不影响净额）；
  - 内部车型转让重复申报（`/internal-model-transfers` 登记）→ 冲减生产口径正积分/净积分；
  - **外部交易、跨年度结转永不抵销**；抵销后双方原始记录全部保留。
- **新版本而非改写**：成员迟交、退出、更正均生成新合并版本，并在 `member_diff_json`/`amount_diff_json` 中给出与前版的成员范围与金额差异。版本一经 `/lock` 采用，监管结论冻结，后续更正只能另出新版本。
- **层级勾稽**：`/consolidation-versions/{id}/reconciliation` 校验成员层级与集团层级的净积分、对外买卖、结转、缺口/结余、合规状态相互勾稽（`all_balanced`）。

测试：

```bash
python3 -m pytest -q test_group_consolidation.py
```
