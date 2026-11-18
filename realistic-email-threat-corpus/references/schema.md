# Schema 2.0 and semantic annotation

Read when creating or validating records. The storage format remains one JSON array. `assets/example_pair.json` contains three historical synthetic pairs for structural reference only. They predate the grounding contract and are not factual sources or compliant new-record templates. Do not rewrite, relabel or append them while maintaining this skill.

## Record fields

| Field | Contract |
|---|---|
| `schema_version` | String `2.0`; activates strict checks |
| `content_profile` | Optional and outside classifier input. Omit it by default: length is decided by the writer from persona and situation and checked in blind review. Use `detailed` only when the user explicitly asks for detailed bodies (length contract below); `concise` remains valid on existing records |
| `id` | Unique opaque string, e.g. `REC-000001`; no label suffix |
| `business_region` | `CN` for new records under this mainland profile; legacy records may omit it |
| `transaction_scope` | `domestic` or `cross_border` |
| `currencies` | Unique list containing only `CNY` and/or `USD`; `[]` for a non-monetary message |
| `cross_border_context` | Nonempty explanation required for cross-border cases, with relevant facts also visible in `input.business_context` |
| `currency_context` | Required for a domestic USD case; explains the actual foreign-currency business rather than inventing a cross-border transaction |
| `register` | `daily_business`, `customer_service` or `formal_notice`; choose by relationship and document type, not by topic or label |
| `domain` | `finance`, `accounting`, `shopping` (including brand/merchant-to-consumer prize activities), or `workplace` for general work accounts, internal access and document sharing outside those domains; classify by the actual matter, not the sender's company name |
| `scenario_type` | Neutral business category, shared by a pair |
| `scenario` | Nonempty neutral description; metadata, excluded from classifier input |
| `language` | `zh`, `en`, or `zh-en`; English acronyms alone need not make Chinese bilingual |
| `difficulty` | `easy`, `medium`, `hard`; reasoning effort on sufficient observable evidence, not label. Missing evidence is a review issue, not `hard`. |
| `thread_family_id` | Shared across the pair and its paraphrases; grouping key for dataset splits |
| `pair_id`, `pair_type` | Optional pair identity and `minimal` or `scenario`; omit both for a standalone record |
| `changed_paths` | For `minimal`, the same list of differing input leaf paths on both members, typically `['/input/current_email/body']` |
| `provenance` | Source attribution, real-entity/identifier facts and declared adaptations; see below |
| `input` | Only material the classifier may receive, in canonical token form; training and testing use the rendered form |
| `render` | Declared people, fictional or real organizations, mailbox relationships, optional users/phones and the writer's style card. Outside classifier input; consumed by `scripts/render_records.py`. Required for new records with `--require-render`; see [persona-rendering.md](persona-rendering.md) |
| `source_group`, `template_family_id` | Optional grouping keys for split isolation, e.g. a real false positive and the benign variants derived from it |
| `target` | Label, evidence and proportionate safe action; never classifier input |

`input` contains `history` (an array, possibly empty), `current_email` (one message), and optionally `business_context` (a neutral string of established facts). Do not put the answer or a threat interpretation into context. A message requires `from`, `subject`, `body`. Sender may be a role string or `{name, role, address}`. Personal names are `[PERSON_n]`; any address is `[EMAIL_n]`. Name parts and signatures use `[SURNAME_n]`, `[GIVEN_n]` and `[SIGNATURE_n]`; fictional organizations use `[ORG_n]`, `[ORGSHORT_n]`, `[DOMAIN_n]` and `[LOOKALIKE_n]`. A record with `render` must declare every person, organization and mailbox token it uses. Recipients `to`/`cc` are arrays of email tokens or similarly anonymized objects. `reply_to` is null or an email token/object. `sent_at` is an ISO timestamp with timezone, optional for legacy records and required on every message under `--require-render`, in chronological order; `attachments` is a list of `{name, type}` metadata, never executable contents. Keep history in narrative chronology unless a documented forwarding structure explains otherwise.

For newly composed mail, `--require-current-year` checks every message's local `sent_at` date against January 1 through the batch run date, inclusive. Source publication dates and the original dates of imported correspondence retain their factual meaning.

A standalone email uses `history: []` and can omit `business_context` entirely; no prior correspondence is mandatory. When available and allowed, context can describe consumer activity/order status as well as workplace facts. Choose eligible topics and input forms using [topic-selection.md](topic-selection.md) before composition, respecting the cross-border/USD constraints below and pair invariants. No new randomization or recipient-type field is required. A standalone email must be understandable from its subject and body alone; its length and form are the writer's judgment ([writing-brief.md](writing-brief.md)) and are checked in [blind review](blind-review.md). Planning constraints for standalone mail are in [realism-details.md](realism-details.md#独立邮件).

This v2 contract defines no attachment-body field. A task that needs readable attachment text must explicitly extend the input contract, extraction provenance, redaction and evidence checks before using it; acceptance of extra JSON keys by the current script is not such validation. Until then, do not insert attachment summaries into the sender's authored `body` or silently use `business_context` to carry them. A sender's own quoted attachment text already present in the actual email remains part of that email.

For newly composed correspondence, `from` is an object whose `address` is an `[EMAIL_n]` token and whose `name` is a person token or the display text a team or system would actually use, consistent with the body's voice and signature. `current_email.to` lists at least one recipient. Plain role strings such as “生产计划｜[PERSON_1]” remain only in legacy records. A workflow label is not automatically a sender identity. What a message contains (greeting, background, sign-off) is the writer's judgment as that sender; human messages sign with `[SIGNATURE_n]` when the sender would sign. A short reply needs an actual prior turn. Preserve source-retained fragments honestly. These are semantic matters checked in blind review, not JSON fields or keyword checks; post-review coherence checks are in [realism-details.md](realism-details.md#5-连贯性与格式核对).

Automated account/security notices can use a brief card or table, button text and service footer, with `formal_notice` where appropriate. Do not add a personal sign-off or a long business narrative to satisfy human-mail conventions. See [system notices](system-notices.md). Unknown source display text is a claimed identity, not a verified entity. Personal login/usernames use `[USER_n]`; use consistent tokens across labels and threads.

Use `[PHONE_n]`, `[ORDER_n]`, `[INVOICE_n]`, `[CONTRACT_n]`, `[TICKET_n]`, `[ADDRESS_n]` and `[SLUG_n]` for private, unnecessary or case-specific details. These tokens preserve repeated-object relationships and must not encode label words such as `MALICIOUS`. The renderer turns them into realistic-format fictional values, so write the surrounding sentence as a person would (“订单 [ORDER_1] 已签收”), not as a placeholder description. Public sourced bank accounts/customer numbers/institution codes are retained exactly; `[ACCOUNT_n]` and `SYN-ACCT` are not accepted for new records.

New records retain sourced literal mail URLs and known QR destinations, including their original structure and display-text/target relationship, inside the allowed message text. They are not replaced wholesale with `[URL_n]`. Keep research-source URLs in provenance distinct from mail targets; do not invent a target, add a new unvalidated link field, or infer page contents. Personal names, addresses/usernames and authentication secrets embedded in a URL receive only the necessary segment replacement, with the change disclosed outside input. Preserve the remaining URL. See [raw links and identity handling](reality-contract.md#2-链接保留原文个人信息分开处理). Historical URL tokens remain compatible by default. `--require-raw-urls` rejects URL tokens in new input, but does not require a URL to be present or establish authenticity. Literal email addresses still require anonymization. Validation never fetches mail targets.

## Observation scope and external verdicts

Declare the classifier's actual input scope and decision time in the batch plan/report: current message, thread, or message plus available business context. This is a workflow contract, not a new required v2 field. A current-message-only batch cannot rely on hidden history or added context; existing cross-border/USD requirements below necessitate context-assisted input. Do not add future page behavior to an earlier email's context. Reassess label support after personal-data redaction; historical tokenized links do not preserve the original destination, and retained URLs do not reveal unseen page behavior.

For original-message classification, exclude confirmed gateway/client verdicts and appended warnings such as “检测结果：垃圾邮件” from `input`, retaining their existence and preprocessing in provenance or processing notes. There is no spam label. Advertising alone is not evidence: genuine marketing from real merchants is `benign`, while inducement that uses deception or illegal services as bait (fake diplomas or certificates, task-scam jobs, stock tips, loan cash-outs, gambling referrals, fake prizes) is `malicious`. If the target is a quarantine summary, warning or forwarded report, interpret its own communicative act and distinguish quoted content. Unresolved layering or missing evidence belongs in the separate review queue. These semantic checks are described in [classification-quality.md](classification-quality.md) and are not enforced by the current validator. A retained URL supplies its visible structure, not unseen landing-page behavior or proof of present control; maintain the observation boundary.

## Mainland/currency contract and natural Chinese

`--require-cn-context` requires the mainland fields on every checked record. Presence of any new business-region/transaction/currency field also activates the contextual checks. Older records with none of these fields remain compatible; the option audits them without rewriting anything. The classifier still receives only `input`, not this metadata.

Dollar amounts require a meaningful business explanation and nonempty `input.business_context`. Cross-border cases require `cross_border_context`; legitimate domestic USD business requires `currency_context`, for example a source-supported foreign-currency deposit service. Explain the mainland participant and actual business relationship; do not simply write “uses USD”. Both pair members have the same business region, scope, currency list, currency/cross-border context and register. A currency switch can be a semantic issue within the supported CNY/USD setting, but must be explained by visible evidence, not resolved by changing the source amount.

Currency scanning checks input and annotations, excluding raw URL spans and research-source descriptions. A query/path segment is not itself a prose amount; this exclusion is not permission to conceal material pricing in a URL. Amounts visibly expressed in the record must be included in `currencies`. New records exclude unsupported currencies and reject code-adjacent money expressions such as `USD 100` or `100 USD`. Chinese and mixed-language mail uses “100美元”, “2,450元” or “人民币2,450元”; do not use a bare dollar sign. Explicitly requested English correspondence can use natural English currency expressions in an adequately specified context. Codes such as `CNY` and `USD` remain valid in metadata. Account numbers and SWIFT identifiers are not monetary amounts.

Choose `register` according to the relation and document type. New messages default to natural, complete, professionally courteous writing, with the user's requested formality applied across registers. Daily colleague/vendor follow-up can use plain language without becoming abrupt; service replies use appropriate courtesy; formal notices retain their proper written register. The validator can check the enum and pair consistency, not whether the wording sounds natural. Do not introduce rigid word bans for “您” or “谢谢”; manually review appropriateness and repetition.

Keep money precision meaningful. Use integer yuan when cents are zero and irrelevant, retain cents for reconciliation, and never round away a decisive difference. Do not add currencies, invent FX rates or convert previous records during formatting. Rates, dates, currencies and bank-account purposes require source/context review, not a regex-based claim of business validity.

## Detailed-body acceptance

For `content_profile: detailed`, the authored current body must contain at least **350 Chinese characters (`zh`), 220 English words (`en`), or 350 mixed units (`zh-en`, Chinese characters + twice the English word count)**. Count after stripping quotations, identity tokens, numbers, common greeting/signature/footer material and duplicate paragraphs; history, subject and business context do not contribute. Keep appropriate greetings and signatures even though they do not count. These heuristics do not prove meaningful detail; [blind review](blind-review.md) decides whether the length serves the recipient.

`--require-detailed` requires this profile on all checked records. Use it only when the user explicitly asks for detailed bodies, and then state the length requirement in the situation card. Any record marked `detailed` receives the minimum-length check even without the flag. When content is insufficient, report the gap instead of adding unrelated subplots to pass a count. Detailed pairs share a profile and should have comparable substantive lengths. Large differences or unusually long bodies trigger review warnings. Preserve the form and length of source excerpts. Add case detail to adapted emails only when the researched process supports it.

## Provenance

New records use `kind: redacted-source` for actual communication or `source-adapted` for paraphrase, translation, format changes or researched scenario adaptation. A supplied original email is cited as a source with `origin: user_supplied`; it needs no URL. A real detector miss carries `provenance.detector_feedback` with `detector`, `observed_verdict`, `observed_at` (YYYY-MM-DD), `outcome` (`false_positive` or `false_negative`) and `review_basis`; it is allowed only on `redacted-source`, the label must be the reviewed truth (`benign` for a false positive, `malicious` for a false negative), and the verdict never enters `input`. See [feedback-and-benign.md](feedback-and-benign.md). Record each verified named organization and its supported role in `provenance.entities`, including a real organization whose identity is being misused. Unverified service/display wording in supplied messages remains a sender claim with its uncertainty recorded; do not invent an entity source for it. Role-only emails with no named organization can use `entities: []`. Historic `synthetic` records keep their `synthetic_scope` and remain inspectable without `--require-grounding`. `source` remains a legacy-only kind.

Illustrative source/entity fragment (not a complete record; add grounding as specified below):

```json
{
  "kind": "source-adapted",
  "entities": [
    {"name": "Exact real organization name", "role": "account owner", "source_ids": ["SRC-1"]}
  ],
  "sources": [
    {"id": "SRC-1", "title": "Official source title", "publisher": "Publisher",
     "url": "https://official-source.example/page", "accessed_at": "2026-11-11",
     "roles": ["entity"],
     "supports": "Precisely which entity or account tuple this page establishes"}
  ]
}
```

This block is notation, not a verified source to reuse; the placeholder URL cannot serve as evidence. Sources may additionally contain `published_at`, `effective_at`, `jurisdiction` and a page/section locator. If a named parent bank and opening branch both appear, record both or identify their documented relationship. An official platform rule does not establish a particular merchant exception or prove an email was sent. An entity-only fragment cannot satisfy the material-source gate. Research public material relevant to the task; do not collect personal contact lists.

For each retained financial identifier add:

```json
{
  "kind": "bank_account",
  "value": "Exact source value, preserving formatting used in the record",
  "owner": "Verified corporate account holder",
  "bank": "Exact opening branch from the same disclosure",
  "usage_scope": "Documented currency and business purpose",
  "basis": "official_public",
  "source_ids": ["SRC-1"]
}
```

Place these objects in `provenance.identifiers`. `kind` is `bank_account`, `customer_number`, or `institution_code`. For bank accounts, `owner` and `bank` are required and both must appear in `provenance.entities`; customer numbers require their owning entity. Institution codes require the owning entity and additionally record `code_system` (e.g. `SWIFT/BIC`, `CNAPS`, or `USCC` for 统一社会信用代码) and the entity/branch identified. USCC ownership refers to the exact registered organization, not its bank; a bank routing code refers to its documented bank/branch, not the customer. Do not treat these code systems as interchangeable. `basis` is `official_public` for researched official disclosures or `user_authorized_source` for material explicitly supplied/authorized by the user. The default research route is official public corporate information.

Preserve exact values across input and metadata. The validator exempts only exact declared strings from numeric heuristics when their source references are structurally valid; this cannot exempt private email addresses or disguise a URL as a bank/code value. Literal mail URLs are allowed by their own rule, not by identifier exemptions. This is not proof that an identifier is real: the author must read the source and jointly verify owner, bank/branch, code system, purpose, value and applicable period. Recheck older disclosures at generation time. Do not fabricate a customer number when a source supplies only an account number. Personal financial identifiers are not sourced from open-web people searches. Required relationship checks are in [reality-contract.md](reality-contract.md#1-先核对关系再核对字面); no new identifier enum or claim of automated business verification is introduced.

## Source-grounding contract

Read [source-grounding.md](source-grounding.md) before research or composition. **Mail scenarios may be adapted; institutions and accounts must be real.** `--require-grounding` requires schema 2.0 and this contract. Checks also activate when `provenance.grounding` is present or kind is `source-adapted`. Existing `redacted-source` data without grounding remains backward-compatible only when this flag is omitted. New batches must always use the flag.

Every source entry has nonempty `roles`, chosen from `material`, `context`, `entity`, `policy`. Material supports the actual communication, business process or risk mechanism used for the record; a homepage/account listing alone is insufficient. A process or incident page may carry multiple roles when justified. Role labels do not establish authenticity or relevance.

`provenance.grounding` is an object with these fields:

| Field | Contract |
|---|---|
| `theme` | Nonempty specific business theme derived from research, not only a domain/label |
| `context` | Object with nonempty `region`, `period`, `setting`. For newly composed mail, the first four-digit year in `period` is the year of the correspondence. A referenced tax or billing period can follow. |
| `source_material` | Object with `type`: `email`, `email_thread`, `official_notice`, `case_report` or `business_document`; nonempty `source_ids` referencing existing sources, including a `material` source. Type describes the actual source, not the adapted output. A help/process page is a business document. |
| `retrieval` | Object with nonempty string array `queries` (actual executed searches) and `searched_at` as `YYYY-MM-DD`; no fabricated research log. Omit it only when every source is `origin: user_supplied` |
| `transformations` | Nonempty array from `anonymization`, `faithful_paraphrase`, `translation`, `format_adaptation`, `excerpt`, `scenario_adaptation`; list operations actually performed |
| `adaptation_scope` | Required nonempty string for `source-adapted`; explain wording/case changes and their limits, without implying actual correspondence |
| `fact_map` | Array of verified-fact mappings. May be empty for a declared `source-adapted` scenario with no independently asserted source facts and valid material-based adaptations covering each required input field. |
| `adaptations` | Required nonempty array when `scenario_adaptation` is used; any nonempty adaptation list requires that transformation. Omit when no case facts were designed/changed. |

Each `fact_map` entry contains nonempty strings:

| Field | Meaning |
|---|---|
| `input_path` | JSON Pointer to a string within `/input` |
| `input_quote` | Exact nonempty substring of that input string |
| `source_id` | Existing source ID |
| `locator` | Reproducible section/paragraph/page location in the source |
| `source_claim` | Narrow, faithful statement of what the source establishes; never a designed transaction, amount or dialogue |

Each `adaptations` entry contains `input_path` and `input_quote` with the same exact-match rules, a nonempty `basis_source_ids` array referencing existing sources with at least one selected material source, and nonempty `change` and `reason` strings. `change` identifies the designed/changed case fact; `reason` ties it to the researched process/risk mechanism. `source_claim` is prohibited in an adaptation entry. Do not use this mechanism to invent or alter real institutions, account values, bank relationships, codes or institutional policies. Meaning-preserving paraphrase/translation alone does not require a scenario adaptation.

For `redacted-source`, only anonymization, excerpt and non-substantive format changes are valid. `faithful_paraphrase`, `translation`, `scenario_adaptation` or nonempty `adaptations` require `source-adapted` instead.

Every current/history body needs at least one valid fact mapping to a selected material source or an adaptation entry with such a basis. Any present `input.business_context` also needs mapping coverage. A fact mapping there may use a context, policy or entity source. Keep the fact map nonempty for retained or paraphrased material. Cite all verified facts that are asserted in an adapted scenario. An empty fact map still requires a material source with exact-quote adaptation coverage for each body and any context.

These are structural minimums, not permission to leave other claims unreviewed. Manually review all material facts in subjects, roles, attachments, messages and business context. Distinguish source facts from allowed adaptations; inspect entity/account/policy exactness separately. The validator does not browse or prove searches occurred, source claims are true, changes are reasonable, or every factual clause is covered. Actual verified-source review is mandatory.

## Target and evidence

`target.label` uses `malicious` or `benign`, or the user's configured equivalents. It identifies the semantic behavior of the current email, not the character of a named organization/account. Evidence is a nonempty list of objects:

```json
{
  "code": "approval_path_bypass",
  "detail": "Explains how the requested action conflicts with the prior approval.",
  "spans": [
    {"path": "/input/history/0/body", "quote": "Exact text establishing the prior decision"},
    {"path": "/input/current_email/body", "quote": "Exact text requesting the deviation"}
  ]
}
```

Paths are JSON Pointers into string fields under `input`; quotes must be nonempty exact substrings. Use multiple spans for cross-message relationships. Quote existence is mechanical; entailment is reviewed separately. `target.safe_action` is a nonempty proportionate response. Avoid declaring an invoice paid from a payment-request email alone, or treating a sender's assurance as verified authorization. Business errors, security incidents described by a legitimate alert, and an outside spam verdict do not automatically make the message malicious. Insufficient evidence cannot be labeled benign merely by absence of an obvious threat. Use the [separate review queue](classification-quality.md#5-复核队列的交付约定): no `target.label`, no fabricated v2 fields, no merge into corpus and no validation with this training-record script. Resolve and validate a full record before promotion.

The sender never supplies the analysis. Writers receive the sender's situation and private intent, not the label ([writing-brief.md](writing-brief.md)), so a fraudulent sender gives a plausible reason instead of explaining the attack; an independent reader checks this in [blind review](blind-review.md). Evidence comes from the request itself and its conflict with visible baselines, preferably the passages the blind reader quoted, never from a confession written for the label.

For phishing or impersonation, cite the actual request and its effect or conflict. For business-process manipulation, quote the approved or observed baseline and the divergent instruction or record when both are required. Later investigation and hidden landing-page behavior may substantiate provenance. The training label must also have evidence visible at the modeled decision time.

| Code | Required semantic observation |
|---|---|
| `payment_route_change`, `refund_route_change` | Proposed route differs from the established route in a consequential, unsupported way; change alone is not enough |
| `credential_or_mfa_request` | Requests transfer/disclosure of a credential or code; distinguish from entering it within the user's legitimate authentication flow |
| `approval_path_bypass` | Requests action inconsistent with a visible approval condition or authorized amount |
| `transaction_mismatch` | Amount, item, beneficiary obligation or payment status conflicts with established transaction facts |
| `unsupported_charge_claim` | Asserts a debit/obligation unsupported by, or contradictory to, the visible payment status |
| `advance_fee_request` | Introduces an unsupported upfront payment as a condition for refund/benefit |
| `excessive_data_request` | Requested disclosure exceeds the specific visible business need |
| `history_contradiction`, `timeline_conflict` | Cite both the earlier fact and current incompatible statement |
| `channel_shift`, `secrecy_request` | Explain the resulting loss of authorization/verification, not merely use of another channel or confidentiality |
| `unexpected_link_or_attachment` | Explain the anomalous requested action or document purpose; a link/file alone is insufficient |
| `process_consistent`, `expected_next_step`, `matches_prior_reference`, `verification_via_known_channel` | Visible positive support for the requested action within the established business state |

Do not use `sender_domain_mismatch`, `reply_to_mismatch`, `display_name_mismatch` or identity-only `sender_consistent` as decisive semantic evidence. Mailbox relationships declared in `render` become visible after rendering and may be mentioned in `detail` as supporting context, but each relationship must occur under both labels and cannot decide a label alone. All four are rejected by v2 validation and retained only for legacy vocabulary compatibility. Unknown codes are errors in v2 (warnings in legacy); use `--extra-codes code_a,code_b` after deliberately defining the extension.

## Pair and split invariants

Pairs are optional. Rendering seeds people and organizations by `thread_family_id`, so pair members receive identical names; keep their `render` declarations identical except for a deliberately changed mailbox relationship, which then appears in `changed_paths` (for example `/input/current_email/from/address`). A complete pair has exactly two records, one per configured binary label, equal history/business context, scenario/domain and real-entity set. A singleton is a warning to support odd-sized requests. Identical `input` with opposing labels is an error across the entire dataset. Minimal pairs declare exactly the differing input leaf paths; history/context cannot be changed between members to manufacture a label. Source-adapted pairs may design a semantic contrast within a researched workflow and documented risk mechanism; both members record their adapted context and changes. Do not infer that either adapted message was actually sent. Label balance never justifies an unsupported plot or fake institution/account.

A benign/malicious/needs-review comparison is an audit grouping, not a three-member pair. Context-changing comparisons use standalone records; keep their source/template/thread relationship for split isolation. Review candidates are outside this schema until resolved, and retain those grouping relationships on promotion. Normal hard cases, unresolved cases and behavior-stage changes are audited under [classification-quality.md](classification-quality.md).

Store optional `source_group` or `template_family_id` when needed to keep related records together. Group splitting must include these relationships, not just `pair_id`. Statistical leakage summaries inspect only a few surface features; reviewers must also check entity/account correlation, template repetition, semantic evidence and input/answer separation.
