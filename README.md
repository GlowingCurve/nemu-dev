# NEMU 性能优化

本仓库是我进行NEMU性能优化的仓库。

主要目录包括 `nemu`、`abstract-machine` 和 `microbench`。

## 如何运行

### nemu编译

进入nemu目录

```bash
cd nemu
```

运行如下命令

```bash

make clean

make

```

### microbench编译

进入microbench：`cd microbench`

以ref规模编译microbench

```bash
make ARCH=riscv32-nemu mainargs=ref
```

如果想要以huge规模编译microbench

```bash
make ARCH=riscv32-nemu mainargs=huge
```

然后进行跑分

```bash
make ARCH=riscv32-nemu run 
```

### scripts说明

scripts下是脚本，包括进行CPU Isolation的脚本，实验脚本和数据处理脚本

### explog说明

explog下是explog实验日志管理工具的源码，见README.md

explog.toml是explog的配置文件

experiments.jsonl是实验日志文件

### experiment-data

这些是原始实验数据和处理后的数据，其中的perf.data不保证可用
