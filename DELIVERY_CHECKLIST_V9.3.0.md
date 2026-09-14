# 三笙 AI V9.3.0 交付验收记录

- 交付日期：2026-09-14
- 交付形态：源码便携版；不包含个人 API Key、`server/config.json`、日志、报告缓存或历史发布目录。
- 版本一致性：`VERSION.txt`、两个浏览器扩展、服务端和分析引擎均为 `9.3.0`。
- 自动化回归：`python3 -m unittest discover -s tests -p 'test_*.py' -v`，`66/66` 通过。
- 本地冒烟：健康接口返回 `ok=true`、`serverVersion=9.3.0`、`referenceRoleVersion=20260911-reference-role-fix4`，配置错误为空；首页和报告页面可访问。
- 压缩包校验：ZIP 完整性检查通过；包内未发现 `config.json`、日志、报告缓存或 `.DS_Store`。

## Windows 说明

当前环境为 macOS，不能生成可运行的 Windows EXE。Windows 便携版请在 Windows 10/11 上使用包内 `build-windows.ps1` 构建，并按 `WINDOWS_EXE_BUILD_GUIDE.txt` 验收。
