# Mac 完整迁移步骤

适用于自己的另一台 Mac。完整文件夹包含 API Key，请通过自己的移动硬盘或私有传输渠道转移，不上传公共仓库。

## 旧电脑准备

1. 等采集、分析和生图任务结束，并退出本地服务。不要在任务写入文件时制作最终迁移包。
2. 在项目根目录执行 `python3 tools/migration_manifest.py create`，生成 `MIGRATION_MANIFEST.json`。
3. 将整个项目文件夹复制到新电脑，包括 `.git`、server/config.json、server/reports、server/monitor_data 和现有未跟踪文件。Finder 的压缩功能可以制作 ZIP；ZIP 应保存于项目文件夹之外。源文件夹当前约 2.8 GB，目标机器建议预留至少 6 GB 空间。
4. 若复制前有任何文件改变，重新生成清单。清单包含所有普通文件（包括隐藏文件），只排除清单自身。符号链接只核对目标文本，不打包外部目标；工具会报告链接数量，存在外部链接时另行确认目标也已迁移。

## 新 Mac 启动

1. 安装 Python 3.10 或更高版本和 Chrome。执行 `python3 --version` 确认 Python 可用。项目后端不需 npm 或 pip 安装。
2. 解压或复制项目后，进入其根目录执行 `python3 tools/migration_manifest.py verify`。必须返回校验通过；文件缺失、内容变化或多余文件都会报告。先验证，再启动，避免日志写入造成差异。
3. 启动 `start-tmall-ai.command`；也可终端执行 `cd server` 后 `python3 server.py`。终端保持运行。启动脚本无执行权限时使用 `bash start-tmall-ai.command`。
4. 打开 http://127.0.0.1:17962/，检查渠道与模型配置。使用项目附带 cacert.pem；证书问题优先修复 Python 证书环境，不关闭证书校验。
5. Chrome 打开 chrome://extensions/，开启开发者模式，加载新路径的 extension 文件夹。重新登录淘宝/天猫；旧电脑浏览器登录和插件存储不会随项目复制。

## 验收

- 执行 `python3 -m unittest discover -s tests -p 'test_*.py'`；本次旧电脑结果为 93 项通过，新电脑应记录实际结果。
- 打开 /health，确认 ok=true、serverVersion=9.3.0、referenceRoleVersion=20260911-reference-role-fix4。
- 打开旧报告：http://127.0.0.1:17962/report.html?data=/reports/tmall_881261885588_20260918_084841_d57b3.json。
- 核对缓存图、历史批次、不同版本图片、上传产品图和离线 HTML 下载。
- 试采集一个商品并验证新报告保存。付费生图须自己决定是否执行；如执行，要分别验收上传产品图身份、参考展示关系以及旧裂变基准读取。
- 执行 git remote -v，确认只有 fenxibaogao；执行 git status，了解已有未跟踪文件。不要在验收时自动提交配置或报告。

同一报告 URL 可在新 Mac 使用，127.0.0.1 指向使用浏览器的那台电脑。报告 JSON 无需改 URL，但任务内的旧绝对路径可能影响裂变重生成，详见 PROJECT_HANDOFF.md。

文件校验通过只证明复制内容一致。新机启动、浏览器状态和生成效果需按上述步骤另行验证。

