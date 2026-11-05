# 物料台账 / Material Ledger

Windows x64 便携物料台账。支持条码、非挂账物品、服务器管理、Excel 对账和本地操作日志。

- [发布下载](https://github.com/wuzixianhao/material-ledger-updates/releases/latest)
- 从 2.6.0 起，程序默认从本仓库检查更新。既有台账保留在本地 `data/` 目录。
- 仓库仅包含通用源码；不包含个人盘点、台账、备份或导出文件。首次启动为空台账。

## 源码运行和发布

使用带 Tk 的 Python 3.13，在仓库目录运行 `python app.py`。程序将使用源码目录旁的本地 `data/`。

推送到 `main` 会在 Windows runner 上运行测试、打包并保存构建产物，便于验收。
确认准备发布后，修改 `portable.py` 中的版本号，提交并推送匹配的 `vX.Y.Z` 标签。
标签构建通过后，工作流自动把程序 ZIP 和校验文件发布到 GitHub Releases。工作机下次检查时可一键更新。
