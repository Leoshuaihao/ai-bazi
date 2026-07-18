"""ai-bazi UI 流程测试 - Playwright 自动化"""
import asyncio
from playwright.async_api import async_playwright
import json

URL = "https://ai-bazi-production.up.railway.app"

async def test_bazi_flow():
    results = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        
        # ====== 1. 页面加载 ======
        print("[1/6] 加载页面...")
        await page.goto(URL, wait_until="networkidle", timeout=30000)
        title = await page.title()
        results.append(("页面标题", title, "包含'命盘'" in title))
        
        # 截图首页
        await page.screenshot(path="/tmp/bazi_01_home.png", full_page=False)
        print("  截图: bazi_01_home.png")
        
        # 检查关键元素
        has_title = await page.locator("h1, .title, header").count() > 0
        results.append(("首页有标题/头部", str(has_title), has_title))
        
        # ====== 2. 输入表单测试 ======
        print("[2/6] 填写出生信息...")
        
        # 找输入框 - 尝试多种可能的 selector
        inputs = page.locator("input, select, textarea")
        input_count = await inputs.count()
        results.append(("表单输入元素数量", str(input_count), input_count > 2))
        
        # 尝试填写年份
        year_inputs = page.locator('input[type="number"], input[placeholder*="年" i], input[name*="year" i], input#year')
        year_count = await year_inputs.count()
        
        if year_count > 0:
            await year_inputs.first.fill("1995")
            print("  -> 填写年份: 1995")
        
        # 尝试填写月份
        month_inputs = page.locator('input[placeholder*="月" i], input[name*="month" i], input#month')
        month_count = await month_inputs.count()
        if month_count > 0:
            await month_inputs.first.fill("8")
            print("  -> 填写月份: 8")
        
        # 尝试填写日
        day_inputs = page.locator('input[placeholder*="日" i], input[name*="day" i], input#day')
        day_count = await day_inputs.count()
        if day_count > 0:
            await day_inputs.first.fill("15")
            print("  -> 填写日期: 15")
        
        # 尝试填写时
        hour_inputs = page.locator('input[placeholder*="时" i], input[name*="hour" i], input#hour')
        if await hour_inputs.count() > 0:
            await hour_inputs.first.fill("12")
            print("  -> 填写时辰: 12")
        
        # 截图表单
        await page.screenshot(path="/tmp/bazi_02_form.png", full_page=True)
        print("  截图: bazi_02_form.png")
        
        # ====== 3. 点击排盘按钮 ======
        print("[3/6] 点击排盘...")
        
        submit_btns = page.locator('button:has-text("排盘"), button:has-text("分析"), button:has-text("开始"), button[type="submit"], button:has-text("测算")')
        btn_count = await submit_btns.count()
        results.append(("找到排盘按钮", str(btn_count > 0), btn_count > 0))
        
        if btn_count > 0:
            await submit_btns.first.click()
            print("  -> 已点击排盘按钮")
        
        # 等待结果加载
        await asyncio.sleep(3)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except:
            pass
        
        await page.screenshot(path="/tmp/bazi_03_result.png", full_page=True)
        print("  截图: bazi_03_result.png")
        
        # ====== 4. 检查结果 ======
        print("[4/6] 检查排盘结果...")
        
        body_text = await page.inner_text("body")
        has_stems = any(c in body_text for c in ["甲","乙","丙","丁","戊","己","庚","辛","壬","癸"])
        results.append(("结果中包含天干", str(has_stems), has_stems))
        print(f"  -> 天干: {'OK' if has_stems else 'FAIL'}")
        
        has_branches = any(c in body_text for c in ["子","丑","寅","卯","辰","巳","午","未","申","酉","戌","亥"])
        results.append(("结果中包含地支", str(has_branches), has_branches))
        print(f"  -> 地支: {'OK' if has_branches else 'FAIL'}")
        
        has_score = any(kw in body_text for kw in ["用神","格局","旺衰","五行","日主","大运"])
        results.append(("结果中包含分析关键词", str(has_score), has_score))
        print(f"  -> 分析内容: {'OK' if has_score else 'FAIL'}")
        
        # ====== 5. API 直接测试 ======
        print("[5/6] API 接口测试...")
        
        api_response = await page.evaluate("""async () => {
            try {
                const resp = await fetch('/api/chart', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        year: 1995, month: 8, day: 15, hour: 12, minute: 0,
                        gender: 'male', calendar: 'solar', city: '北京'
                    })
                });
                const data = await resp.json();
                return {status: resp.status, has_day_master: !!data.day_master, has_yongshen: !!data.yongshen};
            } catch(e) { return {error: e.message}; }
        }""")
        results.append(("API /chart 返回正常", str(api_response), api_response.get("has_day_master", False)))
        print(f"  -> API: {api_response}")
        
        # ====== 6. 响应式检查 ======
        print("[6/6] 移动端响应式...")
        await page.set_viewport_size({"width": 390, "height": 844})  # iPhone 14
        await asyncio.sleep(1)
        await page.screenshot(path="/tmp/bazi_04_mobile.png", full_page=True)
        print("  截图: bazi_04_mobile.png")
        
        # 检查是否有横向溢出
        page_width = await page.evaluate("document.documentElement.scrollWidth")
        viewport_width = 390
        no_horizontal_scroll = page_width <= viewport_width + 10
        results.append(("移动端无横向溢出", f"内容宽度={page_width}px", no_horizontal_scroll))
        print(f"  -> 内容宽度: {page_width}px (视口: {viewport_width}px) {'OK' if no_horizontal_scroll else 'OVERFLOW'}"))
        
        await browser.close()
    
    # 打印报告
    print("\n" + "="*60)
    print("  UI 测试报告")
    print("="*60)
    passed = 0
    failed = 0
    for name, detail, ok in results:
        status = "OK" if ok else "FAIL"
        if ok: passed += 1
        else: failed += 1
        print(f"  [{status}] {name}: {detail}")
    print("="*60)
    print(f"  通过: {passed}/{passed+failed}, 失败: {failed}/{passed+failed}")
    print("="*60)
    return results

if __name__ == "__main__":
    asyncio.run(test_bazi_flow())
