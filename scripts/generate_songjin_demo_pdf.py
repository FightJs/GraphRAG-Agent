#!/usr/bin/env python3
"""生成《锦上添花·苏州宋锦非遗文创商业计划书》演示 PDF（用于跨文档联合问答）"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FONT_PATH = "/System/Library/Fonts/Supplemental/Songti.ttc"
pdfmetrics.registerFont(TTFont("Song", FONT_PATH, subfontIndex=0))

OUT = Path(__file__).resolve().parents[1] / "assets" / "suzhou_songjin_business_plan.pdf"
OUT.parent.mkdir(parents=True, exist_ok=True)

ACCENT = colors.HexColor("#1F4E79")
LIGHT = colors.HexColor("#E8F1F8")
INK = colors.HexColor("#1A1A1A")
MUTED = colors.HexColor("#4A5568")
WARN = colors.HexColor("#B45309")

styles = getSampleStyleSheet()


def s(name, **kw):
    base = dict(fontName="Song", textColor=INK, leading=16)
    base.update(kw)
    return ParagraphStyle(name, **base)


TITLE = s("title", fontSize=22, leading=30, alignment=TA_CENTER, textColor=ACCENT, spaceAfter=6)
SUBTITLE = s("subtitle", fontSize=12, leading=18, alignment=TA_CENTER, textColor=MUTED, spaceAfter=4)
H1 = s("h1", fontSize=15, leading=22, textColor=ACCENT, spaceBefore=14, spaceAfter=8)
H2 = s("h2", fontSize=12.5, leading=18, textColor=colors.HexColor("#0F3D5E"), spaceBefore=10, spaceAfter=5)
BODY = s("body", fontSize=10.5, leading=17, alignment=TA_JUSTIFY, spaceAfter=5)
BULLET = s("bullet", fontSize=10.5, leading=16, leftIndent=12, spaceAfter=3)
META = s("meta", fontSize=10, leading=15, alignment=TA_CENTER, textColor=MUTED)
TABLE_CELL = s("tcell", fontSize=9.5, leading=13)
TABLE_HEAD = s("thead", fontSize=9.5, leading=13, textColor=colors.white)
SMALL = s("small", fontSize=9, leading=13, textColor=MUTED)


def P(text, style=BODY):
    return Paragraph(text, style)


def bullet(text):
    return Paragraph(f"• {text}", BULLET)


def section_table(headers, rows, col_widths):
    data = [[Paragraph(h, TABLE_HEAD) for h in headers]]
    for row in rows:
        data.append([Paragraph(str(c), TABLE_CELL) for c in row])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), LIGHT),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B0C4D8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return t


def build():
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="锦上添花 · 苏州宋锦非遗文创商业计划书",
        author="GraphRAG Demo",
    )
    story = []

    # ── Cover / header ──
    story.append(Spacer(1, 8 * mm))
    story.append(P("BUSINESS PLAN｜国家级非遗活化与时尚文创项目", SUBTITLE))
    story.append(P("「锦上添花」宋锦焕新计划", TITLE))
    story.append(P("苏州宋锦非遗技艺活化与现代时尚文创产业化 商业计划书", SUBTITLE))
    story.append(Spacer(1, 4 * mm))
    story.append(P("项目名称：锦上添花宋锦文创", META))
    story.append(P("行业赛道：非遗文创 / 丝绸织造活化 / 时尚配饰", META))
    story.append(P("规划周期：2026 - 2029（三年期）", META))
    story.append(P("实证支撑：N=1,236 消费者调研与竞品对标模型", META))
    story.append(Spacer(1, 6 * mm))

    story.append(P("一、执行摘要（Executive Summary）", H1))
    story.append(
        P(
            "「锦上添花」立足于国家级非物质文化遗产——苏州宋锦，以「织造技艺当代转译」为核心，"
            "打造面向都市白领与国潮爱好者的时尚文创产品线。项目与「纤毫匠心」核雕文创同属苏州非遗活化赛道，"
            "但聚焦丝绸织造而非雕刻工艺，客群更偏轻奢配饰与商务礼品场景。"
        )
    )
    story.append(P("1.1 项目定位与使命", H2))
    story.append(
        P(
            "通过「纹样数字化 + 小单快反 + 品牌联名」模式，将宋锦从博物馆藏品与高端定制，"
            "转化为可日常佩戴、可商务馈赠、可文化体验的现代生活方式产品，实现「指尖经纬」向「日常美学」的跨越。"
        )
    )
    story.append(P("1.2 核心差异化", H2))
    story.append(bullet("工艺载体不同：宋锦（丝织提花） vs 核雕（果核雕刻），共享「非遗+文创+亲子研学」叙事框架。"))
    story.append(bullet("客群侧重不同：本项目以 25-35 岁都市白领与商务礼品采购为主；核雕项目更侧重亲子教育与收藏。"))
    story.append(bullet("价格带不同：主力 SKU 定价 199-459 元，轻奢配饰带；高于日常轻文创，低于大师收藏级。"))

    story.append(P("二、行业痛点与机遇", H1))
    story.append(
        section_table(
            ["痛点", "现状描述", "本项目对策"],
            [
                ["技艺认知断层", "大众对宋锦与普通丝绸、云锦、缂丝区分不清，线下触达不足。", "开设「一锦一课」短视频系列与博物馆联名展陈。"],
                ["产品老化", "传统宋锦多用于装裱与高端服饰，日常使用场景少。", "开发丝巾、包饰、书签、商务领带等轻量化 SKU。"],
                ["价格与信任", "低价化纤冒充真丝宋锦，消费者缺乏鉴别能力。", "一织一码溯源 + 成分检测报告 + 设计师联名背书。"],
                ["渠道单一", "过度依赖景区门店与礼品渠道，年轻客群渗透低。", "小红书/抖音内容种草 + 线下 Pop-up 快闪体验。"],
            ],
            [28 * mm, 72 * mm, 72 * mm],
        )
    )
    story.append(Spacer(1, 3 * mm))
    story.append(
        P(
            "政策端：十五五文化和旅游发展规划持续支持非遗创造性转化；国潮经济与「新中式」服饰消费为宋锦提供增量场景。"
            "与苏州核雕项目共同受益于区域公共品牌与文旅流量。"
        )
    )

    story.append(P("三、产品体系与服务形态", H1))
    story.append(P("3.1 核心产品线架构与定价策略", H2))
    story.append(
        section_table(
            ["产品线", "代表 SKU", "目标场景", "价格带（元）"],
            [
                ["日常轻奢配饰", "宋锦丝巾、发带、胸针", "通勤、约会、国潮穿搭", "199-359"],
                ["商务礼品系列", "领带、笔记本封面、礼盒", "企业采购、节日馈赠", "299-459"],
                ["亲子研学体验包", "迷你织机材料包 + 纹样填色", "亲子周末、学校美育", "159-229"],
                ["大师联名收藏", "限量织造作品、艺术家合作款", "收藏、艺术展陈", "1280-3680"],
            ],
            [32 * mm, 42 * mm, 48 * mm, 32 * mm],
        )
    )
    story.append(Spacer(1, 2 * mm))
    story.append(
        P(
            "产品矩阵覆盖「自用—送礼—体验—收藏」四层需求，与核雕项目的「日常轻文创 + 大师收藏级」双线策略互补，"
            "便于知识库内跨文档对比定价与客群。"
        )
    )

    story.append(P("四、市场实证调研与目标用户画像", H1))
    story.append(P("4.1 调研基本情况说明", H2))
    story.append(
        P(
            "调研采用全国配额抽样与线上问卷结合，有效样本 N=1,236，覆盖长三角、珠三角与京津冀核心城市。"
            "分析方法包括 SEM 结构方程模型、K-means 聚类与联合分析（Conjoint）。"
        )
    )
    story.append(P("4.2 现有消费者购买行为驱动模型（SEM）", H2))
    story.append(
        P(
            "SEM 分析显示，现有消费者购买行为受「质感属性」（路径系数 0.762***）与「文化属性」"
            "（路径系数 0.521*）共同驱动。质感属性（光泽、手感、包装精致度）是第一成交动力；"
            "文化属性（非遗故事、纹样寓意）显著提升溢价接受度与复购意愿。"
        )
    )
    story.append(P("4.3 目标用户画像（聚类结果）", H2))
    story.append(
        section_table(
            ["客群", "占比", "人口特征", "核心动机", "偏好品类", "价格敏感"],
            [
                ["Ⅰ型·新中式白领", "42.18%", "25-35 岁，一二线城市职员/设计师", "身份表达、通勤点缀", "丝巾、胸针", "中等（接受 220-380 元）"],
                ["Ⅱ型·商务礼品采购", "27.05%", "30-45 岁，企业行政/中层管理", "体面、文化格调", "礼盒、领带", "较低（接受 300-500 元）"],
                ["Ⅲ型·亲子美育家庭", "18.60%", "30-40 岁家长，孩子 6-12 岁", "传统文化启蒙", "研学体验包", "低（接受 160-230 元）"],
                ["Ⅳ型·国潮学生党", "12.17%", "18-24 岁，大学生/初入职场", "社交分享、性价比", "书签、小配饰", "高（接受 99-199 元）"],
            ],
            [28 * mm, 18 * mm, 42 * mm, 28 * mm, 28 * mm, 28 * mm],
        )
    )
    story.append(Spacer(1, 2 * mm))
    story.append(
        P(
            "与「纤毫匠心」核雕项目对比：核雕Ⅰ型潜在消费者占比约 10.04%、更偏亲子教育驱动；"
            "本项目Ⅰ型新中式白领占比 42.18%，商务礼场景更强，适合在知识库问答中做横向对比。"
        )
    )

    story.append(P("五、营销与渠道策略", H1))
    story.append(P("5.1 线上内容与社交种草", H2))
    story.append(
        P(
            "以小红书、抖音、微博为主阵地，发布「宋锦纹样解码」「一分钟辨别真丝宋锦」等内容。"
            "计划首年线上渠道贡献 GMV 占比目标 68.5%，低于核雕项目的 81.4% 线上主导策略，"
            "因商务礼品更依赖线下品鉴与企业直销。"
        )
    )
    story.append(P("5.2 线下文旅与快闪", H2))
    story.append(
        P(
            "在苏州平江路、山塘街及诚品书店商圈开设季节性 Pop-up，提供「上机试织 15 分钟」体验，"
            "将游客转化为线上私域会员。与苏州博物馆、中国昆曲博物馆联名推出限定纹样。"
        )
    )
    story.append(P("5.3 口碑与信任体系", H2))
    story.append(
        P(
            "建立「一织一码」溯源：扫码可查看织造工坊、匠人信息、成分检测与养护指南。"
            "联合第三方质检机构出具桑蚕丝含量报告，打击化纤仿冒，巩固「真丝宋锦」品类心智。"
        )
    )

    story.append(P("六、财务预测与融资规划", H1))
    story.append(P("6.1 2026-2028 年财务收入预测（单位：万元 RMB）", H2))
    story.append(
        section_table(
            ["年度", "线上 GMV", "线下/礼品", "研学体验", "合计营收", "毛利率"],
            [
                ["2026", "320", "180", "60", "560", "52%"],
                ["2027", "680", "360", "140", "1,180", "55%"],
                ["2028", "1,250", "620", "260", "2,130", "58%"],
            ],
            [24 * mm, 28 * mm, 28 * mm, 28 * mm, 28 * mm, 22 * mm],
        )
    )
    story.append(Spacer(1, 3 * mm))
    story.append(P("6.2 融资需求与资金使用规划", H2))
    story.append(
        P(
            "项目拟天使轮融资 RMB 350 万元，释放 12%-18% 股权。资金主要用途分配如下（与核雕项目 200 万/10%-15% 方案可对比）："
        )
    )
    story.append(
        section_table(
            ["投资方向", "预算占比", "金额（万元）", "预期成果/里程碑"],
            [
                ["纹样数字化与新品研发", "28%", "98.0", "完成 30+ 纹样库，上市 12 款核心 SKU"],
                ["全渠道营销与内容", "32%", "112.0", "打造百万级新中式话题，签约 20 位 KOC"],
                ["线下快闪与渠道拓展", "18%", "63.0", "落地 4 城快闪，签约 50 家企业礼品客户"],
                ["供应链与织造产能", "15%", "52.5", "合作 3 家苏州织造工坊，小单快反周期 ≤21 天"],
                ["团队与运营储备", "7%", "24.5", "核心团队扩至 15 人"],
            ],
            [42 * mm, 22 * mm, 28 * mm, 70 * mm],
        )
    )

    story.append(P("七、风险控制与展望", H1))
    story.append(bullet("供应链风险：真丝原料价格波动，采用年度框架采购 + 安全库存。"))
    story.append(bullet("仿冒风险：一织一码 + 平台投诉绿色通道 + 律师函批量维权。"))
    story.append(bullet("内容合规：种草内容标注广告，杜绝虚假「大师手作」宣传。"))
    story.append(Spacer(1, 3 * mm))
    story.append(
        P(
            "结语：「锦上添花」以宋锦为舟、以时尚设计为帆，与苏州核雕等非遗项目共同构成区域文创矩阵。"
            "在知识库场景中，可与《纤毫匠心》商业计划书联合检索，回答「两个项目的融资差异」「客群如何互补」"
            "「防伪体系有何异同」等跨文档问题。"
        )
    )
    story.append(Spacer(1, 6 * mm))
    story.append(P("锦上添花｜苏州宋锦非遗文创商业计划书　　页码见文末", SMALL))
    story.append(P("文档用途：GraphRAG Agent 跨文档联合问答演示素材（虚构项目，仅用于功能演示）", SMALL))

    doc.build(story)
    print(f"OK {OUT} size={OUT.stat().st_size}")


if __name__ == "__main__":
    build()
