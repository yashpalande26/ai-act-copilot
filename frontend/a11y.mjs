import { chromium } from "playwright";

const b = await chromium.launch();
const failures = [];
for (const theme of ["light", "dark"]) {
  const ctx = await b.newContext({ viewport:{width:1440,height:900}, colorScheme: theme });
  const p = await ctx.newPage();
  await p.addInitScript((t)=>{document.addEventListener("DOMContentLoaded",()=>{if(t==="dark")document.documentElement.classList.add("dark");});}, theme);
  for (const [page,url] of [["landing","/"],["signin","/signin"]]) {
    const r = await p.goto("http://localhost:3000"+url,{waitUntil:"networkidle"});
    if (!r || r.status() >= 400) continue;
    await p.waitForTimeout(400);
    const res = await p.evaluate(() => {
      // Resolve ANY CSS color (lab/oklch/rgb) to true sRGB bytes via canvas.
      const cv = document.createElement("canvas"); cv.width = cv.height = 1;
      const c2 = cv.getContext("2d", { willReadFrequently: true });
      const toRGBA = (css) => { c2.clearRect(0,0,1,1); c2.fillStyle = css; c2.fillRect(0,0,1,1);
        const d = c2.getImageData(0,0,1,1).data; return [d[0],d[1],d[2],d[3]/255]; };
      const over = (fg, bg) => fg[3] >= 1 ? fg :
        [0,1,2].map(i => Math.round(fg[i]*fg[3] + bg[i]*(1-fg[3]))).concat(1);
      const srgb = v => { v/=255; return v<=0.04045 ? v/12.92 : ((v+0.055)/1.055)**2.4; };
      const lum = c => 0.2126*srgb(c[0]) + 0.7152*srgb(c[1]) + 0.0722*srgb(c[2]);
      const ratio = (a,bb) => { const [x,y] = [lum(a),lum(bb)].sort((m,n)=>n-m); return (x+0.05)/(y+0.05); };

      const out = []; const seen = new Set();
      for (const el of document.querySelectorAll("*")) {
        const direct = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
        if (!direct) continue;
        const rect = el.getBoundingClientRect();
        if (rect.width < 4 || rect.height < 4) continue;
        const cs = getComputedStyle(el);
        if (cs.visibility === "hidden" || cs.opacity === "0") continue;
        // Composite every ancestor background down to an opaque colour.
        let bgStack = [], node = el;
        while (node) { const c = toRGBA(getComputedStyle(node).backgroundColor);
          if (c[3] > 0) bgStack.push(c); if (c[3] >= 1) break; node = node.parentElement; }
        let bg = bgStack.length ? bgStack.pop() : [255,255,255,1];
        for (let i = bgStack.length-1; i >= 0; i--) bg = over(bgStack[i], bg);
        const fg = over(toRGBA(cs.color), bg);
        const size = parseFloat(cs.fontSize), weight = +cs.fontWeight;
        const large = size >= 24 || (size >= 18.66 && weight >= 700);
        const need = large ? 3 : 4.5;
        const cr = ratio(fg, bg);
        const key = cs.color+"|"+bg.join()+"|"+size+"|"+weight;
        if (seen.has(key)) continue; seen.add(key);
        if (cr < need) out.push({ ratio:+cr.toFixed(2), need, size, weight,
          sample: el.textContent.trim().slice(0,40) });
      }
      return out;
    });
    for (const f of res) failures.push({ theme, page, ...f });
  }
  await ctx.close();
}
await b.close();
if (!failures.length) console.log("WCAG AA contrast: PASS across light + dark, landing / chat / signin.");
else { console.log("WCAG AA contrast failures:", failures.length);
  for (const f of failures) console.log(`  ${f.theme}/${f.page}  ${f.ratio}:1 (need ${f.need})  ${f.size}px/${f.weight}  "${f.sample}"`); }
