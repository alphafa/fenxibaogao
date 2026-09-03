# V9.2.3 版本一致性修复

- 修复主扩展 `manifest.json` 已是 9.2.2，但 `popup.js` 仍固定校验 9.2.1，导致错误提示“插件 9.2.1 / 后端 9.2.2”。
- 统一主扩展、standalone 扩展、capture-extension、后端、AI client、analysis engine、renderer、启动脚本、VERSION 为 9.2.3。
- 保留 V9.2.2 图片归一化与图片缓存修复。
- 新增版本一致性自检。
