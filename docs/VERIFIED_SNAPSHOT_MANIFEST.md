# 创建可验证的 OKX 快照 manifest

`scripts/run_research.py` 不接受裸 CSV。验证/留出研究需要 schema-v1 manifest，把真实市场 CSV 绑定到精确 SHA-256、字段顺序、时间边界和来源声明。

仓库生成的 OKX snapshot 已包含规范化 CSV 与配套 metadata。使用下面的跨平台 helper 创建 manifest，避免手写长 `python -c` 命令或复制错误的字段。

## 输入文件

先运行一次真实 OKX 研究：

```bash
python scripts/run_okx_research.py \
  --inst-id BTC-USDT \
  --output-dir reports/okx/BTC-USDT \
  --manifest-path reports/okx/experiment-manifest.jsonl
```

该命令应生成同一目录中的：

```text
reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.csv
reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.metadata.json
```

helper 要求 metadata、CSV 和输出 manifest 位于同一目录，防止 manifest 通过父目录跳转引用其他文件。

## macOS / Linux

```bash
python scripts/create_verified_snapshot_manifest.py \
  --metadata reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.metadata.json \
  --csv reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.csv \
  --output reports/okx/BTC-USDT/snapshot/verified-snapshot.json
```

## Windows PowerShell

```powershell
python scripts/create_verified_snapshot_manifest.py `
  --metadata reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.metadata.json `
  --csv reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.csv `
  --output reports/okx/BTC-USDT/snapshot/verified-snapshot.json
```

成功时，命令打印 manifest 路径、CSV SHA-256、观测数和首尾时间戳。

## 创建前执行的校验

helper 会在写文件前验证：

- metadata 和 CSV 都是可读取的普通文件；
- metadata、CSV 和输出 manifest 位于同一目录；
- metadata 是 JSON object，并包含 provider、instrument、bar、观测数、首尾时间戳和 normalized CSV SHA-256；
- CSV 的实际 SHA-256 与 metadata 中的 `normalized_csv_sha256` 完全一致；
- CSV header 非空、无重复，并包含 `timestamp` 与 `close`；
- 每行字段数与 header 一致；
- metadata 观测数及首尾时间戳与 CSV 一致；
- provenance 至少包含经过 ISO-8601 与显式时区校验的 `fetched_at_utc`，或者 metadata 中存在 `source_workflow_run_id` 声明；
- `raw_pages_sha256`（存在时）是格式有效的 SHA-256。

`source_workflow_run_id` 只检查字段是否存在；其类型与取值不会在 helper 中验证。`source_artifact_id`、`source_artifact_name`、`source_artifact_sha256` 和 `source_head_sha` 也会按 metadata 声明复制到 manifest。helper 当前不会校验这些字段的类型、取值或格式，也不会证明它们与 workflow、artifact、commit 或本地 CSV 互相对应。

这些限制只描述 manifest **创建阶段**。`run_research.py` 随后调用 `load_verified_price_snapshot()` 重新验证 manifest：`source_workflow_run_id` 和 `source_artifact_id`（存在时）必须是非布尔正整数，`source_artifact_sha256`（存在时）必须是格式有效的 SHA-256。`source_artifact_name` 与 `source_head_sha` 仍然只是未联网核验的声明。因而，helper 成功写出的 manifest 仍可能在研究入口读取时因 provenance 类型或 digest 格式错误而 fail closed；该失败发生在配置加载、回测和报告写入之前。

任何创建阶段校验失败都会返回非零状态，并且不会创建目标 manifest。

## 运行验证/留出研究

创建 manifest 后执行：

```bash
python scripts/run_research.py \
  --snapshot-manifest reports/okx/BTC-USDT/snapshot/verified-snapshot.json \
  --config config/okx_holdout.json \
  --output-dir reports/holdout/BTC-USDT
```

`config/okx_holdout.json` 与 rolling OKX baseline 使用相同的策略参数、365 日年化、每单位换手 10 bps 成本和候选参数族，但使用固定 validation/holdout 比例。它不是 rolling 730/90 fold 报告的直接复算。

## 证据边界

helper 只证明本地 CSV 字节与本地 metadata 声明一致。loader 额外核对部分 provenance 字段的类型和 digest 格式，但两者都不会联网证明 provider、workflow、artifact 或 commit 标识真实且互相对应，也不会根据 `timeframe` 自动推导 cadence。可审计复现仍须保留原始 OKX 分页响应、snapshot metadata、下载请求、workflow run、artifact ID、exact head 和下载包哈希。
