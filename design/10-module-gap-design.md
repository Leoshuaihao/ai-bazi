# 10 项缺失模块逐项技术设计方案

> 基于《子平断前事研究报告-终稿.md》与 ai-bazi 现有四层架构（rules/ → services/ → api/ → public/）
> 设计原则：理论先行、规则引擎优先、兼容现有架构、可量化

---

## 第一组：🔴 核心缺失（4 项）

---

## 模块 1：事前不确定参数预标注器

### 理论依据

**报告引用**：第 3 章 "事前不确定参数：五类系统枚举"

五类不确定参数的源起：
- **用神真假**：《滴天髓·真假》"真假参差难辨论，不明不暗受迍邅" + "大纲不与真神照，暗处寻真也有真"
- **旺衰边界**：《滴天髓·旺衰》以五行颠倒十理描述"太旺"与"旺极"之间的模糊地带："木太旺者似金，喜火之炼也；木旺极者似火，喜水之克也"
- **格局层次**：《子平真诠·论用神成败得失》"有先败后成者……有先成后败者……"——格局成败存在动态转化
- **从格真假**：《滴天髓·从化》"真从之象有几人，假从亦可发其身"——真从假从之判带有模糊性
- **时辰准确**：《滴天髓·生时》"时之不的当者，十有四五"——时辰准确性是结构性不确定参数

设计原则（报告第 5 章第 1 步）："在此阶段必须完成「不确定参数枚举」——即对可能出错的关键节点进行预标注"

### 现有代码状态

- `bazi_engine.py`：产出 `BaziChart`，包含 `YongShen`、`WuxingScore`，但没有预标注任何不确定参数
- `rules/yongshen.py`：产出旺衰五等（太旺/偏强/中和/偏弱/太弱），每个维度有得分但未标注边界风险
- `rules/pattern.py`：产出格局类型（`determine_pattern_type`）、从格检测（`_check_special_pattern`），未标注真假从边界或化气格条件满足度
- `true_solar_time.py`：提供真太阳时校正工具，但未集成到预标注系统
- **结论：完全缺失**。没有`UncertaintyReport`概念，没有预标注流程

### 设计方案

#### 1. 新文件：`services/precheck/uncertainty_labeler.py`

#### 2. 数据模型

```python
# models.py 新增
class UncertaintyItem(BaseModel):
    dimension: str         # "shichen"|"yongshen"|"wangshuai"|"pattern"|"congge"
    risk_score: float      # 0.0-1.0, 越高越不确定
    label: str             # "低风险"|"中风险"|"高风险"
    detail: str            # 文字说明
    verification_priority: int  # 建议验证优先级 1-5 (1=最高)
    
class UncertaintyReport(BaseModel):
    items: list[UncertaintyItem]
    overall_risk: float    # 综合风险 0-1
    suggested_questions: list[str]  # 建议的验证问题
```

#### 3. 核心算法：五个维度的量化标注

**维度 1：时辰风险（shichen）**

```python
def _label_shichen_risk(hour: int, minute: int, longitude: float, 
                         month: int, day: int) -> UncertaintyItem:
    risk = 0.0
    details = []
    
    # 1.1 子时边界（子初 23:00 vs 子正 00:00）
    if hour == 23 or hour == 0:
        risk += 0.3
        details.append("子时出生，存在子初/子正边界歧义")
    
    # 1.2 时辰交界 ±30 分钟（任何奇数小时的 0-30 或 58-59 分）
    if hour % 2 == 1:  # 奇数小时为时辰边界
        if minute <= 30:
            risk += 0.2
            details.append(f"生于{hour}时{minute}分，处于时辰交界区域")
    
    # 1.3 节气交接 ±1 小时内（需查节气表）
    jieqi_hours = _get_jieqi_distance(month, day, hour)
    if jieqi_hours is not None and jieqi_hours <= 1.0:
        risk += 0.25
        details.append(f"出生时间距节气交接仅{int(jieqi_hours*60)}分钟，月柱可能错排")
    
    # 1.4 经度偏差 > 30 分钟（即经度差 > 7.5°）
    lon_offset = abs(120.0 - longitude) * 4  # 分钟
    if lon_offset > 30:
        risk += 0.25
        details.append(f"出生地经度偏差{lon_offset:.0f}分钟（东经{longitude}°），真太阳时校正可能改变时辰")
    
    return UncertaintyItem(
        dimension="shichen",
        risk_score=min(risk, 1.0),
        label="高风险" if risk > 0.5 else ("中风险" if risk > 0.2 else "低风险"),
        detail="；".join(details),
        verification_priority=1 if risk > 0.3 else 3
    )
```

**维度 2：用神争议度（yongshen）**

```python
def _label_yongshen_risk(pattern: str, chart_data: dict, dm_stem: str) -> UncertaintyItem:
    risk = 0.0
    details = []
    
    # 2.1 月令藏干多透（2+ 干透出）
    from rules.pattern import detect_ganzhi_touchu
    touchu = detect_ganzhi_touchu(chart_data)
    if touchu.get("level") in ("中气", "余气") and touchu.get("is_strong"):
        risk += 0.25
        details.append(f"月令{touchu['level']}{touchu['touched_stem']}强透，本气{touchu['level']}与透干可能产生两种用神")
    
    # 2.2 三合局可能成立 vs 不成立边界
    from rules.pattern import detect_zhi_heju
    month_branch = chart_data.get("four_pillars", {}).get("month", {}).get("branch", "")
    heju = detect_zhi_heju(chart_data, month_branch)
    if heju.get("type") == "半合":
        risk += 0.20
        details.append(f"月支{month_branch}构成半合局，若补齐则用神可能改变")
    
    # 2.3 真神假神判别：用神透干无根 vs 藏干有根不透
    from rules.pattern import PATTERN_XIANGSHEN_RULES, _check_shen_status
    yongshen_rules = PATTERN_XIANGSHEN_RULES.get(pattern, {})
    ys_tg = yongshen_rules.get("yongshen", "")
    exists, has_root, touches = _check_shen_status(ys_tg, chart_data)
    if touches and not has_root:
        risk += 0.20
        details.append(f"用神{ys_tg}透干但无根，可能为假神")
    elif has_root and not touches:
        risk += 0.15
        details.append(f"用神{ys_tg}有根但未透干，力量隐伏")
    
    return UncertaintyItem(
        dimension="yongshen",
        risk_score=min(risk, 1.0),
        label="高风险" if risk > 0.5 else ("中风险" if risk > 0.2 else "低风险"),
        detail="；".join(details) or "用神判定无明显争议",
        verification_priority=2
    )
```

**维度 3：旺衰模糊度（wangshuai）**

```python
def _label_wangshuai_risk(strength_detail: dict) -> UncertaintyItem:
    """判断旺衰五等的边界模糊度"""
    total = strength_detail.get("total_score", 50)
    risk = 0.0
    details = []
    
    # 旺衰五等边界：
    # 极旺(>85) → 身旺(65-85) → 中和(35-65) → 身弱(15-35) → 极弱(<15)
    
    # 边界模糊区间（前后 ±8 分）
    if 57 <= total <= 73:  # 身旺与中和边界
        risk += 0.30
        details.append(f"得分{total}处于身旺与中和边界（65±8），取用方向可能有歧义")
    elif 27 <= total <= 43:  # 中和与身弱边界
        risk += 0.30
        details.append(f"得分{total}处于中和与身弱边界（35±8），取用方向可能有歧义")
    elif 77 <= total <= 93:  # 身旺与极旺（太旺 vs 旺极）边界
        risk += 0.35
        details.append(f"得分{total}处于身旺与极旺边界（85±8），'太旺'宜泄 vs '旺极'宜生")
    elif 7 <= total <= 23:  # 身弱与极弱（太衰 vs 衰极）边界
        risk += 0.35
        details.append(f"得分{total}处于身弱与极弱边界（15±8），'太衰'宜生 vs '衰极'宜顺")
    
    # 检查四要素得分的离散度
    deling = strength_detail.get("deling", {}).get("score", 0)
    dedi = strength_detail.get("dedi", {}).get("score", 0)
    desheng = strength_detail.get("desheng", {}).get("score", 0)
    dezhu = strength_detail.get("dezhu", {}).get("score", 0)
    scores = [deling, dedi, desheng, dezhu]
    max_s = max(scores) if scores else 1
    min_s = min(scores)
    if max_s > 0 and (max_s - min_s) / max_s > 0.7:
        risk += 0.15
        details.append("四要素得分离散度大（某个要素极强但其他要素极弱）")
    
    return UncertaintyItem(
        dimension="wangshuai",
        risk_score=min(risk, 1.0),
        label="高风险" if risk > 0.5 else ("中风险" if risk > 0.2 else "低风险"),
        detail="；".join(details) or "旺衰判定无明显模糊",
        verification_priority=2
    )
```

**维度 4：格局多解性（pattern）**

```python
def _label_pattern_risk(primary_pattern: str, strength_detail: dict, 
                        chart_data: dict, dm_stem: str) -> UncertaintyItem:
    risk = 0.0
    details = []
    total = strength_detail.get("total_score", 50)
    
    # 4.1 正格 vs 从格边界（总分 15-25 或 75-85）
    if 15 <= total <= 25:
        risk += 0.40
        details.append(f"得分{total}处于正格身弱与从格边界（15-25），可能为从格")
    elif 75 <= total <= 85:
        risk += 0.40
        details.append(f"得分{total}处于正格身旺与专旺格边界（75-85），可能为从强格")
    
    # 4.2 化气格条件接近满足
    from rules.pattern import check_huaqi_ge, _detect_huaqi_wuxing
    huaqi_wx = _detect_huaqi_wuxing(dm_stem, chart_data)
    if huaqi_wx:
        month_branch = chart_data.get("four_pillars", {}).get("month", {}).get("branch", "")
        from rules.pattern import get_month_stems
        month_stems = get_month_stems(month_branch)
        month_wx_set = {WUXING_MAP.get(s, "") for s in month_stems}
        if huaqi_wx in month_wx_set:
            risk += 0.30
            details.append(f"日主参与天干五合化{huaqi_wx}，化神在月令得气，可能为化气格")
    
    # 4.3 格局混杂（官杀混杂 / 正偏混杂）
    from rules.pattern import check_purity
    purity = check_purity(primary_pattern, chart_data)
    if purity.get("is_mixed"):
        risk += 0.20
        details.append(f"格局{purity['mix_type']}，清浊难辨")
    
    return UncertaintyItem(
        dimension="pattern",
        risk_score=min(risk, 1.0),
        label="高风险" if risk > 0.5 else ("中风险" if risk > 0.2 else "低风险"),
        detail="；".join(details) or "格局判定无多解性",
        verification_priority=3
    )
```

**维度 5：从格真假（congge）**

```python
def _label_congge_risk(pattern: str, strength_detail: dict, 
                       chart_data: dict, dm_stem: str) -> UncertaintyItem:
    risk = 0.0
    details = []
    
    # 只有当前格局与从格相关时才计算
    if "从" not in pattern and "专旺" not in pattern:
        return UncertaintyItem(
            dimension="congge", risk_score=0, label="低风险",
            detail="非从格格局，不适用", verification_priority=5
        )
    
    from rules.pattern import check_zhen_jia_cong
    zj = check_zhen_jia_cong(chart_data)
    if not zj.get("is_zhen"):
        reason = zj.get("reason", "")
        if "有根" in reason:
            risk += 0.35
            details.append(f"假从：日主有微根（{reason}），从得不纯")
        elif "印比暗藏" in reason:
            risk += 0.30
            details.append(f"假从：日主有印比暗藏（{reason}），自顾不暇但仍有牵绊")
    
    # 量化"微根"：检查日主藏干根的权重
    dm_wx = WUXING_MAP.get(dm_stem, "")
    fp = chart_data.get("four_pillars", {})
    max_root_weight = 0.0
    for pos in ["year", "month", "day", "hour"]:
        for hs in fp.get(pos, {}).get("hidden_stems", []):
            s = hs.get("stem", "") if isinstance(hs, dict) else hs
            w = hs.get("weight", 0.3) if isinstance(hs, dict) else 0.3
            if WUXING_MAP.get(s, "") == dm_wx:
                max_root_weight = max(max_root_weight, w)
    
    if 0 < max_root_weight < 0.5:  # 只有余气根
        risk += 0.25
        details.append(f"日主仅余气通根（最大权重{max_root_weight}），界于'无根无气'与'根浅力薄'之间")
    
    return UncertaintyItem(
        dimension="congge",
        risk_score=min(risk, 1.0),
        label="高风险" if risk > 0.5 else ("中风险" if risk > 0.2 else "低风险"),
        detail="；".join(details) or "从格判定清晰",
        verification_priority=4
    )
```

#### 4. 主函数接口

```python
def generate_uncertainty_report(
    chart: BaziChart,
    strength_detail: dict,
    chart_data: dict,
    birth_longitude: float = 120.0,
) -> UncertaintyReport:
    """生成不确定参数预标注报告
    
    Args:
        chart: BaziChart（bazi_engine.py 输出）
        strength_detail: calculate_strength_detail 输出
        chart_data: chart.model_dump()
        birth_longitude: 出生地经度（默认北京 120°）
    
    Returns:
        UncertaintyReport: 五维标注报告
    """
    dm_stem = chart.day_master
    items = []
    
    # 维度 1: 时辰风险
    items.append(_label_shichen_risk(
        hour=chart_data.get("birth_info", {}).get("hour", 12),
        minute=chart_data.get("birth_info", {}).get("minute", 0),
        longitude=birth_longitude,
        month=chart_data.get("birth_info", {}).get("month", 1),
        day=chart_data.get("birth_info", {}).get("day", 1),
    ))
    
    # 维度 2: 用神争议度
    pattern = chart.yongshen.pattern
    items.append(_label_yongshen_risk(pattern, chart_data, dm_stem))
    
    # 维度 3: 旺衰模糊度
    items.append(_label_wangshuai_risk(strength_detail))
    
    # 维度 4: 格局多解性
    items.append(_label_pattern_risk(pattern, strength_detail, chart_data, dm_stem))
    
    # 维度 5: 从格真假
    items.append(_label_congge_risk(pattern, strength_detail, chart_data, dm_stem))
    
    # 综合风险 = 前4个维度加权平均（权重递减：时辰最重要）
    weights = [0.30, 0.25, 0.20, 0.15, 0.10]
    overall = sum(item.risk_score * w for item, w in zip(items, weights))
    
    # 生成建议验证问题（按优先级取 Top 3）
    sorted_items = sorted(items, key=lambda x: (x.verification_priority, -x.risk_score))
    suggested = [
        f"[{item.dimension}] {item.label}: {item.detail}"
        for item in sorted_items[:3]
    ]
    
    return UncertaintyReport(
        items=items,
        overall_risk=round(overall, 2),
        suggested_questions=suggested,
    )
```

#### 5. Mock 回退

```python
def mock_uncertainty_report() -> UncertaintyReport:
    """无数据时的保守回退：所有维度标注中风险"""
    return UncertaintyReport(
        items=[UncertaintyItem(dimension=d, risk_score=0.3, label="中风险",
                detail="缺少排盘数据，默认中风险", verification_priority=i+1)
               for i, d in enumerate(["shichen","yongshen","wangshuai","pattern","congge"])],
        overall_risk=0.3,
        suggested_questions=["建议完成排盘后再进行不确定参数分析"],
    )
```

### 与现有代码的关系

| 操作 | 文件 |
|------|------|
| **新增** | `services/precheck/__init__.py` |
| **新增** | `services/precheck/uncertainty_labeler.py` |
| **修改** | `models.py`：新增 `UncertaintyItem`、`UncertaintyReport` |
| **修改** | `bazi_engine.py`：在 build 流程末尾调用 `generate_uncertainty_report` |
| **不变** | `rules/yongshen.py`、`rules/pattern.py`、`true_solar_time.py` 现有逻辑不变 |

### 测试验证

1. **时辰高/低风险对比**：子时出生（23:00）+ 成都经度（104°）→ risk ≥ 0.6；午时（12:00）+ 上海（121°）→ risk < 0.2
2. **旺衰边界探测**：total_score=62（身旺/中和边界）→ risk ≥ 0.3；total_score=50 → risk=0
3. **用神争议**：月令中气强透 → risk ≥ 0.25；单透本气 → risk=0
4. **从格真假**：日主仅余气根 weight=0.3 → risk ≥ 0.25；日主本气根 weight=0.7 → not applicable（非从格触发）

---

## 模块 2：六维验证评分卡

### 理论依据

**报告引用**：第 2 章 2.2 节 "六大验证维度体系"

六大维度及其古籍依据：
- **旺衰验证**：《滴天髓·旺衰》五行颠倒十理——任铁樵以二十造实例证明"此等格局颇多……以致吉凶颠倒"
- **格局喜忌验证**：《子平真诠·论用神成败得失》"救应"理论 + 《论行运》"运向用神则吉，运背用神则凶"
- **用神验证**：《滴天髓·真假》"真神得用生平贵，用假终为碌碌人"
- **大运走向验证**：《子平真诠·论行运成格变格》"大运交脱之际，亦为人生之转折点"
- **六亲验证**：《渊海子平·六亲总篇》十神配六亲 + 《子平真诠·论六亲》"六亲之论，以十神定其本，以宫位明其位"
- **性格验证**：《渊海子平·论性情》五行配五常 + 《滴天髓·论性情》十种性情类型

### 现有代码状态

- `services/calibration.py`：实现了三关判定（父母关、兄弟关、婚姻关）+ 辅助项判定 + 最终 verdict，但维度单一（仅按"准确/部分准确/不准确"计数），缺乏六维打分和古籍引用能力
- `services/reconciler.py`：对账器（对 predictions 和 feedbacks 做匹配），但未从六维角度计算
- **结论：部分实现**。有基础校准框架，但完全没有六维验证体系

### 设计方案

#### 1. 扩展 `services/calibration.py`，新增 `HexagramValidator` 类

#### 2. 每个维度的打分函数

```python
class HexagramValidator:
    """六维验证评分卡
    
    六大验证维度，每个维度 0-10 分，输出打分依据 + 古籍引用
    """
    
    SOURCES = {
        "旺衰验证": "《滴天髓·旺衰》：'能知衰旺之真机，其于三命之奥，思过半矣'",
        "格局喜忌验证": "《子平真诠·论用神成败得失》：'用神之成，在于得护得救。用神之败，在于被伤被破'",
        "用神验证": "《滴天髓·真假》：'令上寻真聚得真，假神休要乱真神'",
        "大运走向验证": "《子平真诠·论大运流年》：'大运交脱之际，亦为人生之转折点'",
        "六亲验证": "《渊海子平·六亲总篇》：'用日干为主：正印正母；偏印偏母及祖父也'",
        "性格验证": "《滴天髓·论性情》：'五气不戾，性正情和；浊乱偏枯，性乖情逆'",
    }
```

**维度 1：旺衰验证（0-10）**

```python
def score_wangshuai(self, chart_data: dict, feedbacks: list[dict], 
                    predictions: list[dict]) -> dict:
    """
    大运吉凶方向反推法：
    遍历每步大运，计算"喜忌运的吉凶一致性"
    - 喜神运中用户反馈 positive 的比例
    """
    yongshen = chart_data.get("yongshen", {})
    ri_zhu_strength = yongshen.get("ri_zhu_strength", "")
    dayun = chart_data.get("dayun", [])
    
    # 根据旺衰确定喜忌五行
    is_strong = ri_zhu_strength in ("偏强", "太旺", "极旺")
    is_weak = ri_zhu_strength in ("偏弱", "太弱", "极弱")
    
    happy_wx = set()  # 喜神五行集合
    bad_wx = set()    # 忌神五行集合
    
    primary = yongshen.get("primary", "")
    ji_shen = yongshen.get("ji_shen", "")
    if primary:
        happy_wx.add(primary)
    if ji_shen:
        bad_wx.add(ji_shen)
    
    # 收集用户反馈中关于"运势好坏"的有效条目
    positive_years = set()  # 用户确认好的年份/时期
    negative_years = set()  # 用户反馈差的年份/时期
    
    pred_map = {p.get("id"): p for p in predictions}
    for fb in feedbacks:
        pred = pred_map.get(fb.get("prediction_id"), {})
        content = pred.get("content", "") + fb.get("note", "")
        # 从内容和备注中提取年份/时期信息
        # ...提取逻辑...
        if fb.get("status") == "accurate":
            positive_years.add(pred.get("basis", ""))
        elif fb.get("status") == "inaccurate":
            negative_years.add(pred.get("basis", ""))
    
    # TODO: 对每个大运计算喜忌匹配度
    # 简化版：统计大运十神的喜忌分布
    happy_dayun_count = 0
    total_dayun_rated = 0
    
    from rules.pattern import PATTERN_DAYUN_RULES, get_dayun_xiji
    xiji = get_dayun_xiji(yongshen.get("pattern", ""))
    xi_shi_shen = set(xiji.get("xi", []))
    ji_shi_shen = set(xiji.get("ji", []))
    
    for da in dayun:
        tg = da.get("ten_god", "")
        if tg in xi_shi_shen:
            happy_dayun_count += 1
        elif tg in ji_shi_shen:
            total_dayun_rated += 1
    
    # 打分：喜神运越多越应见顺遂
    if total_dayun_rated == 0:
        score = 5
        detail = "无足够大运数据评估旺衰"
    else:
        ratio = happy_dayun_count / max(total_dayun_rated, 1)
        score = min(10, int(ratio * 10))
        detail = f"喜神大运比例 {ratio:.0%}，{happy_dayun_count}/{total_dayun_rated} 步大运为喜运"
    
    return {
        "dimension": "旺衰验证",
        "score": score,
        "detail": detail,
        "source": self.SOURCES["旺衰验证"],
    }
```

**维度 2：格局喜忌验证（0-10）**

```python
def score_pattern_jixi(self, chart_data: dict, feedbacks: list[dict],
                       predictions: list[dict]) -> dict:
    """对每个大运标记'喜/忌/中性'，计算用户反馈分布"""
    yongshen = chart_data.get("yongshen", {})
    pattern = yongshen.get("pattern", "")
    dayun = chart_data.get("dayun", [])
    
    from rules.pattern import PATTERN_DAYUN_RULES
    xiji = PATTERN_DAYUN_RULES.get(pattern, {"xi": [], "ji": []})
    xi_ten_gods = set(xiji.get("xi", []))
    ji_ten_gods = set(xiji.get("ji", []))
    
    # 收集每个大运的用户反馈分布
    dayun_feedback = []
    for da in dayun:
        tg = da.get("ten_god", "")
        is_xi = tg in xi_ten_gods
        is_ji = tg in ji_ten_gods
        if not is_xi and not is_ji:
            continue  # 中性运不参与评分
        
        # 找到该大运期间用户反馈的正/负面倾向
        # ...匹配逻辑...
        dayun_feedback.append({
            "dayun": f"{da.get('stem','')}{da.get('branch','')}",
            "expected": "喜" if is_xi else "忌",
            "actual": "N/A"  # 需从用户反馈推断
        })
    
    # 简化打分
    if not dayun_feedback:
        return {"dimension": "格局喜忌验证", "score": 5, 
                "detail": "无大运反馈数据", "source": self.SOURCES["格局喜忌验证"]}
    
    matched = sum(1 for d in dayun_feedback if d.get("matched"))
    score = min(10, int(matched / len(dayun_feedback) * 10))
    
    return {
        "dimension": "格局喜忌验证",
        "score": score,
        "detail": f"大运喜忌匹配度 {matched}/{len(dayun_feedback)}",
        "source": self.SOURCES["格局喜忌验证"],
    }
```

**维度 3：用神验证（0-10）**

```python
def score_yongshen(self, chart_data: dict, feedbacks: list[dict],
                   predictions: list[dict]) -> dict:
    """选取 ≥3 个用神透干/得禄的流年，检查用户反馈"""
    yongshen = chart_data.get("yongshen", {})
    ys_wx = yongshen.get("primary", "")
    
    # 从大运+流年中找出用神五行透干的年份（≥3个）
    from rules.pattern import WUXING_MAP
    ys_years = []
    dayun = chart_data.get("dayun", [])
    
    for da in dayun:
        da_stem = da.get("stem", "")
        da_start = da.get("start_year", 0)
        if WUXING_MAP.get(da_stem, "") == ys_wx:
            # 该大运用神透干
            for offset in range(10):
                yr = da_start + offset
                ys_years.append({"year": yr, "type": "dayun_stem"})
    
    # 也考虑天干透出用神的流年
    # ...
    
    # 取前 3 个有反馈的
    verified = 0
    total = min(len(ys_years), 3)
    if total == 0:
        return {"dimension": "用神验证", "score": 5, 
                "detail": "未找到用神透干的流年", "source": self.SOURCES["用神验证"]}
    
    for yr in ys_years[:3]:
        yr_str = str(yr["year"])
        # 检查是否有该年份的正面反馈
        for fb in feedbacks:
            if yr_str in fb.get("note", "") and fb.get("status") == "accurate":
                verified += 1
                break
    
    score = min(10, int(verified / total * 10))
    return {
        "dimension": "用神验证",
        "score": score,
        "detail": f"{verified}/{total} 个用神流年验证通过",
        "source": self.SOURCES["用神验证"],
    }
```

**维度 4：大运走向验证（0-10）**

```python
def score_dayun_trend(self, chart_data: dict, feedbacks: list[dict],
                      predictions: list[dict]) -> dict:
    """交运前后 ±2 年的反馈变化方向是否符合大运转换"""
    dayun = chart_data.get("dayun", [])
    xx = list(xiji.get("xi", []))
    jj = list(xiji.get("ji", []))
    
    transitions = 0
    matched = 0
    
    for i in range(1, len(dayun)):
        prev = dayun[i-1]
        curr = dayun[i]
        prev_tg = prev.get("ten_god", "")
        curr_tg = curr.get("ten_god", "")
        
        # 判断方向：从喜→忌应见向下转折，忌→喜应见向上
        if prev_tg in xx and curr_tg in jj:
            expected = "down"  # 从喜到忌应转差
        elif prev_tg in jj and curr_tg in xx:
            expected = "up"    # 从忌到喜应转好
        else:
            continue
        
        transitions += 1
        # 检查反馈中是否有该转换期的验证
        # ...
    
    if transitions == 0:
        return {"dimension": "大运走向验证", "score": 5, 
                "detail": "无可用的大运转换点", "source": self.SOURCES["大运走向验证"]}
    
    score = min(10, int(matched / transitions * 10))
    return {
        "dimension": "大运走向验证",
        "score": score,
        "detail": f"{matched}/{transitions} 个大运转换点验证一致",
        "source": self.SOURCES["大运走向验证"],
    }
```

**维度 5：六亲验证（0-10）**

```python
def score_six_kin(self, chart_data: dict, feedbacks: list[dict],
                  predictions: list[dict]) -> dict:
    """
    将 predictions 中六亲相关断事的反馈映射到对应十神的旺衰喜忌
    六亲→十神映射（《渊海子平·六亲总篇》）：
    - 父母→偏财(父)、正印(母)
    - 兄弟→比肩/劫财
    - 配偶→正财(妻)、正官(夫)
    - 子女→食神(子)、伤官(女)
    """
    kin_map = {
        "父母关": {"偏财": "父亲", "正印": "母亲"},
        "兄弟关": {"比肩": "手足", "劫财": "手足"},
        "婚姻关": {"正财": "配偶", "正官": "配偶"},
    }
    
    # 收集六亲类别的反馈
    kin_feedbacks = []
    pred_map = {p.get("id"): p for p in predictions}
    for fb in feedbacks:
        pred = pred_map.get(fb.get("prediction_id"), {})
        if pred.get("category") in kin_map:
            kin_feedbacks.append({
                "category": pred["category"],
                "status": fb["status"],
                "note": fb.get("note", ""),
            })
    
    if not kin_feedbacks:
        return {"dimension": "六亲验证", "score": 5, 
                "detail": "无六亲相关反馈", "source": self.SOURCES["六亲验证"]}
    
    accurate = sum(1 for f in kin_feedbacks if f["status"] == "accurate")
    score = min(10, int(accurate / len(kin_feedbacks) * 10))
    
    return {
        "dimension": "六亲验证",
        "score": score,
        "detail": f"{accurate}/{len(kin_feedbacks)} 六亲推断准确",
        "source": self.SOURCES["六亲验证"],
        "warning": "注意防范巴纳姆效应：性格描述有泛化倾向，不作为独立决策依据",
    }
```

**维度 6：性格验证（0-10）**

```python
def score_personality(self, chart_data: dict, feedbacks: list[dict],
                      predictions: list[dict]) -> dict:
    """
    性格推断反馈与十神组合推论对照
    《滴天髓·论性情》：以旺衰描述十种性情类型
    《渊海子平·论性情》：五行配五常（仁/礼/信/义/智）
    
    ⚠️ 防巴纳姆效应：要求具体化表述
    - "为人正直" → 太泛
    - "在规则面前不愿妥协，曾因此与人发生冲突" → 具体化
    """
    personality_fbs = []
    pred_map = {p.get("id"): p for p in predictions}
    for fb in feedbacks:
        pred = pred_map.get(fb.get("prediction_id"), {})
        if pred.get("category") == "性格":
            personality_fbs.append(fb)
    
    if not personality_fbs:
        return {"dimension": "性格验证", "score": 5, 
                "detail": "无性格反馈", "source": self.SOURCES["性格验证"]}
    
    accurate = sum(1 for f in personality_fbs if f["status"] == "accurate")
    # 性格验证权重降低 50%（防范巴纳姆效应）
    adjusted_accurate = accurate * 0.5
    score = min(10, int(adjusted_accurate / len(personality_fbs) * 10))
    
    return {
        "dimension": "性格验证",
        "score": score,
        "detail": f"{accurate}/{len(personality_fbs)} 性格推断准确（经巴纳姆效应 50% 折扣）",
        "source": self.SOURCES["性格验证"],
    }
```

#### 3. 聚合判定逻辑

```python
def aggregate(self, scores: list[dict]) -> dict:
    """
    聚合六维打分卡，输出 HexagramReport
    
    判定标准（来自报告 2.5 节）：
    - ≥4/6 维度一致性（score ≥ 6 视为一致）
    - ≤1 个明确反例
    - ≥3 个独立流年交叉验证通过
    """
    consistent_dims = [s for s in scores if s["score"] >= 6]
    inconsistent_dims = [s for s in scores if s["score"] < 6]
    
    # 核心三角（前三个维度已构成）
    core_triangle_pass = all(
        scores[i]["score"] >= 6 for i in range(min(3, len(scores)))
    )
    
    return {
        "total_score": sum(s["score"] for s in scores),
        "max_score": len(scores) * 10,
        "consistent_count": len(consistent_dims),
        "consistent_ratio": len(consistent_dims) / max(len(scores), 1),
        "inconsistent_dims": [s["dimension"] for s in inconsistent_dims],
        "scores": scores,
        "core_triangle_pass": core_triangle_pass,
        "pass": len(consistent_dims) >= 4,
    }
```

### 与现有代码的关系

| 操作 | 文件 |
|------|------|
| **修改** | `services/calibration.py`：新增 `HexagramValidator` 类（≈300 行） |
| **新增** | `models.py`：`HexagramReport` 数据模型 |
| **不变** | 现有 `judge_core_gates`、`judge_auxiliary`、`final_verdict` 保持不变 |

### 测试验证

1. **全准确场景**：全部 7 条 feedback 为 accurate → 6 维度应全 ≥ 8 分
2. **全不准确**：全部 inaccurate → 6 维度 ≤ 3 分
3. **核心三角崩溃**：前 3 维度 ≤ 3 但后 3 维度 ≥ 8 → aggregate 应为 FAIL
4. **性格巴纳姆**：仅性格维度 10 分、其余 0 分 → 综合 < 4/6 一致性

---

## 模块 3：验证判定三重标准

### 理论依据

**报告引用**：第 2 章 2.5 节 "验证成功与失败的判定标准"

三重判定标准：
1. **多维一致性（≥4/6）**：前三个维度构成"核心三角"（旺衰→格局→用神），此三角一致是验证通过的最低门槛
2. **反例容限（≤1）**：不允许出现与核心判断直接矛盾的明确反例
3. **流年交叉一致性（≥3）**：至少 3 个以上互不关联的关键流年验证一致

"视为验证失败"的情形：
- 核心三角任一维度矛盾
- 2+ 明确反例
- 六亲既定事实与推论根本矛盾

### 现有代码状态

- `services/calibration.py`：`final_verdict()` 有五级判定（passed/ai_fix/ai_fix_first/hour_fix），但未实现三重标准
- `services/correction_v2.py`：`CorrectionEngine` 有渐进修正，但触发条件以准确率（accuracy）为单位，而非六维维度级别
- **结论：部分实现**。有基本校准判定逻辑，但缺少三重标准的显式实现和"明确反例"的量化定义

### 设计方案

#### 在 `HexagramValidator` 中新增三个判定函数

```python
# === 判定函数 1：多维一致性 ===
def check_multidimensional_consistency(self, hexagram_scores: list[dict]) -> dict:
    """
    判定 ≥4/6 维度一致性（score ≥ 6 视为一致）
    核心三角（旺衰→格局→用神）任意维度矛盾则失败
    """
    core_dims = ["旺衰验证", "格局喜忌验证", "用神验证"]
    core_scores = {s["dimension"]: s["score"] for s in hexagram_scores}
    
    core_all_pass = all(core_scores.get(d, 0) >= 6 for d in core_dims)
    total_consistent = sum(1 for s in hexagram_scores if s["score"] >= 6)
    
    return {
        "name": "多维一致性",
        "pass": total_consistent >= 4,
        "detail": f"{total_consistent}/6 维度一致（需 ≥4）",
        "core_triangle_pass": core_all_pass,
        "core_triangle_detail": " → ".join(
            f"{d}({core_scores.get(d, 'N/A')}分)" for d in core_dims
        ),
    }
```

```python
# === 判定函数 2：反例容限 ===
def check_counter_examples(self, hexagram_scores: list[dict], 
                           feedbacks: list[dict], predictions: list[dict]) -> dict:
    """
    "明确反例"的判定标准（量化定义）：
    
    【明确反例 A 类：用神到位之年遭遇重大灾厄】
    - 反馈标注为 inaccurate 且 note 中提到重大负面事件
    - 对应推断的 confidence ≥ 0.80（系统高度自信此推断）
    
    【明确反例 B 类：六亲既定事实与推论根本矛盾】
    - 六亲类别推断 → inaccurate
    - 且 note 中用户补充了明确反例（如"我父母早已离婚"、"我是独子"）
    
    【非关键偏差（允许）】：
    - 情绪波动与运势方向不一致
    - partial 反馈（部分准确部分不准）
    - 低置信度（confidence < 0.60）推断的不准确
    """
    pred_map = {p.get("id"): p for p in predictions}
    counter_examples = []
    
    for fb in feedbacks:
        pred = pred_map.get(fb.get("prediction_id"), {})
        status = fb.get("status", "")
        confidence = pred.get("confidence", 0.5)
        note = fb.get("note", "")
        category = pred.get("category", "")
        
        # 判定 A 类
        if status == "inaccurate" and confidence >= 0.80:
            # 检查 note 中是否包含重大负面事件
            negative_keywords = ["重大", "灾", "祸", "离婚", "去世", "破产", "失业", "事故"]
            is_major = any(kw in note for kw in negative_keywords)
            if is_major:
                counter_examples.append({
                    "type": "A",
                    "category": category,
                    "detail": f"高置信推断({confidence}) → 用户否定，涉及重大负面事件",
                    "is_major": True,
                })
            elif category in ("关键年份", "事业"):
                counter_examples.append({
                    "type": "A_light",
                    "category": category,
                    "detail": f"高置信推断({confidence}) → 用户否定",
                    "is_major": False,
                })
        
        # 判定 B 类
        if status == "inaccurate" and category in ("父母关", "兄弟关", "婚姻关"):
            # 六亲类别的 inaccurate 自动升级为明确反例
            counter_examples.append({
                "type": "B",
                "category": category,
                "detail": f"{category}推断错误，可能涉及既定事实矛盾" + (f"：{note}" if note else ""),
                "is_major": True,
            })
    
    major_count = sum(1 for ex in counter_examples if ex.get("is_major"))
    
    return {
        "name": "反例容限",
        "pass": major_count <= 1,
        "total_counter_examples": len(counter_examples),
        "major_counter_examples": major_count,
        "examples": counter_examples,
        "detail": f"{major_count} 个明确反例（允许 ≤1）",
    }
```

```python
# === 判定函数 3：流年交叉一致性 ===
def check_liunian_cross_validation(self, chart_data: dict, 
                                   feedbacks: list[dict]) -> dict:
    """
    至少 3 个互不关联的关键流年验证一致
    
    "互不关联"的定义：
    - 不在同一大运内
    - 不属于连续年份（间隔 ≥ 2 年）
    """
    # 从 feedback 中提取已验证的年份
    verified_years = []
    
    for fb in feedbacks:
        note = fb.get("note", "")
        status = fb.get("status", "")
        # 从 note 中提取年份
        import re
        years = re.findall(r'(19\d{2}|20\d{2})', note)
        for yr_str in years:
            yr = int(yr_str)
            if status == "accurate":
                verified_years.append({"year": yr, "status": "verified"})
            elif status == "inaccurate":
                verified_years.append({"year": yr, "status": "contradicted"})
    
    # 去重并按大运分组
    dayun = chart_data.get("dayun", [])
    
    def get_dayun_for_year(year: int) -> int:
        for i, da in enumerate(dayun):
            if da.get("start_year", 0) <= year <= da.get("end_year", 9999):
                return i
        return -1
    
    # 选取互不关联的年份
    selected = []
    used_dayun = set()
    
    for yr_item in verified_years:
        dn = get_dayun_for_year(yr_item["year"])
        if dn in used_dayun or dn < 0:
            continue
        # 确保不与已选年份连续
        if any(abs(yr_item["year"] - s["year"]) < 2 for s in selected):
            continue
        selected.append(yr_item)
        used_dayun.add(dn)
    
    consistent = sum(1 for s in selected if s["status"] == "verified")
    
    return {
        "name": "流年交叉一致性",
        "pass": len(selected) >= 3 and consistent >= 3,
        "detail": f"{consistent}/{len(selected)} 个互不关联的流年验证一致（需 ≥3）",
        "selected_years": selected,
    }
```

#### 最终判定函数

```python
def final_verdict_v2(self, 
                     multi_dim: dict, 
                     counter_ex: dict, 
                     liunian: dict) -> dict:
    """
    三重标准综合判定：
    
    PASS:           全部通过 → 锁定命盘
    CONDITIONAL_PASS: 2/3 通过 → 可进入但不锁死
    INDETERMINATE:    1/3 通过 → 数据不足
    FAIL:             0/3 通过 → 触发修正
    """
    passes = [multi_dim["pass"], counter_ex["pass"], liunian["pass"]]
    pass_count = sum(passes)
    
    if pass_count == 3:
        status = "PASS"
        message = "三重标准全部通过，命盘可锁定。"
        need_correction = False
    elif pass_count == 2:
        status = "CONDITIONAL_PASS"
        message = "两重标准通过，可进入断未来但不锁死。"
        need_correction = False
    elif pass_count == 1:
        status = "INDETERMINATE"
        message = "仅一重标准通过，数据不足，建议增加验证问题。"
        need_correction = True
    else:
        status = "FAIL"
        message = "三重标准全部失败，必须触发修正流程。"
        need_correction = True
    
    # FAIL 时自动触发修正（调用 correction_v2.py）
    correction_trigger = None
    if need_correction and status == "FAIL":
        correction_trigger = {
            "level": 0 if not multi_dim["core_triangle_pass"] else 1,
            "reason": "核心三角失败" if not multi_dim["core_triangle_pass"] 
                      else f"反例过多({counter_ex['major_counter_examples']}个) + 流年验证不足",
        }
    
    return {
        "status": status,
        "message": message,
        "pass_count": pass_count,
        "criteria": {
            "multi_dim": multi_dim,
            "counter_examples": counter_ex,
            "liunian_cross": liunian,
        },
        "need_correction": need_correction,
        "correction_trigger": correction_trigger,
    }
```

### 与现有代码的关系

| 操作 | 文件 |
|------|------|
| **修改** | `services/calibration.py`：在 `HexagramValidator` 中实现三重判定 |
| **不变** | 现有 `run_calibration` 保持向后兼容，新增 `run_calibration_v2` 调用新方法 |

### 测试验证

1. **PASS 场景**：三关全 accurate + 多个流年验证一致 → 3/3 通过
2. **FAIL 场景（核心三角崩溃）**：旺衰维度 2 分 → 核心三角失败 → FAIL
3. **FAIL 场景（过多反例）**：六亲反馈两条 inaccurate + 关键年份 inaccurate → ≥2 明确反例 → FAIL
4. **CONDITIONAL_PASS**：核心三角 2/3 + 0 反例 + 2 流年验证 → 2/3 通过

---

## 模块 4：宫位取象规则模块

### 理论依据

**报告引用**：第 2 章 2.3 节 "信息推导逻辑：中间层四要素的主次关系"

宫位取象的角色是"空间锚定"（次），在十神和生克的基础上确定事件发生的具体人生领域。

理论基础：
- 《子平真诠·论六亲》（宫位部分）："六亲之论，以十神定其本，以宫位明其位，以旺衰判其力。三者合参，六亲之事可推矣。"
- 四柱对应的年龄分段：年柱 1-16 岁、月柱 17-32 岁、日柱 33-48 岁、时柱 49 岁以后

### 现有代码状态

- `rules/` 目录下没有宫位取象相关的模块
- `services/predictions.py` 中 `_build_parents`、`_build_siblings`、`_build_marriage` 等函数有简单的宫位逻辑（如年柱→父母关），但不成体系
- `bazi_engine.py` 有四柱拆分（year/month/day/hour）但未按宫位维度进行系统化规则封装
- `rules/pattern.py` 有一些支合冲检查函数，但未从宫位角度组织
- **结论：完全缺失**。没有专门的宫位取象规则模块

### 设计方案

#### 新文件：`rules/gongwei.py`

```python
"""宫位取象规则模块 - 子平格局派
理论基础：《子平真诠·论六亲》宫位部分
"六亲之论，以十神定其本，以宫位明其位，以旺衰判其力"
"""

# ============================================================
# 宫位取象规则表
# ============================================================

GONGWEI_RULES = {
    "年柱": {
        "domain": "祖上/童年",
        "age_range": (1, 16),
        "six_kin": ["祖父母", "父母"],
        "event_types": ["家庭出身", "祖业", "童年运势", "先天禀赋"],
        "social_layer": "根源层",
        "classical_source": "《子平真诠》：'年为祖上，乃根基所在'",
    },
    "月柱": {
        "domain": "父母/门第",
        "age_range": (17, 32),
        "six_kin": ["父母", "兄弟"],
        "event_types": ["学历", "事业起步", "父母状况", "社交圈"],
        "social_layer": "成长层",
        "classical_source": "《子平真诠》：'月为提纲，父母兄弟之宫'",
    },
    "日柱": {
        "domain": "自身/配偶",
        "age_range": (33, 48),
        "six_kin": ["自己", "配偶"],
        "event_types": ["婚姻", "事业高峰", "健康", "中年运程"],
        "social_layer": "核心层",
        "classical_source": "《渊海子平》：'日为自身，夫妻之宫'",
    },
    "时柱": {
        "domain": "子女/晚年",
        "age_range": (49, 99),
        "six_kin": ["子女"],
        "event_types": ["子女状况", "晚年运势", "归宿", "遗产"],
        "social_layer": "延续层",
        "classical_source": "《子平真诠》：'时乃归宿之地，子息晚运之所'",
    },
}

# ============================================================
# 宫位与十神交叉映射
# ============================================================

# 每个宫位中，六亲对应的十神定位
# 例如：年柱中父亲看偏财，父亲在年柱则为"祖上得力"
GONGWEI_SIX_KIN_MAP = {
    "年柱": {
        "偏财": "父亲（祖上根基看父星在年柱是否得位）",
        "正印": "母亲（祖上根基看母星在年柱是否得位）",
        "正官": "祖上有官职/地位",
        "七杀": "祖上武职/创业",
    },
    "月柱": {
        "偏财": "父亲（月柱看父星的社会地位）",
        "正印": "母亲（月柱看母星的社会地位）",
        "比肩": "兄弟姐妹数量与助力",
        "劫财": "兄弟姐妹竞争关系",
        "正官": "青年时期社会地位",
    },
    "日柱": {
        "正财": "妻子（日支为妻宫）",
        "正官": "丈夫（日支为夫宫）",
        "七杀": "配偶性格刚烈/偏房",
        "比肩": "配偶与自己性格相似",
    },
    "时柱": {
        "食神": "儿子（时柱食神得位多子）",
        "伤官": "女儿（时柱伤官得位多女）",
        "正官": "子女有出息（官星在时为子贵）",
        "偏印": "晚年孤独或偏门专长",
    },
}

# ============================================================
# 事件类型 → 宫位映射
# ============================================================

EVENT_TO_GONGWEI = {
    "家庭出身": ["年柱"],
    "祖业继承": ["年柱"],
    "童年健康状况": ["年柱"],
    "学历/教育": ["月柱"],
    "事业起步": ["月柱"],
    "父母状况": ["年柱", "月柱"],
    "兄弟姐妹关系": ["月柱"],
    "婚姻/感情": ["日柱"],
    "事业发展/高峰": ["日柱"],
    "中年健康": ["日柱"],
    "子女教育": ["时柱"],
    "晚年生活": ["时柱"],
    "退休/归宿": ["时柱"],
    "遗产/传承": ["时柱"],
}

# ============================================================
# 核心函数
# ============================================================

def map_event_to_gongwei(event_type: str, current_age: int) -> list[str]:
    """
    根据事件类型 + 命主年龄，将断事结论映射到特定宫位
    
    Args:
        event_type: 事件类型（如 "婚姻/感情"）
        current_age: 命主当前年龄
    
    Returns:
        对应的宫位列表（可能跨多个宫位）
    """
    # 先从事件类型获取宫位
    type_gongweis = EVENT_TO_GONGWEI.get(event_type, [])
    
    # 再从年龄获取宫位
    age_gongwei = None
    for gongwei_name, rules in GONGWEI_RULES.items():
        lo, hi = rules["age_range"]
        if lo <= current_age <= hi:
            age_gongwei = gongwei_name
            break
    
    # 合并结果
    result = list(type_gongweis)
    if age_gongwei and age_gongwei not in result:
        result.append(age_gongwei)
    
    return result if result else ["日柱"]  # 默认为日柱


def gongwei_six_kin_cross_validate(
    gongwei_name: str,
    ten_god: str,
    chart_data: dict,
) -> dict:
    """
    宫位六亲与十神六亲的交叉验证
    
    《子平真诠·论六亲》："六亲之论，以十神定其本，以宫位明其位，以旺衰判其力"
    
    例：偏财在年柱得位 → 父亲祖上根基好
    例：正官在月柱 → 青年有官职或社会地位，但需与旺衰合参
    
    Args:
        gongwei_name: 宫位名（年柱/月柱/日柱/时柱）
        ten_god: 十神名
        chart_data: 排盘数据
    
    Returns:
        {
            "is_valid": bool,         # 十神在此宫位是否有意义
            "interpretation": str,    # 交叉解读
            "warning": str,           # 矛盾警告
        }
    """
    kin_map = GONGWEI_SIX_KIN_MAP.get(gongwei_name, {})
    if ten_god not in kin_map:
        return {
            "is_valid": False,
            "interpretation": f"{ten_god}在{gongwei_name}无标准六亲映射",
            "warning": "可能不适用于传统六亲推断",
        }
    
    # 获取该十神在此宫位的旺衰（有根/透干）
    from rules.pattern import _check_shen_status
    exists, has_root, touches = _check_shen_status(ten_god, chart_data)
    
    strength = ""
    if touches and has_root:
        strength = "得位有力"
    elif touches:
        strength = "透干但根浅"
    elif has_root:
        strength = "暗藏不显"
    else:
        strength = "宫位中该十神不显"
    
    return {
        "is_valid": True,
        "interpretation": kin_map[ten_god],
        "strength": strength,
        "warning": "",
    }


def get_gongwei_event_rules(gongwei_name: str) -> dict:
    """获取指定宫位的完整取象规则"""
    return GONGWEI_RULES.get(gongwei_name, {})


def get_age_gongwei(age: int) -> str:
    """根据年龄获取当前应属的宫位"""
    for gw_name, rules in GONGWEI_RULES.items():
        lo, hi = rules["age_range"]
        if lo <= age <= hi:
            return gw_name
    return "时柱" if age > 48 else "年柱"


def get_gongwei_for_pillar_position(position: str) -> str:
    """将四柱位置名映射到宫位名"""
    pos_map = {"year": "年柱", "month": "月柱", "day": "日柱", "hour": "时柱"}
    return pos_map.get(position, "日柱")
```

### 与现有代码的关系

| 操作 | 文件 |
|------|------|
| **新增** | `rules/gongwei.py`（约 200 行） |
| **修改** | `rules/__init__.py`：导出新模块 |
| **修改** | `services/predictions.py`：`_build_parents`/`_build_siblings` 可调用 gongwei 模块增强推断 |
| **不变** | 所有其他模块 |

### 测试验证

1. **事件映射**：`map_event_to_gongwei("婚姻/感情", 35)` → 应包含 "日柱"（既是事件对应宫位也是年龄宫位）
2. **年龄宫位**：`get_age_gongwei(20)` → "月柱"；`get_age_gongwei(60)` → "时柱"
3. **六亲交叉验证**：`gongwei_six_kin_cross_validate("年柱", "偏财", chart)` → 父亲信息
4. **边界**：`get_age_gongwei(16)` → "年柱"；`get_age_gongwei(17)` → "月柱"

---

## 第二组：🟡 部分实现（6 项）

---

## 模块 5：Level 1 用神修正子维度细化

### 理论依据

**报告引用**：第 3 章 "Level 1: 用神修正——透干会支变化与真假判别"

三个子维度：
- **1A 透干会支变化**：《子平真诠·论用神变化》"透干不同则用神变，会局成功则用神亦变"
- **1B 真假判别**：《滴天髓·真假》"真神失势，假神得局，法当以真为假，以假为真"
- **1C 救应失效**：《子平真诠·论用神成败得失》"救应被伤，两番损伤，其败更甚"

### 现有代码状态

- `services/correction_v2.py`：`_level1()` 方法实现了基本的真神假神检查和救应检查，但：
  - 1A 透干会支变化：仅在 `rules/pattern.py` 中有 `check_yongshen_bianhua()`，在 correction 流程中未被深度利用
  - 1B 真假：仅检查透干有根 vs 无根，未枚举藏干候选
  - 1C 救应失效：仅检查是否存在救应，未检查救应是否被伤
- `rules/pattern.py`：有 `JIUYING_TABLE`（救应对应表）、`check_chengbai`、`check_jiuying_v2`，但未在 correction 流程中系统调用
- **结论：部分实现**。有核心组件但缺少细化方法和系统化流程整合

### 设计方案

#### 新增文件：`services/correction/level1_yongshen.py`

```python
"""Level 1 用神修正 - 三个子维度细化"""

class Level1YongshenCorrector:
    """Level 1 用神修正器：1A 透干会支 + 1B 真假 + 1C 救应"""
    
    # === 1A: 透干会支变化 ===
    
    def _fix_1a_tougan_huizhi(self, chart_data: dict, dm_stem: str) -> dict:
        """
        遍历月令藏干的多种透干/会支组合，枚举候选格局
        用规则引擎过滤出 ≤3 种有效候选
        
        《子平真诠·论用神变化》：
        "透干不同则用神变，会局成功则用神亦变"
        """
        from rules.pattern import (
            detect_ganzhi_touchu, detect_zhi_heju, 
            get_month_stems, _calc_ten_god, _TG_TO_PATTERN
        )
        
        month_branch = chart_data.get("four_pillars", {}).get("month", {}).get("branch", "")
        month_stems = get_month_stems(month_branch)
        candidates = []
        
        # 1. 本气格局（基准）
        main_tg = _calc_ten_god(dm_stem, month_stems[0]) if month_stems else ""
        main_pattern = _TG_TO_PATTERN.get(main_tg, "")
        if main_pattern:
            candidates.append({
                "pattern": main_pattern,
                "source": "月令本气",
                "confidence": 0.60,
                "detail": f"月令本气{month_stems[0]}→{main_tg}→{main_pattern}",
            })
        
        # 2. 透干变化：中气/余气在天干透出
        touchu = detect_ganzhi_touchu(chart_data)
        touched_stem = touchu.get("touched_stem", "")
        touched_level = touchu.get("level", "")
        if touched_level in ("中气", "余气") and touchu.get("is_strong"):
            touched_tg = touchu.get("touched_ten_god", "")
            touched_pattern = _TG_TO_PATTERN.get(touched_tg, "")
            if touched_pattern and touched_pattern != main_pattern:
                candidates.append({
                    "pattern": touched_pattern,
                    "source": f"月令{touched_level}透干（{touched_stem}）",
                    "confidence": 0.40 if touched_level == "中气" else 0.25,
                    "detail": f"月令{touched_level}{touched_stem}强透→{touched_tg}→{touched_pattern}",
                })
        
        # 3. 会局变化：三合三会局可能改变用神
        heju = detect_zhi_heju(chart_data, month_branch)
        if heju.get("pending"):
            hua_wx = heju.get("hua_wuxing", "")
            # 根据化神五行推断格局
            # ...推断逻辑...
            if hua_wx:
                candidates.append({
                    "pattern": f"{heju['type']}成格",
                    "source": f"月支参与{heju['type']}化{hua_wx}",
                    "confidence": 0.30,
                    "detail": f"月支{month_branch}参与{heju['type']}成化{hua_wx}",
                })
        
        # 过滤：最多保留 3 个有效候选（confidence ≥ 0.20）
        candidates = [c for c in candidates if c["confidence"] >= 0.20]
        candidates.sort(key=lambda x: x["confidence"], reverse=True)
        candidates = candidates[:3]
        
        return {
            "sub_dimension": "1A-透干会支变化",
            "candidates": candidates,
            "recommendation": candidates[0]["pattern"] if candidates else main_pattern,
            "classical_source": "《子平真诠·论用神变化》：'透干不同则用神变，会局成功则用神亦变'",
        }
    
    # === 1B: 真假判别 ===
    
    def _fix_1b_zhengjia(self, chart_data: dict, yongshen_ten_god: str) -> dict:
        """
        判断当前用神是"真神得用"还是"假神得局"
        检查：
        1. 用神是否有根（地支/藏干同五行）
        2. 用神是否透干
        3. 用神是否被伤（被合、被冲、被克）
        
        《滴天髓·真假》：
        "令上寻真聚得真，假神休要乱真神"
        "真神失势，假神得局，法当以真为假，以假为真"
        """
        from rules.pattern import _check_shen_status, JIUYING_TABLE
        from rules.pattern import _check_yongshen_chong, _check_yongshen_be_he
        
        exists, has_root, touches = _check_shen_status(yongshen_ten_god, chart_data)
        
        # 检查伤克
        is_hurt = False
        hurt_detail = ""
        
        # 用神被冲？
        if _check_yongshen_chong(chart_data.get("yongshen", {}).get("pattern", ""), chart_data):
            is_hurt = True
            hurt_detail += "月令被冲，用神之根受损；"
        
        # 用神被合？
        pattern = chart_data.get("yongshen", {}).get("pattern", "")
        dm_stem = chart_data.get("day_master", "")
        if _check_yongshen_be_he(pattern, dm_stem, chart_data):
            is_hurt = True
            hurt_detail += "用神被天干所合，失其用；"
        
        # 判定结论
        if has_root and touches and not is_hurt:
            conclusion = "真神得用"
            is_zhen = True
            detail = f"用神{yongshen_ten_god}透干有根且无损，真神也"
        elif has_root and touches and is_hurt:
            conclusion = "真神受损"
            is_zhen = False
            detail = f"用神{yongshen_ten_god}透干有根但被伤：{hurt_detail}"
        elif touches and not has_root:
            conclusion = "假神得局"
            is_zhen = False
            detail = f"用神{yongshen_ten_god}透干但无根，虚浮之假神"
        elif has_root and not touches:
            conclusion = "真神暗藏"
            is_zhen = False
            detail = f"用神{yongshen_ten_god}有根但未透干，真神不显"
        else:
            conclusion = "用神不显"
            is_zhen = False
            detail = f"用神{yongshen_ten_god}既未透干也无根"
        
        return {
            "sub_dimension": "1B-真假判别",
            "is_zhen": is_zhen,
            "conclusion": conclusion,
            "detail": detail,
            "has_root": has_root,
            "is_touched": touches,
            "is_hurt": is_hurt,
            "classical_source": "《滴天髓·真假》：'真神得用生平贵，用假终为碌碌人'",
        }
    
    # === 1C: 救应失效 ===
    
    def _fix_1c_jiuying(self, chart_data: dict, pattern: str) -> dict:
        """
        检查用神的"救应"链条：
        1. 喜神是否得力？
        2. 忌神是否有制？
        3. 救应之神是否被伤？（救应被伤 → 两番损伤）
        
        《子平真诠·论用神成败得失》：
        "救应被伤，两番损伤，其败更甚"
        """
        from rules.pattern import PATTERN_XIANGSHEN_RULES, JIUYING_TABLE
        from rules.pattern import check_chengbai, check_jiuying_v2
        
        rules = PATTERN_XIANGSHEN_RULES.get(pattern, {})
        defeat_causes = rules.get("defeat_causes", [])
        
        # 1. 成败检测
        chengbai = check_chengbai(
            pattern,
            {"ten_god": rules.get("yongshen", ""), "five_element": ""},
            {},
            chart_data,
        )
        
        if not chengbai["is_defeated"]:
            return {
                "sub_dimension": "1C-救应检查",
                "status": "成格无败",
                "detail": "用神无败因，救应无需触发",
                "classical_source": "《子平真诠·论用神成败得失》",
            }
        
        # 2. 救应检测
        jiuying = check_jiuying_v2(pattern, chengbai["defeat_causes"], chart_data)
        
        if jiuying["has_jiuying"]:
            # 3. 检查救应是否被伤
            jiuying_hurt = self._check_jiuying_hurt(
                jiuying["jiuying_shen"], chart_data
            )
            
            if jiuying_hurt:
                return {
                    "sub_dimension": "1C-救应检查",
                    "status": "救应被伤",
                    "detail": f"用神有败因'{chengbai['defeat_causes']}'，"
                            f"虽有{jiuying['jiuying_shen']}救应，"
                            f"但{jiuying_hurt}——两番损伤，其败更甚",
                    "defeat_causes": chengbai["defeat_causes"],
                    "jiuying_shen": jiuying["jiuying_shen"],
                    "jiuying_level": jiuying["jiuying_level"],
                    "jiuying_hurt": True,
                    "classical_source": "《子平真诠·论用神成败得失》：'救应被伤，两番损伤，其败更甚'",
                }
            else:
                return {
                    "sub_dimension": "1C-救应检查",
                    "status": "救应得力",
                    "detail": f"用神有败因'{chengbai['defeat_causes']}'，"
                            f"但有{jiuying['jiuying_shen']}({jiuying['jiuying_level']})救应——有救不为败",
                    "defeat_causes": chengbai["defeat_causes"],
                    "jiuying_shen": jiuying["jiuying_shen"],
                    "jiuying_level": jiuying["jiuying_level"],
                    "jiuying_hurt": False,
                    "classical_source": "《子平真诠·论用神成败得失》",
                }
        else:
            return {
                "sub_dimension": "1C-救应检查",
                "status": "败格无救",
                "detail": f"用神有败因'{chengbai['defeat_causes']}'且无救应之神——败格",
                "defeat_causes": chengbai["defeat_causes"],
                "classical_source": "《子平真诠·论用神成败得失》",
            }
    
    def _check_jiuying_hurt(self, jiuying_shen: str, chart_data: dict) -> str:
        """检查救应之神是否被伤"""
        from rules.pattern import _check_shen_status
        exists, has_root, touches = _check_shen_status(jiuying_shen, chart_data)
        
        if not exists:
            return "救应之神不存于局中"
        if not has_root:
            return "救应之神无根，其力不足"
        # 检查救应是否被克/被合
        # ...详细检查...
        return ""  # 空字符串 = 未受伤
    
    # === 综合 Level 1 修正 ===
    
    def run_full_level1(self, chart_data: dict, dm_stem: str, 
                        pattern: str, yongshen_ten_god: str) -> dict:
        """执行完整的 Level 1 三个子维度检查"""
        
        result_1a = self._fix_1a_tougan_huizhi(chart_data, dm_stem)
        result_1b = self._fix_1b_zhengjia(chart_data, yongshen_ten_god)
        result_1c = self._fix_1c_jiuying(chart_data, pattern)
        
        # 汇总修正建议
        suggestions = []
        if len(result_1a.get("candidates", [])) > 1:
            suggestions.append(f"透干会支变化检测到{len(result_1a['candidates'])}种候选格局")
        if not result_1b.get("is_zhen"):
            suggestions.append(f"用神判定为'{result_1b['conclusion']}'，建议重新审视")
        if result_1c.get("status") == "救应被伤":
            suggestions.append("救应被伤，两番损伤——需优先处理")
        
        return {
            "level": 1,
            "level_name": "用神修正",
            "sub_results": {
                "1A": result_1a,
                "1B": result_1b,
                "1C": result_1c,
            },
            "suggestions": suggestions,
            "confidence": 0.70 if not suggestions else 0.50,
        }
```

### 与现有代码的关系

| 操作 | 文件 |
|------|------|
| **新增** | `services/correction/__init__.py` |
| **新增** | `services/correction/level1_yongshen.py`（约 300 行） |
| **修改** | `services/correction_v2.py`：`_level1()` 改为调用 `Level1YongshenCorrector.run_full_level1()` |
| **不变** | `rules/pattern.py`：JIUYING_TABLE, check_chengbai, check_jiuying_v2 等基础函数不变 |

### 测试验证

1. **1A 多候选**：月令本气为七杀格，中气正官在天干透出 → 应产出 2 种候选
2. **1B 假神**：用神透干但无根（如用火但地支无水木之外的根）→ is_zhen=False
3. **1C 救应被伤**：官格伤官克官，有印制伤官但印星被财星克 → "救应被伤"

---

## 模块 6：Level 5 行运修正深度增强

### 理论依据

**报告引用**：第 3 章 "Level 5: 行运修正——大运成格变格"

四种行运效应：
- **运中成格**："原局格局之不足，得运而补足也"——《子平真诠·论行运成格变格》
- **运中变格**：大运可能暂时改变格局性质，但"运过之后，格局恢复原状"（徐乐吾评注）
- **运中破格**：大运破坏原局格局优势
- **运中并存**：多格局特征并存

### 现有代码状态

- `services/correction_v2.py`：`_level5()` 简化实现——仅检查大运天干是否为用神五行，过于粗糙
- `rules/pattern.py`：有 `PATTERN_DAYUN_RULES`（大运喜忌表）但 correction 未深度利用
- `services/correction.py`：有时辰试错和 AI 修正，但无大运专项
- **结论：部分实现**。`_level5` 仅做了天干匹配，缺少地支分析、成格/变格/破格/并存四种效应的全面检测

### 设计方案

#### 新增文件：`services/correction/level5_dayun.py`

核心设计：

```python
"""Level 5 行运修正 - 大运成格变格深度分析"""

class Level5DayunCorrector:
    """四种行运效应检测器"""
    
    PATTERN_DAYUN_REQUIREMENTS = {
        "正官格": {
            "needs": ["财星", "印星"],  # 格之所需
            "avoids": ["伤官", "七杀"],  # 格之所忌
            "cheng_conditions": [
                ("财星到位", "原局缺财星，大运行财运则财生官，格局成"),
                ("印星到位", "原局缺印星，大运行印运则印护官，格局成"),
            ],
            "bai_conditions": [
                ("伤官到位", "大运行伤官运 → 伤官克官，破格"),
                ("七杀到位", "大运行七杀运 → 官杀混杂，变格"),
            ],
        },
        "七杀格": {
            "needs": ["食神", "印星"],
            "avoids": ["财星"],
            "cheng_conditions": [
                ("食神到位", "原局杀无制，大运逢食神 → 食神制杀，成格"),
                ("印星到位", "原局无印，大运逢印 → 印化七杀，成格"),
            ],
            "bai_conditions": [
                ("财星到位", "大运行财运 → 财星党杀，破格"),
            ],
        },
        # ... 其他格局类似 ...
    }
    
    def _detect_dayun_chengge(self, pattern: str, dayun_list: list, 
                               chart_data: dict) -> list[dict]:
        """
        检测运中成格：
        原局格局有不足（缺关键用神/喜神），当前大运补足
        
        例：原局官格缺财（无财星生官），行财运则成格
        """
        reqs = self.PATTERN_DAYUN_REQUIREMENTS.get(pattern, {})
        needs = reqs.get("needs", [])
        cheng_conditions = reqs.get("cheng_conditions", [])
        results = []
        
        for da in dayun_list:
            da_stem = da.get("stem", "")
            da_branch = da.get("branch", "")
            da_ten_god = da.get("ten_god", "")
            
            for cond_desc, explanation in cheng_conditions:
                # 检查该大运是否满足成格条件
                if self._dayun_matches_condition(da, cond_desc):
                    # 检查原局是否确实缺这个
                    if self._chart_lacks(chart_data, cond_desc, pattern):
                        results.append({
                            "dayun": f"{da_stem}{da_branch}",
                            "start_year": da.get("start_year"),
                            "end_year": da.get("end_year"),
                            "effect": "运中成格",
                            "detail": explanation,
                            "is_temporary": True,  # "运过即止"（徐乐吾评注）
                        })
        
        return results
    
    def _detect_dayun_biange(self, pattern: str, dayun_list: list,
                             chart_data: dict) -> list[dict]:
        """
        检测运中变格：
        大运改变了格局性质，例如：
        - 原局官格清纯，行杀运则官杀混杂 → 变格
        - 原局伤官格，行官运则伤官见官 → 变格（祸）
        """
        bai_conditions = self.PATTERN_DAYUN_REQUIREMENTS.get(pattern, {}).get("bai_conditions", [])
        results = []
        
        for da in dayun_list:
            for cond_desc, explanation in bai_conditions:
                if self._dayun_matches_condition(da, cond_desc):
                    results.append({
                        "dayun": f"{da.get('stem','')}{da.get('branch','')}",
                        "start_year": da.get("start_year"),
                        "end_year": da.get("end_year"),
                        "effect": "运中变格",
                        "detail": explanation,
                        "warning": "此大运为临时变化，运过即止",
                        "classical_source": "《子平真诠·论行运成格变格》",
                    })
        
        return results
    
    def _detect_dayun_poge(self, pattern: str, dayun_list: list,
                           chart_data: dict) -> list[dict]:
        """
        检测运中破格：
        大运破坏了原局格局优势
        例：原局官格有财生官+印护官，行伤官运则伤官克官 → 破格
        
        对格局的破坏性大于成格变格，需特别标记
        """
        results = []
        
        for da in dayun_list:
            da_ten_god = da.get("ten_god", "")
            da_branch = da.get("branch", "")
            
            # 检查大运十神是否为格局的忌神
            from rules.pattern import PATTERN_DAYUN_RULES
            xiji = PATTERN_DAYUN_RULES.get(pattern, {})
            ji_dayun = set(xiji.get("ji", []))
            
            if da_ten_god in ji_dayun:
                results.append({
                    "dayun": f"{da.get('stem','')}{da.get('branch','')}",
                    "start_year": da.get("start_year"),
                    "effect": "运中破格",
                    "detail": f"大运{da_ten_god}为该格局忌神运，可能破坏原局优势",
                    "severity": "high",
                })
            
            # 额外检查：大运地支是否冲月令
            from rules.pattern import _OPPOSITES
            month_branch = chart_data.get("four_pillars", {}).get("month", {}).get("branch", "")
            if da_branch == _OPPOSITES.get(month_branch, ""):
                results.append({
                    "dayun": f"{da.get('stem','')}{da.get('branch','')}",
                    "start_year": da.get("start_year"),
                    "effect": "运中破格（地支冲月令）",
                    "detail": f"大运地支{da_branch}冲月令{month_branch}，格局根基动摇",
                    "severity": "critical",
                    "classical_source": "《子平真诠》第22章：月令逢冲则气受损",
                })
        
        return results
    
    def _detect_dayun_bingcun(self, pattern: str, dayun_list: list) -> list[dict]:
        """
        检测运中并存：
        大运同时带来成格和变格因素，多格局特征并存
        """
        results = []
        
        reqs = self.PATTERN_DAYUN_REQUIREMENTS.get(pattern, {})
        needs = reqs.get("needs", [])
        avoids = reqs.get("avoids", [])
        
        for da in dayun_list:
            da_stem = da.get("stem", "")
            da_branch = da.get("branch", "")
            
            # 天干和地支分别判断（可能是天干吉地支凶或反之）
            stem_good = self._stem_helps_pattern(da_stem, needs)
            branch_bad = self._branch_hurts_pattern(da_branch, avoids, pattern)
            
            if stem_good and branch_bad:
                results.append({
                    "dayun": f"{da_stem}{da_branch}",
                    "effect": "运中并存",
                    "detail": f"天干{da_stem}有成格之效，但地支{da_branch}有破格之嫌",
                    "suggestion": "此运前五年（天干主事）好，后五年（地支主事）差",
                })
        
        return results
    
    def run_full_level5(self, chart_data: dict) -> dict:
        """综合 Level 5 四种效应分析"""
        pattern = chart_data.get("yongshen", {}).get("pattern", "")
        dayun = chart_data.get("dayun", [])
        
        chengge = self._detect_dayun_chengge(pattern, dayun, chart_data)
        biange = self._detect_dayun_biange(pattern, dayun, chart_data)
        poge = self._detect_dayun_poge(pattern, dayun, chart_data)
        bingcun = self._detect_dayun_bingcun(pattern, dayun)
        
        # 汇总
        all_effects = chengge + biange + poge + bingcun
        all_effects.sort(key=lambda x: x.get("start_year", 0))
        
        return {
            "level": 5,
            "level_name": "行运修正",
            "total_effects": len(all_effects),
            "effects": {
                "chengge": chengge,
                "biange": biange,
                "poge": poge,
                "bingcun": bingcun,
            },
            "dayun_report": all_effects,
            "classical_source": "《子平真诠·论行运成格变格》："
                               "'运中成格，可以补原局之不足'——徐乐吾评注："
                               "'运中之成，不过十年风光，运过即止'",
        }
```

### 与现有代码的关系

| 操作 | 文件 |
|------|------|
| **新增** | `services/correction/level5_dayun.py`（约 350 行） |
| **修改** | `services/correction_v2.py`：`_level5()` 改为调用新模块 |
| **不变** | `rules/pattern.py`：PATTERN_DAYUN_RULES 不变 |

### 测试验证

1. **运中成格**：官格无财 → 第一步大运为财运 → 应返回 chengge 效应
2. **运中破格**：七杀格有食神制杀 → 大运走财运（财星党杀）→ poge
3. **运中并存**：正印格，甲子大运（甲为财星 g 破印，子为印星之根）→ bingcun
4. **运过即止**：所有 chengge/biange 标注 "运过即止"

---

## 模块 7：Level 3 从格硬校验增强

### 理论依据

**报告引用**：第 3 章 "Level 3: 格局切换——正格与从格/化格互转"

- **真从**："日主孤弱无气，四柱无生扶之意"——《滴天髓·从化》
- **假从**："日主根浅力薄，局中虽有劫印，亦自顾不暇"——同上
- **从格类型**：从强（从旺/从强/从气/从势/从儿）、从杀、从财、从儿（从食伤）
- **化气格条件**：天干五合成化 + 化神当令 + 透干 + 通根 + 无克破

### 现有代码状态

- `rules/pattern.py`：`_check_special_pattern()` 仅以 total_score < 15 判断从弱格、> 85 判断专旺格，过于简单
- `check_zhen_jia_cong()`：检查日主是否有根和印比暗藏，但"有根"的量化标准不精细（仅以 weight ≥ 0.3 判断）
- `check_huaqi_ge()`：检查化气格条件，但缺少化神透干、通根、无克破的完整五要素验证
- **结论：部分实现**。有从格和化气格检测，但边界条件不够精细，缺少"假从"的量化定义和化气格的五要素验证表

### 设计方案

#### 增强 `rules/pattern.py` 中的 `_check_special_pattern()` 和新增化气格五要素表

```python
# ============================================================
# 增强版从格检测：量化"假从"边界
# ============================================================

def check_congge_detailed(chart_data: dict, dm_stem: str) -> dict:
    """
    详细从格判断（增强版）
    
    假从三要素量化：
    1. 日主有根但根极浅：仅余气通根（非本气/中气）
    2. 生扶力量薄弱：全局比劫印绶力量 < 日主力量的 20%
    3. "自顾不暇"：虽有劫印，但被克/被泄/被合，无法有效生扶日主
    """
    from rules.wuxing import WUXING_MAP
    
    dm_wx = WUXING_MAP.get(dm_stem, "")
    fp = chart_data.get("four_pillars", {})
    
    # === 1. 根气量化 ===
    root_detail = _quantify_roots(dm_wx, fp)
    has_benzhi_root = root_detail["has_benzhi_root"]     # 本气根（weight≥0.5）
    has_zhongqi_root = root_detail["has_zhongqi_root"]   # 中气根（0.3≤weight<0.5）
    has_yuqi_root = root_detail["has_yuqi_root"]         # 余气根（weight<0.3）
    total_root_weight = root_detail["total_weight"]
    
    # === 2. 全局生扶力量占比 ===
    bi_jie_yin_force = _calc_support_force(dm_wx, fp, dm_stem)
    total_force = _calc_total_force(dm_wx, fp)
    support_ratio = bi_jie_yin_force / max(total_force, 1)
    
    # === 3. 比劫印绶"自顾不暇"检查 ===
    restricted_support = _check_restricted_support(dm_wx, fp, dm_stem)
    
    # === 从格类型判定 ===
    if total_root_weight == 0 and support_ratio < 0.10:
        cong_type = "真从"
        cong_subtype = _determine_cong_subtype(fp, dm_stem)
        detail = "日主无根无气，全局无生扶，真从"
    elif (has_yuqi_root or total_root_weight < 0.3) and support_ratio < 0.20:
        cong_type = "假从"
        cong_subtype = _determine_cong_subtype(fp, dm_stem)
        if restricted_support:
            detail = f"日主根浅力薄（根重{total_root_weight}），劫印自顾不暇，假从"
        else:
            detail = f"日主有微根（根重{total_root_weight}），但印比力量不足（占比{support_ratio:.0%}），假从"
    elif support_ratio < 0.15 and restricted_support:
        cong_type = "假从"
        cong_subtype = _determine_cong_subtype(fp, dm_stem)
        detail = "日主虽略有根气，但劫印自顾不暇，从局成立"
    else:
        cong_type = "非从"
        cong_subtype = ""
        detail = f"不满足从格条件（根重{total_root_weight}，印比占比{support_ratio:.0%}）"
    
    return {
        "is_congge": cong_type in ("真从", "假从"),
        "cong_type": cong_type,  # "真从" | "假从" | "非从"
        "cong_subtype": cong_subtype,  # "从杀"|"从财"|"从儿"|"从强"
        "root_detail": root_detail,
        "support_ratio": round(support_ratio, 2),
        "restricted_support": restricted_support,
        "detail": detail,
        "classical_source": "《滴天髓·从化》：'真从之象有几人，假从亦可发其身'",
    }


def _quantify_roots(dm_wx: str, fp: dict) -> dict:
    """量化日主在各柱藏干中的根气"""
    from rules.pattern import WUXING_MAP
    
    has_benzhi = False
    has_zhongqi = False
    has_yuqi = False
    total = 0.0
    
    for pos in ["year", "month", "day", "hour"]:
        for hs in fp.get(pos, {}).get("hidden_stems", []):
            s = hs.get("stem", "") if isinstance(hs, dict) else hs
            w = hs.get("weight", 0.0) if isinstance(hs, dict) else 0.3
            if WUXING_MAP.get(s, "") == dm_wx:
                total += w
                if w >= 0.5:
                    has_benzhi = True
                elif w >= 0.3:
                    has_zhongqi = True
                else:
                    has_yuqi = True
    
    return {
        "has_benzhi_root": has_benzhi,
        "has_zhongqi_root": has_zhongqi,
        "has_yuqi_root": has_yuqi,
        "total_weight": round(total, 1),
    }


# ============================================================
# 化气格五要素验证表
# ============================================================

HUAHUAGE_CONDITIONS = {
    "甲己合化土": {
        "合化天干": ("甲", "己"),
        "化神五行": "土",
        "化神当令（月令）": ["辰", "戌", "丑", "未", "巳", "午"],  # 土旺之月
        "透干条件": "甲或己透于月干或时干",  # 日干需参与合化
        "通根条件": "化神土在月支有本气或中气根",
        "无克破条件": "无木（甲乙）强力克化神土",
        "真化标志": "日主无强根（无本气根）",
        "source": "《子平真诠·论十干配合性情》",
    },
    "乙庚合化金": {
        "合化天干": ("乙", "庚"),
        "化神五行": "金",
        "化神当令（月令）": ["申", "酉", "戌", "丑"],  # 金旺之月
        "透干条件": "乙或庚透于月干或时干",
        "通根条件": "化神金在月支有本气或中气根",
        "无克破条件": "无火（丙丁）强力克化神金",
        "真化标志": "日主无强根",
        "source": "《子平真诠·论十干配合性情》",
    },
    "丙辛合化水": {
        "合化天干": ("丙", "辛"),
        "化神五行": "水",
        "化神当令（月令）": ["亥", "子", "申", "辰"],  # 水旺之月
        "透干条件": "丙或辛透于月干或时干",
        "通根条件": "化神水在月支有本气或中气根",
        "无克破条件": "无土（戊己）强力克化神水",
        "真化标志": "日主无强根",
        "source": "《子平真诠·论十干配合性情》",
    },
    "丁壬合化木": {
        "合化天干": ("丁", "壬"),
        "化神五行": "木",
        "化神当令（月令）": ["寅", "卯", "亥", "未"],  # 木旺之月
        "透干条件": "丁或壬透于月干或时干",
        "通根条件": "化神木在月支有本气或中气根",
        "无克破条件": "无金（庚辛）强力克化神木",
        "真化标志": "日主无强根",
        "source": "《子平真诠·论十干配合性情》",
    },
    "戊癸合化火": {
        "合化天干": ("戊", "癸"),
        "化神五行": "火",
        "化神当令（月令）": ["巳", "午", "寅", "戌"],  # 火旺之月
        "透干条件": "戊或癸透于月干或时干",
        "通根条件": "化神火在月支有本气或中气根",
        "无克破条件": "无水（壬癸）强力克化神火",
        "真化标志": "日主无强根",
        "source": "《子平真诠·论十干配合性情》",
    },
}


def check_huaqi_ge_5elements(dm_stem: str, chart_data: dict) -> dict:
    """
    化气格五要素完整验证
    
    五要素：
    1. 天干五合成化
    2. 化神当令（月令）
    3. 透干
    4. 通根
    5. 无克破
    
    Returns:
        {
            "is_huaqi": bool,
            "hua_type": str,
            "conditions_met": [str],
            "conditions_failed": [str],
            "is_zhen": bool,
        }
    """
    fp = chart_data.get("four_pillars", {})
    month_stem = fp.get("month", {}).get("stem", "")
    hour_stem = fp.get("hour", {}).get("stem", "")
    month_branch = fp.get("month", {}).get("branch", "")
    
    # 找到日干参与的合化类型
    hua_type = None
    partner = None
    for partner_stem in [month_stem, hour_stem]:
        for hua_name, cond in HUAHUAGE_CONDITIONS.items():
            pair = cond["合化天干"]
            if (dm_stem in pair and partner_stem in pair and dm_stem != partner_stem):
                hua_type = hua_name
                partner = partner_stem
                break
        if hua_type:
            break
    
    if not hua_type:
        return {"is_huaqi": False, "detail": "日干未参与天干五合"}
    
    cond = HUAHUAGE_CONDITIONS[hua_type]
    met = []
    failed = []
    
    # 条件 1：天干五合成化 ✓（我们已经找到了）
    met.append("天干五合成化")
    
    # 条件 2：化神当令
    if month_branch in cond["化神当令（月令）"]:
        met.append(f"化神{cond['化神五行']}在月令{month_branch}当令")
    else:
        failed.append(f"化神{cond['化神五行']}不在月令当令（当前月支{month_branch}）")
    
    # 条件 3：透干（月干或时干）
    if month_stem == dm_stem or month_stem == partner:
        met.append("日干透于月干")
    elif hour_stem == dm_stem or hour_stem == partner:
        met.append("日干透于时干")
    else:
        failed.append("化神未透于月干或时干")
    
    # 条件 4：通根
    from rules.pattern import get_month_stems
    month_stems = get_month_stems(month_branch)
    month_wx = [WUXING_MAP.get(s, "") for s in month_stems]
    if cond["化神五行"] in month_wx:
        met.append(f"化神{cond['化神五行']}在月支有根")
    else:
        failed.append(f"化神{cond['化神五行']}在月支无根")
    
    # 条件 5：无克破
    from rules.pattern import WUXING_MAP
    ke_hua_wx = _KE.get(cond["化神五行"], "")
    has_ke = False
    for pos in ["year", "month", "hour"]:
        stem = fp.get(pos, {}).get("stem", "")
        if WUXING_MAP.get(stem, "") == ke_hua_wx and stem != dm_stem:
            has_ke = True
            failed.append(f"化神{cond['化神五行']}被{stem}({ke_hua_wx})所克")
            break
    if not has_ke:
        met.append("化神无克破")
    
    # 真化判定
    is_zhen = len(failed) == 0
    
    return {
        "is_huaqi": is_zhen or len(met) >= 3,
        "hua_type": hua_type,
        "is_zhen": is_zhen,
        "conditions_met": met,
        "conditions_failed": failed,
        "score": len(met),  # 满足条件数 1-5
        "detail": f"{'真化' if is_zhen else '假化'}：满足 {len(met)}/5 条件",
        "classical_source": cond["source"],
    }
```

#### 修正路径增强

```python
# 从格触发后的修正路径（扩充 _level3）

async def _level3_enhanced(self) -> CorrectionResult:
    """增强版从格检测和修正"""
    from rules.pattern import check_congge_detailed, check_huaqi_ge_5elements
    
    dm_stem = self.chart.get("day_master", "")
    
    # 1. 详细从格检测
    cong_detail = check_congge_detailed(self.chart, dm_stem)
    
    # 2. 化气格五要素检测
    huaqi_detail = check_huaqi_ge_5elements(dm_stem, self.chart)
    
    # 优先检查化气格（条件更严格，满足 4+/5 才建议切换）
    if huaqi_detail["is_huaqi"] and huaqi_detail["score"] >= 4:
        new_chart = copy.deepcopy(self.chart)
        new_chart["pattern"] = "化气格"
        return CorrectionResult(
            success=True, level=3,
            chart=new_chart,
            detail=f"化气格切换：{huaqi_detail['hua_type']}（满足 {huaqi_detail['score']}/5 条件）",
            source="《滴天髓·从化》",
        )
    
    # 从格切换判断
    if cong_detail["is_congge"]:
        existing_pattern = self.chart.get("pattern", "")
        if "从" not in existing_pattern:
            new_chart = copy.deepcopy(self.chart)
            new_chart["pattern"] = cong_detail["cong_subtype"]
            new_chart["cong_detail"] = cong_detail
            return CorrectionResult(
                success=True, level=3,
                chart=new_chart,
                detail=f"格局切换：正格 → {cong_detail['cong_type']}{cong_detail['cong_subtype']}（{cong_detail['detail']}）",
                source="《滴天髓·从化》",
            )
    
    return CorrectionResult(success=False, detail="无需格局切换")
```

### 与现有代码的关系

| 操作 | 文件 |
|------|------|
| **修改** | `rules/pattern.py`：增强 `_check_special_pattern()`，新增 `check_congge_detailed`、`check_huaqi_ge_5elements`、`HUAHUAGE_CONDITIONS` |
| **修改** | `services/correction_v2.py`：`_level3()` 改为调用增强版 |
| **不变** | 现有 `check_zhen_jia_cong`、`check_huaqi_ge` 保持不变（向后兼容） |

### 测试验证

1. **真从**：total_root_weight=0, support_ratio=0.05 → "真从"
2. **假从**：仅余气根（weight=0.2），support_ratio=0.15 → "假从"
3. **化气格五要素**：全部满足 → is_zhen=True, score=5
4. **化气格不全**：有合化但化神不当令、无根 → score=3, is_huaqi=False
5. **非从**：有本气根（weight=0.7），support_ratio=0.30 → is_congge=False

---

## 模块 8：高区分度断事智能选取

### 理论依据

**报告引用**：第 2 章 2.5 节 "高区分度断事选取原则"

四原则：
- **原则一**：选取与喜忌直接相关的事件（正官格以财印为喜、伤官为忌）
- **原则二**：优先与当前假设矛盾的"临界事件"（证伪式验证比证实式验证更有效）
- **原则三**：六亲与学历信息优先（具有高度客观性，当事人无法主观篡改）
- **原则四**：选取有明显对比性的运程段（"先败后成"或"先成后败"）

过三关：父母关（年柱月柱）、兄弟关（月柱）、婚姻关（日柱）——是传统命师验证时辰格局的三大原始锚点

### 现有代码状态

- `services/predictions.py`：有固定的 7 条生成顺序（性格→父母→兄弟→学历→婚姻→事业→关键年份），有 Mock 和 AI 双模式
- 但现有逻辑是静态顺序——始终按固定顺序生成，不根据用户的反馈动态调整
- 没有"区分度评分"概念，所有推断的验证权重相同
- **结论：部分实现**。有推断生成基础但缺少智能选取逻辑

### 设计方案

#### 在 `services/predictions.py` 中新增 `SmartPredictionSelector` 类

```python
class SmartPredictionSelector:
    """
    高区分度断事智能选取器
    
    输入：UncertaintyReport + 用户已反馈历史
    输出：Top 3-5 条高区分度断事
    """
    
    # 事件类型的基础区分度（来自报告）
    BASE_DISCRIMINATION = {
        "父母关": 8,    # 极其客观，对时辰/格局区分度极高
        "兄弟关": 7,    # 极其客观，与年柱关联
        "婚姻关": 7,    # 极其客观，与日柱关联
        "学历": 6,      # 较客观，印星验证
        "事业": 5,      # 中等，可变化
        "关键年份": 5,  # 中等，可对比
        "性格": 3,      # 低（巴纳姆效应），但总是第一问以建立信任
    }
    
    def calculate_discrimination_score(self, prediction: dict, 
                                       uncertainty: UncertaintyReport,
                                       history: list[dict]) -> dict:
        """
        计算每条候选断事的"区分度评分"（0-10）
        
        维度1：理论区分度（5 分）——该断事对区分不同假设的贡献
        维度2：不确定参数覆盖度（3 分）——该断事能验证几个不确定参数
        维度3：用户友好度（2 分）——该问题是否容易回答
        """
        category = prediction.get("category", "")
        score = 0.0
        details = []
        
        # === 维度1: 理论区分度（0-5 分） ===
        base = self.BASE_DISCRIMINATION.get(category, 3)
        theoretical_score = min(5, base / 8 * 5)
        
        # "过三关"加成：父母关/兄弟关/婚姻关
        if category in ("父母关", "兄弟关", "婚姻关"):
            # 这三关是传统验证时辰格局的三大原始锚点
            theoretical_score += 0.5
            details.append(f"{category}为过三关之一，区分度加成")
        
        # 性格推断区分度折减（巴纳姆效应）
        if category == "性格":
            theoretical_score *= 0.6
            details.append("性格推断受巴纳姆效应影响，理论区分度折减")
        
        # === 维度2: 不确定参数覆盖度（0-3 分） ===
        coverage = self._calculate_param_coverage(prediction, uncertainty)
        details.append(f"覆盖 {coverage} 个不确定参数")
        
        # === 维度3: 用户友好度（0-2 分） ===
        friendliness = self._calculate_user_friendliness(category, history)
        details.append(f"用户友好度 {friendliness}/2")
        
        total = theoretical_score + coverage + friendliness
        return {
            "prediction": prediction,
            "total_score": round(total, 1),
            "breakdown": {
                "theoretical": round(theoretical_score, 1),
                "param_coverage": round(coverage, 1),
                "user_friendliness": round(friendliness, 1),
            },
            "details": details,
            "rationale": self._generate_rationale(prediction, category, total),
        }
    
    def _calculate_param_coverage(self, prediction: dict, 
                                   uncertainty: UncertaintyReport) -> float:
        """
        计算该断事能验证多少个不确定参数
        - 父母关 → 时辰风险 + 格局多解性（2 个）
        - 兄弟关 → 格局多解性（1 个）
        - 学历 → 用神争议度 + 旺衰模糊度（2 个）
        - 婚姻关 → 时辰风险 + 从格真假（2 个）
        - 事业 → 用神争议度（1 个）
        - 关键年份 → 旺衰模糊度（1 个）
        - 性格 → 所有弱覆盖（0.5 个）
        """
        mapping = {
            "父母关": ["shichen", "pattern"],
            "兄弟关": ["pattern"],
            "婚姻关": ["shichen", "congge"],
            "学历": ["yongshen", "wangshuai"],
            "事业": ["yongshen"],
            "关键年份": ["wangshuai"],
            "性格": ["yongshen"],  # 弱覆盖
        }
        
        dims = mapping.get(prediction.get("category", ""), [])
        if not dims:
            return 1.0
        
        # 只计高/中风险的不确定参数
        high_risk_dims = {
            item.dimension for item in uncertainty.items 
            if item.label in ("高风险", "中风险")
        }
        
        covered = sum(1 for d in dims if d in high_risk_dims)
        return min(3.0, covered * 1.0 + (0.5 if prediction.get("category") == "性格" else 0))
    
    def _calculate_user_friendliness(self, category: str, 
                                     history: list[dict]) -> float:
        """
        用户友好度评分：
        - 父母状况：0.9（绝大多数人知道）
        - 兄弟姐妹：0.8（绝大多数人知道）
        - 婚姻：0.8（绝大多数人知道）
        - 学历：0.9（绝大多数人知道）
        - 事业：0.7（部分人可能不确定）
        - 关键年份：0.5（很多人不记得具体年份细节）
        - 性格：0.6（主观性强，可能答"不太确定"）
        
        如果用户连续 3 条反馈都是"不确定"（supplement），降低整体友好度
        """
        base_friendliness = {
            "父母关": 0.9, "兄弟关": 0.8, "婚姻关": 0.8,
            "学历": 0.9, "事业": 0.7, "关键年份": 0.5, "性格": 0.6,
        }
        
        base = base_friendliness.get(category, 0.7)
        
        # 检查最近 3 条反馈
        recent = history[-3:] if len(history) >= 3 else history
        supplement_count = sum(1 for h in recent if h.get("status") == "supplement")
        if supplement_count >= 3:
            base *= 0.7
        
        return round(base * 2, 1)  # 映射到 0-2 范围
    
    def _generate_rationale(self, prediction: dict, category: str, 
                           total_score: float) -> str:
        """生成为何选中此断事的理由"""
        templates = {
            "父母关": "父母关对时辰和格局区分度极高，是过三关的核心锚点，且用户几乎必定知道答案",
            "兄弟关": "兄弟关直接关联月柱格局，且为过三关之一，信息客观不可篡改",
            "婚姻关": "婚姻关直接关联日柱和配偶宫，是过三关之一，区分度高",
            "学历": "学历验证印星是否得力，可同时覆盖用神和旺衰两个不确定参数",
            "事业": "事业验证格局用神正确性的间接指标",
            "关键年份": "关键年份利用'内部对照'原理，最适合证伪式验证",
            "性格": "性格为开场破冰问题，虽区分度低但有助于建立信任关系",
        }
        return templates.get(category, "具有验证价值")
    
    def select_top_predictions(self, candidates: list[dict],
                               uncertainty: UncertaintyReport,
                               history: list[dict],
                               max_count: int = 5) -> list[dict]:
        """
        从候选断事中选取 Top N 条高区分度断事
        
        动态题量调整：
        - 初始 5 条
        - 如果用户连续 3 条 feedback 都是"不确定"（supplement），缩短为 3 条
        """
        # 动态题量
        recent_supplements = sum(
            1 for h in history[-3:] 
            if h.get("status") == "supplement"
        )
        if recent_supplements >= 3:
            max_count = min(3, max_count)
        
        # 计算每条候选的区分度评分
        scored = [self.calculate_discrimination_score(c, uncertainty, history) 
                  for c in candidates]
        
        # 按总分排序
        scored.sort(key=lambda x: x["total_score"], reverse=True)
        
        # 选取 Top N
        selected = scored[:max_count]
        
        return [{
            **s["prediction"],
            "discrimination_score": s["total_score"],
            "breakdown": s["breakdown"],
            "rationale": s["rationale"],
            "selected_because": s["details"],
        } for s in selected]
```

### 与现有代码的关系

| 操作 | 文件 |
|------|------|
| **修改** | `services/predictions.py`：新增 `SmartPredictionSelector` 类（约 200 行） |
| **修改** | `services/predictions.py`：`generate_predictions` 可选调用 selector |
| **不变** | Mock 构建函数（`_build_*`）、AI 生成函数不变 |

### 测试验证

1. **区分度排序**：父母关 + 高风险时辰 → 应排第一（≈9 分）
2. **性格低区分度**：性格推断 → 应排最后（≈4 分）
3. **动态题量**：history 中连续 3 条 supplement → max_count 降为 3
4. **不确定参数覆盖**：学历推断 → 覆盖 yongshen + wangshuai → coverage≥2

---

## 模块 9：六步推导法 Prompt 嵌入

### 理论依据

**报告引用**：第 2 章 2.4 节 "六步推导法详解"

六步：定格局→辨用神→明喜忌→十神定位→宫位取象→应期锁定

中间层四要素的主次关系：
- 主干：十神定位 + 生克制化
- 分支：宫位取象 + 刑冲合害

"在断前验证中，优先检查十神定位和生克制化两个主干是否正确；若主干有误，分支层面的调整无法挽救整体判断"

### 现有代码状态

- `services/verification.py`：`SYSTEM_PROMPT` 有格局派概念（顺用/逆用、相神角色、败因检测），但未显式嵌入六步推导法
- prompt 是单一层级的，没有逐步调用的能力
- `services/classical_judge.py`：有典籍 AI 判断，但未按六步结构化
- **结论：部分实现**。有基本的 Prompt 体系但缺少六步结构化模板

### 设计方案

#### 新增文件：`services/six_step_prompt.py`

```python
"""六步推导法 Prompt 模板工厂

基于《子平断前事研究报告-终稿.md》第 2.4 节：
定格局→辨用神→明喜忌→十神定位→宫位取象→应期锁定
"""

SIX_STEP_TEMPLATES = {
    1: {
        "name": "定格局",
        "core_question": "命主的基本格局类型是什么？",
        "classical_basis": "《子平真诠·论用神》：'八字用神，专求月令。以日干配月令地支，而生克不同，格局分焉。'",
        "operation_rules": """
1. 以月令地支藏干本气相对于日主的十神确定格局类型
2. 若月令本气不透，检查中气/余气是否在天干透出（透干优先）
3. 若月令被冲，则需从他处另寻用神
4. 枚举从正八格→建禄/月刃→特殊格局的优先级
""",
        "output_format": """
格局类型：{正官格/七杀格/正财格/偏财格/正印格/偏印格/食神格/伤官格/建禄格/月刃格}
月令依据：月支{地支}藏干{本气天干}→十神{十神}→{格局}
透干变化：{有/无}
""",
    },
    2: {
        "name": "辨用神",
        "core_question": "真正决定命局走向的力量是什么？",
        "classical_basis": "《滴天髓·真假》：'令上寻真聚得真，假神休要乱真神。真神得用生平贵，用假终为碌碌人。'",
        "operation_rules": """
1. 用神 = 月令定格之物（格局本身），直接确定，不竞争
2. 区分真神（透干有根无伤）与假神（透干无根 / 有根不透 / 被克被合）
3. 检查用神是"当权"还是"透出"——《子平真诠》第 6 章："当权者而不用，不当权者而用之，则失其本矣"
""",
        "output_format": """
用神十神：{十神}
用神五行：{五行}
用神状态：{真神得用/假神得局/真神暗藏/用神不显}
判断依据：{透干/有根/无伤 的检查结果}
""",
    },
    3: {
        "name": "明喜忌",
        "core_question": "谁助我？谁伤我？",
        "classical_basis": "《子平真诠·论用神成败得失》：'用神之成，在于得护得救。用神之败，在于被伤被破。'",
        "operation_rules": """
1. 根据格局类型确定喜忌方向：
   - 善神（财官印食）顺用：喜生护之神，忌克破之神
   - 恶神（杀伤枭刃）逆用：喜制化之神，忌助恶之神
2. 根据 PATTERN_XIANGSHEN_RULES 查找相神候选和忌神列表
3. 应用调候/扶抑加权因子调整
""",
        "output_format": """
喜神：{十神1}（{五行}）、{十神2}（{五行}）
忌神：{十神1}（{五行}）、{十神2}（{五行}）
喜忌依据：{顺用/逆用规则 + 调候考量}
""",
    },
    4: {
        "name": "十神定位",
        "core_question": "财官印食伤各应何事何人？",
        "classical_basis": "《渊海子平·六亲总篇》：'用日干为主：正印正母；偏印偏母及祖父也；偏财是父……'",
        "operation_rules": """
主干检查（优先）：
1. 十神定位是全盘的逻辑骨架，必须优先验证是否正确
2. 检查日干与各天干的十神关系 -> 确保 `_calc_ten_god` 正确
3. 十神定错 = 全盘皆误，必须优先修正
""",
        "output_format": """
年干{天干}→{十神}：{应事/应人}
月干{天干}→{十神}：{应事/应人}
日支{地支}→{十神}：{应事/应人}
时干{天干}→{十神}：{应事/应人}
""",
    },
    5: {
        "name": "宫位取象",
        "core_question": "事件发生在哪个生活层面？",
        "classical_basis": "《子平真诠·论六亲》：'六亲之论，以十神定其本，以宫位明其位，以旺衰判其力。'",
        "operation_rules": """
分支映射（依赖前四步）：
1. 年柱→祖上/童年/1-16岁
2. 月柱→父母/门第/17-32岁
3. 日柱→自身/配偶/33-48岁
4. 时柱→子女/晚年/49岁以后
""",
        "output_format": """
事件类型：{事件}
对应宫位：{年/月/日/时 柱}（{宫位解释}）
年龄范围：{起始-结束} 岁
""",
    },
    6: {
        "name": "应期锁定",
        "core_question": "吉凶应于何年何月？",
        "classical_basis": "《子平真诠·论大运流年》：'体用变三者合一，方能准确判断一岁之吉凶。'",
        "operation_rules": """
1. 先定大运（十年应期）：
   - 喜神运 → 此十年趋势向上
   - 忌神运 → 此十年趋势向下
2. 再定流年（一年应期）：
   - 用神透干/得禄之年 → 显著事件应期
   - 刑冲合害触发之年 → 变故应期
""",
        "output_format": """
当前大运：{干支}（{十神}）{喜/忌/中性}
关键流年：
  - {年份}年：{用神/忌神}透干/得禄 → 应{吉/凶/变}
  - {年份}年：{冲/合/刑}触发 → 应{事件}
""",
    },
}


def build_step_prompt(step_number: int, bazi_data: dict, 
                      rag_results: list = None) -> str:
    """
    构建单步推导 Prompt
    
    Args:
        step_number: 1-6
        bazi_data: 八字排盘数据
        rag_results: RAG 检索到的典籍原文
    
    Returns:
        该步骤的完整 Prompt 字符串
    """
    template = SIX_STEP_TEMPLATES.get(step_number, {})
    if not template:
        return f"步骤 {step_number} 不存在（六步推导法仅 1-6 步）"
    
    # 构建前序步骤的结论摘要（如果存在）
    prior_context = ""
    if "prior_conclusions" in bazi_data:
        prior_context = "前序步骤结论：\n"
        for i in range(1, step_number):
            if str(i) in bazi_data.get("prior_conclusions", {}):
                prior_context += f"步骤{i}：{bazi_data['prior_conclusions'][str(i)]}\n"
    
    # 构建典籍引用
    classical_refs = ""
    if rag_results:
        classical_refs = "\n典籍参考：\n" + "\n".join(
            r.get("text", r.get("excerpt", ""))[:200] 
            for r in rag_results[:3]
        )
    
    prompt = f"""## 步骤 {step_number}：{template['name']}

### 核心问题
{template['core_question']}

### 古籍依据
{template['classical_basis']}

### 操作规则
{template['operation_rules']}

### 八字数据
{_format_bazi_for_step(bazi_data, step_number)}

### 输出格式
{template['output_format']}

{prior_context}
{classical_refs}

### 中间层主次关系提醒
⚠️ 优先检查十神定位和生克制化两个主干是否正确。
   若主干有误，分支层面的调整无法挽救整体判断。
"""
    return prompt


def build_full_pipeline_prompt(bazi_data: dict, rag_results: list = None) -> str:
    """
    构建一次性全量六步推导 Prompt（供一次性分析场景）
    """
    steps_text = []
    for i in range(1, 7):
        t = SIX_STEP_TEMPLATES[i]
        steps_text.append(
            f"### 步骤{i}：{t['name']}\n"
            f"核心问题：{t['core_question']}\n"
            f"古籍依据：{t['classical_basis']}\n"
            f"操作规则：{t['operation_rules']}\n"
            f"输出格式：{t['output_format']}\n"
        )
    
    pipeline = "\n---\n".join(steps_text)
    
    return f"""你是一位严格遵循子平格局派体系的命理师。请按以下六步推导法完整分析此命盘。

## 六步推导法

{pipeline}

## 八字数据
{_format_bazi_full(bazi_data)}

## 重要提醒
1. 每一步依赖前序步骤的结论，不可跳跃
2. 优先检查十神定位和生克制化两个主干
3. 每步必须引用对应的古籍原文
4. 所有判断必须有明确的命理依据，不可猜测
"""
```

#### 重构 `services/verification.py` 的 `SYSTEM_PROMPT`

在现有 `SYSTEM_PROMPT` 中嵌入六步推导法骨架：

```python
SYSTEM_PROMPT_V2 = SYSTEM_PROMPT + """

## 六步推导框架（必须遵循）

在进行任何命理分析时，遵循以下六步推导法：

1. 定格局 — 月令取格，确定正八格或变格
2. 辨用神 — 区分真神假神，确认格局用神
3. 明喜忌 — 确定喜神（辅格助用）与忌神（破格损用）
4. 十神定位 — 各十神配六亲、配事象（⚠️ 主干，优先检查）
5. 宫位取象 — 年月日时四柱对应人生领域（分支，依赖前四步）
6. 应期锁定 — 大运流年与命局作用定吉凶时间

中间层主次关系：
- 主干：十神定位 + 生克制化 → 优先检查，主干有误则分支无效
- 分支：宫位取象 + 刑冲合害 → 依赖主干，不纠缠分支

每一步推导必须引用对应的古籍原文。不可跳跃步骤。
"""
```

### 与现有代码的关系

| 操作 | 文件 |
|------|------|
| **新增** | `services/six_step_prompt.py`（约 250 行） |
| **修改** | `services/verification.py`：`SYSTEM_PROMPT` 嵌入六步框架 |
| **不变** | 现有 `init_verification`、`process_verification` 逻辑不变 |

### 测试验证

1. **逐步调用**：`build_step_prompt(1, data)` → 输出仅第 1 步（定格局）的 Prompt
2. **全量调用**：`build_full_pipeline_prompt(data)` → 输出完整六步 Prompt
3. **前序依赖**：step=4 的 prompt 中包含 step 1-3 的 prior_conclusions
4. **主干提醒**：所有 prompt 包含"优先检查十神定位和生克制化"的提醒

---

## 模块 10：修正触发阈值量化

### 理论依据

**报告引用**：第 3 章 "Level 0-5 逐层触发条件"

| Level | 触发条件 | 量化标准 |
|-------|---------|---------|
| L0 | 大面积不匹配 | 超过 50% 的验证项出现偏差 |
| L1 | 用神所主事项与命主实际经历矛盾 | 时辰无误但用神相关推断 inaccurate |
| L2 | 喜忌方向与事实违背 | 用神取定无误但喜忌方向反了 |
| L3 | 正格取用无法解释重大人生转折 | 日主明显孤弱或过旺 |
| L4 | 整体方向（富/贵/贫/贱）与事实相反 | 整体方向仍与事实相反 |
| L5 | 特定大运期间事项与推论严重不符 | 原局判定无误但大运矛盾 |

### 现有代码状态

- `services/correction_v2.py`：`CorrectionEngine` 有从 `reconciliation.get("correction_level", 0)` 开始循环的逻辑，但触发条件由比 `reconciler` 的输出决定
- `services/correction.py`：`determine_next_path` 有双路径切换逻辑，但 Level 触发判断分散在各处
- **结论：部分实现**。有修正框架但缺少统一的 `CorrectionTriggerConfig` 和 `should_trigger()` 判定体系

### 设计方案

#### 在 `services/correction_v2.py` 中新增 `CorrectionTriggerConfig`

```python
# ============================================================
# 修正触发阈值配置
# ============================================================

from pydantic import BaseModel

class TriggerRule(BaseModel):
    """单条触发规则"""
    condition: str      # 条件描述
    threshold: float    # 阈值
    enabled: bool = True

class CorrectionTriggerConfig:
    """五级修正触发阈值配置"""
    
    TRIGGER_CONFIG = {
        "L0": {
            "name": "验盘修正",
            "classical_source": "《滴天髓·生时》：'时之不的当者，十有四五'",
            "rules": [
                TriggerRule(condition="inaccurate_rate", threshold=0.50),
                TriggerRule(condition="core_pass_count", threshold=0),  # 核心三关 0/3
            ],
            "trigger_logic": "inaccurate_rate ≥ 0.5 AND core_pass_count ≤ 0",
        },
        "L1": {
            "name": "用神修正",
            "classical_source": "《子平真诠·论用神变化》：'透干不同则用神变'",
            "rules": [
                TriggerRule(condition="inaccurate_rate_yongshen_related", threshold=0.30),
                TriggerRule(condition="yongshen_true_pass", threshold=0),  # 用神真假验证失败
            ],
            "trigger_logic": "yongshen_true_pass = False OR inaccurate_rate_yongshen_related ≥ 0.3",
        },
        "L2": {
            "name": "旺衰重判",
            "classical_source": "《滴天髓·旺衰》：'旺者抑之，如不可抑，又宜扶之'",
            "rules": [
                TriggerRule(condition="wangshen_related_inaccurate", threshold=True),
                TriggerRule(condition="dayun_xi_ji_mismatch_rate", threshold=0.50),
            ],
            "trigger_logic": "wangshen_related_inaccurate = True AND dayun_xi_ji_mismatch_rate ≥ 0.5",
        },
        "L3": {
            "name": "格局切换",
            "classical_source": "《滴天髓·从化》：'真从之象有几人，假从亦可发其身'",
            "rules": [
                TriggerRule(condition="career_prediction_inaccurate", threshold=True),
                TriggerRule(condition="day_master_extreme", threshold=True),
                TriggerRule(condition="congge_boundary", threshold=True),
            ],
            "trigger_logic": "(career_prediction_inaccurate OR marriage_prediction_inaccurate) "
                           "AND (day_master_extreme OR congge_boundary)",
        },
        "L4": {
            "name": "众寡之势",
            "classical_source": "《滴天髓·众寡》：'强众而敌寡者，势在去其寡'",
            "rules": [
                TriggerRule(condition="overall_direction_contradicts", threshold=True),
                TriggerRule(condition="one_element_dominance", threshold=True),
            ],
            "trigger_logic": "overall_direction_contradicts = True AND one_element_dominance = True",
        },
        "L5": {
            "name": "行运修正",
            "classical_source": "《子平真诠·论行运成格变格》",
            "rules": [
                TriggerRule(condition="specific_dayun_contradicts", threshold=True),
                TriggerRule(condition="original_pattern_confirmed", threshold=True),
            ],
            "trigger_logic": "specific_dayun_contradicts = True AND original_pattern_confirmed = True",
        },
    }
    
    # 修正迭代上限
    MAX_CORRECTION_ITERATIONS = 3  # 最多 3 轮完整修正（L0→L5 算一轮）
    
    # 不可逆原则
    IRREVERSIBLE_LEVELS = True  # 只能从 max(applied_levels) + 1 开始
    
    def should_trigger(self, level: str, state: dict) -> dict:
        """
        判断某 Level 是否应该触发
        
        Args:
            level: "L0"|"L1"|"L2"|"L3"|"L4"|"L5"
            state: 当前修正状态字典，包含：
                - inaccurate_rate: 不准确比例
                - core_pass_count: 核心三关通过数
                - inaccurate_rate_yongshen_related: 用神相关不准确比例
                - yongshen_true_pass: 用神真假是否通过
                - wangshen_related_inaccurate: 旺衰相关是否不准确
                - dayun_xi_ji_mismatch_rate: 大运喜忌不匹配率
                - career_prediction_inaccurate: 事业推断是否不准确
                - day_master_extreme: 日主是否极端
                - congge_boundary: 是否在从格边界
                - overall_direction_contradicts: 整体方向是否矛盾
                - one_element_dominance: 是否单一五行主导
                - specific_dayun_contradicts: 是否特定大运矛盾
                - original_pattern_confirmed: 原局判定是否确认
                - applied_levels: 已应用的修正等级列表
                - iteration_count: 当前迭代轮数
        
        Returns:
            {"trigger": bool, "reason": str, "level_config": dict}
        """
        config = self.TRIGGER_CONFIG.get(level, {})
        if not config:
            return {"trigger": False, "reason": f"未知层级 {level}"}
        
        # === 不可逆原则检查 ===
        applied_levels = state.get("applied_levels", [])
        if applied_levels:
            current_level_num = int(level[1])  # "L3" → 3
            max_applied = max(applied_levels)
            if current_level_num <= max_applied:
                return {
                    "trigger": False,
                    "reason": f"不可逆原则：Level {max_applied} 已应用，不可回退到 Level {current_level_num}",
                }
        
        # === 迭代上限检查 ===
        iteration = state.get("iteration_count", 0)
        if iteration >= self.MAX_CORRECTION_ITERATIONS:
            return {
                "trigger": False,
                "reason": f"已达最大修正迭代次数（{self.MAX_CORRECTION_ITERATIONS}），返回 INDETERMINATE",
            }
        
        # === 触发条件判定 ===
        rules = config.get("rules", [])
        
        if level == "L0":
            inaccurate_rate = state.get("inaccurate_rate", 0)
            core_pass = state.get("core_pass_count", 3)
            trigger = inaccurate_rate >= 0.5 and core_pass <= 0
            reason = (f"不准确率 {inaccurate_rate:.0%}（阈值 50%），"
                     f"核心三关通过 {core_pass}/3" +
                     (" → 触发" if trigger else " → 不触发"))
        
        elif level == "L1":
            # L0 通过但用神相关不准确
            yongshen_false = not state.get("yongshen_true_pass", True)
            yongshen_inacc = state.get("inaccurate_rate_yongshen_related", 0)
            trigger = yongshen_false or yongshen_inacc >= 0.3
            reason = (f"用神真假验证={'通过' if not yongshen_false else '失败'}，"
                     f"用神相关不准确率 {yongshen_inacc:.0%}（阈值 30%）" +
                     (" → 触发" if trigger else " → 不触发"))
        
        elif level == "L2":
            wangshuai_wrong = state.get("wangshen_related_inaccurate", False)
            mismatch = state.get("dayun_xi_ji_mismatch_rate", 0)
            trigger = wangshuai_wrong and mismatch >= 0.5
            reason = (f"旺衰相关={'不准确' if wangshuai_wrong else '准确'}，"
                     f"大运喜忌不匹配率 {mismatch:.0%}（阈值 50%）" +
                     (" → 触发" if trigger else " → 不触发"))
        
        elif level == "L3":
            career_wrong = state.get("career_prediction_inaccurate", False)
            marriage_wrong = state.get("marriage_prediction_inaccurate", False)
            extreme = state.get("day_master_extreme", False)
            boundary = state.get("congge_boundary", False)
            trigger = (career_wrong or marriage_wrong) and (extreme or boundary)
            reason = (f"事业={'不准确' if career_wrong else '准确'}，"
                     f"日主极端={extreme}，从格边界={boundary}" +
                     (" → 触发" if trigger else " → 不触发"))
        
        elif level == "L4":
            contradicts = state.get("overall_direction_contradicts", False)
            dominance = state.get("one_element_dominance", False)
            trigger = contradicts and dominance
            reason = (f"整体方向矛盾={contradicts}，"
                     f"单一五行主导={dominance}" +
                     (" → 触发" if trigger else " → 不触发"))
        
        elif level == "L5":
            dayun_contra = state.get("specific_dayun_contradicts", False)
            confirmed = state.get("original_pattern_confirmed", False)
            trigger = dayun_contra and confirmed
            reason = (f"特定大运矛盾={dayun_contra}，"
                     f"原局判定确认={confirmed}" +
                     (" → 触发" if trigger else " → 不触发"))
        
        else:
            trigger = False
            reason = f"未知层级 {level}"
        
        return {
            "trigger": trigger,
            "reason": reason,
            "level_config": {
                "name": config["name"],
                "classical_source": config["classical_source"],
            },
        }
    
    def get_next_level(self, state: dict) -> int:
        """根据不可逆原则，获取下一个应尝试的修正层级"""
        applied = state.get("applied_levels", [])
        if not applied:
            return 0  # 从 L0 开始
        return max(applied) + 1  # 不可逆：只能向前
    
    def check_iteration_limit(self, state: dict) -> dict:
        """检查是否超过迭代上限"""
        iteration = state.get("iteration_count", 0)
        if iteration >= self.MAX_CORRECTION_ITERATIONS:
            return {
                "exceeded": True,
                "status": "INDETERMINATE",
                "message": f"已进行 {iteration} 轮完整修正（上限 {self.MAX_CORRECTION_ITERATIONS}），"
                          f"建议人工复核或确认出生时间。",
            }
        return {"exceeded": False}


def build_correction_state(hexagram_report: dict, 
                           uncertainty: dict,
                           feedback_stats: dict) -> dict:
    """
    从六维报告、不确定参数、反馈统计构建修正状态字典
    
    用于传递给 should_trigger()
    """
    scores = {s["dimension"]: s["score"] for s in hexagram_report.get("scores", [])}
    
    return {
        # L0 条件
        "inaccurate_rate": feedback_stats.get("inaccurate_rate", 0),
        "core_pass_count": feedback_stats.get("core_pass_count", 0),
        
        # L1 条件
        "inaccurate_rate_yongshen_related": feedback_stats.get("yongshen_inaccurate_rate", 0),
        "yongshen_true_pass": (scores.get("用神验证", 0) >= 6),
        
        # L2 条件
        "wangshen_related_inaccurate": (scores.get("旺衰验证", 0) < 6),
        "dayun_xi_ji_mismatch_rate": feedback_stats.get("dayun_mismatch_rate", 0),
        
        # L3 条件
        "career_prediction_inaccurate": feedback_stats.get("career_inaccurate", False),
        "marriage_prediction_inaccurate": feedback_stats.get("marriage_inaccurate", False),
        "day_master_extreme": uncertainty.get("day_master_extreme", False),
        "congge_boundary": uncertainty.get("congge_boundary", False),
        
        # L4 条件
        "overall_direction_contradicts": feedback_stats.get("overall_contradiction", False),
        "one_element_dominance": uncertainty.get("one_element_dominance", False),
        
        # L5 条件
        "specific_dayun_contradicts": feedback_stats.get("dayun_contradiction", False),
        "original_pattern_confirmed": (scores.get("格局喜忌验证", 0) >= 6),
        
        # 修正状态
        "applied_levels": [],
        "iteration_count": 0,
    }
```

### 与现有代码的关系

| 操作 | 文件 |
|------|------|
| **修改** | `services/correction_v2.py`：新增 `CorrectionTriggerConfig`（约 200 行）、`build_correction_state` |
| **修改** | `services/correction_v2.py`：`CorrectionEngine.correct()` 用 `should_trigger()` 替代现有硬编码逻辑 |
| **不变** | `models.py`、外部接口 |

### 测试验证

1. **L0 触发**：inaccurate_rate=0.6 + core_pass_count=0 → trigger=True
2. **L0 不触发**：inaccurate_rate=0.4 + core_pass_count=2 → trigger=False
3. **不可逆原则**：applied_levels=[0, 1]，尝试 L1 → trigger=False（已应用）
4. **迭代上限**：iteration_count=3 → trigger=False, status="INDETERMINATE"
5. **L3 触发**：career_prediction_inaccurate=True + day_master_extreme=True → trigger=True

---

## 总结

### 文件变更矩阵

| 分类 | 新增文件 | 修改文件 |
|------|---------|---------|
| **核心缺失** | `services/precheck/__init__.py`<br>`services/precheck/uncertainty_labeler.py` | `models.py`（新增 2 个模型）<br>`bazi_engine.py`（集成接口） |
| | `rules/gongwei.py` | `services/calibration.py`（新增 HexagramValidator） |
| | — | `services/calibration.py`（新增三重判定 + final_verdict_v2） |
| **部分实现** | `services/correction/__init__.py`<br>`services/correction/level1_yongshen.py` | `services/correction_v2.py`（调用新模块） |
| | `services/correction/level5_dayun.py` | 同上 |
| | — | `rules/pattern.py`（增强从格/化气格检测） |
| | — | `services/predictions.py`（新增 SmartPredictionSelector） |
| | `services/six_step_prompt.py` | `services/verification.py`（SYSTEM_PROMPT 嵌入六步法） |
| | — | `services/correction_v2.py`（新增 CorrectionTriggerConfig） |

### 设计原则验证

| 原则 | 验证 |
|------|------|
| 理论先行 | 每个模块第一节即为"理论依据"，引用报告章节 + 古籍原文 |
| 规则引擎优先 | 模块 1、4 为纯规则引擎；模块 2、3、10 为规则+判定；模块 5-9 仅在需要语义推理时调用 AI |
| 兼容现有架构 | 所有新增模块在 `rules/` 或 `services/` 下，遵循四层架构；所有修改保持向后兼容 |
| 可量化 | 所有阈值（≥4/6、≤1 反例、≥3 流年、0.5/0.3 触发比、0-10 评分）均有明确数值 |
