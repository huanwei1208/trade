# Config Layout

运行时外部配置只保留一个可选覆盖文件：

- `config/trade.yaml`

如果这个文件不存在，系统会直接使用：

- DB settings
- 迁移导入后的历史默认配置
- 内建默认值

优先级固定为：

`CLI args > ENV > config/trade.yaml > DB settings > built-in defaults`

仓库里保留的：

- `config/trade.yaml.example`：唯一示例文件
- `config/defaults.json`：历史默认值基线，只用于首次导入/恢复
- `config/feeds/*.json`：历史 feed catalog 基线，只用于首次导入/恢复
- `config/modules/*.yaml`：历史模块配置基线，只用于首次导入/恢复

说明：

- `config/trade.yaml` 只做 override，不再作为大而全配置真源。
- 运行时应优先从 DB 读取配置；文件只保留为迁移基线。
- 不应继续新增 `config/modules/*.yaml` 或新的多文件配置族。
