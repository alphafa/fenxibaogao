# 三笙 AI 项目接手说明

开始工作前阅读 `PROJECT_HANDOFF.md` 和 `MIGRATION.md`，再核对相关代码；文档不是实现正确性的保证。

- 当前源码版本为 V9.3.0，Python 标准库后端，Chrome Manifest V3 扩展。
- 唯一推送仓库：`https://github.com/alphafa/fenxibaogao.git`。默认远端 origin、分支 main。提交或推送需用户明确授权；不要增加其他推送地址。
- 从项目根目录启动：`cd server && python3 server.py`。服务端口 17962。
- 完整回归：`python3 -m unittest discover -s tests -p 'test_*.py'`。JavaScript 语法可用 `node --check server/report.js` 检查；Node 不是后端运行依赖。
- 保留已有模型、渠道和生图模式设定；未经用户要求，不换模型、不触发付费生成。
- 产品图决定商品身份；匹配参考图模式下采集图决定展示方式。不同模式不可混用。当前实现差异和待验证问题见交接文档。
- 保留未跟踪文件和已有改动，不擅自清理历史包、演示文件或报告。
- `server/config.json`、环境文件、报告和图片是本地私有数据。不要输出密钥，不提交到 GitHub。
- 普通 Git 克隆不含历史报告和配置。迁移时按完整本地文件夹处理，不能用源码发布包代替。
- 浏览器操作遵循用户当前授权；可以用代码、测试和本地接口检查代替浏览器验证。

