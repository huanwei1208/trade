# Trade Web

`trade_web/frontend` 是独立于 `trade_py` 的前端项目。

当前结构：

- `trade_py` / `trade_web`
  提供 FastAPI API、事件流、在线推理和静态托管
- `trade_web/frontend`
  提供 React + Vite 前端

开发方式：

```bash
# 1. 启动后端 API
./trade web --port 8080

# 2. 启动 React 开发服务器
npm --prefix trade_web/frontend run dev
```

默认代理：

- `/api` -> `http://127.0.0.1:8080`
- `/predict` -> `http://127.0.0.1:8080`

构建方式：

```bash
npm --prefix trade_web/frontend install
npm --prefix trade_web/frontend run build
```

构建完成后：

- 产物输出到 `trade_web/frontend/dist`
- `./trade web` 会优先托管 `trade_web/frontend/dist`
- 如果 `dist` 不存在，会回退到旧的 `trade_py/web/static/index.html`

当前目标：

- 用 React 重构控制台
- 让前端和 `trade_py` 解耦
- 保留后端 API 和旧页面兼容层，避免一次性切断现有流程
