# Python 依赖审计与 `pyproject.toml` 边界

本仓库把 pull request 中的依赖声明视为**不可信数据**。`.github/workflows/dependency-review.yml` 使用 `pull_request_target` 运行，但只检出目标分支的受信任代码；PR head 的 `pyproject.toml` 通过 GitHub API 下载为普通文件，不检出、不安装、也不执行 PR 中的 Python 源码。

这项门禁用于约束依赖声明和已解析 artifact，不代表第三方包本身已经被证明无恶意，也不替代代码审查。

## 工作流实际执行什么

每个面向 `main` 的 pull request 都会在以下矩阵上运行依赖审计：

- Python `3.11`、`3.12`、`3.13`、`3.14`；
- Linux x86-64、Linux arm64、Windows x86-64、macOS x86-64、macOS arm64。

工作流按以下顺序 fail closed：

1. 检出 PR base 的受信任策略代码，权限仅为 `contents: read`，并禁用 credential persistence；
2. 下载 PR head 的 `pyproject.toml`、根目录清单和 legacy build-file 状态作为数据；
3. 在任何第三方安装之前，验证根目录、静态依赖语法及受信任的 direct-dependency declaration-scope allowlist；
4. 只有 allowlist 通过后，才持久化 resolver 输入，并通过 public PyPI、`--only-binary=:all:`、`--dry-run` 和目标平台参数解析 build/project 两组依赖；不安装 proposed project；
5. 记录 approved/declared direct names、其原始声明 scope、解析出的精确版本、PyPI artifact URL 和 SHA-256；
6. 使用固定版本 `pip-audit` 分别审计 build 与 project 依赖；
7. 无论审计是否通过，都把 `reports/security/` 作为 14 天 artifact 上传；任一依赖审计失败会使门禁失败。

## 当前允许的静态声明

`pyproject.toml` 必须满足当前受信任解析器的完整边界：

- `[build-system].build-backend` 必须精确为 `setuptools.build_meta`；
- `[build-system].requires` 必须是非空字符串列表；
- `[project].requires-python` 必须精确为 `>=3.11,<3.15`；
- `[project].dependencies` 与 `[project.optional-dependencies]` 必须是静态字符串列表，二者合计不能都为空；
- requirement 可以使用版本范围和 environment marker，但 marker 只能引用 `python_version`；
- optional extra 名称在 `-`、`_`、`.` 归一化后必须唯一；
- build、runtime 和 optional requirements 不能引用项目自身。

当前仓库的有效声明会被规范为：

```text
build scope ([build-system].requires):
  setuptools>=69

runtime scope ([project].dependencies):
  numpy>=1.26,<3
  pandas>=2.1,<3

optional:dev scope ([project.optional-dependencies].dev):
  pytest>=8,<10
  ruff>=0.9,<1
```

后续 resolver 仍会把 runtime 与 optional requirements 合并为 project 解析输入；direct-policy evidence 则保留它们原本的声明 scope，不能用合并后的 resolver 分组替代 scope 审计。

## 受信任的 direct-dependency declaration-scope policy

通过静态语法检查还不够。受信任的 `scripts/dependency_audit_direct_policy.py` 会把 distribution name 转为小写，并把连续的 `-`、`_`、`.` 统一为 `-`，同时把 optional extra 名称规范化，然后按**原始声明 scope**核对：

- `build`（`[build-system].requires`）只批准 `setuptools`；
- `runtime`（`[project].dependencies`）只批准 `numpy`、`pandas`；
- `optional:dev`（`[project.optional-dependencies].dev`）只批准 `pytest`、`ruff`。

策略不会把 runtime 和 optional 声明压平为一个 `project` scope。新增 `optional:qa` 等未批准 extra，即使其中只包含已知包名，也会作为未批准声明 scope 失败。把 `pytest` 提升到 runtime、把 `numpy` 移入 `optional:dev`，或把 `setuptools` 移出 build，同样失败。

每个规范包名在同一 scope 内最多声明一次，并且不能跨 scope 重复。版本范围或大小写不同不能隐藏重复项：例如同一 runtime 列表同时声明 `numpy>=1.26` 与 `NumPy<3` 会失败；runtime 与 `optional:dev` 同时声明 `pytest` 也会失败。重复与 scope 校验都发生在持久化 resolver 输入和任何第三方安装之前。

allowlist 约束的是规范化后的**直接包名和声明 scope**，不是版本范围。已批准名称在原 scope 内的版本变化仍会进入后续跨平台解析、artifact 记录和 vulnerability audit。

成功时会写出 `reports/security/direct-dependency-policy.json`，包含：

- `schema_version: 2`；
- `approved_direct_dependencies`：受信任策略按 `build`、`runtime`、`optional:dev` 批准的规范名称；
- `declared_direct_dependencies`：当前 proposed `pyproject.toml` 按相同声明 scope 实际声明的规范名称。

当前有效 evidence 的核心结构为：

```json
{
  "schema_version": 2,
  "approved_direct_dependencies": {
    "build": ["setuptools"],
    "optional:dev": ["pytest", "ruff"],
    "runtime": ["numpy", "pandas"]
  },
  "declared_direct_dependencies": {
    "build": ["setuptools"],
    "optional:dev": ["pytest", "ruff"],
    "runtime": ["numpy", "pandas"]
  }
}
```

该文件是本次门禁的策略证据，不是给 PR 作者自行扩展的配置。新增 direct dependency、声明 scope 或 optional extra 必须先在受信任 base policy 中获得明确审查和批准；不能只修改 PR head 的 `pyproject.toml` 来绕过。

## 当前明确拒绝的声明

以下输入会在生成 `build-requirements.in`、`project-requirements.in` 或 `dependency-inputs.json` 之前失败：

- 根目录存在 `setup.py` 或 `setup.cfg`；
- `[build-system].backend-path`；
- 非 `setuptools.build_meta` 的 build backend；
- 非空 `[project].dynamic`；
- `[tool.setuptools.dynamic]`；
- `[tool.setuptools.cmdclass]`；
- direct URL、VCS URL、`file:` URL、本地/父目录路径、Windows 绝对路径或以 `-` 开头的 pip option；
- 引用 `python_version` 以外变量的 environment marker；
- 归一化后冲突的 optional extra 名称；
- 项目对自身的 build/runtime/optional dependency；
- 未获批准的 direct package name；
- 已批准名称出现在错误的 `build`、`runtime` 或 `optional:dev` scope；
- 未批准的 optional declaration scope，例如 `optional:qa`；
- 同一 scope 内重复声明同一规范包名；
- 同一规范包名跨多个声明 scope 重复出现。

`dynamic` 与 `cmdclass` 都不是本门禁中的惰性配置：它们可能要求 build backend 读取或导入 proposed source 才能确定 metadata。当前策略因此只接受无需执行 PR 代码即可完整解析的静态依赖声明。

## 本地可执行预检

macOS/Linux：

```bash
rm -rf reports/security/local-dependency-inputs
python scripts/dependency_audit_direct_policy.py \
  pyproject.toml \
  reports/security/local-dependency-inputs/direct-dependency-policy.json
python scripts/dependency_audit_inputs.py prepare \
  pyproject.toml \
  reports/security/local-dependency-inputs
python -m json.tool \
  reports/security/local-dependency-inputs/direct-dependency-policy.json
python -m json.tool \
  reports/security/local-dependency-inputs/dependency-inputs.json
```

Windows PowerShell：

```powershell
Remove-Item -Recurse -Force reports/security/local-dependency-inputs `
  -ErrorAction SilentlyContinue
python scripts/dependency_audit_direct_policy.py `
  pyproject.toml `
  reports/security/local-dependency-inputs/direct-dependency-policy.json
python scripts/dependency_audit_inputs.py prepare `
  pyproject.toml `
  reports/security/local-dependency-inputs
python -m json.tool `
  reports/security/local-dependency-inputs/direct-dependency-policy.json
python -m json.tool `
  reports/security/local-dependency-inputs/dependency-inputs.json
```

先删除旧目录很重要：direct-policy 失败不会创建目标目录；但 direct-policy 成功后若后续 `prepare` 失败，policy JSON 会保留，而 resolver input 集合并不完整。只有两条命令都成功时，才把该目录视为当前 proposed manifest 的完整预检结果；不要把旧文件或部分新文件误认为完整证据。

完整的本地策略回归为：

```bash
pytest -q \
  tests/test_dependency_audit_workflow.py \
  tests/test_dependency_dynamic_metadata_policy.py \
  tests/test_dependency_direct_policy.py \
  tests/test_dependency_audit_documentation.py
```

这些命令验证受信任解析、direct-name declaration-scope policy 和工作流声明，不会在本地复现 GitHub Actions 的全部 20 个 Python/平台解析任务，也不会替代远端 vulnerability audit。

## PR 作者提交前检查

在修改 `pyproject.toml` 的 pull request 中：

1. 先运行上面的 direct-policy 与 `prepare` 命令，并审阅两份 JSON 中的 approved、declared、声明 scope 与规范化 requirements；
2. 确认没有新增未批准名称或 optional scope、跨 scope 移动/重复、同 scope 重复、legacy build file、dynamic metadata、`cmdclass`、本地路径或 direct URL；
3. 在 Actions 中检查全部 Python/平台 dependency-audit jobs，而不是只看普通 package build；
4. 若门禁失败，下载对应 `python-dependency-audit-*` artifact，先查看 direct-policy evidence/错误、校验 stderr、resolution JSON 和两份 `pip-audit` 输出，再修改声明。

## 证据边界

通过门禁表示：受信任解析器能够静态读取声明；每个 direct dependency name 位于当前批准的原始声明 scope；没有同 scope 或跨 scope 的规范名称重复；解析结果来自 public PyPI binary artifacts；记录的 artifact SHA-256 格式有效；两组锁定依赖在当次 `pip-audit` 数据下未触发门禁失败。

它不表示：批准的 direct package 或其 transitive dependencies 没有未知漏洞、artifact 内容或 publisher identity 已经人工/密码学审查、许可证适合所有用途、每个运行时路径都安全，或未来重新解析一定得到相同版本。direct-name allowlist 也不固定版本和 transitive closure；后两者仍由当次 resolver evidence 与 vulnerability audit 约束。审计 artifact 只保留 14 天；需要长期复现时，应另行保存对应 workflow run、base/head SHA、`proposed-pyproject.sha256`、`direct-dependency-policy.json`、resolved requirements 和 resolved-artifacts JSON。
