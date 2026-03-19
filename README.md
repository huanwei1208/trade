# trade

统一入口：`./trade`

## 1. 先做环境检查

```bash
./trade doctor
```

要求：
- `clang-13`/`clang++-13`
- `cmake`、`ninja`
- `uv`（用于 Python UI）

## 2. 构建 C++ CLI

```bash
./trade configure linux-clang
./trade build linux-clang
```

如果你安装了多个 clang 版本，建议先设置：

```bash
export CC=/usr/bin/clang-13
export CXX=/usr/bin/clang++-13
```

然后再执行 configure/build。

## 3. 运行项目（CLI）

查看帮助：

```bash
./trade cli --help
```

示例：

```bash
./trade py data kline sync --mode range --symbols 600000.SH --start 2024-01-01 --end 2024-01-31
./trade py data sentiment --start 2026-01-01 --dry-run
./trade cli report --symbol 600000.SH
```

## 4. 运行项目（Web UI）

```bash
./trade setup-python
./trade web
```

默认会启动 FastAPI + uvicorn，监听 http://localhost:8080：
- API 入口：`trade_web/backend/app.py`
- 核心端点：`/api/today-page`、`/api/explain/{symbol}`、`/api/state/{symbol}`、`/api/actions-page`

## 5. 运行测试

```bash
./trade test linux-clang
```

## 6. 情绪新闻源（RSSHub）

当公共 `rsshub.app` 返回 403 时，可在项目内自建 RSSHub：

```bash
cd deployment/rsshub
docker compose up -d
cd ../..
uv run python -m trade_py.cli.main data sentiment --date 2026-03-04 --dry-run --rsshub-base-url http://127.0.0.1:1200
```
