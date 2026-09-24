# Validation: GameQuery 可靠性升级

> 本文件是可靠性升级完成时的历史快照；其中“尚未运行规模实验”的陈述已由后续 `specs/synthetic-business-scale/validation.md` 补充，不应继续作为当前容量状态。

验证基线：`5a79be4`（2026-09-24）。本文件只记录可复现证据，不把 fixture、smoke 或工具能力外推为线上效果。

## 验收结论

- 21 个普通 MUST、3 个 SHOULD 与 1 个 UNCHANGED/MUST 均已有实现和自动化证据。
- GitHub Actions `reliability-ci` #30 全绿，耗时 59 秒；其中后端在真实 MySQL 8.0 与 Qdrant 1.16 服务容器上运行。
- 本地回归为 117 passed、2 skipped；两个 skip 是显式依赖 CI 服务容器的集成用例，不是静默忽略。
- AC-23 已验证生成器、报告契约、Locust 场景与 CI smoke；尚未在目标硬件执行正式 10 万/100 万负载，因此没有容量、吞吐或延迟结论。
- 真实 LLM Agent 评测未运行，`agent_correction_accuracy` 保持 `null / not_run`。

## 自动化验证

| 门禁 | 结果 | 证据 |
|---|---|---|
| Python lint | 通过 | `uv run ruff check app tests eval main.py` |
| 后端测试 | 117 passed、2 skipped（本地） | `uv run pytest -q` |
| 服务集成 | 通过（CI） | `tests/integration/test_services.py`；MySQL reader 拒绝 INSERT/UPDATE/DELETE/CREATE/DROP；Qdrant dense 与原生 BM25 均命中 |
| SQL fixture | 20 条；Guard accuracy 1.0；首轮 fixture rate 0.75；预设修复执行率 1.0 | `eval/latest_metrics.json` |
| 检索 fixture | 32 条；融合 Hit@5/MRR 1.0；no-match false-positive 0.2 | `eval/latest_retrieval_metrics.json` |
| 工作流 E2E | 六类终态通过 | `tests/test_agent_workflow_e2e.py` |
| API 兼容 | `/health`、`/api/query`、请求 ID、SSE content type 通过 | `tests/test_api_routes.py` |
| 前端 | type-check + production build 通过 | `pnpm build` |
| CI | #30 通过 | <https://github.com/youcaifang66-ops/gamequery-agent/actions/runs/35958347356> |

SQL 与检索数字都是固定 fixture 回归指标。它们证明计算和合同可复现，不等价于真实自然语言流量中的准确率。

## Acceptance Criteria 追踪

| AC | 状态 | 主要证据 |
|---|---|---|
| AC-01~03 SQL 边界、白名单、LIMIT | 通过 | `tests/test_sql_guard.py`、`app/security/sql_guard.py` |
| AC-04 Guard→EXPLAIN→Run | 通过 | `tests/test_agent_sql_safety.py`、`tests/test_dw_repository.py` |
| AC-05~06 有界纠错与安全拒绝 | 通过 | `tests/test_agent_graph.py`、`tests/test_agent_workflow_e2e.py` |
| AC-07 最小权限 | 通过 | `tests/test_deployment_security.py`、`tests/integration/test_services.py`、CI #30 |
| AC-08 截止时间 | 通过 | `tests/test_dw_repository.py`、`tests/test_query_service.py` |
| AC-09~10 稳定错误与 SSE 终态 | 通过 | `tests/test_api_contracts.py`、`tests/test_query_service.py`、`tests/test_api_routes.py` |
| AC-11~12 审计与并发一致性 | 通过 | `tests/test_trace_store.py`、`tests/test_trace_dependencies.py` |
| AC-13 图汇合 | 通过 | `tests/test_agent_graph.py` |
| AC-14~16 检索证据、隔离、确定性 | 通过 | `tests/test_retrieval_fusion.py`、`tests/test_hybrid_qdrant_repository.py`、`tests/test_recall_evidence.py` |
| AC-17 澄清 | 通过 | `tests/test_query_clarification.py` |
| AC-18 确定性 E2E | 通过 | `tests/test_agent_workflow_e2e.py` |
| AC-19 容器集成 | 通过（CI） | `tests/integration/test_services.py`、CI #30 |
| AC-20 检索黄金集与消融 | 通过（fixture） | `tests/test_retrieval_eval_contract.py`、`eval/retrieval_benchmark.json` |
| AC-21 指标真实性 | 通过 | `tests/test_sql_benchmark_contract.py`、`eval/latest_metrics.json` |
| AC-22 CI 门禁 | 通过 | `tests/test_ci_contract.py`、`.github/workflows/ci.yml` |
| AC-23 规模工具与报告 | 部分实证 | `tests/test_scale_harness.py`；工具与 smoke 通过，正式负载未跑 |
| AC-24 资源清理 | 通过 | Repository、QueryService、TraceStore 取消/复用测试 |
| AC-25 入口兼容 | 通过 | `tests/test_api_routes.py`、前端 build |

COULD 项 AC-C1（检查点续跑）和 AC-C2（追踪保留清理）没有实现；WONT 项公网多租户鉴权、自动 Agentic RAG、千万级能力声明保持不在本轮范围内。

## 漂移与失败处理

- 研究阶段发现 SQLGuard、RRF、TraceStore 和 SSE encoder 只是孤立组件；最终均已接入在线 `QueryService → graph` 链路。
- 原三条独立入边依赖 LangGraph 调度语义；现在改为显式 barrier，并有乱序完成回归测试。
- 原 DW 账号拥有过大权限；现在拆分 meta writer 与 DW reader，并由真实 MySQL 集成测试证明写操作被拒绝。
- 原评测把预设修复冒充 Agent 纠错；现在分成 `preset_repair_execution_accuracy` 与未运行的 `agent_correction_accuracy`。
- 本机 Docker CLI 不可用，因此真实服务证据来自 GitHub CI；没有声称完成本机全栈 Compose 验收。

## 复现命令

```bash
uv sync --frozen --group dev
uv run ruff check app tests eval main.py
uv run pytest -q
uv run python -c "from eval.run_sql_eval import evaluate; print(evaluate())"
uv run python -c "from eval.run_retrieval_eval import evaluate; print(evaluate('fixture'))"
uv run python eval/generate_scale_data.py --preset smoke --output ./tmp-scale-smoke
cd frontend && pnpm install --frozen-lockfile && pnpm build
```

正式负载实验必须额外记录硬件、服务版本、索引、数据量、并发、spawn rate、持续时间和预热参数，并按 `eval/load_report.schema.json` 输出；未实际运行前不得填写性能数字。
