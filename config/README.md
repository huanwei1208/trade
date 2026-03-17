# Config Layout

运行时外部配置只保留一个可选覆盖文件：

- `config/trade.yaml`

如果这个文件不存在，系统会直接使用：

- DB settings
- `config/defaults.json`
- 内建默认值

优先级固定为：

`CLI args > ENV > config/trade.yaml > DB settings > built-in defaults`

仓库里保留的：

- `config/trade.yaml.example`：唯一示例文件
- `config/defaults.json`：历史默认值基线，后续逐步迁入 DB
- `config/feeds/*.json`：仍在使用中的 feed catalog，后续逐步迁入 DB

说明：

- `config/trade.yaml` 只做 override，不再作为大而全配置真源。
- `config/modules/*.yaml` 已进入退场期，不应继续新增。
