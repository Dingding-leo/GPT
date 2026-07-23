# 可执行复现指南

本指南描述如何从干净检出复现 `GPT Quant Lab` 当前真实数据研究流程。所有研究、回测、示例和可执行验证都必须使用真实交易所数据；不得使用生成、模拟或伪造的行情作为绩效证据。

## 1. 环境准备

要求 Python 3.11 或更高版本。

为复现当前 CI 的依赖解析环境，macOS/Linux 与 Windows PowerShell 都固定安装 workflow 声明的 `pip==26.1.2`。不要改回不固定版本的 pip bootstrap；否则新的 pip 发布可能在没有仓库 commit 的情况下改变依赖解析或 editable install 行为。

### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install "pip==26.1.2"
python -m pip install -e ".[dev]"
```

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install "pip==26.1.2"
python -m pip install -e ".[dev]"
```

记录用于复现的代码版本：

```bash
git rev-parse HEAD
python --version
python -m pip freeze
```

## 2. 软件质量门禁

```bash
ruff check .
ruff format --check .
pytest
```

当前 `main` 的 pytest 默认不访问交易所网络。共享的价格回归测试读取仓库内不可变的真实 OKX `BTC-USDT` `1Dutc` fixture：

```text
tests/fixtures/okx/btc-usdt-1dutc-20180111-20200628/
```

fixture 保存真实收盘价、真实 UTC 时间戳和来源元数据。加载器会在测试收到价格前核对 SHA-256、provider、instrument、timeframe、完整 K 线标记、观测数、首尾时间戳、唯一性、递增顺序及精确日线 cadence；任一项不一致都会 fail closed。

可单独运行这一离线完整性门禁：

```bash
pytest tests/test_real_data_fixture.py
```

因此，安装依赖后，干净检出可以在没有 OKX 网络连接、API key 或 `OKX_BASE_URL` 的情况下执行 pytest。网络只在后续 `run_okx_research.py` 下载新快照时需要；`OKX_BASE_URL` 影响下载入口，不影响仓库内 fixture。

测试成功只能证明软件门禁通过；它本身不证明策略存在可交易优势。

## 3. 运行 OKX 滚动样本外研究

### 单一品种

```bash
python scripts/run_okx_research.py \
  --inst-id BTC-USDT \
  --output-dir reports/okx/BTC-USDT \
  --manifest-path reports/okx/experiment-manifest.jsonl
```

### BTC 与 ETH

```bash
for instrument in BTC-USDT ETH-USDT; do
  python scripts/run_okx_research.py \
    --inst-id "$instrument" \
    --output-dir "reports/okx/$instrument" \
    --manifest-path reports/okx/experiment-manifest.jsonl
done
```

PowerShell 等价命令：

```powershell
foreach ($instrument in @("BTC-USDT", "ETH-USDT")) {
  python scripts/run_okx_research.py `
    --inst-id $instrument `
    --output-dir "reports/okx/$instrument" `
    --manifest-path reports/okx/experiment-manifest.jsonl
}
```

常用覆盖参数：

```bash
python scripts/run_okx_research.py \
  --config config/okx_research.json \
  --inst-id ETH-USDT \
  --bar 1Dutc \
  --start 2018-01-01 \
  --end 2026-07-20 \
  --max-pages 40 \
  --base-url https://www.okx.com \
  --output-dir reports/okx/ETH-USDT \
  --manifest-path reports/okx/experiment-manifest.jsonl
```

API 域名优先级为：

1. `--base-url`；
2. `OKX_BASE_URL`；
3. 配置文件中的 `data.base_url`；
4. `https://www.okx.com`。

如果指定了 `--start`，下载器只会在 `max_pages` 用尽且最早返回 bar 仍晚于请求起点时直接失败。如果 OKX 在到达起点前返回短页（或已有数据后的空页），下载器会保留可用历史，并在 metadata 中记录 `pagination_termination`；此时 `requested_start_reached` 可能为 `false`，例如品种上市晚于请求日期。审计者必须检查这两个字段，不能仅凭命令包含 `--start` 就认定样本覆盖到了该日期。

### Walk-forward 记账边界

要逐字节复算当前结果，必须保留以下窗口边界语义：

- 每个候选参数在每个 selection 窗口都视为从现金独立开始；第一行换手按 `abs(position - 0.0)` 计算，并立即计入建仓成本；
- selection 窗口之前的价格只用于特征预热和一根 bar 的执行延迟，不计入该窗口的收益或评分；
- 非重叠 OOS test folds 不是每折重新从现金开始，而是以上一折最后一个实际 OOS 仓位作为下一折首行的 `previous_position`，据此重新计算换手、成本、收益和 NAV；
- 参数扰动路径使用各自独立的前一 OOS 仓位，不能与主策略或其他扰动路径混用。

因此，selection 指标与连续 OOS 指标具有不同但明确的初始仓位边界。省略 selection 的首笔建仓成本，或在 OOS fold 之间重置为现金，都会改变候选排名或聚合结果。

## 4. 预期输出

以 `BTC-USDT` 为例：

```text
reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.csv
reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.raw.json
reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.metadata.json
reports/okx/BTC-USDT/walk_forward.json
reports/okx/BTC-USDT/walk_forward.md
reports/okx/BTC-USDT/walk_forward_returns.csv
reports/okx/experiment-manifest.jsonl
```

命令标准输出还会给出：

- API 域名、品种和周期；
- 观测数及规范化 CSV SHA-256；
- fold 数、聚合 Sharpe、最大回撤和稳健性分类；
- experiment ID、run ID、manifest 路径及 manifest SHA-256；
- 各报告与快照路径。

## 5. 验证快照来源与哈希

先检查 metadata：

```bash
python -c "import json,pathlib; p=pathlib.Path('reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.metadata.json'); print(json.dumps(json.loads(p.read_text()), indent=2, sort_keys=True))"
```

跨平台重新计算文件哈希：

```bash
python -c "import hashlib,pathlib; files=['reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.csv','reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.raw.json','reports/okx/experiment-manifest.jsonl']; [print(hashlib.sha256(pathlib.Path(f).read_bytes()).hexdigest(), f) for f in files]"
```

核对以下证据：

- provider、instrument、bar 和请求日期；
- 只包含 `confirm=1` 的完整 K 线；
- 首尾时间戳、行数、分页终止原因和完整性字段；
- CSV 与原始响应的 SHA-256；
- experiment manifest 中的代码 commit、有效配置、数据哈希、候选数量、结果分类及 artifact 哈希。

任何快照字节、配置或代码版本变化，都应产生不同的哈希或 experiment ID。

## 6. 使用 manifest 验证已有真实 CSV

`run_research.py` 不再接受裸 `--csv`。它要求一个 schema-v1 JSON manifest，在任何配置加载、候选选择、holdout 计算或报告写入前绑定并验证外部 CSV。

### 从本仓库生成的 OKX 快照创建 manifest

先运行第 3 节的 BTC 命令，然后使用仓库内经过测试的 helper。helper 会在写入前核对 metadata、CSV SHA-256、header、每行字段数、观测数、首尾时间戳和 provenance。

macOS / Linux：

```bash
python scripts/create_verified_snapshot_manifest.py \
  --metadata reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.metadata.json \
  --csv reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.csv \
  --output reports/okx/BTC-USDT/snapshot/verified-snapshot.json
```

Windows PowerShell：

```powershell
python scripts/create_verified_snapshot_manifest.py `
  --metadata reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.metadata.json `
  --csv reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.csv `
  --output reports/okx/BTC-USDT/snapshot/verified-snapshot.json
```

成功时，helper 会打印 manifest 路径、CSV SHA-256、观测数和首尾时间戳。完整校验规则见 [`VERIFIED_SNAPSHOT_MANIFEST.md`](VERIFIED_SNAPSHOT_MANIFEST.md)。

BTC-USDT `1Dutc` 的验证/留出示例使用 `config/okx_holdout.json`。该配置与 rolling 基线共享完整 strategy、365 日年化、每单位换手 10 bps 成本和候选参数族。运行前可执行以下跨平台断言，防止文档命令与 rolling OKX 市场假设发生静默漂移：

```bash
python -c "import json,pathlib; o=json.loads(pathlib.Path('config/okx_research.json').read_text()); h=json.loads(pathlib.Path('config/okx_holdout.json').read_text()); keys=('momentum_lookbacks','reversal_lookbacks','trend_weights'); assert h['strategy']==o['strategy']; assert all(h['search'][k]==o['search'][k] for k in keys); assert h['strategy']['annualization']==365; assert h['strategy']['transaction_cost_bps']==10.0; print('okx_holdout_config=verified')"
```

`run_research.py` 使用固定 `validation_fraction=0.20` 和 `holdout_fraction=0.20`，而 rolling OOS 使用 730 根 selection bars 与 90 根 test bars。两者共享市场、成本和候选族假设，但切分协议不同；不得把 holdout 指标当作 rolling 报告的直接复算结果。运行验证/留出研究：

```bash
python scripts/run_research.py \
  --snapshot-manifest reports/okx/BTC-USDT/snapshot/verified-snapshot.json \
  --config config/okx_holdout.json \
  --output-dir reports/holdout/BTC-USDT
```

PowerShell 的研究命令等价写法为：

```powershell
python scripts/run_research.py `
  --snapshot-manifest reports/okx/BTC-USDT/snapshot/verified-snapshot.json `
  --config config/okx_holdout.json `
  --output-dir reports/holdout/BTC-USDT
```

manifest 必须包含：

- `schema_version: 1`；
- 非空的 `provider`、`market_type`、`instrument_id` 和 `timeframe`；
- `schema.columns` 的精确 CSV header 顺序，以及不同的 `timestamp_column` 与 `close_column`；
- 正整数 `observations`；
- 带显式时区的 `start` 与 `end`；
- 相对于 manifest 目录、且不能包含父目录跳转的 `data_path`；
- 精确 CSV 字节的 `data_sha256`；
- 非空 `provenance`，至少包含 UTC `retrieved_at_utc` 或正整数 `source_workflow_run_id`。

加载器会 fail closed 地核对：文件必须留在 manifest 目录内；SHA-256 必须匹配；header、字段顺序和每行字段数必须精确一致；行数必须匹配；时间戳必须有效、显式带时区、唯一且严格递增；首尾时间戳必须匹配；close 必须可解析、有限且严格为正。

旧的 `--csv`、`--timestamp-col` 和 `--close-col` 参数保留为隐藏迁移错误入口，使用它们会立即失败并要求改用 `--snapshot-manifest`。

### 证据边界

manifest 会绑定调用者声明和本地文件字节，但不会联网查询 OKX 或 GitHub 来证明 provider、workflow、artifact、commit 或其他 provenance 标识真实且互相对应。`timeframe` 也只是声明字段；通用 loader 不会根据它推导期望 cadence。对于本仓库的 OKX 快照，连续性由下载器在写 CSV 前验证；对于其他外部数据，调用者必须保存并独立验证相应的交易所响应、请求参数、metadata、cadence 和 artifact 证据。

输出：

```text
reports/holdout/BTC-USDT/latest.json
reports/holdout/BTC-USDT/latest.md
```

候选参数只在 validation 区间选择；sealed holdout 只用于最终报告。不得根据 holdout 结果反复调参。

## 7. 运行 paired moving-block bootstrap

先完成 walk-forward 研究，再对其真实 OOS returns 运行。以下基础命令不写入外部 workflow 或 artifact 标识，仅适合本地检查，不能单独作为可审计来源证据：

```bash
python scripts/run_bootstrap_research.py \
  --returns-csv reports/okx/BTC-USDT/walk_forward_returns.csv \
  --instrument BTC-USDT \
  --output-dir reports/bootstrap/BTC-USDT \
  --block-length 20 \
  --resamples 2000 \
  --confidence 0.95 \
  --annualization 365 \
  --seed 20260722
```

对来自 GitHub Actions artifact 的输入，先把与该 CSV 匹配的真实标识写入环境变量。`${VAR:?message}` 只会在变量为空或未设置时立即失败；当前 CLI 会原样记录这三个标识，不会验证它们是否真的对应输入 CSV、workflow 或 artifact。因此，下面的命令只能防止遗漏字段，不能防止错误、占位或伪造标识。运行前必须在 GitHub 中独立核对 run、artifact、exact head 与 CSV SHA-256 的对应关系：

```bash
: "${SOURCE_RUN_ID:?export SOURCE_RUN_ID with the workflow run that produced the CSV}"
: "${SOURCE_ARTIFACT_ID:?export SOURCE_ARTIFACT_ID with the artifact containing the CSV}"
: "${SOURCE_HEAD_SHA:?export SOURCE_HEAD_SHA with the exact 40-character source commit}"

python scripts/run_bootstrap_research.py \
  --returns-csv reports/okx/BTC-USDT/walk_forward_returns.csv \
  --instrument BTC-USDT \
  --output-dir reports/bootstrap/BTC-USDT \
  --block-length 20 \
  --resamples 2000 \
  --confidence 0.95 \
  --annualization 365 \
  --seed 20260722 \
  --source-run-id "$SOURCE_RUN_ID" \
  --source-artifact-id "$SOURCE_ARTIFACT_ID" \
  --source-head-sha "$SOURCE_HEAD_SHA"
```

`run_bootstrap_research.py` 会自行计算并写入 `returns_csv_sha256`，但不会把该哈希与 GitHub artifact 清单或 experiment manifest 自动交叉验证。可审计复现必须保存下载包哈希、解压后的 CSV 哈希、workflow run、artifact ID、exact head 和对应 manifest，并由复现者确认这些证据属于同一运行。

输出：

```text
reports/bootstrap/BTC-USDT/bootstrap.json
reports/bootstrap/BTC-USDT/bootstrap.md
```

Bootstrap CLI 会在计算任何指标或开始重采样之前验证输入 chronology：必须存在 `timestamp` 列；每个时间戳必须有效且显式携带时区；转换为 UTC 后必须无重复、严格递增，并保持精确的一天间隔。乱序、重复、缺口、无效或 timezone-naive 时间戳都会直接失败。直接调用底层 `paired_moving_block_bootstrap()` 的库代码不会自动执行该检查，必须先调用 `validate_chronological_returns_frame(..., expected_frequency="1D")`。

Bootstrap 只能对已观察到的真实收益做重采样，不能生成或模拟价格路径。

## 8. 与 GitHub Actions 对齐

`.github/workflows/hourly-research.yml` 在 pull request、`main` push、手动触发及每小时第 17 分钟执行：

1. 安装固定版本的 pip bootstrap 和项目；
2. 执行 Ruff lint 与 format check；
3. 使用仓库内不可变 OKX fixture 运行 pytest；该步骤不下载行情；
4. 通过公共 OKX 接口重新下载 BTC-USDT 与 ETH-USDT 日线，运行 rolling OOS 研究并写 experiment manifest；
5. 核对两份 `walk_forward_returns.csv` 存在且非空，并计算各自的 SHA-256；
6. 先将完整 `reports/okx/` 上传为 `quant-research-source-<run-number>-attempt-<run-attempt>` 不可变来源 artifact，保留 14 天；
7. 使用该来源 artifact 的 ID、digest、workflow run ID、exact head SHA 和两份 return 文件哈希生成固定初始权重、无再平衡的 BTC/ETH portfolio-risk 报告；
8. 将 `reports/portfolio/` 单独上传为 `quant-portfolio-risk-<run-number>-attempt-<run-attempt>` artifact，同样保留 14 天。

attempt 后缀是 artifact 身份的一部分；workflow rerun 会生成新的 source 和 portfolio artifact，不会覆盖上一尝试。组合报告是 development-market 风险诊断，不是新的 alpha 或 untouched-holdout 证据。

复现 CI 时，至少保存：

- workflow run ID、run attempt 与 exact head commit SHA；
- source artifact 的 ID、名称、下载包 SHA-256 digest；
- portfolio artifact 的 ID、名称、下载包 SHA-256 digest；
- 两份 `walk_forward_returns.csv` 的 SHA-256；
- experiment manifest；
- 两个品种的 snapshot metadata、raw response、normalized CSV 和 rolling reports；
- `portfolio_risk.json`、`portfolio_risk.md` 与 `portfolio_returns.csv`。

历史绿色 workflow 只对其确切 commit、配置和两个对应 artifact 有效，不能自动替代当前 head 的验证。portfolio artifact 必须能追溯到同一运行先上传的 source artifact；不能把不同 run 或 attempt 的证据拼接在一起。

## 9. 常见失败

### `--csv` 被拒绝

这是预期迁移行为。不要恢复旧参数；为真实 CSV 创建 schema-v1 manifest，并改用 `--snapshot-manifest`。

### manifest 或 CSV 校验失败

不要通过重排、去重、补值或重写 CSV 来绕过校验。先确认 manifest 是否对应当前文件字节、精确 header、行数和时间边界；任何有意修改都必须生成新的 SHA-256 和新的 manifest，并保留来源证据。

### Ruff 失败，后续步骤全部跳过

运行：

```bash
ruff check .
ruff format .
ruff format --check .
```

格式修复后必须在未变化的 exact head 上重新跑完整门禁。

### OKX 网络或地区域名失败

该问题只影响下载新快照和网络研究，不影响使用仓库内 fixture 的 pytest。为下载入口设置可访问的公共域名：

```bash
export OKX_BASE_URL=https://www.okx.com
```

不要加入 API key，也不要改用账户或订单端点。

### `requested_start_reached` 为 `false`

先检查 snapshot metadata 的 `pagination_termination`：

- `max_pages`：当前代码会直接失败；提高 `--max-pages` 或缩短请求区间后重新下载；
- `short_page` 或已有数据后的 `empty_page`：OKX 没有返回更早的 bar，常见原因是品种上市晚于请求日期。该快照不能声称覆盖到 `requested_start`；应核对交易所上市历史，或把研究起点调整到实际可验证的最早 bar。

不要删除完整性检查，也不要把未到达请求起点的快照包装为完整历史。

### 没有生成 artifact

确认研究命令成功写入 `reports/`，并检查 workflow 的前置 lint、format 和 pytest 是否已经通过。被跳过的步骤不算成功。

## 10. 证据边界

- 真实历史回测不是前向交易结果；
- 日线收盘价无法证明盘口成交、容量或滑点；
- 单个市场、单个时期或单条收益曲线不足以证明 alpha；
- validation、OOS 和 holdout 必须按时间隔离；
- 不得隐藏失败候选、费用敏感性或不稳定参数；
- 仓库不包含下单、账户、资金划转或杠杆操作路径。

本项目仅用于研究与软件工程验证，不构成投资建议，也不保证收益或回撤。
