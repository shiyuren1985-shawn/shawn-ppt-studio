const PAGE_REFERENCE_RE = /\bP\s*0*(\d{1,3})\b/gi;

function normalizedMessage(value) {
  return typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
}

function pageLabels(message) {
  const labels = [];
  for (const match of message.matchAll(PAGE_REFERENCE_RE)) {
    const label = `P${String(Number(match[1])).padStart(2, "0")}`;
    if (!labels.includes(label)) labels.push(label);
  }
  return labels;
}

function taskTitle(message, modeHint) {
  const pages = pageLabels(message);
  if (modeHint === "retouch") return `${pages[0] || "当前页"} · 修图`;
  if (modeHint === "fast_8x1") return `${pages[0] || "当前页"} · 8×1`;
  if (modeHint === "fast_4x3") {
    const scope = pages.length > 1 ? `${pages[0]}–${pages.at(-1)}` : pages[0] || "当前页";
    return `${scope} · 4×3`;
  }
  if (pages.length > 1) return `${pages[0]} 等 ${pages.length} 页 · 作图`;
  if (pages.length === 1) return `${pages[0]} · 作图`;
  return "图片生成";
}

export function classifyImageTaskRequest({
  message,
  retouchContext = false,
  referenceImages = [],
} = {}) {
  const text = normalizedMessage(message);
  if (!text) return null;
  let modeHint = null;
  if (retouchContext) modeHint = "retouch";
  else if (/(?:fast\s*8|8\s*[×xX]\s*1)/i.test(text)) modeHint = "fast_8x1";
  else if (/(?:fast\s*4|4\s*[×xX]\s*3)/i.test(text)) modeHint = "fast_4x3";

  const explicitPipeline = Boolean(modeHint) || /(?:selected[_ -]?style|选定风格扩页|整稿扩页)/i.test(text);
  const directChinese = /(?:请|帮我|给我|为|开始|执行|走|进行|我要|我想|需要|重新|继续|按|用).{0,24}(?:作图|生图|修图|改图|扩页)/u.test(text)
    || /(?:作图|生图|修图|改图|扩页).{0,18}(?:一下|一轮|一版|候选|图片|页面|管线|流程)/u.test(text)
    || /(?:请|帮我|给我|我要|我想|需要|重新|继续).{0,16}(?:做|画|出).{0,10}(?:\d+\s*张)?(?:图片|候选图|页面图)/u.test(text)
    || /(?:生成|制作|重做|修改|调整|优化|替换).{0,18}(?:图片|图像|候选图|页面图|PPT\s*页)/iu.test(text)
    || /(?:图片|图像|候选图|页面图|PPT\s*页).{0,18}(?:生成|制作|重做|修改|调整|优化|替换)/iu.test(text);
  const directEnglish = /\b(?:generate|create|redraw|edit|revise)\b.{0,28}\b(?:image|visual|slide|candidate)\b/i.test(text);
  const anchoredRedraw = Array.isArray(referenceImages)
    && referenceImages.length > 0
    && /(?:重做|重新做|照着|参考|沿用|按这个风格)/u.test(text)
    && pageLabels(text).length > 0;
  if (!explicitPipeline && !directChinese && !directEnglish && !anchoredRedraw) return null;
  return {
    kind: "image",
    mode_hint: modeHint || "image_generation",
    title: taskTitle(text, modeHint),
  };
}
