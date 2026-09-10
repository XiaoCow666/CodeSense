# CodeSense 前端第三方依赖

这些文件由应用通过同源 `/static/vendor/` 提供，避免用户浏览器访问公共 CDN 时受到 DNS、代理或网络策略影响。

已固定并本地托管的主要依赖：

- `marked.min.js`：Marked 9.1.6，MIT License
- `purify.min.js`：DOMPurify 3.0.6，Apache-2.0 / MPL-2.0 License
- `bootstrap/5.1.3`、`bootstrap/5.2.3`：Bootstrap，MIT License
- `bootstrap-icons/1.10.5`：Bootstrap Icons，MIT License
- `codemirror/5.65.2`：CodeMirror，MIT License
- `jquery/3.6.0`：jQuery，MIT License
- `chart.js/3.9.1`：Chart.js，MIT License
- `chartjs-plugin-datalabels/2.0.0`：MIT License
- `highlight.js/11.9.0`：Highlight.js，BSD 3-Clause License
- `animejs/3.2.1`、`canvas-confetti/1.6.0`、`animate.css/4.1.1`：各自上游许可证
- `ace/1.23.4`、`monaco/0.40.0`：编辑器资源，许可证和第三方声明见对应上游项目
- `fonts/`：Inter 5.3.0、JetBrains Mono 5.3.0、Caveat 5.3.0、Ma Shan Zheng 5.3.1，字体许可证见 `fonts/licenses/`

SortableJS 1.15.0 已复用 `static/lib/Sortable.min.js`。

版本固定在模板或脚本的 URL 查询参数/本地路径中。更新依赖时请同步修改版本号，并重新部署静态文件。
