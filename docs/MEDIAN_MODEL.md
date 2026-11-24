# 七档中位数与 Call 相对价格比较

本轮直接更新现有 FastAPI / Next.js 监测台，继续使用富途 OpenD 行情。没有订单接口。默认监测最近有效到期日；每个行权价使用同一期限、同规格的一对 Call / Put，而不是单独七只 Call。

## 选档及汇总

从正股最新成交价 S_last 找到距离最近的行权价 K0，等距时取较低行权价。按真实期权链的行权价排序，默认选择 K0 下方三档、K0 本身、上方三档；间距不必相等。输出按行权价升序排列。中心档只是最接近现价，不一定严格平值。两侧数量可在设置中调整，0 表示该侧不选，两侧均为 0 时全部不选。

先定档，再验证合约与报价。缺少一腿时保留缺失档位及原因，不用更远档位补足；链边缘不足时不从另一侧补足。页面显示可计算数量/请求数量，例如 6/7，并标明样本不完整。

每档基础反推价 `S_i = C_i - P_i + K_i exp(-rT_i)`。T 沿用快照估值时刻与合约定价参考时刻之差，按 ACT/365；最近到期模式的常规收盘时间是研究假设。利率为人工假设，未知股息不假装已核实为零。基础反推值不是未来股价预测。

保留两种完整计算模式：
- LAST：Call 与 Put 分别使用最新成交价，可能存在成交时间不同步。
- MID：Call 与 Put 分别取买一/卖一中间价；人工 reportedMid 规则不变。

两种模式分别输出 `rawMean`、`rawMedian`、`min`、`max`、`computableCount`、`requestedCount`、`complete`。旧版对照价取同一组可计算档的算术平均值，单独展示。原始中位数使用可计算档；`validatedMedian` 仅使用质量合格档，两者分开。偶数个可计算值取中间两数的平均作为中位数；零样本返回 null。不会以均值作为回退。

主指标、侧栏、总览和图表均采用中位数。`rawGapBps = 10000*(rawMedian-stockReference)/stockReference`。旧模型历史数据不串入新图表。买一、卖一、自定义期权反推模式停止计算。仍保留原始盘口、合成盘口区间及其风险提示，用于解释价差及数据质量。

用户七档示例的验收：行权价 123、124.5、127、129.5、133、134、135；反推值 129.33、130.11、131.06、129.18、128.98、130.51、131.02，结果为中位数 130.11、最小 128.98、最大 131.06。

## 三档 Call 相对估值

在逐档表下方选择三个不同行权价，点击“比较这三档”。使用所选快照和当前 LAST/MID 口径。结果固定标注计算快照时间；行情更新后显示需重新比较，不把旧结果作为最新计算。

对目标 i，另外两档为 j、k：

`w_j=(K_k-K_i)/(K_k-K_j)`，`w_k=1-w_j`

`C_ref_i = P_i + w_j*(C_j-P_j) + w_k*(C_k-P_k)`

`premiumPct = 100*(C_i-C_ref_i)/C_ref_i`

两个权重之和为 1、行权价加权值为目标行权价；同到期时折现行权价项抵消。外侧目标可能出现负权重，即复制组合含空头。程序支持不等距行权价，不固定套用 2 或 0.5。按溢价从低到高排序；同值允许并列。参考价非正、缺失必要价格、跨档合约规格不兼容时不排名。事件时间差和其他报价质量原因单独显示，不把原始价格排名标成质量合格。

附件 GOOG 示例作为用户提供的历史算术案例，并未重新核实其当日行情：275、277.5、280 的 Call 价格 7.59、5.85、4.66；Put 价格 3.67、4.72、6.13。复制参考价为 7.400、5.945、4.470；溢价约 2.57%、-1.60%、4.25%，277.5 在三者中相对最低。

此排名没有扣除交易成本。LAST、MID 不是复制组合的可成交报价，费用、点差、美式期权提前行权及不同步行情可能改变排名，不构成保证套利或买入建议。参考：[OIC Put/Call Parity](https://www.optionseducation.org/advancedconcepts/put-call-parity)。

## 升级与运行

在项目根目录使用已有虚拟环境：

```sh
.venv/bin/python scripts/upgrade_median_model.py
.venv/bin/python scripts/upgrade_median_model.py --apply
FRONTEND_PORT=3100 BACKEND_PORT=8100 bash scripts/dev.sh
```

升级脚本将所有活跃监测改为 3＋1＋3，保留已选 LAST/MID；停用的旧口径改为 MID。先保存本机配置备份，再追加配置版本，不删除旧报价。首次新安装直接运行 dev.sh（或 macOS 启动监测台.command）安装依赖；新建监测默认 3＋1＋3。富途实时报价仍要求本机 OpenD 登录及相应行情权限。

验证：

```sh
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q
cd frontend
npm run typecheck
npm run build
```

模型版本 `parity-median-v3-centered`。新增 `POST /api/monitors/{id}/call-comparison`，请求 `{snapshotId, basis: "LAST"|"MID", strikes: ["275","277.5","280"]}`。快照必须属于该监测，行权价必须属于该快照按配置选中的档位。
