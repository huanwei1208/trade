# 定时任务部署

两条独立的 dagu DAG,共用 `/home/peng/etc/docker/dagu/base.yaml`
(retryPolicy limit 3、失败邮件告警)。

| DAG | 文件 | 排程 | 内容 |
|---|---|---|---|
| A股 | `trade-daily.yaml` | 工作日 18:30 JST | K线 + 新闻 → 信念 → 推荐 (EBRT) |
| 美股哨兵 | `us-daily.yaml` | 周二至周六 06:30 JST | K线 + EDGAR + 英文新闻 → 晨报 |

## 部署

```bash
cd deployment/cron
make deploy        # 两个都部署
make deploy-us     # 只部署美股
```

## 美股 DAG 的两个前置条件

**1. SEC 身份标识**(缺失则 EDGAR 步骤直接拒绝运行)

`.env` 里加:

```
SEC_EDGAR_USER_AGENT="trade-project 你的邮箱"
```

SEC 的 fair-access 政策要求调用方声明身份和联系方式。

**2. ollama 服务由 DAG 自己启停**

`us-news` 那步要用本地 Qwen 做新闻富化,所以 DAG 会:

```
ollama-start  →  sudo systemctl start ollama
                 轮询 /api/tags 等就绪(最多 60 秒)
                 发一次 prompt 预热,把模型载入显存
us-news       →  实际富化
handlerOn.exit → sudo systemctl stop ollama
```

几个设计点:

- **预热是必须的**。冷启动要把 14B 模型载入显存,实测第一次调用 163 秒,
  而 `OllamaClient` 单次超时 60 秒 —— 不预热的话开头几篇必然超时重试。
  预热后显存占用约 9.3 GB。
- **关闭放在 `handlerOn.exit`**,而不是最后一个 step。exit handler 在
  成功、失败、取消三种情况下都会执行,step 不会 —— 富化失败时模型仍会被卸载。
- **需要免密 sudo**:`sudo -l` 里要有 `(ALL) NOPASSWD: /usr/bin/systemctl`。

如果希望 ollama 平时完全不启动,还要取消开机自启:

```bash
sudo systemctl disable ollama
```

注意:这个 DAG 会无条件关闭 ollama。如果你有其它程序也在用它,
`handlerOn.exit` 会把它们一起断掉。

## 手动跑一次

```bash
./trade py data edgar sync   --start 2026-08-25
./trade py data edgar form4  --start 2026-08-25 --universe-file config/us_universe.txt
./trade py show us-sentinel  --date  2026-08-25
```

## 附:被 dagu 取代的旧 crontab

```
30 17 * * 1-5  cd /home/peng/PROGRAM/GitHub/trade && ./trade py data kline sync --mode incremental --adjust hfq --provider sina
30 18 * * 1-5  cd /home/peng/PROGRAM/GitHub/trade && ./trade py data sentiment
0  19 * * 1-5  cd /home/peng/PROGRAM/GitHub/trade && ./trade py daily belief && ./trade py daily recommend
```
