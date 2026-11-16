# 官方实体、账户与业务／风险来源

参考入口核查日期：**2026-11-11**。每次任务先依 [source-grounding.md](source-grounding.md) 实际检索并打开相关官方来源，明确主题、业务背景及来源支持的范围；本表不代替本次检索。机构、企业户名、账号、开户行、机构代码和公开规则必须真实，完整对应关系及用途不能改编。公开披露只支持其中明示的事实，不证明账户目前可用、某笔交易发生或付款已获授权。

可以基于已核实业务流程／风险机制改编邮件情节、金额、时间、对话与内部安排，逐项记录 `provenance.grounding.adaptations`；不能伪称原始邮件或真实案件新增事实。改编不允许把真实企业写成已证实的涉案主体，也不能把无关官方账户拼进匿名原案。

情节、转述或翻译改编使用 `provenance.kind: source-adapted`，填写 `provenance.grounding.adaptation_scope`，并将个案变化逐项放入 `provenance.grounding.adaptations`；保留实际原始通信且仅脱敏／节选／非实质排版时才用 `redacted-source`。新批次须通过 `--require-grounding`，详细正文再用 `--require-detailed`。

## 地区、币种和来源版本

默认支持中国大陆的中文日常业务邮件，优先国内银行、税务和电商来源。记录 `business_region: CN`、`transaction_scope: domestic` 和实际币种 `currencies: [CNY]`。美元例需要明确业务依据：有中国参与方的跨境交易标 `cross_border` 并补 `cross_border_context`；境内美元外币业务仍标 `domestic`，用 `currency_context` 解释来源支持的业务和币种用途。不能由美元直接推断境外市场。来源为英文不等于邮件要用英文，来源列有多币种也不扩大本次仅人民币／美元的范围。

邮件正文用“32,480元”“2,450美元”，ISO 代码用于元数据；这些数字仅为格式示意。引用原记录时不改数值，改编个案金额时明确记录。此规则只管金额表达，不能改动下面任何真实户名、账号、空格、开户行或机构代码。公开的内销账户资料不证明该账户可以接收美元或用于跨境结算；缺少相应用途依据时换场景，不擅自给现有账户加外汇用途。

核对来源的发布／更新日期、地区、产品和账户类别。美国帮助页可用于有明确边界的风险模式研究，不能据此安排中国账户的退款、争议处理、自动扣款或费用。具体汇率、手续费、税率和到账时限必须另核适用来源；不把旧数值顺手填入当前邮件，也不将美元金额自行换算成人民币。

正式官方公告可采用合适的正式称谓；机构名称或来源本身是正式文件，不意味着所有同事跟进邮件也要照搬公文腔。按关系选择 `daily_business`、`customer_service` 或 `formal_notice`，规则见 `realism-details.md`。审查旧记录时列出地区／币种／语气／来源版本冲突；用户仅要求优化 Skill 时，不因此重写原语料、示例、金额或账户。

## Public corporate accounts

Source: [康冠官网：银行资料](https://www.ktc.cn/bank.html), publisher 深圳市康冠科技股份有限公司. The source lists these as domestic-sales bank accounts and asks customers to independently confirm account details before payment. Publication date is not shown. These are organization disclosures, not private customer records.

| Account owner | Exact account string | Exact opening-bank name as published | Scope |
|---|---|---|---|
| 深圳市康冠科技股份有限公司 | `4420 1566 4000 5251 9408` | 中国建设银行深圳中心区支行 | 内销银行账号 |
| 深圳市康冠科技股份有限公司 | `40000 305191 0000 2711` | 工商银行深圳坂田支行 | 内销银行账号 |

The second row's source uses the short form “工商银行”; do not fabricate a different branch. Keep the literal bank string when presenting the tuple; the banking institution is 中国工商银行. These disclosures establish the stated account relationships and domestic-sales purpose only. They do not establish any purchase, payment, approval, dispute or wrongdoing in an email. Do not insert either account into an unrelated published case. Any independently adapted context must fit the verified business purpose and be recorded as adaptation, not attributed to an actual incident involving the company.

For new organizations, search the organization's own site for “银行资料 / 对公账户 / 收款账户 / 开票信息”, then read the actual page or official disclosure. Search snippets and account-aggregation sites are discovery aids, not sufficient verification. Check whether the number is a payment account, invoicing-only field, collection account, escrow account or a project-limited account. Carry that restriction into the scene. A registration fee account must not become a shopping refund account.

## Institution codes

Source: [中国工商银行北京市分行：外币汇款路径](https://www.icbc.com.cn/icbc/html/branches/beijing/guanggao/wh_040831/whgg/whhk061218.htm).

- Entity named on the page: 中国工商银行股份有限公司北京市分行.
- Code system: **SWIFT/BIC**.
- Published code: `ICBKCNBJBJM`.
- Supports this branch's published SWIFT identity only. It is **not** a CNAPS number, customer number, the Shenzhen branch's code, or proof of a particular company's banking relationship. This is an older page; revalidate before using contemporary routing facts. Do not reuse the page's intermediary-account numbers as corporate customer accounts.

There is no verified general-purpose customer number/户号 in this register. If a scenario needs one, locate an official public organizational disclosure where that field is explicitly identified; never relabel an account, SWIFT code, company tax ID or order number as 户号. Do not invent a value just to fill the field.

## 统一社会信用代码与行号的核验入口

以下入口于 **2026-11-12** 打开阅读，只提供核验方法或字段含义，本节未新增任何企业信用代码或具体 CNAPS 值。

- [北京市市场监督管理局：统一代码构成](https://scjgj.beijing.gov.cn/zwxx/scjgdt/202407/t20240719_3753300.html)，页面日期 2024-07-18。说明统一社会信用代码为 18 位、包含主体标识及校验部分。格式或校验位符合并不证明生成的值属于某企业；实际值须另核企业官方披露或可查阅的登记资料及对应全称。元数据用 `kind: institution_code`、`code_system: USCC`，`owner` 指向登记主体。
- [中国建设银行：支付系统行号查询](https://ibsbjstar.ccb.com.cn/CCBIS/B2CMainPlat?CCB_IBSVersion=V6&ISSHOWINFO=Y&PT_STYLE=1&SERVLET_NAME=B2CMainPlat&TOOLSVER=3.1.2&TXCODE=418105)。页面分别列示行别、地区、开户网点与支付系统行号，支持按具体网点查对应关系；只打开查询页不等于已核实某个行号。无法获得具体结果时不补造，不以其他网点或总行编号代替。

同一套资料须联合核对企业全称、信用代码、账户户名、账号、开户行及行号；多份来源应证明彼此对应，并与邮件设定的时间相容。母子公司、曾用名、分支机构、代理收款关系需有相应依据。信用代码、税务字段、银行账号、客户号和路由代码按来源真实含义记录，不能为了填满模板互换。见 [现实关系表](reality-contract.md#1-先核对关系再核对字面)。

## Current business context references

| Entity | Official source | Narrow supported use |
|---|---|---|
| 中国建设银行 | [关于取消龙卡信用卡纸质账单服务的公告](https://creditcard.ccb.com/chn/2026-04/30/article_2026043009205242542.shtml), published 2026-04-30 | Describes email statement settings and statement-query channels; paper statements stop from 2026-06-20. Use the applicable date, not an older FAQ's paper-service promise. Does not establish that any customer received an email or completed a transaction; adapted correspondence must be marked as adaptation. |
| 中国工商银行 | [不法分子欺诈的通常手法](https://www.icbc.com.cn/page/721855867900428296.html)，本轮重新打开 | 官方描述冒名邮件以账户冻结／系统升级为借口，引向假网页窃取资料。只支持风险机制；页面无可见发布日期，不能把“近期”解释为 2026 年事件，也不证明新改编邮件由工行发送。 |
| 国家外汇管理局广东省分局 | [2020 年以来跨境诈骗案件通报](https://www.safe.gov.cn/guangdong/2020/0911/1832.html)，页面发布日期 **2020-09-14**，本轮重新打开 | 案例 1 为 2020 年 6 月进口尾款邮件／发票收款资料被篡改；案例 2 为 2020 年 7 月账户／汇款地变更经独立确认被否认。支持历史事件与冒名变更机制，不含真实公司／银行名称、具体账号、金额或完整邮件。可独立改编机制并披露，不能为原案填入康冠、工行等实名或复原所谓原邮件。 |
| 中国工商银行 | [工银融e行个人信息保护政策](https://m.icbc.com.cn/page/721855777227554839.html), effective 2026-06-16 | Establishes the real bank/platform and explains relevant data collection. Do not infer specific support-email procedures or invent a customer's account. |
| 京东 | [售后退款说明](https://help.jd.com/user/issue/130-978.html) | Refund route depends on payment type; online card payment generally returns through the original method, while corporate transfer/cash/check cases differ. Do not turn “generally” into an unconditional rule. |
| PayPal／贝宝支付 | [面向中国大陆用户的 PayPal 全球服务条款](https://www.paypal.cn/portal/paypal-worldwide-services-terms-and-conditions), updated 2026-05-28 | 明确中国大陆用户的服务关系，包含购物退款、自动付款及其条件。仅用于有中国参与方的跨境业务；不能假定某客户已开通所有功能，不自行补收费、汇率或时效。 |
| PayPal（跨境风险补充） | [美国站收款请求骗局说明](https://www.paypal.com/us/cshelp/article/what-are-invoice-scams-and-money-request-scams-on-paypal-help1059) | 仅支持无采购依据的收款请求可被滥用这一风险模式；不是中国账户功能或规则来源，也不把所有 PayPal 请求判为恶意。 |
| 京东 | [物流显示签收但未收到](https://help.jd.com/user/issue/108-385.html) | 支持国内购物中代收／误操作的可能性，以及自营和第三方商品的不同咨询渠道。替代美国购物默认参照，不承诺任何本例一定补发或退款。 |

## 使用与核查

其他主题的一手来源见 [scenario-playbook.md](scenario-playbook.md)。每条记录只引用实际使用的来源到 `provenance.sources`，所有具名组织列入 `provenance.entities`，保留的公开账户／代码完整元组及用途列入 `provenance.identifiers`。主题、现实背景、依据与改编按 [source-grounding.md](source-grounding.md) 记录；`provenance.grounding.adaptations` 明确哪些对话、金额、时间和个案条件是新改编，不能把它们伪装成来源证实的事实。

| 来源类型 | 可以支持 | 不能据此宣称 |
|---|---|---|
| 企业公开账户页 | 来源列明的户名、账号、开户行及用途 | 某笔订单存在、已获批准、该账户涉案、现在仍能收款 |
| 官方业务公告／帮助 | 对应地区、产品、日期的流程和规则 | 任意客户已办理，或机构实际发送了改编邮件 |
| 官方反诈模式说明 | 明确记载的行为机制，作为有依据改编的基础 | 一封未披露邮件的原文、当前具体案件、额外未记载的银行政策 |
| 真实案件通报 | 所记载的历史事实与核实结果 | 未披露的公司、银行、账户、金额、完整对话，或替换后的真实企业涉案 |

SAFE 通报页面日期与 URL 中的日期片段不同，以页面 **2020-09-14** 为发布日期；事件分别按原文的年月记录。ICBC 反诈页无可见日期，不猜发布时间。CCB 公告本轮确认发布 **2026-04-30**、纸质账单服务于 **2026-06-20** 停止；该事实不扩展为其他银行统一规则。上述业务／风险来源可以支撑明确标注的独立改编，不代表提供了完整邮件语料。

资料不足时继续检索；无法核实机构、账户或所需规则／风险机制时少交并说明，不能以改编为由补造这些事实。只提炼必要事实与短小依据，不整篇复制官方材料或私人联系方式。旧 `assets`／语料仅作历史结构参考，不能作为新事实依据；仅优化 Skill 时不改写旧样本。
