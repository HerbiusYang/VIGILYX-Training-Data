#!/usr/bin/env python3
"""Render canonical corpus records into realistic, human-looking emails.

Usage: python3 render_records.py corpus.json --out rendered.json
       [--format json|eml] [--seed N] [--variants K] [--name-pool all|train|heldout]
       [--history both|array] [--ids ID1,ID2] [--names-report names.json] [--no-marker]

Canonical records keep tokens such as [PERSON_1], [ORG_1] and [EMAIL_1]. This
script replaces them with fictional people, organizations and mailboxes, adds
dates, recipients, quoted reply chains, signatures and device footers, and can
write MIME .eml files. Undated threads use the local run date as their upper
bound. Persona choices depend only on --seed, thread_family_id (or id), the
variant number and the token name. target is never read while they
are chosen, so names cannot encode the label, and pair members and variants of
one thread share the same people and organizations.

Rendered names, companies, domains and mailboxes are fictional but can coincide
with real ones. Review --names-report before publishing rendered output, and
inject .eml files only into an isolated test mail system. Records without a
render object use neutral defaults listed in each output's rendering.defaults.
Standard library only; nothing is fetched or sent.
"""
import argparse
import copy
import hashlib
import html
import json
import random
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from email.headerregistry import Address
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
from pathlib import Path

TOKEN_RE = re.compile(r"\[([A-Z][A-Z_]*)_([1-9][0-9]*)\]")
PREFIX_RE = re.compile(r"^\s*((?:(?:回复|答复|转发|Re|RE|re|Fw|FW|Fwd|FWD|fwd)\s*[:：]\s*)+)")
FORWARD_RE = re.compile(r"^\s*(?:转发|Fw|FW|Fwd|FWD|fwd)\s*[:：]")
CST = timezone(timedelta(hours=8))
NUMBERED = re.compile(r"(?:PERSON|ORG)_[1-9][0-9]*")


def pairs(text):
    return [(item[0], item[1:]) for item in text.split()]


# Common surnames in rough frequency order; pinyin is the email-local-part form.
SURNAMES = pairs(
    "王wang 李li 张zhang 刘liu 陈chen 杨yang 黄huang 赵zhao 吴wu 周zhou 徐xu 孙sun 马ma 朱zhu 胡hu "
    "郭guo 何he 林lin 罗luo 高gao 郑zheng 梁liang 谢xie 宋song 唐tang 许xu 韩han 冯feng 邓deng 曹cao "
    "彭peng 曾zeng 肖xiao 田tian 董dong 袁yuan 潘pan 蒋jiang 蔡cai 余yu 杜du 叶ye 程cheng 苏su 魏wei "
    "吕lv 丁ding 任ren 沈shen 姚yao 卢lu 姜jiang 崔cui 钟zhong 谭tan 陆lu 汪wang 范fan 金jin 石shi "
    "廖liao 贾jia 夏xia 韦wei 付fu 方fang 白bai 邹zou 孟meng 熊xiong 秦qin 邱qiu 江jiang 尹yin 薛xue "
    "闫yan 段duan 雷lei 侯hou 龙long 史shi 陶tao 黎li 贺he 顾gu 毛mao 郝hao 龚gong 邵shao 万wan "
    "钱qian 严yan 武wu 戴dai 莫mo 孔kong 向xiang 汤tang 常chang 温wen 康kang 施shi 牛niu 樊fan 葛ge "
    "邢xing 安an 齐qi 易yi 乔qiao 伍wu 庞pang 颜yan 倪ni 庄zhuang 聂nie 章zhang 鲁lu 岳yue 翟zhai "
    "殷yin 詹zhan 申shen 欧ou 耿geng 关guan 兰lan 焦jiao 俞yu 左zuo 柳liu 甘gan 祝zhu 包bao 宁ning "
    "尚shang 符fu 舒shu 阮ruan 柯ke 纪ji 梅mei 童tong 凌ling 毕bi 季ji 裴pei 霍huo 涂tu 苗miao 谷gu "
    "盛sheng 曲qu 翁weng 冉ran 骆luo 蓝lan 路lu 游you 辛xin 靳jin 管guan 柴chai 鲍bao 喻yu 祁qi")
GIVEN_M = pairs(
    "伟wei 强qiang 磊lei 军jun 勇yong 杰jie 涛tao 斌bin 超chao 明ming 刚gang 平ping 辉hui 鹏peng 华hua "
    "飞fei 鑫xin 波bo 宇yu 浩hao 凯kai 健jian 俊jun 帆fan 旭xu 宁ning 龙long 林lin 阳yang 建jian "
    "国guo 志zhi 文wen 海hai 东dong 永yong 振zhen 晨chen 博bo 毅yi 峰feng 立li 新xin 亮liang 成cheng "
    "嘉jia 子zi 天tian 昊hao 庆qing 春chun 光guang 晓xiao 云yun 松song 青qing 维wei 培pei 学xue 剑jian "
    "思si 远yuan 洋yang 晖hui 彬bin 泽ze 铭ming 轩xuan 睿rui 哲zhe 航hang 鸿hong 家jia 德de 荣rong "
    "兵bing 锋feng 江jiang 继ji 宏hong 顺shun 祥xiang 安an 胜sheng 坤kun 敬jing 诚cheng 方fang 翔xiang "
    "君jun 驰chi 皓hao 逸yi 楷kai 骏jun 岩yan 晟sheng 煜yu 鸣ming 韬tao 赫he 瀚han")
GIVEN_F = pairs(
    "敏min 静jing 丽li 艳yan 娟juan 霞xia 芳fang 燕yan 婷ting 雪xue 慧hui 琳lin 晶jing 颖ying 洁jie "
    "玲ling 倩qian 萍ping 红hong 梅mei 莉li 欣xin 悦yue 佳jia 雯wen 璐lu 瑶yao 怡yi 楠nan 蕾lei "
    "薇wei 晓xiao 春chun 月yue 秀xiu 文wen 思si 雨yu 诗shi 梦meng 婧jing 涵han 莹ying 露lu 丹dan "
    "彤tong 妍yan 琪qi 媛yuan 菲fei 蓉rong 凤feng 兰lan 青qing 云yun 茜qian 珊shan 琦qi 岚lan 晴qing "
    "宁ning 嘉jia 心xin 可ke 馨xin 欢huan 冰bing 珍zhen 娜na 玉yu 婉wan 素su 琴qin 蓓bei 茹ru "
    "瑾jin 清qing 子zi 一yi 艺yi 依yi 语yu 若ruo 芸yun 舒shu")
# Common two-character given names; single characters below supply one-character given names.
NAMES_M = [(n[:2], n[2:]) for n in (
    "建国jianguo 志强zhiqiang 俊杰junjie 浩然haoran 宇航yuhang 文博wenbo 晓东xiaodong 海涛haitao 建华jianhua "
    "立新lixin 国强guoqiang 永刚yonggang 明轩mingxuan 天宇tianyu 博文bowen 思远siyuan 鹏飞pengfei 晨阳chenyang "
    "子轩zixuan 宇轩yuxuan 浩宇haoyu 俊豪junhao 志明zhiming 建军jianjun 振华zhenhua 文杰wenjie 海波haibo 立军lijun "
    "卫东weidong 建平jianping 永强yongqiang 少华shaohua 宏伟hongwei 家豪jiahao 泽宇zeyu 一鸣yiming 明杰mingjie "
    "志伟zhiwei 春雷chunlei 晓峰xiaofeng 德明deming 国庆guoqing 学文xuewen 正阳zhengyang 凯文kaiwen 锦程jincheng "
    "亚军yajun 振宇zhenyu 晓光xiaoguang 金龙jinlong 海军haijun 光明guangming 伟东weidong 俊峰junfeng 世杰shijie "
    "东升dongsheng 新宇xinyu 启航qihang 子健zijian 皓轩haoxuan 铭宇mingyu 远航yuanhang 子墨zimo 梓豪zihao").split()]
NAMES_F = [(n[:2], n[2:]) for n in (
    "晓燕xiaoyan 丽娟lijuan 秀英xiuying 雅婷yating 欣怡xinyi 梓涵zihan 诗涵shihan 婉婷wanting 雨涵yuhan 佳怡jiayi "
    "思琪siqi 静怡jingyi 晓丽xiaoli 红梅hongmei 玉兰yulan 海燕haiyan 春梅chunmei 雪梅xuemei 丽华lihua 美玲meiling "
    "慧敏huimin 婷婷tingting 晶晶jingjing 文静wenjing 佳琪jiaqi 梦瑶mengyao 一诺yinuo 欣妍xinyan 雨欣yuxin 可馨kexin "
    "子萱zixuan 思雨siyu 晓婷xiaoting 丽萍liping 桂英guiying 秀兰xiulan 淑芬shufen 丽红lihong 艳红yanhong 晓敏xiaomin "
    "雪莹xueying 嘉欣jiaxin 心怡xinyi 佳慧jiahui 静雯jingwen 雅琴yaqin 海霞haixia 秀梅xiumei 金凤jinfeng 春燕chunyan "
    "丹丹dandan 莉莉lili 倩倩qianqian 雨桐yutong 若曦ruoxi 梦琪mengqi 安琪anqi 雅静yajing 晓雯xiaowen 玉梅yumei").split()]
TRADE = pairs(
    "恒heng 泰tai 瑞rui 丰feng 嘉jia 禾he 启qi 衡heng 沐mu 川chuan 拓tuo 辰chen 澜lan 岳yue 锦jin "
    "宏hong 远yuan 卓zhuo 越yue 致zhi 诚cheng 博bo 达da 星xing 辉hui 弘hong 毅yi 立li 科ke 汇hui "
    "润run 通tong 明ming 德de 盈ying 鑫xin 凯kai 源yuan 晟sheng 昊hao 翔xiang 睿rui 峰feng 正zheng "
    "聚ju 方fang 宇yu 舜shun 祥xiang 富fu 雅ya 朗lang 沃wo 腾teng 骏jun 崇chong 鼎ding 盛sheng "
    "煦xu 屹yi 曜yao 柏bai 楷kai 琦qi 霖lin 澄cheng 坤kun 森sen 浩hao 杉shan 桐tong 韵yun 衍yan")
# Public figures and well-known institutions that random combinations could reproduce.
NAME_BLOCKLIST = set(
    "习近平 李强 赵乐际 王沪宁 蔡奇 丁薛祥 李希 韩正 王岐山 李克强 王毅 何立峰 刘鹤 王文涛 王军 胡静林 "
    "吴清 潘功胜 易纲 郭树清 雷军 刘强东 王健林 丁磊 张勇 陈磊 李斌 王兴 李想 马云 马化腾 李彦宏 "
    "董明珠 王传福 曹德旺 任正非 孟晚舟 何小鹏 余承东 张一鸣 黄峥 周鸿祎 王石 柳传志 杨元庆 宗庆后".split())
TRADE_BLOCKLIST = set(
    "华润 中海 中信 华泰 中金 华安 汇丰 恒丰 新华 天安 永安 海天 中通 安信 平安 国信 广发 招商 兴业 "
    "浙商 民生 光大 华夏 盈科 泰康 博时 鼎晖 汇通 中科 德邦 瑞银 宏源 方正 通达".split())
PROVINCES = ("北京 天津 上海 重庆 河北 山西 辽宁 吉林 黑龙江 江苏 浙江 安徽 福建 江西 山东 河南 湖北 "
             "湖南 广东 海南 四川 贵州 云南 陕西 甘肃 青海 内蒙古 广西 西藏 宁夏 新疆").split()
AREA_CODES = {"北京": "010", "上海": "021", "天津": "022", "重庆": "023", "广州": "020", "深圳": "0755",
              "杭州": "0571", "宁波": "0574", "南京": "025", "苏州": "0512", "无锡": "0510", "成都": "028",
              "武汉": "027", "西安": "029", "青岛": "0532", "厦门": "0592", "福州": "0591", "长沙": "0731",
              "郑州": "0371", "合肥": "0551", "济南": "0531", "东莞": "0769", "佛山": "0757", "沈阳": "024",
              "大连": "0411", "哈尔滨": "0451", "昆明": "0871", "温州": "0577", "绍兴": "0575", "常州": "0519"}
COMPANY_SUFFIXES = ["科技有限公司", "实业有限公司", "贸易有限公司", "有限公司", "股份有限公司", "供应链管理有限公司"]
FREEMAIL = [("qq.com", 30), ("163.com", 25), ("126.com", 10), ("foxmail.com", 5), ("sina.com", 4), ("139.com", 4),
            ("aliyun.com", 3), ("yeah.net", 3), ("sohu.com", 3), ("outlook.com", 5), ("hotmail.com", 3), ("gmail.com", 5)]
PROVIDER_CLIENT = {"qq.com": "foxmail", "foxmail.com": "foxmail", "163.com": "netease", "126.com": "netease",
                   "yeah.net": "netease", "gmail.com": "gmail", "outlook.com": "outlook", "hotmail.com": "outlook"}
ROLE_LOCALS = ["service", "notice", "info", "admin", "office", "noreply", "support"]
EXTERNAL_WORDS = ["mail", "notice", "office", "secure", "verify", "cloud", "portal", "service", "center",
                  "online", "docs", "hr", "pay", "account", "info", "system", "update"]
EXTERNAL_TLDS = ["com", "net", "cn", "top", "xyz", "cc", "vip", "icu", "site", "online"]
DISTRICTS = ["高新区", "经济技术开发区", "工业园区", "滨江新区", "开发区"]
ROADS = ["科创路", "兴业大道", "创新路", "东方路", "长江路", "建设路", "光明路", "新华路", "滨河路", "工业大道"]
REPLY_PREFIX = {"outlook": "回复: ", "foxmail": "回复：", "netease": "Re:", "coremail": "回复：", "gmail": "回复：",
                "iphone": "回复：", "generic": "回复：", "outlook_en": "RE: ", "gmail_en": "Re: ",
                "iphone_en": "Re: ", "generic_en": "RE: "}
FORWARD_PREFIX = {"outlook": "转发: ", "foxmail": "转发：", "netease": "Fw:", "coremail": "转发：", "gmail": "Fwd: ",
                  "iphone": "转发：", "generic": "转发：", "outlook_en": "FW: ", "gmail_en": "Fwd: ",
                  "iphone_en": "Fwd: ", "generic_en": "FW: "}
WEEKDAYS = "一二三四五六日"
EN_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
             "October", "November", "December"]


def pool_slice(items, pool):
    """Partition first-name and trade-name characters so held-out names never occur in training renders."""
    if pool == "all":
        return items
    # Hash the characters themselves so a character shared by two lists lands in one partition.
    return [item for item in items
            if (hashlib.sha256(item[0].encode("utf-8")).digest()[0] % 4 == 3) == (pool == "heldout")]


def weighted(rng, options):
    return rng.choices([value for value, _ in options], [weight for _, weight in options])[0]


def city_of(region):
    region = region.strip().rstrip("市")
    for province in PROVINCES:
        if region.startswith(province) and len(region) > len(province):
            return region[len(province):].lstrip("省").rstrip("市") or province
    return region.rstrip("省")


def hostname_ok(host):
    return re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", host) is not None


def lookalike_of(domain, rng):
    label, _, tld = domain.partition(".")
    swaps = [(old, new) for old, new in (("i", "l"), ("l", "1"), ("o", "0"), ("m", "rn"), ("n", "m")) if old in label]
    makers = [
        lambda: f"{label}-{rng.choice(['mail', 'oa', 'hr', 'service', 'office', 'notice', 'secure'])}.{rng.choice(['com', 'cn', 'net', 'top', 'cc'])}",
        lambda: f"{label}{rng.choice(['mail', 'oa', 'hr', 'cloud', 'online'])}.com",
        lambda: f"{label}.{rng.choice(['com.co', 'cn.com', 'net.cn', 'co'])}",
        lambda: f"{domain}.{rng.choice(['mail-secure', 'office-verify', 'cloud-login'])}.{rng.choice(['top', 'xyz', 'com'])}",
        lambda: (lambda k: f"{label[:k]}-{label[k:]}.{tld}")(rng.randint(2, max(2, len(label) - 2))),
    ]
    if swaps:
        makers.append(lambda: (lambda s: label.replace(s[0], s[1], 1) + "." + tld)(rng.choice(swaps)))
    for _ in range(10):
        host = rng.choice(makers)()
        if host != domain and hostname_ok(host):
            return host
    return f"{label}-mail.com"


def fmt_addr(display, address):
    return f"{display} <{address}>" if display else address


def zh_time(dt):
    return f"{dt.year}年{dt.month}月{dt.day}日 {dt.hour}:{dt.minute:02d}"


def ampm(dt):
    hour = dt.hour % 12 or 12
    return ("上午" if dt.hour < 12 else "下午") + f"{hour}:{dt.minute:02d}"


def en_time(dt):
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


class Context:
    """Rendering state for one record; every choice is seeded without the label."""

    def __init__(self, renderer, record):
        self.r = renderer
        self.family = str(record.get("thread_family_id") or record.get("id") or "")
        profile = record.get("render")
        self.profile = copy.deepcopy(profile) if isinstance(profile, dict) else {}
        self.legacy = not isinstance(profile, dict)
        self.lang = record.get("language") if record.get("language") in ("zh", "en", "zh-en") else "zh"
        self.defaults, self.warnings = set(), []
        self.cache = {}
        self.year = renderer.as_of.year
        if self.legacy:
            self.defaults.add("no_render_profile")

    def rng(self, *parts):
        key = "|".join(str(part) for part in (self.r.seed, self.family, self.r.variant) + parts)
        return random.Random(int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big"))

    def section(self, name):
        value = self.profile.get(name)
        return value if isinstance(value, dict) else {}

    def memo(self, key, build):
        if key not in self.cache:
            self.cache[key] = build()
        return self.cache[key]

    # Organizations -----------------------------------------------------
    def org(self, key):
        return self.memo(("org", key), lambda: self._org(key))

    def _org(self, key):
        spec = self.section("orgs").get(key)
        if spec is None:
            if key != "AUTO":
                self.defaults.add("organization")
            spec = {"kind": "fictional", "region": self.rng("auto-region").choice(sorted(AREA_CODES)), "industry": ""}
        if spec.get("kind") == "real":
            domain = spec.get("domain") if isinstance(spec.get("domain"), str) else None
            return {"name": spec.get("name", ""), "short": spec.get("name", ""), "domain": domain, "city": None,
                    "kind": "real", "client": "generic", "local_style": "full", "display_style": "name", "initials": ""}
        taken = {self.org(f"ORG_{j}").get("trade") for j in range(1, self._index(key))} if NUMBERED.fullmatch(key) else set()
        trades = pool_slice(TRADE, self.r.pool)
        for attempt in range(50):
            rng = self.rng("org", key, attempt)
            (c1, p1), (c2, p2) = rng.sample(trades, 2)
            trade = c1 + c2
            if trade not in TRADE_BLOCKLIST and trade not in taken:
                break
        city = city_of(spec.get("region") or "") or rng.choice(sorted(AREA_CODES))
        org_type = spec.get("org_type") if spec.get("org_type") in ("company", "school", "hospital") else "company"
        trade_py = p1 + p2
        initials = p1[0] + p2[0]
        if org_type == "school":
            name = city + trade + rng.choice(["学院", "职业技术学院"])
            domain = initials + rng.choice(["u", "c", "vtc"]) + ".edu.cn"
            client = weighted(rng, [("coremail", 7), ("outlook", 2), ("foxmail", 1)])
        elif org_type == "hospital":
            name = city + trade + rng.choice(["医院", "医疗中心"])
            domain = trade_py + rng.choice(["hospital.com", "yy.com", "-hospital.cn"])
            client = weighted(rng, [("coremail", 4), ("outlook", 3), ("foxmail", 3)])
        else:
            suffix = spec.get("suffix") or rng.choice(COMPANY_SUFFIXES)
            name = city + trade + suffix if rng.random() < 0.7 else f"{trade}（{city}）{suffix}"
            domain = trade_py + rng.choice([".com.cn", ".cn", ".com", "group.com", "-tech.com"])
            client = weighted(rng, [("outlook", 35), ("foxmail", 35), ("netease", 15), ("coremail", 15)])
        if not domain.startswith(trade_py) and not domain.startswith(initials):
            domain = trade_py + ".com"
        self.r.names["organizations"].add(name)
        self.r.names["domains"].add(domain)
        return {"name": name, "short": trade, "trade": trade, "domain": domain, "city": city, "kind": "fictional",
                "client": client, "initials": initials.upper(),
                "local_style": rng.choice(["full", "given.sur", "sur.given", "surinit", "sur_given"]),
                "display_style": weighted(rng, [("name", 6), ("name(dept)", 2), ("dept-name", 1)])}

    @staticmethod
    def _index(key):
        return int(key.rsplit("_", 1)[1])

    # People ------------------------------------------------------------
    def person(self, key):
        return self.memo(("person", key), lambda: self._person(key))

    def _person(self, key):
        spec = self.section("people").get(key)
        if spec is None:
            if not self.legacy:
                self.defaults.add("person")
            spec = {"org": "AUTO"} if self.legacy or key.startswith("AUTOPERSON") else {}
        taken = {self.person(f"PERSON_{j}")["name"] for j in range(1, self._index(key))} if NUMBERED.fullmatch(key) else set()
        gender = spec.get("gender") if spec.get("gender") in ("m", "f") else self.rng("gender", key).choice("mf")
        given_pool = pool_slice(GIVEN_M if gender == "m" else GIVEN_F, self.r.pool)
        weights = [1 / (1 + i * 0.06) for i in range(len(SURNAMES))]
        for attempt in range(80):
            rng = self.rng("person", key, attempt)
            surname, sur_py = rng.choices(SURNAMES, weights)[0]
            if rng.random() < 0.7:
                given, given_py = rng.choice(pool_slice(NAMES_M if gender == "m" else NAMES_F, self.r.pool))
                parts = list(zip(given, split_py(given_py, given)))
            else:
                parts = [rng.choice(given_pool)]
                given, given_py = parts[0]
            name = surname + given
            if name not in NAME_BLOCKLIST and name not in taken:
                break
        org_key = spec.get("org") if isinstance(spec.get("org"), str) else None
        self.r.names["people"].add(name)
        return {"key": key, "name": name, "surname": surname, "given": given, "sur_py": sur_py, "given_py": given_py,
                "given_parts": [p for _, p in parts], "gender": gender, "org": org_key,
                "dept": spec.get("dept") or "", "title": spec.get("title") or "",
                "device": spec.get("device") if spec.get("device") in ("desktop", "mobile") else "desktop",
                "sig_style": rng.randrange(5), "ext": str(rng.randint(2000, 8999)),
                "line": str(rng.randint(5, 8)) + "".join(str(rng.randint(0, 9)) for _ in range(7))}

    def local_for(self, person, style):
        sur, given = person["sur_py"], person["given_py"]
        initials = "".join(part[0] for part in person["given_parts"])
        return {"full": sur + given, "given.sur": f"{given}.{sur}", "sur.given": f"{sur}.{given}",
                "surinit": sur + initials, "sur_given": f"{sur}_{given}"}.get(style, sur + given)

    # Mailboxes ---------------------------------------------------------
    def mailbox(self, key):
        return self.memo(("mailbox", key), lambda: self._mailbox(key))

    def _mailbox(self, key):
        spec = self.section("mailboxes").get(key)
        if spec is None:
            spec = self.default_mailbox_spec(key)
        rng = self.rng("mailbox", key)
        owner = spec.get("owner") if isinstance(spec.get("owner"), str) else None
        person = self.person(owner) if owner and owner.startswith(("PERSON_", "AUTOPERSON")) else None
        org_key = owner if owner and (owner.startswith("ORG_") or owner == "AUTO") else (person or {}).get("org")
        org = self.org(org_key) if org_key else None
        kind = spec.get("domain") if spec.get("domain") in ("org", "freemail", "lookalike", "external", "observed") else "org"
        value = spec.get("value") if isinstance(spec.get("value"), str) else None
        if value:
            host = value
        elif kind == "freemail":
            host = spec.get("provider") or weighted(rng, FREEMAIL)
        elif kind == "lookalike" and org and org["domain"]:
            host = lookalike_of(org["domain"], rng)
            self.r.names["domains"].add(host)
        elif kind == "external" or not (org and org["domain"]):
            if kind in ("org", "lookalike"):
                self.warnings.append(f"{key}: no organization domain available; used an external domain")
            host = f"{rng.choice(EXTERNAL_WORDS)}{rng.choice(['', '-'])}{rng.choice(EXTERNAL_WORDS)}{rng.choice(['', str(rng.randint(1, 99))])}.{rng.choice(EXTERNAL_TLDS)}"
            self.r.names["domains"].add(host)
        else:
            host = org["domain"]
        local = spec.get("local") if isinstance(spec.get("local"), str) else None
        if not local and person:
            if kind == "freemail":
                if host == "qq.com" and rng.random() < 0.5:
                    local = str(rng.randint(10**7, 3 * 10**9))
                else:
                    base = self.local_for(person, rng.choice(["full", "surinit", "given.sur"]))
                    local = base + rng.choice(["", str(rng.randint(1975, 2002)), str(rng.randint(10, 999))])
            else:
                local = self.local_for(person, (org or {}).get("local_style", "full"))
        if not local:
            local = rng.choice(ROLE_LOCALS)
        address = f"{local}@{host}"
        used = self.cache.setdefault("addresses", {})
        n = 2
        while used.get(address, key) != key:
            address = f"{local}{n}@{host}"
            n += 1
        used[address] = key
        if kind == "freemail":
            client = PROVIDER_CLIENT.get(host, "generic")
        elif kind == "org" and org:
            client = org["client"]
        else:
            client = rng.choice(["foxmail", "outlook", "generic"])
        if person and person["device"] == "mobile" and client != "outlook":
            client = "iphone"
        if self.lang == "en":
            client = {"outlook": "outlook_en", "gmail": "gmail_en", "iphone": "iphone_en"}.get(client, "generic_en")
        self.r.names["mailboxes"].add(address)
        return {"address": address, "kind": kind, "person": person, "org": org, "client": client}

    def default_mailbox_spec(self, key):
        """Legacy fallback: bind an address to the person named beside it, else a role mailbox."""
        self.defaults.add("mailbox")
        owner = self.cache.get(("owner-hint", key))
        if owner:
            return {"owner": owner, "domain": "org"}
        return {"owner": "AUTO", "domain": "org"}

    # Token rendering ---------------------------------------------------
    def token(self, kind, index):
        key = f"{kind}_{index}"
        if kind in ("PERSON", "SURNAME", "GIVEN", "SIGNATURE"):
            person = self.person(f"PERSON_{index}")
            if kind == "SIGNATURE":
                return self.signature(person)
            return {"PERSON": person["name"], "SURNAME": person["surname"], "GIVEN": person["given"]}[kind]
        if kind in ("ORG", "ORGSHORT", "DOMAIN", "LOOKALIKE"):
            org = self.org(f"ORG_{index}")
            if kind == "ORG":
                return org["name"]
            if kind == "ORGSHORT":
                return org["short"]
            if kind == "DOMAIN":
                return org["domain"] or f"[{key}]"
            if org["kind"] == "real":
                self.warnings.append(f"[{key}] cannot be generated for a real organization; left as a token")
                return f"[{key}]"
            return self.memo(("lookalike", index), lambda: lookalike_of(org["domain"], self.rng("lookalike", index)))
        if kind == "EMAIL":
            return self.mailbox(key)["address"]
        if kind == "USER":
            return self.memo(("user", index), lambda: self.username(key))
        if kind == "PHONE":
            return self.memo(("phone", index), lambda: self.phone(key))
        if kind in IDENTIFIERS:
            return self.memo((kind, index), lambda: IDENTIFIERS[kind](self.rng("value", key), self))
        rng = self.rng("value", key)
        if kind == "URL":
            self.defaults.add("legacy_url_token")
            return f"[{key}]"
        self.defaults.add("generic_identifier")
        abbr = "".join(word[0] for word in kind.split("_")) if "_" in kind else kind[:2]
        return self.memo((kind, index), lambda: f"{abbr}{self.year}{rng.randint(1, 999999):06d}")

    def org_initials(self):
        return next((org["initials"] for org in self.known_orgs() if org.get("initials")), "HT")

    def org_city(self):
        return next((org["city"] for org in self.known_orgs() if org.get("city")), None)

    def known_orgs(self):
        return [value for key, value in self.cache.items() if isinstance(key, tuple) and key[0] == "org"]

    def username(self, key):
        spec = self.section("users").get(key, {})
        owner = spec.get("owner") if isinstance(spec.get("owner"), str) else None
        if owner:
            person = self.person(owner)
            org = self.org(person["org"]) if person["org"] else None
            return self.local_for(person, (org or {}).get("local_style", "full"))
        rng = self.rng("user", key)
        surname, sur_py = rng.choice(SURNAMES)
        return sur_py + "".join(p for _, p in rng.sample(pool_slice(GIVEN_M + GIVEN_F, self.r.pool), 2))

    def phone(self, key):
        spec = self.section("phones").get(key, {})
        kind = spec.get("kind") if spec.get("kind") in ("extension", "landline", "mobile", "hotline") else "extension"
        rng = self.rng("phone", key)
        if kind == "extension":
            return str(rng.randint(2000, 8999))
        if kind == "hotline":
            return f"400-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}"
        if kind == "mobile":
            return "1" + rng.choice(["38", "39", "58", "59", "87", "88", "35", "36", "50", "51", "52", "82", "86", "33", "53", "80", "89", "77", "99"]) + f" {rng.randint(1000, 9999)} {rng.randint(1000, 9999)}"
        city = next((org["city"] for org in self.known_orgs() if org.get("city")), rng.choice(sorted(AREA_CODES)))
        return f"{AREA_CODES.get(city, '0571')}-{rng.randint(5, 8)}{rng.randint(1000000, 9999999)}"

    def signature(self, person):
        if person["device"] == "mobile":
            # A custom phone signature replaces the device footer; keep the default footer and sign by name.
            return f"{person['given_py'].capitalize()} {person['sur_py'].capitalize()}" if self.lang == "en" else person["name"]
        org = self.org(person["org"]) if person["org"] else None
        org_name = org["name"] if org else ""
        city = org["city"] if org else None
        landline = f"{AREA_CODES.get(city or '', '0571')}-{person['line']}"
        if self.lang == "en":
            name = f"{person['given_py'].capitalize()} {person['sur_py'].capitalize()}"
            lines = [name, person["title"], org_name]
            if person["sig_style"] >= 3:
                lines.append(f"Tel: +86 {landline.lstrip('0')} ext. {person['ext']}")
            return "\n".join(line for line in lines if line)
        style = person["sig_style"] if org else 0
        lines = {
            0: [person["name"]],
            1: [person["name"], person["dept"]],
            2: [" | ".join(part for part in (person["name"], person["title"]) if part), org_name],
            3: [person["name"], "  ".join(part for part in (person["title"], person["dept"]) if part), org_name,
                f"电话：{landline} 转 {person['ext']}"],
            4: ["--", person["name"], " ".join(part for part in (org_name, person["dept"]) if part), f"分机：{person['ext']}"],
        }[style]
        return "\n".join(line for line in lines if line)

    def text(self, value):
        return TOKEN_RE.sub(lambda m: self.token(m.group(1), int(m.group(2))), value) if isinstance(value, str) else value


class Renderer:
    def __init__(self, seed=0, variant=1, pool="all", history="both", marker=True, as_of=None):
        self.seed, self.variant, self.pool, self.history, self.marker = seed, variant, pool, history, marker
        self.as_of = as_of if as_of is not None else date.today()
        self.names = {"people": set(), "organizations": set(), "domains": set(), "mailboxes": set()}

    def render(self, record):
        """Return (rendered record, context). target is copied but never consulted."""
        source = {key: value for key, value in record.items() if key != "target"}
        ctx = Context(self, source)
        inp = source.get("input") if isinstance(source.get("input"), dict) else {}
        history = [m for m in inp.get("history", []) if isinstance(m, dict)] if isinstance(inp.get("history"), list) else []
        current = inp.get("current_email") if isinstance(inp.get("current_email"), dict) else {}
        messages = history + [current]
        if ctx.legacy:
            self.bind_legacy_owners(ctx, messages)
        times = self.timeline(ctx, messages)
        ctx.year = times[-1].year
        rendered_msgs, views = [], []
        for i, message in enumerate(messages):
            out, view = self.message(ctx, message, times[i], views[-1] if views else None)
            rendered_msgs.append(out)
            views.append(view)
        new_input = copy.deepcopy(inp)
        for key in new_input:
            if key not in ("history", "current_email"):
                new_input[key] = render_strings(ctx, new_input[key])
        if "history" in new_input:
            new_input["history"] = rendered_msgs[:-1]
        new_input["current_email"] = rendered_msgs[-1]
        result = {key: copy.deepcopy(value) for key, value in record.items() if key != "render"}
        result["input"] = new_input
        quote_fixes = self.requote(ctx, result)
        result["rendering"] = {"source_id": record.get("id"), "variant": self.variant, "seed": self.seed,
                               "name_pool": self.pool, "client": views[-1]["client"],
                               "defaults": sorted(ctx.defaults), "warnings": ctx.warnings + quote_fixes}
        result["_eml"] = views
        return result, ctx

    def bind_legacy_owners(self, ctx, messages):
        for message in messages:
            for field in ("from", "reply_to"):
                self.hint_owner(ctx, message.get(field))
            for field in ("to", "cc"):
                for recipient in message.get(field) or []:
                    self.hint_owner(ctx, recipient)

    @staticmethod
    def hint_owner(ctx, party):
        if isinstance(party, dict) and isinstance(party.get("address"), str) and isinstance(party.get("name"), str):
            email, person = TOKEN_RE.fullmatch(party["address"]), TOKEN_RE.search(party["name"])
            if email and email.group(1) == "EMAIL" and person and person.group(1) == "PERSON":
                ctx.cache[("owner-hint", f"EMAIL_{email.group(2)}")] = f"PERSON_{person.group(2)}"

    def timeline(self, ctx, messages):
        stamps = []
        for message in messages:
            try:
                stamp = message.get("sent_at")
                parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00")) if isinstance(stamp, str) else None
                stamps.append(parsed if parsed and parsed.tzinfo else None)
            except ValueError:
                stamps.append(None)
        if all(stamps):
            return stamps
        ctx.defaults.add("sent_at")
        rng = ctx.rng("timeline")

        def gap():
            return weighted(rng, [(timedelta(minutes=rng.randint(8, 180)), 6),
                                  (timedelta(days=1, minutes=rng.randint(-120, 120)), 3),
                                  (timedelta(days=rng.randint(2, 5), minutes=rng.randint(-60, 60)), 1)])

        def weekend_gap(stamp, step):
            weekday = stamp.weekday()
            if weekday < 5:
                return timedelta()
            return timedelta(days=7 - weekday if step > 0 else weekday - 4)

        def end_of_window(stamp):
            last_day = date(stamp.year, 12, 31)
            if stamp.date() <= self.as_of < last_day:
                last_day = self.as_of
            return datetime.combine(last_day, time.max, stamp.tzinfo)

        def fill(indices, anchor, boundary, step):
            for offset, i in enumerate(indices):
                available = step * (boundary - anchor)
                delay = gap()
                if delay < available:
                    delay += weekend_gap(anchor + step * delay, step)
                if delay >= available:
                    # Share the remaining time among the missing messages.
                    delay = available / (len(indices) - offset + 1)
                anchor += step * delay
                stamps[i] = anchor

        known = [i for i, stamp in enumerate(stamps) if stamp]
        if not known:
            jan1 = date(self.as_of.year, 1, 1)
            day = jan1 + timedelta(days=rng.randint(0, (self.as_of - jan1).days))
            to_weekday = weekend_gap(day, 1)
            if to_weekday <= self.as_of - day:
                day += to_weekday
            stamps[0] = datetime.combine(day, time(rng.randint(8, 18), rng.randrange(60), rng.randrange(60)), CST)
            known = [0]
        first, last = known[0], known[-1]
        first_stamp, last_stamp = stamps[first], stamps[last]
        year_start = datetime(first_stamp.year, 1, 1, tzinfo=first_stamp.tzinfo)
        fill(range(first - 1, -1, -1), first_stamp, year_start, -1)
        for left, right in zip(known, known[1:]):
            boundary = stamps[right]
            if stamps[left].year == boundary.year:
                # The right anchor can fall on the next calendar day in the left anchor's time zone.
                boundary = min(boundary, end_of_window(stamps[left]))
            fill(range(left + 1, right), stamps[left], boundary, 1)
        fill(range(last + 1, len(stamps)), last_stamp, end_of_window(last_stamp), 1)
        return stamps

    def party(self, ctx, party, sender=False):
        """Render a from/to/cc/reply_to value to (display, address, mailbox info, original type)."""
        if isinstance(party, str):
            match = TOKEN_RE.fullmatch(party)
            if match and match.group(1) == "EMAIL":
                box = ctx.mailbox(f"EMAIL_{match.group(2)}")
                person = box["person"]
                return (person["name"] if person else ""), box["address"], box
            display = ctx.text(party)
            person = TOKEN_RE.search(party)
            owner = f"PERSON_{person.group(2)}" if person and person.group(1) == "PERSON" else None
            key = f"AUTO_{owner or 'ROLE'}"
            box = ctx.memo(("legacy-box", key), lambda: self.legacy_box(ctx, owner))
            return display, box["address"], box
        if isinstance(party, dict):
            address = party.get("address")
            match = TOKEN_RE.fullmatch(address) if isinstance(address, str) else None
            box = ctx.mailbox(f"EMAIL_{match.group(2)}") if match and match.group(1) == "EMAIL" else None
            name = party.get("name")
            person_match = TOKEN_RE.fullmatch(name) if isinstance(name, str) else None
            if person_match and person_match.group(1) == "PERSON":
                person = ctx.person(f"PERSON_{person_match.group(2)}")
                display = person["name"]
                if box and box["kind"] == "org" and box["org"] and person["org"] and box["org"] is ctx.org(person["org"]):
                    style = box["org"]["display_style"]
                    if style == "name(dept)" and person["dept"]:
                        display = f"{person['name']}({person['dept']})"
                    elif style == "dept-name" and person["dept"]:
                        display = f"{person['dept']}-{person['name']}"
            elif isinstance(name, str):
                display = ctx.text(name)
            else:
                display = box["person"]["name"] if box and box["person"] else ""
            return display, (box["address"] if box else ctx.text(address) if isinstance(address, str) else ""), box
        return "", "", None

    def legacy_box(self, ctx, owner):
        ctx.defaults.add("mailbox")
        spec = {"owner": owner, "domain": "org"} if owner else {"owner": "AUTO", "domain": "org"}
        key = f"LEGACY_{owner or 'ROLE'}"
        ctx.profile.setdefault("mailboxes", {})[key] = spec
        return ctx.mailbox(key)

    def message(self, ctx, message, when, previous):
        display, address, box = self.party(ctx, message.get("from"), sender=True)
        client = box["client"] if box else ("generic_en" if ctx.lang == "en" else "generic")
        recipients = []
        for value in message.get("to") or []:
            recipients.append(self.party(ctx, value)[:2])
        if not recipients and "to" not in message:
            recipients.append(self.default_recipient(ctx, message, box))
        cc = [self.party(ctx, value)[:2] for value in message.get("cc") or []]
        subject_raw = message.get("subject") if isinstance(message.get("subject"), str) else ""
        subject_text = ctx.text(subject_raw)
        prefix = PREFIX_RE.match(subject_text)
        base = subject_text[prefix.end():] if prefix else subject_text
        is_forward = bool(prefix and FORWARD_RE.match(subject_text))
        is_reply = (bool(prefix) and not is_forward) or (previous is not None and base.strip() == previous["base"].strip())
        subject = ((FORWARD_PREFIX if is_forward else REPLY_PREFIX)[client] + base) if (is_reply or is_forward) else base
        authored = ctx.text(message["body"]) if isinstance(message.get("body"), str) else ""
        person = box["person"] if box else None
        if person and person["device"] == "mobile":
            authored = authored.rstrip() + "\n\n" + self.device_footer(ctx, client)
        quote = previous if previous is not None and (is_reply or is_forward) and self.history == "both" else None
        view = {"display": display, "address": address, "to": recipients, "cc": cc, "when": when, "subject": subject,
                "base": base, "authored": authored, "quote": quote, "client": client, "reply": is_reply,
                "attachments": message.get("attachments") or []}
        view["text"] = authored if quote is None else authored.rstrip() + "\n\n" + quote_text(client, quote, ctx.lang)
        out = {key: render_strings(ctx, copy.deepcopy(value)) for key, value in message.items() if key not in ("from", "to", "cc")}
        out["from"] = fmt_addr(display, address) if isinstance(message.get("from"), str) else {"name": display, "address": address}
        out["to"] = [{"name": name, "address": addr} for name, addr in recipients]
        if cc:
            out["cc"] = [{"name": name, "address": addr} for name, addr in cc]
        if message.get("reply_to") is not None:
            name, addr, _ = self.party(ctx, message["reply_to"])
            out["reply_to"] = {"name": name, "address": addr}
        out["sent_at"] = when.isoformat()
        out["subject"] = subject
        out["body"] = view["text"]
        return out, view

    def default_recipient(self, ctx, message, sender_box):
        ctx.defaults.add("recipient")
        body = message.get("body") if isinstance(message.get("body"), str) else ""
        first = body.strip().splitlines()[0] if body.strip() else ""
        sender_person = sender_box["person"]["key"] if sender_box and sender_box["person"] else None
        for kind, index in TOKEN_RE.findall(first):
            if kind in ("PERSON", "SURNAME", "GIVEN") and f"PERSON_{index}" != sender_person:
                box = ctx.memo(("legacy-box", f"AUTO_PERSON_{index}"), lambda: self.legacy_box(ctx, f"PERSON_{index}"))
                return box["person"]["name"], box["address"]
        box = ctx.memo(("legacy-box", "AUTO_RECIPIENT"), lambda: self.legacy_box(ctx, "AUTOPERSON_RECIPIENT"))
        return box["person"]["name"], box["address"]

    @staticmethod
    def device_footer(ctx, client):
        if client.startswith("outlook"):
            return "Get Outlook for iOS" if ctx.lang == "en" else "获取 Outlook for iOS"
        return "Sent from my iPhone" if ctx.lang == "en" else "发自我的iPhone"

    def requote(self, ctx, result):
        """Re-render evidence and provenance quotes so they stay exact substrings."""
        problems = []
        targets = []
        target = result.get("target")
        if isinstance(target, dict) and isinstance(target.get("evidence"), list):
            for item in target["evidence"]:
                if isinstance(item, dict) and isinstance(item.get("spans"), list):
                    targets.extend((span, "path", "quote") for span in item["spans"] if isinstance(span, dict))
        grounding = (result.get("provenance") or {}).get("grounding") if isinstance(result.get("provenance"), dict) else None
        if isinstance(grounding, dict):
            for field in ("fact_map", "adaptations"):
                for entry in grounding.get(field) or []:
                    if isinstance(entry, dict):
                        targets.append((entry, "input_path", "input_quote"))
        for entry, path_key, quote_key in targets:
            quote = entry.get(quote_key)
            if not isinstance(quote, str):
                continue
            rendered = ctx.text(quote)
            value = resolve(result, entry.get(path_key))
            if isinstance(value, str) and rendered not in value:
                prefix = PREFIX_RE.match(rendered)
                if prefix and rendered[prefix.end():] in value:
                    rendered = rendered[prefix.end():]
            entry[quote_key] = rendered
            if not isinstance(value, str) or rendered not in value:
                problems.append(f"quote no longer matches {entry.get(path_key)}: {rendered[:40]}")
        return problems


def digits(rng, count):
    return str(rng.randint(1, 9)) + "".join(str(rng.randint(0, 9)) for _ in range(count - 1))


def split_py(pinyin, chars):
    """Split a curated two-character pinyin string at the syllable boundary."""
    for cut in range(1, len(pinyin)):
        head, tail = pinyin[:cut], pinyin[cut:]
        if re.fullmatch(SYLLABLE, head) and re.fullmatch(SYLLABLE, tail):
            return head, tail
    return pinyin, ""


SYLLABLE = (r"(?:zh|ch|sh|[bpmfdtnlgkhjqxrzcsyw])?(?:iang|iong|uang|ang|eng|ing|ong|uan|ian|iao|uai|ai|ei|ao|ou|an|en"
            r"|in|un|ia|ie|iu|ua|uo|ui|ue|er|a|o|e|i|u|v)(?:n|ng)?")
IDENTIFIERS = {
    "ORDER": lambda rng, ctx: digits(rng, rng.choice([12, 16, 19])),
    "INVOICE": lambda rng, ctx: f"{ctx.year % 100:02d}" + "".join(str(rng.randint(0, 9)) for _ in range(18)),
    "CONTRACT": lambda rng, ctx: rng.choice([f"{ctx.org_initials()}-{ctx.year}-{rng.randint(1, 999):04d}",
                                            f"{ctx.org_initials()}{ctx.year}{rng.randint(1, 999):03d}"]),
    "TICKET": lambda rng, ctx: rng.choice([f"SR{ctx.year}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}{rng.randint(1, 9999):04d}",
                                          f"#{rng.randint(100000, 999999)}", f"T{rng.randint(10**7, 10**8 - 1)}"]),
    "ADDRESS": lambda rng, ctx: f"{ctx.org_city() or rng.choice(sorted(AREA_CODES))}{rng.choice(DISTRICTS)}{rng.choice(ROADS)}{rng.randint(1, 399)}号",
    "SLUG": lambda rng, ctx: "".join(rng.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
                                     for _ in range(rng.choice([8, 10, 12, 16, 22]))),
    "OTP": lambda rng, ctx: f"{rng.randint(0, 999999):06d}",
    "CODE": lambda rng, ctx: f"{rng.randint(0, 999999):06d}",
    "REDEMPTION_CODE": lambda rng, ctx: f"****-****-****-{rng.randint(0, 9999):04d}",
    "SECRET": lambda rng, ctx: "******",
    "REFERENCE": lambda rng, ctx: rng.choice([f"REF{ctx.year}{rng.randint(1, 99999):05d}", digits(rng, 12)]),
    "CASE": lambda rng, ctx: f"CS{ctx.year}{rng.randint(1, 12):02d}{rng.randint(1, 9999):04d}",
    "QUOTE": lambda rng, ctx: f"QT-{ctx.year}-{rng.randint(1, 9999):04d}",
    "RFQ": lambda rng, ctx: f"RFQ-{ctx.year}-{rng.randint(1, 999):03d}",
    "TRANSACTION": lambda rng, ctx: digits(rng, rng.choice([16, 18, 20])),
    "TRANSFER": lambda rng, ctx: digits(rng, rng.choice([14, 16, 18])),
    "RECEIPT": lambda rng, ctx: f"{ctx.year}" + "".join(str(rng.randint(0, 9)) for _ in range(10)),
    "SHIPMENT": lambda rng, ctx: digits(rng, rng.choice([12, 13, 15])),
    "MANDATE": lambda rng, ctx: f"MD{ctx.year}{rng.randint(1, 999999):06d}",
    "PORTFOLIO": lambda rng, ctx: f"P{rng.randint(1000, 999999)}",
    "DEVICE": lambda rng, ctx: rng.choice([f"PC-{rng.randint(1000, 99999)}", f"NB{rng.randint(10000, 99999)}"]),
    "EMPLOYEE": lambda rng, ctx: rng.choice(["E", "", ctx.org_initials()]) + f"{rng.randint(10000, 999999)}",
    "DOC": lambda rng, ctx: f"DOC-{ctx.year}-{rng.randint(1, 9999):04d}",
    "CLAIM": lambda rng, ctx: f"CL{ctx.year}{rng.randint(1, 999999):06d}",
    "CREDIT_NOTE": lambda rng, ctx: f"CN{ctx.year}{rng.randint(1, 99999):05d}",
    "POLICY": lambda rng, ctx: digits(rng, rng.choice([15, 18, 20])),
    "RETURN": lambda rng, ctx: f"RT{ctx.year}{rng.randint(1, 999999):06d}",
    "REFUND": lambda rng, ctx: f"RF{ctx.year}{rng.randint(1, 999999):06d}",
}


def render_strings(ctx, value):
    if isinstance(value, str):
        return ctx.text(value)
    if isinstance(value, list):
        return [render_strings(ctx, item) for item in value]
    if isinstance(value, dict):
        return {key: render_strings(ctx, item) for key, item in value.items()}
    return value


def resolve(record, path):
    if not isinstance(path, str) or not path.startswith("/"):
        return None
    node = record
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None
    return node


def header_block(client, view, lang):
    """Return (separator, header lines) for header-style quotes or None for attribution styles."""
    when = view["when"]
    sender = fmt_addr(view["display"], view["address"])
    to = "; ".join(fmt_addr(name, addr) for name, addr in view["to"])
    cc = "; ".join(fmt_addr(name, addr) for name, addr in view["cc"])
    if client == "outlook":
        lines = [f"发件人: {sender}", f"发送时间: {zh_time(when)}", f"收件人: {to}"] + ([f"抄送: {cc}"] if cc else []) + [f"主题: {view['subject']}"]
        return "________________________________", lines
    if client == "outlook_en":
        sent = f"{EN_DAYS[when.weekday()]}, {EN_MONTHS[when.month - 1]} {when.day}, {when.year} {en_time(when)}"
        lines = [f"From: {sender}", f"Sent: {sent}", f"To: {to}"] + ([f"Cc: {cc}"] if cc else []) + [f"Subject: {view['subject']}"]
        return "________________________________", lines
    if client == "foxmail":
        quoted = lambda name, addr: f'"{name}"<{addr}>;' if name else f"<{addr}>;"
        lines = [f"发件人: {quoted(view['display'], view['address'])}",
                 f"发送时间: {when.year}年{when.month}月{when.day}日(星期{WEEKDAYS[when.weekday()]}) {ampm(when)}",
                 "收件人: " + " ".join(quoted(n, a) for n, a in view["to"])]
        lines += (["抄送: " + " ".join(quoted(n, a) for n, a in view["cc"])] if view["cc"] else []) + [f"主题: {view['subject']}"]
        return "------------------ 原始邮件 ------------------", lines
    if client == "coremail":
        quoted = lambda name, addr: f'"{name}" <{addr}>' if name else f"<{addr}>"
        lines = [f"发件人:{quoted(view['display'], view['address'])}",
                 f"发送时间:{when:%Y-%m-%d %H:%M:%S} (星期{WEEKDAYS[when.weekday()]})",
                 "收件人:" + ", ".join(quoted(n, a) for n, a in view["to"])]
        lines += (["抄送:" + ", ".join(quoted(n, a) for n, a in view["cc"])] if view["cc"] else []) + [f"主题:{view['subject']}"]
        return "-----原始邮件-----", lines
    if client == "generic_en":
        lines = [f"From: {sender}", f"Sent: {when:%Y-%m-%d %H:%M}", f"To: {to}"] + ([f"Cc: {cc}"] if cc else []) + [f"Subject: {view['subject']}"]
        return "-----Original Message-----", lines
    if client == "generic":
        lines = [f"发件人: {sender}", f"发送时间: {when:%Y-%m-%d %H:%M}", f"收件人: {to}"] + ([f"抄送: {cc}"] if cc else []) + [f"主题: {view['subject']}"]
        return "-----原始邮件-----", lines
    return None


def attribution(client, view):
    when, sender = view["when"], fmt_addr(view["display"], view["address"])
    if client == "netease":
        quoted = f'"{view["display"]}" <{view["address"]}>' if view["display"] else view["address"]
        return f"在 {when:%Y-%m-%d %H:%M:%S}，{quoted} 写道："
    if client == "gmail":
        return f"{sender} 于{when.year}年{when.month}月{when.day}日周{WEEKDAYS[when.weekday()]} {when.hour}:{when.minute:02d}写道："
    if client == "gmail_en":
        return f"On {EN_DAYS[when.weekday()][:3]}, {EN_MONTHS[when.month - 1][:3]} {when.day}, {when.year} at {en_time(when)} {sender} wrote:"
    if client == "iphone_en":
        return f"On {EN_MONTHS[when.month - 1][:3]} {when.day}, {when.year}, at {when.hour:02d}:{when.minute:02d}, {sender} wrote:"
    return f"在 {when.year}年{when.month}月{when.day}日，{when.hour:02d}:{when.minute:02d}，{sender} 写道："


def quote_text(client, previous, lang):
    block = header_block(client, previous, lang)
    if block:
        separator, lines = block
        return separator + "\n" + "\n".join(lines) + "\n\n" + previous["text"]
    quoted = "\n".join(("> " + line) if line else ">" for line in previous["text"].splitlines())
    if client.startswith("iphone"):
        return "> " + attribution(client, previous) + "\n>\n" + quoted
    return attribution(client, previous) + "\n\n" + quoted


def html_of(view, lang):
    def paragraphs(text):
        return "".join(f"<div>{html.escape(line) or '<br>'}</div>" for line in text.splitlines())
    body = paragraphs(view["authored"])
    previous = view["quote"]
    if previous is None:
        return body
    block = header_block(view["client"], previous, lang)
    inner = html_of(previous, lang)
    if block:
        separator, lines = block
        header = "<br>".join(html.escape(line) for line in lines)
        return (body + f'<div><br></div><div style="border-top:1px solid #E1E1E1;padding-top:6px">'
                f"{html.escape(separator)}<br>{header}</div><div><br></div>{inner}")
    return (body + f"<div><br></div><div>{html.escape(attribution(view['client'], previous))}</div>"
            f'<blockquote style="margin:0 0 0 .8ex;border-left:1px solid #ccc;padding-left:1ex">{inner}</blockquote>')


def message_id(rendered, index, view):
    host = view["address"].rsplit("@", 1)[-1] or "localhost"
    digest = hashlib.sha256(f"{rendered['rendering']['source_id']}|{rendered['rendering']['variant']}|{index}".encode()).hexdigest()
    return f"<{digest[:24]}@{host}>"


def to_eml(rendered, marker=True):
    views = rendered["_eml"]
    view = views[-1]
    msg = EmailMessage(policy=SMTP)
    msg["From"] = Address(display_name=view["display"], addr_spec=view["address"])
    if view["to"]:
        msg["To"] = tuple(Address(display_name=name, addr_spec=addr) for name, addr in view["to"])
    if view["cc"]:
        msg["Cc"] = tuple(Address(display_name=name, addr_spec=addr) for name, addr in view["cc"])
    reply_to = rendered["input"]["current_email"].get("reply_to")
    if isinstance(reply_to, dict) and reply_to.get("address"):
        msg["Reply-To"] = Address(display_name=reply_to.get("name") or "", addr_spec=reply_to["address"])
    msg["Subject"] = view["subject"]
    msg["Date"] = format_datetime(view["when"])
    msg["Message-ID"] = message_id(rendered, len(views) - 1, view)
    if view["quote"] is not None:
        refs = [message_id(rendered, i, v) for i, v in enumerate(views[:-1])]
        msg["In-Reply-To"] = refs[-1]
        msg["References"] = " ".join(refs)
    if marker:
        msg["X-Corpus-Rendered"] = "fictional; not real correspondence"
    msg.set_content(view["text"])
    msg.add_alternative(f'<html><body style="font-family:sans-serif;font-size:14px">{html_of(view, rendered.get("language"))}</body></html>', subtype="html")
    for attachment in view["attachments"]:
        if isinstance(attachment, dict) and isinstance(attachment.get("name"), str):
            kind = str(attachment.get("type") or "application/octet-stream")
            maintype, _, subtype = kind.partition("/") if "/" in kind else ("application", "", kind if kind.isalnum() else "octet-stream")
            msg.add_attachment(b"placeholder attachment: canonical records keep attachment metadata only\n",
                               maintype=maintype, subtype=subtype or "octet-stream", filename=attachment["name"])
    return msg


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path")
    parser.add_argument("--out", required=True, help="output JSON file (json format) or directory (eml format)")
    parser.add_argument("--format", choices=["json", "eml"], default="json")
    parser.add_argument("--seed", type=int, default=0, help="global seed; change it to draw a different set of personas")
    parser.add_argument("--variants", type=int, default=1, help="render each record K times with different personas")
    parser.add_argument("--name-pool", choices=["all", "train", "heldout"], default="all",
                        help="train and heldout use disjoint given-name and trade-name characters")
    parser.add_argument("--history", choices=["both", "array"], default="both",
                        help="both: keep history and quote replies in the current body; array: no quoted chain")
    parser.add_argument("--ids", default="", help="comma-separated record IDs to render")
    parser.add_argument("--names-report", help="write generated names, organizations, domains and mailboxes for review")
    parser.add_argument("--no-marker", action="store_true", help="omit the X-Corpus-Rendered header in .eml output")
    args = parser.parse_args()
    as_of = date.today()
    if args.variants < 1:
        parser.error("--variants must be at least 1")
    with open(args.path, encoding="utf-8-sig") as handle:
        records = json.load(handle)
    if not isinstance(records, list):
        parser.error("input must be a JSON array of records")
    wanted = {value.strip() for value in args.ids.split(",") if value.strip()}
    if wanted:
        records = [record for record in records if isinstance(record, dict) and record.get("id") in wanted]
    outputs, names = [], {"people": set(), "organizations": set(), "domains": set(), "mailboxes": set()}
    for variant in range(1, args.variants + 1):
        renderer = Renderer(args.seed, variant, args.name_pool, args.history, not args.no_marker, as_of=as_of)
        for record in records:
            if not isinstance(record, dict):
                continue
            rendered, _ = renderer.render(record)
            if args.variants > 1:
                rendered["id"] = f"{record.get('id')}.v{variant}"
                if rendered.get("pair_id"):
                    rendered["pair_id"] = f"{rendered['pair_id']}.v{variant}"
            outputs.append(rendered)
        for key in names:
            names[key] |= renderer.names[key]
    out = Path(args.out)
    if args.format == "json":
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps([{k: v for k, v in r.items() if k != "_eml"} for r in outputs],
                                  ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        out.mkdir(parents=True, exist_ok=True)
        manifest = []
        for rendered in outputs:
            filename = re.sub(r"[^A-Za-z0-9._-]", "_", str(rendered.get("id"))) + ".eml"
            (out / filename).write_bytes(to_eml(rendered, not args.no_marker).as_bytes())
            manifest.append({"file": filename, "id": rendered.get("id"), "label": (rendered.get("target") or {}).get("label"),
                             "thread_family_id": rendered.get("thread_family_id"), "pair_id": rendered.get("pair_id"),
                             "scenario_type": rendered.get("scenario_type"), "defaults": rendered["rendering"]["defaults"]})
        (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.names_report:
        Path(args.names_report).write_text(json.dumps({key: sorted(value) for key, value in names.items()},
                                                      ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with_defaults = sum(1 for r in outputs if r["rendering"]["defaults"])
    warnings = [f"[{r['id']}] {w}" for r in outputs for w in r["rendering"]["warnings"]]
    for line in warnings[:50]:
        print("WARN  " + line)
    print(f"rendered: {len(outputs)} record(s) from {len(records)} x {args.variants} variant(s) -> {out}")
    print(f"defaults used: {with_defaults}  warnings: {len(warnings)}  generated people: {len(names['people'])}  "
          f"organizations: {len(names['organizations'])}  mailboxes: {len(names['mailboxes'])}")
    print("note: names, companies, domains and mailboxes are fictional but may coincide with real ones; "
          "review --names-report before publishing and use .eml files only in an isolated test system")
    return 0


if __name__ == "__main__":
    sys.exit(main())
