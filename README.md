# VIGILYX-Training Data

[GitHub](https://github.com/HerbiusYang/VIGILYX-Training-Data) · [MIT License](LICENSE) · [语料格式](realistic-email-threat-corpus/references/schema.md)

用于邮件安全检测、分类与防御训练的语料项目，包含 JSON 语料、本地查看器，以及指导智能体检索、改编和验收邮件的 Skill。覆盖个人消费者与工作场景中的钓鱼、身份冒用、BPC（业务流程篡改）和 BEC（商业邮件诈骗），并支持正常对照与证据不足时的独立复核。

默认以中国大陆、自然中文和人民币场景为主。根据真实活动、业务流程或已披露风险机制改编的邮件，不代表实际截获的原始邮件；既有记录也不因收录在本项目中就自动符合最新规则。

当前包含 **5,078 条**样本：4,213 条恶意、865 条正常；中文 4,840 条、英文 120 条、中英双语 118 条。来源类型为 4,704 条 `source-adapted` 与 374 条历史 `synthetic`。这是语料数量与元数据统计，不代表模型检测成绩或对每条来源的重新认证。

## 目录

```text
VIGILYX-Training Data/
├── README.md
├── LICENSE
├── data/
│   └── corpus.json                     # 主语料，UTF-8 JSON 数组
├── corpus_viewer.py                    # 本地邮件语料工作台
├── corpus_catalog.py                   # 全库索引与按需读取
├── corpus_detail.py                    # 邮件、证据与来源展示
└── realistic-email-threat-corpus/
    ├── SKILL.md                        # 生成与维护入口
    ├── references/                     # 场景、来源、格式、分类与随机选题规则
    ├── scripts/
    │   ├── validate_records.py         # 结构、引用和配对等校验
    │   └── test_validate_records.py    # 校验器回归测试
    └── assets/example_pair.json        # 历史结构示例
```

下列命令均在项目根目录 `VIGILYX-Training Data` 中运行。

## 查看语料

需要 Python 3.9 或更新版本，以及桌面图形环境和 `tkinter`。macOS 上使用 Tk 8.6 或更新版本。无需安装额外的 Python 包。

```bash
python3 corpus_viewer.py
python3 corpus_viewer.py ./另一份语料.json --page-size 75
```

默认打开项目内的 `data/corpus.json`，路径相对于脚本定位，从其他目录启动也能找到语料。启动时先显示最新追加的 50 条，再在后台建立全库索引；“最新加入”按 JSON 数组中的追加顺序，与邮件发送时间无关。打开其他文件可用右上角“打开文件…”，语料更新后点击“重新载入”。

- **找样本**：按主题、发件人、正文、往来或样本编号搜索，组合标签、领域、难度和语言筛选。筛选项括号内是全库数量，列表顶部显示当前结果数。
- **审证据**：切换当前邮件、往来历史、标注与证据、来源与改编、原始 JSON。在标注或来源页点击“查看原文”，定位到对应引文。存在配对时可查看两条样本的输入差异。
- **做盲测**：开启后隐藏标签、标签筛选、标注、来源和原始 JSON。先读邮件和往来，再对当前样本点击“揭晓答案”。
- **取分类输入**：在“样本操作”中复制或导出分类输入 JSON，也可单独导出完整记录。邮件和来源中的网址仅作为文本显示。

快捷键：`⌘F`（Windows／Linux 为 `Ctrl+F`）聚焦搜索，`⌘O` 打开文件，`⌘R` 重新载入，`⌘[` / `⌘]` 翻页。选中样本后按 Enter 可聚焦正文。

只检查 JSON 语法、不打开图形界面：

```bash
python3 -m json.tool data/corpus.json > /dev/null
```

记录格式见 [schema.md](realistic-email-threat-corpus/references/schema.md)。分类器只接收 `input`；`target` 保存标签和证据，`provenance` 保存来源及改编说明，均不作为分类输入。

## 使用 Skill 生成或续写

让具备网络搜索和文件操作能力的智能体读取 [SKILL.md](realistic-email-threat-corpus/SKILL.md)，再说明数量、标签范围和输出路径。例如：

> 按 realistic-email-threat-corpus/SKILL.md 生成一批新邮件语料，先交付到 new_records.json。按全部适用场景随机选题，说明实际覆盖、来源、验收结果和待核实项。

Skill 的工作方式：

- 每批新生成都实际调用搜索引擎，打开来源全文并建立情节提纲，再改编成邮件。活动主办方、期次、奖品与资格等事实不能编造；冒名活动的诱因和风险机制也需要实际检索依据。详见 [来源与改编](realistic-email-threat-corpus/references/source-grounding.md)。
- 新编正文使用 `source-adapted` 并记录改动；`redacted-source` 用于忠实保留并脱敏的原始通信。来源规则、原案事实、发件人声称和改编设定分别记录。
- 每批从全部适用场景实际随机抽样，参考近期覆盖减少重复。**国补发放、退税、抽奖／中奖**是重点，其他场景仍有抽中机会；用户明确限定范围时在该范围内随机。详见 [选题规则](realistic-email-threat-corpus/references/topic-selection.md)。
- 品牌、平台或商家面向个人消费者的来信属于覆盖范围，例如消费者收到抽奖邀请或中奖通知；不要求收件人具有员工、采购或财务身份。
- 随机选择可成立的独立邮件或有先前往来的形态。单封邮件可用 `history: []` 并省略 `business_context`，正文须独立交代联系缘由、具体事项、当前请求与后续安排。不得为随机性删掉判定必需的证据。
- BPC 除付款变更外，还覆盖收货／售后状态、退换货工单、交付／提货授权、返利佣金、验收尾款、赊销放货、保险／维修理赔、积分／奖品权益八类流程，详见 [BPC 场景](realistic-email-threat-corpus/references/bpc-scenarios.md)。

标签依据当前输入中可见的行为与业务基准。中奖、截止期限、链接、陌生品牌或新地址本身不决定恶意；证据不足的记录进入独立复核队列，不混入正式训练数组。详见 [分类与复核](realistic-email-threat-corpus/references/classification-quality.md)。

## 校验

检查主语料的格式、标签、证据引用与配对一致性：

```bash
python3 realistic-email-threat-corpus/scripts/validate_records.py data/corpus.json --labels malicious,benign
```

将待验收的新批次另存为 `new_records.json` 后，执行新记录检查：

```bash
python3 realistic-email-threat-corpus/scripts/validate_records.py new_records.json \
  --strict --require-cn-context --require-grounding --require-raw-urls
```

只有明确要求整批详细正文时才加 `--require-detailed`；`--balanced` 用于要求标签均衡的批次，不是默认要求。`--require-raw-urls` 检查新记录没有沿用整条 URL 占位符，不要求每封邮件都含链接。校验器不会访问邮件链接或核实来源网页。

运行校验器回归测试：

```bash
python3 -m unittest discover -s . -p 'test_*.py'
python3 -m unittest discover -s realistic-email-threat-corpus/scripts -p 'test_*.py'
```

校验错误使程序以状态码 1 退出；警告仍需审读。结构检查通过不能证明来源真实、正文自然或标签正确，仍须核对全文来源及可见证据。`assets/example_pair.json` 是历史结构参考，不能直接当作符合最新来源规则的新记录模板；不要为了通过新批次开关而静默改写既有语料。

## 许可

项目采用 [MIT License](LICENSE)。引用的第三方资料及其中的品牌、原文和其他内容，其权益不会因本项目采用 MIT 而自动转为 MIT 授权。
