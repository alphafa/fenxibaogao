# 三笙 AI V9.3.0 当前项目交接

记录日期：2026-10-08（Asia/Shanghai）。这是当前源码与本地完整迁移的说明；9 月 14 日源码发布验收记录继续保留。

## 接手阅读顺序

先读 AGENTS.md、本文和 MIGRATION.md，再看 README.md。从下面的入口追踪代码，不以对话中的结论代替检查。

## 工作流程与入口

1. `extension/` 是完整采集插件；`background.js` 采集并提交服务，`popup.html` / `popup.js` 提供操作界面。`collector-extension-standalone/` 是另一套独立采集扩展。
2. `server/server.py` 提供本地 HTTP 服务、分析任务、图片缓存、生成任务和历史接口。
3. `server/analysis.py` 处理证据规范化和七角色分析；`server/prompt_templates.py` 管理模板。
4. `server/ai_client.py` 调用文字和生图渠道，配置来自本地 config.json；运行依赖为 Python 标准库和项目内模块。
5. `server/report.html` 加载 `report.js` 和 `report.css`。报告 URL 使用 JSON 参数；`renderer.py` 也使用同一前端资源。
6. `/api/report-export/<report_id>` 导出包含图片的离线 HTML；下载文件通常在浏览器下载目录。

## 本地数据

- `server/config.json`：渠道、模型、API Key，不入 Git。
- `server/prompts.json`：自定义模板，存在时一并迁移。
- `server/reports/tmall_*.json`：商品报告。
- `server/reports/generated_img_*.json`：生成任务、结果、提示词及版本链。
- `server/reports/assets/`：缓存图、生成图、上传产品图，必须连同 JSON 迁移。
- `server/monitor_data/`：监测数据。
- `.git/`：提交历史和远端配置。

运行中的任务内存状态、浏览器登录和扩展存储不由复制项目文件夹迁移。等待任务结束后复制；新电脑重新安装扩展并登录商品网站。

## 已确认的产品需求与当前实现

历史弹窗默认铺满窗口，可退出铺满；关闭历史中的预览返回历史弹窗。图片按自然高度显示，版本按时间连续编号，同号旧版本也保留。

重新生成输入非必填。空输入且父结果保存了 prompt 时，服务端复用该字符串；没有保存 prompt 的旧记录仍重新组装。填入新要求时当前代码重新构建并合并要求，不是简单追加到原 prompt。

首次生成的上传产品图 + 参考匹配模式向模型发送两张图：产品图在前、对应采集展示图在后。重新生成此模式目前只发送第一张产品图，采集展示图保留在元数据及文字分析中；`displayReferenceTransport=prompt_only` 标记该行为。因此“prompt 相同”不等于“视觉输入相同”。旧 prompt 还可能描述第二张输入图，存在输入与文字不一致的问题，需要后续明确修复方案和真实出图验证，不能宣称已保证精确参考复现。

产品身份应由上传产品图决定；参考图不应替换商品。没有上传、参考匹配关闭、裂变基准与跟随图等模式分别由 `image_reference_mode`、`_slot_reference_images` 和 `_generation_worker` 控制。重新生成从父任务链恢复模式、产品图和裂变基准。

历史任务有 `_path` 旧电脑绝对路径。部分路径解析有基于 URL 的回退；`_generated_item_data_url` 仍依赖 `_path`，裂变重新生成在新目录下可能找不到基准。迁移验收要单独检查，不应无条件批量修改原始记录。

## 验证记录与边界

2026-10-08 在当前 Mac 运行完整回归：`python3 -m unittest discover -s tests -p 'test_*.py'`，93 项通过。测试主要使用模拟模型响应，不证明真实图片身份或展示一致性。

本次未执行付费生图。新电脑的浏览器采集、真实出图、网络渠道和裂变旧路径仍需迁移后验收。发现失败应记录原始错误和任务 ID，不覆盖历史结果。

## Git 与接手提示

唯一远端 origin：`https://github.com/alphafa/fenxibaogao.git`。历史基线提交 `6f312ff`。本地还包含未跟踪发布包与演示文件，完整迁移应保留；源码推送不等于数据备份。

给新的 AI：先阅读三份交接文档，核对实际代码和文件校验，报告已验证事实与待验证事项。沿用现有模型设定，保留历史数据；只向 fenxibaogao 推送，推送前取得用户授权。

