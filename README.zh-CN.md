# index-lantern 中文说明

检查被 `assume-unchanged` / `skip-worktree` 标记隐藏的文件，逐个比较工作区
原始字节与索引 blob ID。适合切换分支、清理工作树前排查遗忘的本地修改。
不会修改索引、清除标记、执行过滤器或联网。

需要 Python 3.11+ 和 Git 2.43+，无 Python 运行时第三方依赖。克隆仓库后创建并
激活虚拟环境，执行 `python -m pip install .`，然后运行 `python examples/demo.py`。
实际检查用 `index-lantern /你的仓库 --json`。尚未发布到 PyPI，可从本仓库或
GitHub Release wheel 安装。

返回码：0 完整检查且通过，1 发现所选规则的问题，2 检查不完整或输入错误。
`--fail-on flags` 要求没有隐藏标记；`--fail-on none` 只关闭问题门禁，不掩盖检查失败。
跳过且不存在的路径显示 `absent-skipped`，不会把正常稀疏检出当成删除。

`raw-different` 仅说明原始字节不同。换行、编码、ident 或过滤器转换也会产生差异，
不能直接据此断言用户修改，更不能据此删除文件。子模块内容、未跟踪文件和权限变化
不在检查范围。默认单文件上限 64 MiB，总索引条目 100000；停止并发写入以获得
稳定结果。完整限制见英文 README。

卸载：`python -m pip uninstall index-lantern`；随后可删除专用虚拟环境及克隆目录。
