# explog

`explog` 是一个小型实验运行器,同时维护一份仅追加写入的 JSONL 日志。每次运行都会记录它与先前实验的关系、当前的 Git 状态、一条说明文字,以及存放所生成数据的目录。

它需要 Python 3.11 或更高版本,除标准库外没有任何运行时依赖。

## 安装

从本检出目录安装该项目:

```bash
python3 -m pip install .
```

如需可编辑的开发安装,请使用 `python3 -m pip install -e .`。

安装后,两种调用入口完全等价:

```bash
explog --help
python3 -m explog --help
```

## 配置

TOML 文件恰好包含以下三个顶层键:

```toml
data_root = "experiment-data"
experiment_scripts = [["python3", "scripts/run.py"]]
data_processing_scripts = [["python3", "scripts/process.py"]]
```

每个脚本都是一个 argv 数组。它必须至少包含一个可执行程序,且每个元素都必须是字符串。允许脚本列表为空。命令会被直接执行、绝不经过 shell,并以 Git 仓库根目录作为工作目录。因此,配置中的相对脚本路径是相对于 Git 根目录的。

`data_root` 可以是相对于 Git 根目录的路径,也可以是绝对路径,但解析后的位置必须位于 Git 仓库之内。对于 ID 为 `baseline` 的实验,该工具会创建:

```text
experiment-data/
└── baseline/
    ├── git.diff
    ├── raw/
    └── processed/
```

每个实验命令会额外收到如下参数:

```text
--output /absolute/path/to/experiment-data/baseline/raw
```

每个数据处理命令会收到:

```text
--input /absolute/path/to/experiment-data/baseline/raw --output /absolute/path/to/experiment-data/baseline/processed
```

所有实验脚本按配置顺序执行,随后所有处理脚本同样按配置顺序执行。同一组内的脚本共享各自的输入或输出目录,并需自行负责选择互不冲突的文件名。

## 初始化

首次运行实验前,可以检查环境并初始化日志和数据根目录:

```bash
explog init --config explog.toml --log experiments.jsonl
```

这两个选项可以省略,默认值分别是当前目录下的 `explog.toml` 和 `experiments.jsonl`。`init` 会检查当前目录属于一个已有 `HEAD` 的 Git 仓库、配置合法、脚本的可执行程序可用、日志合法且 `data_root` 位于仓库内。工作区中的已跟踪修改和未跟踪文件会被报告,但不会阻止初始化。

检查全部通过后,`init` 会按需创建日志的父目录、`data_root` 和一个空 JSONL 日志。它不会创建实验 ID、`raw` 或 `processed` 目录。该命令可以安全地重复执行:已有的合法日志、数据目录及其中内容都会原样保留。已有日志或路径非法时,初始化会失败而不会覆盖它们。

配置中带路径的可执行程序相对于 Git 根目录检查,不带路径的程序从当前 `PATH` 查找。`init` 只检查每条命令的第一个 argv 元素,不会推断其余参数是否表示脚本文件。初始化是可选步骤;原有的实验运行命令仍可直接使用。

## 用法

命令格式是固定的:

```text
explog --config CONFIG --log LOG --message MESSAGE [--parent-id ID] [--id ID]
```

使用自动生成的 ID 启动一个根实验:

```bash
explog \
  --config explog.toml \
  --log experiments.jsonl \
  --message "Initial compiler settings"
```

命令成功后会打印其 ID,例如 `20260823T132045Z`。自动生成的 ID 是精确到秒的 UTC 时间戳。使用 `--id` 可显式指定 ID:

```bash
explog \
  --config explog.toml \
  --log experiments.jsonl \
  --message "Initial compiler settings" \
  --id baseline
```

自定义 ID 会被原样保存。它必须是一个安全的单层目录名:不能为空、不能是 `.` 或 `..`,不能包含 `/`、`\`、NUL 或 ASCII 控制字符。同一日志中不能重复使用某个 ID,且其目标数据目录必须尚不存在。

将某个已有节点指定为父节点,即可创建一个后续实验:

```bash
explog \
  --config explog.toml \
  --log experiments.jsonl \
  --message "Increase the batch size" \
  --parent-id baseline \
  --id larger-batch
```

省略 `--parent-id` 会创建根节点。指定的父节点必须已经存在于同一日志中。

`CONFIG` 和 `LOG` 遵循常规的命令行路径处理规则,以相对路径给出时相对于当前工作目录。直接运行实验时,日志文件的父目录必须已经存在;`explog init` 会按需创建它。

## JSONL 记录

日志采用 UTF-8 编码的 JSON Lines 格式。对象使用紧凑 JSON,非 ASCII 文本以 UTF-8 原样保留,内嵌换行符会做 JSON 转义,因此每个节点恰好占据一行物理行。新记录以追加模式写入。

每个节点恰好包含以下字段:

- `id`:自动生成或用户指定的实验 ID。
- `parent_id`:父节点的 ID,根节点为 JSON `null`。
- `message`:通过 `--message` 传入的原始值。
- `git_commit`:在创建数据目录、运行脚本之前捕获的 `HEAD` 完整哈希。
- `git_diff_path`:Git diff 输出文件的路径,以相对于 Git 根目录的 POSIX 路径表示。该文件固定保存为实验数据目录下的 `git.diff`。生成 diff 前会先在仓库根目录执行 `git add -N -- .`,再执行 `git diff --binary --full-index --no-ext-diff HEAD --`,因此 diff 包括已暂存修改、未暂存修改和未被忽略的未跟踪文件。`git add -N` 只在索引中登记未跟踪文件的路径,不会暂存其内容。
- `data_dir`:运行目录,以相对于 Git 根目录的 POSIX 路径表示,与宿主系统的路径写法无关。

例如,上面两条命令会追加如下形式的行(其中的哈希和路径仅为示意):

```jsonl
{"id":"baseline","parent_id":null,"message":"Initial compiler settings","git_commit":"0123456789abcdef0123456789abcdef01234567","git_diff_path":"experiment-data/baseline/git.diff","data_dir":"experiment-data/baseline"}
{"id":"larger-batch","parent_id":"baseline","message":"Increase the batch size","git_commit":"0123456789abcdef0123456789abcdef01234567","git_diff_path":"experiment-data/larger-batch/git.diff","data_dir":"experiment-data/larger-batch"}
```

## 失败行为

工作流程的步骤顺序是刻意编排的:

1. 加载并校验配置、仓库、日志关系、ID 和路径。
2. 执行 `git add -N -- .`,捕获 Git `HEAD` 和工作区 diff。
3. 创建运行目录、`raw` 和 `processed` 目录。
4. 将 diff 写入运行目录下的 `git.diff`。
5. 运行每个实验脚本。
6. 运行每个处理脚本。
7. 追加一条 JSONL 节点。

任何非法的配置或日志、缺失的父节点、重复或不安全的 ID、数据目录冲突、Git 错误、目录错误,或脚本非零退出、无法执行,都会中止本次运行。只有当所有前置步骤都成功时,才会追加日志节点。如果失败发生在运行目录创建之后,该目录、已写入的 `git.diff` 及任何数据都会被有意保留以供诊断;`explog` 不会回滚它们。

该工具不提供查询子命令、数据库、索引或锁服务。
