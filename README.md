# trade

统一入口：`./trade`

## 1. 先做环境检查

```bash
./trade doctor
```

要求：
- `g++`/`gcc` >= 10（建议 13）
- `cmake`、`ninja`
- `uv`（用于 Python UI）

## 2. 构建 C++ CLI

```bash
./trade configure linux
./trade build linux
```

如果你安装了 GCC 13，建议先设置：

```bash
export CC=/usr/bin/gcc-13
export CXX=/usr/bin/g++-13
```

然后再执行 configure/build。

## 3. 运行项目（CLI）

查看帮助：

```bash
./trade cli --help
```

示例：

```bash
./trade cli collect --action raw --symbol 600000.SH --start 2024-01-01 --end 2024-01-31
./trade cli report --symbol 600000.SH
```

## 4. 运行项目（Web UI）

```bash
./trade setup-python
./trade ui
```

默认会启动 Streamlit：
- 入口文件：`python/app/ui.py`

## 5. 运行测试

```bash
./trade test linux
```

## 6. 情绪新闻源（RSSHub）

当公共 `rsshub.app` 返回 403 时，可在项目内自建 RSSHub：

```bash
cd deployment/rsshub
docker compose up -d
cd ../..
uv run python -m scripts.run_sentiment --date 2026-03-04 --dry-run --rsshub-base-url http://127.0.0.1:1200
```
