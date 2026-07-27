# 项目协作约定

- 使用中文与用户沟通。
- 每次完成代码或配置修改后，先执行与改动相匹配的测试或检查。
- 验证通过后，必须提交并推送到 GitHub 仓库
  `chaoyuebro/Financial-Statement-Reading` 的 `main` 分支，不要只保留在本地。
- GitHub 推送成功后，必须将最新改动增量同步到 Ubuntu 服务器
  `root@192.168.31.199:/srv/financial-reader`，并验证线上服务。
- 日常更新只同步发生变化的文件，只重建受影响的服务：
  - 仅 Worker Python 代码变化：更新文件并重启 Worker。
  - Web 源码变化：只重新构建并重启 Web。
  - Dockerfile、依赖清单或基础环境变化：才完整重建对应镜像。
  - 数据库迁移变化：先备份，再执行迁移；不得清空现有 PostgreSQL 或 MinIO 数据。
- 优先使用 `scripts/deploy_ubuntu.ps1` 的 Git 提交差异增量部署；依赖清单未变化时，
  Web 构建必须使用 `Dockerfile.web.incremental` 跳过 `npm ci`。
- 部署完成后检查容器状态，并访问 `http://192.168.31.199:3001` 或对应 API
  验证功能；如果同步或部署失败，要明确说明失败阶段，不得声称已完成。
- 报告目录采用“元数据先行”：全历史同步只保存公告元数据和官方 PDF 地址；
  用户打开报告时才下载 PDF，进入智能阅读时才解析、分块和抽取指标。
