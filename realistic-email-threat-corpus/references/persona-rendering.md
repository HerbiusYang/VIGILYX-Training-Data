# 真人感渲染与训练使用

登记新记录、准备训练数据时阅读。写作阶段不加载本页；写作者只需要情境卡中列出的占位符，见 [写作简报](writing-brief.md)。目标是让收件人和检测器看到的邮件像真人或真实系统发出：有姓名和地址、收发时间、回复引用、签名和设备痕迹。同时，公开的语料里没有像真人的个人信息，这些表层特征也不与标签相关。

## 1. 两层数据

| 层次 | 内容 | 用途 |
|---|---|---|
| 规范记录（`data/corpus.json`） | `input` 用占位符表示人物、虚构机构和邮箱；`render` 声明人物关系和发件地址类型；来源、证据和标签照常 | 版本管理、公开发布、`validate_records.py` 校验 |
| 渲染件 | `scripts/render_records.py` 把占位符换成虚构的姓名、公司、域名和邮箱，补齐收件人、时间、回复引用、签名和设备落款，可导出 `.eml` | 训练、评估、网关测试；不提交到仓库 |

`validate_records.py` 只校验规范记录。渲染件含有字面邮箱地址，按设计不能通过它的隐私检查，也不需要再校验；渲染器会核对证据和来源引用在渲染后仍是精确子串，不一致时写入 `rendering.warnings`。

渲染只改表层，不改情节、请求、链接和标签；`[DOMAIN_n]` 等域名令牌除外。渲染器不读取 `target`，人物只由 `--seed`、`thread_family_id`、版本号和令牌编号决定。同一往来链、配对两侧和同一记录的多个版本共用一组人物。

## 2. 占位符

| 令牌 | 渲染结果 | 用法 |
|---|---|---|
| `[PERSON_n]` | 全名，如“刘建平” | 称呼、正文提及 |
| `[SURNAME_n]`、`[GIVEN_n]` | 姓、名 | `[SURNAME_1]总`、`[SURNAME_1]工`、`小[SURNAME_1]`，熟人之间只称 `[GIVEN_1]` |
| `[SIGNATURE_n]` | 按人物习惯生成的签名块，从只署名到含职位、公司、电话分机 | 人工邮件结尾，代替手写的 `[PERSON_1]｜岗位` |
| `[ORG_n]`、`[ORGSHORT_n]` | 虚构机构全称、简称（字号） | 公司、学校、医院；真实机构直接写全称 |
| `[DOMAIN_n]`、`[LOOKALIKE_n]` | 机构域名；由虚构机构域名派生的仿冒域名 | 链接和正文，例如 `https://oa.[DOMAIN_1]/flow/[SLUG_1]` |
| `[EMAIL_n]` | 按 `render.mailboxes` 生成的地址 | 发件、收件、抄送和正文中的地址 |
| `[USER_n]`、`[PHONE_n]` | 登录名；分机、座机、手机或 400 热线 | 可在 `render.users`、`render.phones` 声明归属和类型，默认是中性的登录名和分机 |
| `[ORDER_n]`、`[INVOICE_n]`、`[CONTRACT_n]`、`[TICKET_n]`、`[ADDRESS_n]` 等 | 真实格式的虚构编号和地址 | 订单号、数电发票号、合同号、工单号；其他编号令牌使用通用格式 |
| `[SLUG_n]` | 随机路径或参数片段 | 合成 URL 的路径部分 |
| `[OTP_n]`、`[REDEMPTION_CODE_n]` | 无效验证码、遮盖的兑换码 | 不生成可用的秘密 |

旧语料中的 `[URL_n]` 无法还原，渲染后保持原样，并在 `rendering.defaults` 中标记。

## 3. `render` 声明

```json
"render": {
  "orgs": {
    "ORG_1": {"kind": "fictional", "org_type": "company", "region": "浙江宁波", "industry": "注塑设备制造", "suffix": "塑料机械有限公司"},
    "ORG_2": {"kind": "real", "name": "中国建设银行", "domain": "ccb.com", "source_ids": ["SRC-3"]}
  },
  "people": {
    "PERSON_1": {"org": "ORG_1", "dept": "生产计划部", "title": "计划主管", "gender": "m", "device": "mobile"},
    "PERSON_2": {"org": "ORG_1", "dept": "财务部", "title": "薪资专员", "gender": "f"}
  },
  "mailboxes": {
    "EMAIL_1": {"owner": "PERSON_1", "domain": "org"},
    "EMAIL_2": {"owner": "PERSON_2", "domain": "org"},
    "EMAIL_3": {"owner": "PERSON_1", "domain": "freemail"},
    "EMAIL_4": {"owner": "ORG_1", "local": "hr", "domain": "lookalike"}
  },
  "style": {"formality": "随意", "length": "一两句", "habits": ["手机回复", "口语"]}
}
```

这段只演示字段结构，不是可以照抄的个案。

- **`orgs`。**
  - `fictional`：必填 `region`、`industry`，可选 `org_type`（`company`、`school`、`hospital`）和 `suffix`。不得填写 `name` 和 `domain`，由渲染器生成。
  - `real`：`name` 必须与 `provenance.entities` 中的名称一致并引用来源。需要该机构的邮箱或 `[DOMAIN_n]` 时，`domain` 也须有来源。
  - 政府机关、银行、支付平台和被冒用的品牌都用真实机构，不虚构。
- **`people`。** 不写姓名。`org` 指向 `orgs` 中的机构。`device: mobile` 会在发件人正文后加“发自我的iPhone”一类落款，正文应相应简短。
- **`mailboxes.domain`。** `local` 用于 `hr`、`noreply`、`service` 等角色地址。

| 取值 | 含义 | 正常与恶意中的典型用法 |
|---|---|---|
| `org` | 所属机构的域名 | 同事、合作方的正常往来；也可以是被盗用的账号发出的诈骗 |
| `freemail` | qq.com、163.com 等，可用 `provider` 指定 | 个人或小商户的正常使用；冒充同事、领导 |
| `lookalike` | 虚构机构域名的仿冒变体；真实机构只能用有来源的 `value` | 冒充合作方或内部系统 |
| `external` | 与声称身份无关的其他域名，可用有来源的 `value` | 第三方服务、营销平台；陌生的攻击域名 |
| `observed` | 原件中的实际域名，必填 `value` 并引用来源 | 用户提供的真实邮件、公开威胁情报 |

发件地址关系是检测器在真实邮件中能看到的信号，要按情节如实设定，并让每种关系在正常和恶意两类中都出现。校验器会对当前发件人的地址类型和设备在两类之间明显偏斜发出警告。

`style` 记录 [画像卡](writing-brief.md#3-画像卡)，只供审计，渲染器不使用。

新编批次使用 `--require-render --require-current-year` 校验。

- 每封邮件的 `from` 是含 `[EMAIL_n]` 的对象。
- 当前邮件和往来都提供带时区的 `sent_at`，按时间顺序排列，发送日期落在生成当年 1 月 1 日至当天。
- 当前邮件有收件人。
- 用到的每个人物、机构和邮箱令牌都有声明。

## 4. 渲染与训练使用

```bash
# 训练集：每条渲染 3 个人物版本
python3 scripts/render_records.py train.json --out /path/to/rendered/train.json --name-pool train --variants 3
# 测试集：使用训练中没有出现过的名字和字号
python3 scripts/render_records.py test.json --out /path/to/rendered/test.json --name-pool heldout
# 网关测试：每封一个 .eml，标签只写在 manifest.json
python3 scripts/render_records.py test.json --format eml --out /path/to/rendered/eml --names-report /path/to/rendered/names.json
```

1. **先切分再渲染。** 按 `thread_family_id`、`source_group`、`template_family_id` 划分规范记录，再分别渲染。多个版本共用 `thread_family_id`，不能渲染后再随机切分，否则同一封邮件会换个名字同时出现在训练集和测试集里。
2. **训练时让名字成为噪声。** 训练集渲染多个版本，或每轮训练用不同的 `--seed` 重新渲染。姓名、公司和签名不断变化，模型只能从内容里学习。
3. **检验是否记住了名字。** 测试集用 `heldout` 名字池渲染，再用 `train` 名字池渲染同一测试集。两次指标差距明显，说明模型在记名字。
4. **注意长度上限。** 对 BERT 这类模型，签名、设备落款和引用都会占用 token。把发件人、主题和当前正文放在前面，从末尾的引用部分截断，或用 `--history array` 不展开引用。最好把 `.eml` 送入和线上相同的解析流程，再交给模型。
5. **区分默认值。** 旧记录渲染时用到的默认值记在 `rendering.defaults`。整串往来都缺时间时，渲染器在运行当年 1 月 1 日至当天安排日期。部分缺失时，依据已有的发送时间补齐。例如没有声明的发件地址统一取同一个虚构机构的域名，这类发件关系不代表真实情节，评估时应单独统计。

## 5. 风险与限制

- 虚构的姓名、公司、域名和邮箱可能与真实存在的重合，免费邮箱地址尤其如此。渲染件应写到不受版本管理的位置，不要提交到公开仓库；需要公开时，先用 `--names-report` 的清单查重。
- 生成器避开了常见公众人物姓名和知名机构字号，但名单有限，不能保证完全避开。
- `.eml` 只能注入隔离的测试邮件系统，不得经过能向外投递的 MTA。`X-Corpus-Rendered` 头用于识别渲染件，它在两类标签中一致，不携带标签信息。
- 虚构机构不配银行账号、统一社会信用代码等标识。收款账户仍按 [现实一致性](reality-contract.md) 只用有来源的公开对公账户，否则省略。
- 渲染不会改善内容。读不懂、像说明书或发件人自证的正文，要按 [盲审](blind-review.md) 的反馈重写。
