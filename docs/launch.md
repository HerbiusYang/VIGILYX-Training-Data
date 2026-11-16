# 开源发布素材

![朋友圈发布图](assets/wechat-moments.png)

1440 × 1920 PNG，二维码指向 https://github.com/HerbiusYang/VIGILYX-Training-Data 。

配文：

> 把最近整理的邮件安全训练语料开源了：VIGILYX Training Data。
>
> 5,078 条中英文样本，覆盖钓鱼、身份冒用、业务流程篡改和商业邮件诈骗，也保留正常邮件对照。附上本地 Python 语料工作台，以及来源改编、生成和校验 Skill，方便做防御训练和人工复核。
>
> 这些是训练样本，含来源改编和历史合成记录，并非截获的原始邮件。欢迎交流、提建议。
>
> https://github.com/HerbiusYang/VIGILYX-Training-Data

图片采用本地图形与字体排版，中文和二维码均为确定性绘制，未使用 AI 生图接口。

重新制作：

```bash
uv run tools/make_social_poster.py
# 其他系统需指定已安装的中文字体：
uv run tools/make_social_poster.py --font /path/to/chinese-font.ttf
```
