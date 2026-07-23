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
3. 在任何第三方安装之前，用受信任脚本验证根目录和依赖声明；
4. 通过 public PyPI、`--only-binary=:all:`、`--dry-run` 和目标平台参数解析 build/project 两组依赖，不安装 proposed project；
5. 记录解析出的精确版本、PyPI artifact URL 和 SHA-256；
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
- build、project 和 optional requirements 不能引用项目自身。

当前仓库的有效声明会被规范为：

```text
build requirements:
  setuptools>=69

project requirements:
  numpy>=1.26,<3
  pandas>=2.1,<3
  pytest>=8,<10
  ruff>=0.9,<1
```

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
- 项目对自身的 build/project/optional dependency。

`dynamic` 与 `cmdclass` 都不是本门禁中的惰性配置：它们可能要求 build backend 读取或导入 proposed source 才能确定 metadata。当前策略因此只接受无需执行 PR 代码即可完整解析的静态依赖声明。

## 本地可执行预检

macOS/Linux：

```bash
rm -rf reports/security/local-dependency-inputs
python scripts/dependency_audit_inputs.py prepare \
  pyproject.toml \
  reports/security/local-dependency-inputs
python -m json.tool \
  reports/security/local-dependency-inputs/dependency-inputs.json
```

Windows PowerShell：

```powershell
Remove-Item -Recurse -Force reports/security/local-dependency-inputs `
  -ErrorAction SilentlyContinue
python scripts/dependency_audit_inputs.py prepare `
  pyproject.toml `
  reports/security/local-dependency-inputs
python -m json.tool `
  reports/security/local-dependency-inputs/dependency-inputs.json
```

先删除旧目录很重要：一次失败的 `prepare` 不会创建新的 dependency-input 文件，但也不会替调用者删除先前成功运行留下的旧目录。

完整的本地策略回归为：

```bash
pytest -q \
  tests/test_dependency_audit_workflow.py \
  tests/test_dependency_dynamic_metadata_policy.py \
  tests/test_dependency_audit_documentation.py
```

这些命令验证受信任解析和工作流声明，不会在本地复现 GitHub Actions 的全部 20 个 Python/平台解析任务，也不会替代远端 vulnerability audit。

## 证据边界

通过门禁表示：受信任解析器能够静态读取声明；解析结果来自 public PyPI binary artifacts；记录的 artifact SHA-256 格式有效；两组锁定依赖在当次 `pip-audit` 数据下未触发门禁失败。

它不表示：依赖没有未知漏洞、artifact 内容已经人工审查、许可证适合所有用途、每个运行时路径都安全，或未来重新解析一定得到相同版本。审计 artifact 只保留 14 天；需要长期复现时，应另行保存对应 workflow run、base/head SHA、`proposed-pyproject.sha256`、resolved requirements 和 resolved-artifacts JSON。
