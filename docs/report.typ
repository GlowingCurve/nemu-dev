#set page(paper:"a4", margin: (x: 2.5cm, y: 3cm))
#set text(
  font: "Noto Serif CJK SC", 
  size: 12pt,
  lang: "zh",
  region: "cn"
)
#set par(
  justify: true,    
  leading: 0.8em,     
  first-line-indent: 0em 
)
#show heading.where(level: 1): it => block(
  width: 100%,
  spacing: 1em,
  [
    #text(size: 16pt, weight: "bold", font: ("Noto Serif CJK SC"), it.body)
  ]
)
#show heading.where(level: 2): it => block(
  spacing: 1.0em,
  [
    #v(0.5em)
    #text(size: 14pt, weight: "bold", font: ("Noto Serif CJK SC"), it.body)
    #v(0.5em)
  ]
)

#set quote(block: true)
#show quote: it => block(
  fill: luma(248),                    
  int: (x: 1em, y: 0.8em),          
  radius: 4pt,                         
  stroke: (left: 4pt + rgb("5e81ac")),
  width: 100%,
  text(fill: luma(60), it.body)       
)

#set list(indent: 1em, marker: "•")
#set enum(indent: 1em)
#show figure.where(kind: table): set figure.caption(position: top)
#title[NEMU的性能优化]

= 摘要

本文介绍对NEMU的优化工作，实现了端到端最高加速25.2x的优化工作。本文建立了对NEMU的性能测量方法，并通过InstCache,BasicBlockCache逐步展开对NEMU的优化工作。

= 介绍

NEMU(NJU Emulator)是一款面向教学场景的解释型指令集模拟器,对NEMU进行优化有着重要的实际意义

= 原始NEMU的性能测量

== 实验设置

本节称述对NEMU进行性能测量时的平台信息，Benchmark选择，性能测量场景选择与NEMU版本选择。

=== 平台信息

本文使用的平台信息如下

#table(
  columns:(7cm,9cm),
  stroke: 0.5pt,
  [类别],[配置/版本],
  [OS],[Fedora Linux 44 (Workstation Edition)],
  [Kernel],[Linux 7.1.8-200.fc44.x86_64],
  [CPU],[AMD Ryzen 9 9955HX (32) @ 5.46 GHz],
  [RAM],[32.0 GiB, DDR5 5600MT/s],
  [gcc],[ 16.1.1 20260515 (Red Hat 16.1.1-2)],
  [riscv64-linux-gnu-gcc],[(g6afcc4f6d) 16.1.0],
)

=== Benchmark选择

本文选择“一生一芯”所提供的microbench作为NEMU性能测量时使用的Benchmark。
#figure(
  table(
    columns: (3.5cm,3.5cm,8cm),
    stroke: 0.5pt,
    [测试规模],[指令数],[使用场景],
    [test],[约300K],[ 正确性测试],
    [train],[约60M],[在RTL仿真环境中研究微结构行为],
    [ref],[约2B],[在模拟器或FPGA环境中评估处理器性能],
    [huge],[约50B ],[衡量高性能处理器(如真机)的性能]
  ),
  caption: [microbench提供的测试规模]
)
#figure(
  table(
    columns: (5cm,10cm ),
    stroke: 0.5pt,
    [名称],[描述],
    [qsort],[快速排序随机整数数组],
    [queen],[位运算实现的n皇后问题],
    [bf],[Brainf\*\*k解释器，快速排序输入的字符串],
    [fib],[Fibonacci数列f(n)=f(n-1)+…+f(n-m)的矩阵求解],
    [sieve],[Eratosthenes筛法求素数],
    [15pz],[A\*算法求解4x4数码问题],
    [dinic],[Dinic算法求解二分图最大流],
    [lzip],[Lzip数据压缩],
    [ssort],[Skew算法后缀排序],
    [md5],[计算长随机字符串的MD5校验和]
  ),
  caption: [microbench所包含的子项]
)

选择 microbench 作为基准程序，主要基于以下考虑：
+ 规模适中：ref 规模下原始 NEMU 的运行时间可控，便于进行多次重复测量；
+ 不依赖操作系统：无需启动 Linux 即可运行；
+ 覆盖面广：10 个子项覆盖排序、位运算、图算法、压缩、哈希等典型负载；
+ 测试质量高：采用有代表性的真实程序，能较为充分地评估模拟器性能。

本文统一采用 ref 规模（约 $2 times 10 ^ 9$ 条指令）,原因如下：
+ test和train 规模过小，测量结果易受计时误差与系统噪声淹没。
+ huge规模则与 ref 规模在行为特征上无本质差异，而耗时显著增加。

若无特别说明，后文所述 microbench 均指 ref 规模。


=== 性能测量场景

本段介绍对NEMU进行性能测量时使用的不同测量场景。

*真实场景*

实际使用中，NEMU会在有一定负载的系统上运行。为了具体测量NEMU实际情况下的性能，本报告选取如下测量场景：在系统负载不太高、系统资源不紧张的情况下不做限制运行NEMU。本文认为，如果当前系统的Load Average的三个参数均小于0.5\*逻辑CPU数量,系统内存中有8G的可用空间，即可认为系统负载不太高，系统资源不紧张。

*理论场景*

然而，在实际场景下NEMU性能测量的结果将含有大量的系统噪声，无法较为精确评估NEMU的性能，也不利于为之后的性能评估提供精确的基线。

本文采用CPU Isolation有关特性尽力屏蔽系统噪声，对NEMU性能进行较为精确的测量。CPU Isolation是Linux提供的一项机制，通过cgroup等手段，可以将指定的CPU进行一定程度上的隔离，比如调度器不再向该CPU调度任务，中断不再由该CPU处理。

本文采用了一种无持久化、可重启回滚的CPU Isolation方案：利用cgroup v2的cpuset子系统,将目标CPU按照物理核，从根调度域动态摘除，阻止调度器向目标CPU分配任务；修改亲和掩码，阻止目标CPU处理内核线程的延迟工作；通过cpufreq接口将调节器和能效偏好置为performance，并对最高频率施加上限(4GHz)，在目标CPU上建立可复现的频率状态；通过改写掩码，阻止隔离CPU处理watchdog事务；重构中断亲和性体系，尽力迁移存量中断，对于难以迁移的中断，报告但不强行处理。

同时在开发过程中，可并行运行隔离CPU群，运行多个批次完成快速性能评估。

== 统计方法

由于固有的系统噪声，NEMU在相同的编译参数、相同的测试场景等相同条件下的用时难以完全相同。本段讨论了对NEMU进行性能测量时所采用的统计学手段和测量方案。

首先建立样本与性能指标。

=== 样本与性能指标

设在NEMU上运行 $n$ 次microbench，
得到性能测量结果

$
x_1, x_2, ..., x_n.
$

在microbench中，本文使用程序执行时间(Scored Time)作为性能指标，
因此 $x_i$ 表示microben在NEMU上的第 $i$ 次执行时间。执行时间越短，说明模拟器性能越高。

为了评估统计结果的精度和可重复性，本文进一步分析测量数据的样本均值、样本标准差、变异系数以及置信区间。

=== 样本均值

对于 $n$ 次重复实验结果，
样本均值$macron(x)$定义为


$
macron(x) = 1/n sum_(i=1)^n x_i.
$

本文采用样本均值用于描述NEMU执行microbench时的平均运行时间。

=== 样本标准差

对于 $n$ 次重复实验结果，
样本标准差$s$定义为

$
s = sqrt(
  1/(n - 1)
  sum_(i=1)^n
  (x_i - macron(x))^2
).
$

本文进一步采用变异系数
（Coeffi"ci"ent of Variation, CV）
评估测量结果的相对波动情况。

变异系数是无量纲的离散程度指标，定义为
$
"CV" = s / macron(x) times 100%.
$

$"CV"$越低，表明实验结果波动越小,测量结果的可重复性越好。

=== 置信区间

为了进一步描述平均性能估计的不确定性，
本文基于 Student's $t$ 分布构造总体均值的置信区间（Confidence Interval, CI），对平均执行时间计算置信区间

对于置信水平 $1 - alpha$，
总体平均性能的双侧置信区间表示如下

$
macron(x)
plus.minus
t_(1 - alpha/2, n - 1)
s / sqrt(n).
$

其中，
$t_(1 - alpha/2, n - 1)$
表示自由度为 $n - 1$ 的 $t$ 分布临界值。

当采用 $95%$ 置信水平时，
有 $alpha = 0.05$，
双侧置信区间表示为

$
"CI"_(95%)
=
[
  macron(x) -
  t_(0.975, n - 1)
  s / sqrt(n),
  quad
  macron(x) +
  t_(0.975, n - 1)
  s / sqrt(n)
].
$

当采用$99%$ 置信水平时，有 $alpha = 0.01$，双侧置信区间表示为

$
"CI"_(99%)=[ macron(x) -  t\_(0.995, n - 1)  s / sqrt(n), quad macron(x) +  t\_(0.995, n - 1)  s / sqrt(n)].
$

为了进一步衡量平均性能估计误差相对于估计值本身的大小，本文引入相对误差界（Relative Margin of Error, RMOE）指标。RMOE 定义为置信区间半宽度与样本均值的比值，用于表示平均性能估计结果的不确定性比例。对于置信水平 $1 - alpha$，RMOE计算形式如下：

$
"RMOE"_(1 - alpha)= (t\_(1 - alpha/2, n - 1) s / sqrt(n)) / macron(x).
$

当 $"RMOE"$ 较小时，说明估计均值相对于自身尺度具有较小的不确定性，实验结果更加稳定；反之，则表明平均性能估计受到样本波动影响较大。

在 $95%$ 置信水平下，相对误差界表示为：

$
"RMOE"_(95%)= (t\_(0.975, n - 1) s / sqrt(n)) / macron(x).
$

对应地，在 $99%$ 置信水平下，相对误差界表示为：

$
"RMOE"_(99%)= (t\_(0.995, n - 1) s / sqrt(n)) / macron(x).
$

== 性能测量方法

== 性能测量结果

=== 真实场景

=== 理论场景

= 总结