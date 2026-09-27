# V1.3 Word 核验

- 最终规范SHA256：`99ac51b9e20e6cd2de80cd3d406d43a2d86938820c37a3dcda1ef922140a6233`。
- 本机Word隐藏、只读打开并导出PDF：44页。未保存或修改V1.1/V1.2。
- 44页全部渲染并通过逐页联系表检查，未发现裁切、文字重叠或内容溢出；文本边界检查0个越界块。
- 四项最终语义、C5重建、SUPERSEDED_BY_V1_3标记和结案声明均已检查。
- V1.1/V1.2固定SHA256验证通过。规范内容完整性亦有pytest检查。
- 本环境没有可用的文档依赖加载器且缺少LibreOffice soffice，使用现有本机Word只读导出与项目内渲染依赖完成核验。
- outputs/v13_render保存复核产物。它们不是新的规则来源。

## Stage 2 恢复后 V1.4 QA

在现有 V1.4 文件上仅修复版本声明及页眉页脚；没有重新制作历史评分正文。V1.1/V1.2/V1.3 原件 SHA256 全部匹配入场基线。

打包 render_docx.py 实际执行失败：环境缺少 soffice.exe，且当前没有可调用的 workspace dependency loader。随后使用现有隐藏 Word 只读导出 PDF，再用 PyMuPDF 导出全部46页 PNG，逐页检查。最新46页均无可见文字裁切、重叠或缺字；页眉页脚已为V1.4。继承正文保留原排版及历史来源/废止标记。渲染文件只用于内部QA。

V1.4 最终 SHA256：8e6ca483e36fcdd3906a7a08aea3cf3471c820d3e0ec4e81c3ede5d4f3409e5f。
