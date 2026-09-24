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

## 美股 DAG 的三个前置条件

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

**3. 晨报的收件地址**(缺失则只有存档、没有邮件)

报告会走两条出口:

- **存档**:`data/reports/us-sentinel/<日期>.txt`,落在项目里,`data/` 已被
  git 忽略,不会进仓库。
- **邮件**:`sentinel-mail` 这步把报告正文发到你的邮箱。

发信凭据用的是 dagu 自己的 `smtp:` 配置(和失败告警同一套,已经配好)。
但**收发地址不能写在本仓库里——它是公开的**,所以由 dagu 的 `base.yaml`
注入。在 `~/etc/docker/dagu/base.yaml` 里加:

```yaml
env:
  - SENTINEL_MAIL_FROM: 你的发信地址
  - SENTINEL_MAIL_TO: 你的收件地址
```

这两个变量没配时,`sentinel-mail` 会失败,但它带了
`continueOn: failure`,报告存档和整个 DAG 的状态都不受影响。

想在下一次定时运行之前先验证发信是否通,可以拿一个隔离的 dagu home 试发一封,
不影响正式的 dags 目录:

```bash
docker exec dagu sh -c 'mkdir -p /tmp/mt && cat > /tmp/mt/t.yaml <<EOF
steps:
  - name: send
    executor:
      type: mail
      config:
        from: ${SENTINEL_MAIL_FROM}
        to: ${SENTINEL_MAIL_TO}
        subject: "[测试] 哨兵投递链路"
        message: "如果你收到这封,链路就是通的。"
EOF
dagu start --dagu-home /tmp/mt --base /var/lib/dagu/base.yaml /tmp/mt/t.yaml; rm -rf /tmp/mt'
```

## 手动跑一次

```bash
./trade py data edgar sync   --start 2026-08-25
./trade py data edgar form4  --start 2026-08-25 --universe-file config/us_universe.txt
./trade py show us-sentinel  --date  2026-08-25
```

加 `--out` 就同时存档;路径以 `/` 结尾时文件名自动用报告日期:

```bash
./trade py show us-sentinel --date 2026-08-25 --out data/reports/us-sentinel/
```

## 附:被 dagu 取代的旧 crontab

```
30 17 * * 1-5  cd /home/peng/PROGRAM/GitHub/trade && ./trade py data kline sync --mode incremental --adjust hfq --provider sina
30 18 * * 1-5  cd /home/peng/PROGRAM/GitHub/trade && ./trade py data sentiment
0  19 * * 1-5  cd /home/peng/PROGRAM/GitHub/trade && ./trade py daily belief && ./trade py daily recommend
```
