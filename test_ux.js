const { chromium } = require('playwright');

const URL = "https://ai-bazi-production.up.railway.app";

(async () => {
  const report = [];
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  // 1. 加载
  console.log("=== 1. 页面加载 ===");
  await page.goto(URL, { waitUntil: "networkidle", timeout: 30000 });
  const title = await page.title();
  report.push({ item: "页面标题", result: title, pass: title.includes("命盘") });
  console.log(`  标题: ${title}`);

  // 2. 页面结构
  console.log("\n=== 2. 页面结构分析 ===");
  
  // 检查关键区块
  const sections = await page.evaluate(() => {
    const headings = Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,h6,header,.step,.card"));
    return headings.map(h => ({ tag: h.tagName, text: h.textContent.trim().slice(0, 50) }));
  });
  console.log("  页面区块:", JSON.stringify(sections.slice(0, 10), null, 2));

  // 检查按钮
  const btns = await page.evaluate(() => {
    return Array.from(document.querySelectorAll("button")).map(b => ({
      text: b.textContent.trim().slice(0, 30),
      visible: b.offsetParent !== null,
      disabled: b.disabled
    }));
  });
  console.log("  按钮列表:", JSON.stringify(btns, null, 2));
  report.push({ item: "页面按钮数", result: btns.length.toString(), pass: btns.length > 3 });

  // 3. 点击"填入示例"
  console.log("\n=== 3. 填入示例数据 ===");
  const fillBtn = page.locator('button:has-text("填入示例")');
  if (await fillBtn.count() > 0) {
    await fillBtn.click();
    console.log("  已点击'填入示例'");
    await page.waitForTimeout(1000);
    report.push({ item: "填入示例功能", result: "OK", pass: true });
  } else {
    console.log("  未找到'填入示例'按钮");
  }

  // 检查表单是否填充
  const formState = await page.evaluate(() => {
    const inputs = Array.from(document.querySelectorAll("input"));
    return inputs.map(i => ({ 
      type: i.type, 
      placeholder: i.placeholder, 
      value: i.value?.slice(0, 20),
      visible: i.offsetParent !== null 
    }));
  });
  console.log("  表单状态:", JSON.stringify(formState.filter(f => f.visible), null, 2));

  // 4. 点击"生成基础盘"
  console.log("\n=== 4. 提交排盘 ===");
  await page.waitForTimeout(500);
  
  const submitBtn = page.locator('#submit-btn, button:has-text("生成基础盘")').first();
  const submitVisible = await submitBtn.isVisible();
  const submitDisabled = await submitBtn.isDisabled();
  console.log(`  提交按钮: visible=${submitVisible}, disabled=${submitDisabled}`);
  
  if (submitVisible && !submitDisabled) {
    await submitBtn.click();
    console.log("  已点击提交");
    report.push({ item: "提交按钮可点击", result: "OK", pass: true });
  } else {
    // 尝试 force click
    try {
      await submitBtn.click({ force: true, timeout: 5000 });
      console.log("  force click 完成");
    } catch(e) {
      console.log("  无法点击提交按钮:", e.message.slice(0, 80));
      report.push({ item: "提交按钮可用性", result: e.message.slice(0, 60), pass: false });
      
      // 尝试直接调 API
      console.log("\n  改用 API 直接测试...");
    }
  }

  // 等结果
  await page.waitForTimeout(5000);
  try { await page.waitForLoadState("networkidle", { timeout: 10000 }); } catch(e) {}

  // 5. 检查结果
  console.log("\n=== 5. 结果检查 ===");
  const bodyText = await page.locator("body").innerText();
  
  const checks = {
    "天干": ["甲","乙","丙","丁","戊","己","庚","辛","壬","癸"],
    "地支": ["子","丑","寅","卯","辰","巳","午","未","申","酉","戌","亥"],
    "十神": ["正官","七杀","正印","偏印","正财","偏财","食神","伤官","比肩","劫财"],
    "用神": ["用神"],
    "大运": ["大运"],
    "五行": ["金","木","水","火","土"],
  };
  
  for (const [name, keywords] of Object.entries(checks)) {
    const found = keywords.some(k => bodyText.includes(k));
    report.push({ item: `结果包含${name}`, result: found ? "OK" : "MISSING", pass: found });
    console.log(`  ${name}: ${found ? "OK" : "MISSING"}`);
  }

  // 6. API 测试
  console.log("\n=== 6. API 直接测试 ===");
  const apiResult = await page.evaluate(async () => {
    const resp = await fetch("/api/chart", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        year: 1995, month: 8, day: 15, hour: 12, minute: 0,
        gender: "male", calendar: "solar", city: "北京"
      })
    });
    const data = await resp.json();
    return {
      status: resp.status,
      day_master: data.day_master,
      has_pillars: !!data.four_pillars && !!data.four_pillars.year,
      has_dayun: Array.isArray(data.dayun) && data.dayun.length > 0,
      has_yongshen: !!data.yongshen && !!data.yongshen.pattern,
      has_wuxing: !!data.wuxing_score
    };
  });
  console.log("  API:", JSON.stringify(apiResult, null, 2));
  report.push({ item: "API day_master", result: apiResult.day_master || "MISSING", pass: !!apiResult.day_master });
  report.push({ item: "API 四柱", result: apiResult.has_pillars ? "OK" : "FAIL", pass: apiResult.has_pillars });
  report.push({ item: "API 大运", result: apiResult.has_dayun ? "OK" : "FAIL", pass: apiResult.has_dayun });
  report.push({ item: "API 用神", result: apiResult.has_yongshen ? "OK" : "FAIL", pass: apiResult.has_yongshen });
  report.push({ item: "API 五行", result: apiResult.has_wuxing ? "OK" : "FAIL", pass: apiResult.has_wuxing });

  // 7. 移动端
  console.log("\n=== 7. 移动端适配 ===");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(1000);
  const overflow = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    hasOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 10
  }));
  console.log("  移动端:", JSON.stringify(overflow));
  report.push({ item: "移动端无溢出", result: overflow.hasOverflow ? "有溢出" : "OK", pass: !overflow.hasOverflow });

  await browser.close();

  // 报告
  console.log("\n" + "=".repeat(60));
  console.log("  UI/UX 测试报告");
  console.log("=".repeat(60));
  for (const r of report) {
    console.log(`  [${r.pass ? "OK" : "FAIL"}] ${r.item}: ${r.result}`);
  }
  const passCount = report.filter(r => r.pass).length;
  console.log("=".repeat(60));
  console.log(`  通过: ${passCount}/${report.length}`);
  console.log("=".repeat(60));
})();
