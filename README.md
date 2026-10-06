# 企业双积分核算与交易服务

本项目是使用 Python、FastAPI 与 SQLite 实现的服务端应用，覆盖企业、车型、年度核算、订单撮合、交易结转和统计。它可在单个 Linux 应用容器内完成安装、测试、编译和接口验收，不依赖浏览器、外部数据库、缓存、消息队列或额外运行服务。

## 集团统一申报

在逐企业核算之外，系统支持汽车集团统一申报（`/api/v1/groups`）：

- **成员生效区间**：集团成员按年度区间生效（`effective_from_year`/`effective_to_year`），同一企业同一年度只能属于一个集团，区间重叠会被拒绝；成员退出通过截断生效区间实现，历史数据保留。
- **成员封账版本**：成员先各自提交封账申报（提交即封账），系统快照其当年核算、交易与结转数据；更正申报产生新版本，旧版本置为 `superseded`，内容不改写。
- **集团合并版本**：集团选择合并范围（默认全部当年生效成员，可指定成员或钉住特定封账版本）生成合并版本，内部交易抵销项目只挂在生成它的版本上；仅抵销范围内成员之间的当年内部交易，外部交易与跨年度结转一律不抵销，双方原始交易记录完整保留。
- **版本差异说明**：成员迟交、退出集团或更正申报时生成新合并版本，`change_summary` 记录与前一版本的成员增减、成员申报版本变更和各项金额差异；已采用（`adopted`）的监管结论不可改写，更正只能产生新版本。
- **层级勾稽**：`/reconciliation` 接口核对集团层级与成员层级的余额、缺口与合规状态（集团净积分=成员合计、抵销借贷平衡、外部交易与结转未抵销、原始记录保留等）。

## 安装

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
```

## 测试

```bash
python3 -m pytest -q test_dual_credit_integration.py test_group_declaration.py
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
