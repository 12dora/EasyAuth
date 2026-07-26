# 质量门禁

## 静态检查边界

Python 静态门禁分为两层：

- `ruff check .` 覆盖仓库内 Python 代码和测试，迁移目录按生成代码处理，不参与风格检查。
- `basedpyright` 覆盖生产运行时代码 `src/easyauth`，保持 `typeCheckingMode = "all"`。

`basedpyright` 不排除本轮整改范围内的普通生产模块。排除项只有：

- `src/easyauth/**/migrations/**`，迁移正确性由迁移门禁验证，而不是由类型门禁替代；
- `src/easyauth/config/settings/deploy.py`，该文件属于用户明确要求不整改的 `EA-AUD-001`
  反代部署路径。

`deploy.py` 的排除只体现本轮范围边界，不代表该部署路径通过质量验收或可以上线。

## 测试和迁移职责

测试代码由 pytest 执行业务回归，并由 Ruff 检查导入、临时路径、危险调用和结构问题。测试中需要临时文件或临时目录时，应使用 pytest 提供的 `tmp_path`、`tmp_path_factory` 或等价动态目录，不应写入固定的系统临时路径。

Django 迁移必须通过两类证据：

- SQLite 快速层执行 `manage.py makemigrations --check --dry-run` 和主后端测试。
- PostgreSQL 层执行真实迁移回放，并覆盖多连接、Redis、broker、租约和 `skip_locked` 等并发语义。

## CI 命令

CI 中的 Python 静态作业必须使用与本地一致的虚拟环境命令：

```bash
.venv/bin/ruff check .
.venv/bin/basedpyright
```

不得通过降低 `typeCheckingMode`、排除整改范围内的普通生产模块、增加宽泛 `noqa` 或扩大
`per-file-ignores` 来制造绿色结果。静态检查失败时，应修复根因；超出当前修复范围的生产类型
错误必须以明确、可审计的范围边界记录。
