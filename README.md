# NEMU 开发工作区

本仓库是我进行NEMU性能优化的仓库。

主要目录包括 `nemu`、`abstract-machine` 和 `microbench`。

## 如何运行

### nemu编译

进入nemu目录
```
cd nemu
```

运行如下命令
```
make clean
make
```

### microbench编译

进入microbench：`cd microbench`

以ref规模编译microbench

```
make ARCH=riscv32-nemu mainargs=ref
```

如果想要以huge规模编译microbench

```
make ARCH=riscv32-nemu mainargs=huge
```

然后进行跑分

```
make ARCH=riscv32-nemu run 
```

