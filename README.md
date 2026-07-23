# GPT Quant Lab

一个从零构建、可复现、可审计的量化研究工程。当前目标不是宣称“发现了西蒙斯策略”，而是先把最容易造假的环节做对：**时点一致、无未来函数、交易成本、风险约束、滚动样本外测试和数据来源追踪**。

## 可执行复现指南

从干净检出开始的环境安装、真实 OKX 数据下载、rolling OOS、验证/留出研究、paired block bootstrap、跨平台 SHA-256 核验、CI artifact 审计和故障排查，见 [`docs/REPRODUCTION.md`](docs/REPRODUCTION.md)。

指南只接受真实交易所数据作为研究或绩效证据，并明确区分入口自动强制的 chronology 条件、selection/OOS 的初始仓位记账边界，以及仍需调用者独立核验的 provenance 边界。

## 当前研究对象

默认真实数据实验使用 OKX 公共 REST API 的 `BTC-USDT` 与 `ETH-USDT` 现货日线：

- 接口：`GET /api/v5/market/history-candles`；
- 周期：`1Dutc`，按 UTC 0 点划分日线；
- 只接受 `confirm=1` 的完整 K 线；
- 不需要 API key，不读取账户，不连接交易接口；
- 现货策略限制为 **长仓/现金**，不在现货回测中虚构卖空；
- 每次下载保存原始分页响应、规范化 OHLCV CSV、元数据及 SHA-256 哈希。

OKX 的历史 K 线是交易所特定数据；收盘价回测不能复现盘口深度、延迟或保证成交。API 域名具有地区差异，可通过 `OKX_BASE_URL` 或 `--base-url` 覆盖。

## 策略基线

单资产弱信号组合：

\[
s_t = w_T z_{\text{trend},t} + w_R z_{\text{reversal},t}
\]

波动率目标仓位：

\[
p_t^* = \operatorname{clip}\left(\tanh(s_t)\frac{\sigma^*}{\hat\sigma_t},p_{\min},p_{\max}\right)
\]

收盘时刻 \(t\) 计算出的目标仓位只从下一根 bar 开始生效：

\[
r^{\text{strategy}}_t = p^*_{t-1}r_t-c\lvert p^*_{t-1}-p^*_{t-2}\rvert
\]

这条一根 bar 的执行延迟，是防止未来函数的最低要求之一。

## OKX 滚动样本外实验

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
python scripts/run_okx_research.py --inst-id BTC-USDT --output-dir reports/okx/BTC-USDT
```

可覆盖默认品种、固定宽度周期、日期和 API 域名：

```bash
python scripts/run_okx_research.py \
  --inst-id ETH-USDT \
  --bar 1Dutc \
  --start 2018-01-01 \
  --base-url https://www.okx.com \
  --output-dir reports/okx/ETH-USDT
```

当前连续性验证只覆盖秒、分钟、小时、日和周的固定宽度周期，例如 `1s`、`1m`、`2H`、`3Dutc` 和 `1Wutc`。`1M`、`3Mutc` 等日历月周期及未知格式会在网络请求前失败。更改周期不会自动缩放年化参数、lookback 或 fold 长度；完整边界和自检命令见 [`docs/OKX_INTERVALS.md`](docs/OKX_INTERVALS.md)。

实验流程为：

1. 每个 fold 只用测试期之前的 730 根 K 线选择参数；
2. 每个候选的 selection 窗口独立从现金开始，首行换手与建仓成本按 `previous_position=0.0` 计入；
3. 在随后 90 根 K 线上做一次非重叠样本外评估；
4. OOS fold 切换时按真实前一 OOS 仓位重新计算换手与成本，不在每折重置为现金；
5. 同期比较买入持有、波动率目标长仓和简单趋势长仓/现金；
6. 所有基准从现金开始，并计入样本外起点的建仓成本；
7. 将交易成本提高到 2 倍和 4 倍；
8. 对回看期和信号权重做小幅扰动；
9. 报告区分“alpha 候选”和“低回撤风险控制候选”，不通过稳健性条件则标记为 `reject`。

默认成本假设为每单位换手 10 bps，是可配置的研究参数，不代表任何账户的实际 OKX 费率。

报告会写入：

```text
reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.csv
reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.raw.json
reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.metadata.json
reports/okx/BTC-USDT/walk_forward.json
reports/okx/BTC-USDT/walk_forward.md
reports/okx/BTC-USDT/walk_forward_returns.csv
```

研究参数位于 [`config/okx_research.json`](config/okx_research.json)；严格 JSON 类型、候选范围和成本压力边界见 [`docs/OKX_RESEARCH_CONFIG.md`](docs/OKX_RESEARCH_CONFIG.md)。

## 外部真实快照

验证/留出入口不再接受裸 `--csv`。CSV 必须由同目录的 schema-v1 JSON manifest 绑定到精确字节、字段顺序、时间边界、provider、market type、instrument、timeframe 和来源声明。

先从本仓库生成的 OKX snapshot 创建 manifest：

```bash
python scripts/create_verified_snapshot_manifest.py \
  --metadata reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.metadata.json \
  --csv reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.csv \
  --output reports/okx/BTC-USDT/snapshot/verified-snapshot.json
```

Windows PowerShell 等价命令、创建前校验和剩余证据边界见 [`docs/VERIFIED_SNAPSHOT_MANIFEST.md`](docs/VERIFIED_SNAPSHOT_MANIFEST.md)。随后运行：

```bash
python scripts/run_research.py \
  --snapshot-manifest reports/okx/BTC-USDT/snapshot/verified-snapshot.json \
  --config config/okx_holdout.json \
  --output-dir reports/holdout/BTC-USDT
```

此示例使用 `config/okx_holdout.json`。其中 strategy 参数、365 日年化、每单位换手 10 bps 成本及候选参数族与 `config/okx_research.json` 保持一致；但它使用固定 validation/holdout 比例，而 rolling OOS 使用 730/90 bar folds，因此两类报告不是同一种样本外证据，指标不应直接横向比较。

加载器会在研究开始前核对相对路径约束、SHA-256、精确 header 与每行字段数、观测数、显式时区、唯一且严格递增的时间戳、首尾边界，以及有限且严格为正的 close。旧的 `--csv`、`--timestamp-col` 和 `--close-col` 会直接失败。manifest 的 provenance 标识和 timeframe 目前只做结构/声明校验，不会联网证明标识真实性，也不会从 timeframe 推导 cadence；完整字段说明和证据边界见 [`docs/REPRODUCTION.md`](docs/REPRODUCTION.md)。

## 每小时自动化

`.github/workflows/hourly-research.yml` 在 pull request、`main` push、手动触发及每小时第 17 分钟运行：

- lint 与格式检查；
- 使用仓库内带 SHA-256 与来源元数据的不可变 OKX fixture 执行单元测试和未来数据不变性回归；
- 重新下载 BTC-USDT、ETH-USDT 公共日线并运行滚动样本外研究；
- 对两份 `walk_forward_returns.csv` 计算 SHA-256，并先把完整 `reports/okx/` 上传为 `quant-research-source-<run-number>-attempt-<run-attempt>` 不可变来源 artifact；
- 使用该来源 artifact 的 ID、SHA-256 digest、workflow run ID、实际检出 commit 及两份 return 文件哈希生成固定初始权重、无再平衡的 BTC/ETH 风险诊断；工作流显式设置 `MAX_VARIANCE_CONTRIBUTION=0.75` 与 `MAX_PAIRWISE_CORRELATION=0.90`，把两项约束传给 portfolio CLI，并启用 `--fail-on-reject`；
- 将 `portfolio_risk.json`、`portfolio_risk.md` 和 `portfolio_returns.csv` 单独上传为 `quant-portfolio-risk-<run-number>-attempt-<run-attempt>` artifact。

两个 artifact 都保留 14 天，并在 workflow rerun 时使用新的 attempt 后缀，避免把不同尝试写入同一身份。组合报告只有在 buy-and-hold sleeve-weight concentration、initial-weight variance contribution 和 pairwise return correlation 三项约束都通过时才标记为 `pass`：默认最大 sleeve weight 为 75%，单一 sleeve 的最大方差贡献同样为 75%，任意可计算 sleeve pair 的收益相关系数上限为 90%；相关系数严格高于上限，或因零方差等原因不可计算，都会标记为 `reject`。方差贡献预算按固定初始权重与 development-return covariance 计算；相关性预算按对齐的 development-return observations 计算。两者都不是新的优化权重或 untouched-holdout 证据。

工作流启用 `--fail-on-reject` 后，任一组合约束使聚合 `concentration.passes=false` 时，portfolio CLI 会先通过事务式发布完整提交三个 report 文件并打印 `risk_gate_passes=false`，随后返回非零状态，使该 Actions gate 失败。portfolio upload step 使用 `always()` 与 `portfolio_risk.json` file-exists guard，因此 reject 证据仍会上传；若输入或 provenance 在报告生成前失败且没有 JSON，则不会上传空 artifact。未传入该 flag 的手动 CLI 调用保留 report-only 兼容模式，reject 报告本身仍返回零状态。

三个 report payload 会先在输出目录内的临时 staging 目录完整生成，再按 JSON、returns、Markdown 顺序用原子文件替换发布。若发布中途失败且 rollback 成功，已替换文件会按逆序回滚：输出目录此前不存在时，不会留下新建的部分 report 目录；替换已有完整 report 时，会恢复原有三个文件的精确字节。若 rollback 自身也失败，写入器会抛出 `portfolio report commit failed and rollback was incomplete`；此时不能把该目录当作一致证据，必须保留失败日志并重新生成。

生成指标前，portfolio builder 会用已记录的 SHA-256 重新读取每个 return source，并要求内存中的时间戳和收益逐字节对应已验证来源。每个 sleeve 还必须绑定到不同的 `(文件 SHA-256, timestamp 列, return 列, 所选时间戳)`；把同一个已验证 return 列改名成 BTC 与 ETH 两个 sleeve 会直接失败。canonical BTC/ETH CLI 更严格，要求两份 return 文件的 SHA-256 本身不同。

工作流不会生成或上传合成研究结果。工作流对仓库只有读取权限，不会自动提交代码，不包含 API key，也不会向 OKX 发送订单。

## 研究纪律

1. 不用测试 fold 的结果选择该 fold 的参数。
2. 不展示未计成本的结果作为“净收益”。
3. 研究、CI 报告和可执行入口不使用合成数据。
4. 不在完成仿真、纸面交易和风控验收前接入真实订单。
5. 不用单条收益曲线替代跨时期、跨市场、参数扰动和容量测试。
6. 任何数据下载都必须能由原始响应和 SHA-256 哈希追踪。

## 后续阶段

- 在现有固定初始权重 BTC/ETH 风险诊断之上增加更完整的组合约束、流动性和容量测试；
- 增加 block bootstrap 置信区间、Deflated Sharpe 与 PBO；
- 使用盘口或成交数据建立滑点、冲击和容量模型；
- 保存不可变数据快照并建立结果变更审计；
- 通过只读行情的前向仿真检验研究与实际执行的一致性。

> 本仓库仅用于研究与软件工程验证，不构成投资建议，也不保证收益或回撤。
