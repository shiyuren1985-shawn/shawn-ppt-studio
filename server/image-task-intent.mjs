const PAGE_REFERENCE_RE = /\bP\s*0*(\d{1,3})\b/gi;

function normalizedMessage(value) {
  return typeof value === "string" ? value.replace(/[^\S\r\n]+/g, " ").trim() : "";
}

function requestedVisualText(message) {
  let negatedVisual = false;
  const clauses = message.split(/[。！？!?；;，,、.\r\n]+|(?:但是|而是|改为|然后)|\b(?:but|instead)\b/iu);
  const retained = clauses.filter((clause) => {
    const negative = /(?:不要|不需要|无需|不必|先别|暂时别|禁止|不是|不用|别|不)\s*(?:(?:再|实际|立即|直接|给我|帮我|执行|进行|运行|用|使用|调用|走|跑|做)\s*)*(?:生成|制作|重做|重新生成|作图|生图|修图|改图|扩页|fast\s*[48]|[48]\s*[×x]\s*[13]|selected[_ -]?style|选定风格扩页|整稿扩页)/iu.test(clause)
      || /\b(?:do\s+not|don['’]t|never|no|without)\s+(?:(?:use|run|any)\s+)*(?:generate|create|redraw|edit|revise|fast\s*[48]|[48]\s*[×x]\s*[13])/iu.test(clause);
    if (negative) {
      negatedVisual = true;
      return false;
    }
    // These are explanations of a pipeline, not requests to dispatch one.
    return !/(?:如何|怎么|怎样).{0,12}(?:生成|制作|作图|生图|修图)|(?:什么是|解释|介绍|讲讲).{0,12}(?:fast\s*[48]|[48]\s*[×x]\s*[13])|(?:fast\s*[48]|[48]\s*[×x]\s*[13]).{0,8}(?:是什么|什么意思)|\bhow\s+(?:do|can|does|to)\b/iu.test(clause);
  });
  return { text: retained.join("，").trim(), negatedVisual };
}

function pageLabels(message) {
  const labels = [];
  for (const match of message.matchAll(PAGE_REFERENCE_RE)) {
    const label = `P${String(Number(match[1])).padStart(2, "0")}`;
    if (!labels.includes(label)) labels.push(label);
  }
  return labels;
}

function requestedPageCount(message) {
  const match = message.match(/(?:这|那|共|做|重做|再做|生成|制作)?\s*(\d{1,3})\s*页/u);
  const count = Number(match?.[1]);
  return Number.isInteger(count) && count > 0 ? count : null;
}

function deckWideScope(message) {
  return /(?:整个|整份|整套|全套|全稿|全部|所有).{0,12}(?:大纲|PPT|幻灯片|页面|页)/iu.test(message)
    || /(?:大纲|PPT|幻灯片).{0,12}(?:每一页|每页|逐页)/iu.test(message)
    || /(?:selected[_ -]?style|选定风格扩页|整稿扩页)/iu.test(message);
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
  const pageCount = requestedPageCount(message);
  if (pageCount) return `${pageCount} 页作图`;
  if (deckWideScope(message)) return "整套作图";
  return "图片生成";
}

export function classifyImageTaskRequest({
  message,
  retouchContext = false,
  referenceImages = [],
} = {}) {
  const { text, negatedVisual } = requestedVisualText(normalizedMessage(message));
  if (!text) return null;
  let modeHint = null;
  if (retouchContext && !negatedVisual) modeHint = "retouch";
  else if (/(?:fast\s*8|8\s*[×xX]\s*1)/i.test(text)) modeHint = "fast_8x1";
  else if (/(?:fast\s*4|4\s*[×xX]\s*3)/i.test(text)) modeHint = "fast_4x3";

  const explicitPipeline = Boolean(modeHint) || /(?:selected[_ -]?style|选定风格扩页|整稿扩页)/i.test(text);
  const directChinese = /(?:请|帮我|给我|开始|执行|走|进行|我要|需要|重新|继续|按|用|把).{0,24}(?:作图|生图|修图|改图|扩页)/u.test(text)
    || /(?:作图|生图|修图|改图|扩页).{0,8}(?:一下|一轮|一版|候选|管线|流程)/u.test(text)
    || /(?:请|帮我|给我|我要|我想|需要|重新|继续).{0,16}(?:做|画|出).{0,10}(?:\d+\s*张)?(?:图片|候选图|页面图)/u.test(text)
    || /(?:生成|制作|重做|重新生成|替换).{0,18}(?:图片|图像|候选图|页面图|PPT\s*页)/iu.test(text)
    || /把.{0,10}(?:图片|图像|候选图|页面图|PPT\s*页).{0,10}(?:生成|制作|重做|重新生成|替换|修改|调整|优化)/iu.test(text)
    || /(?:修改|调整|优化).{0,8}(?:这张|该张|当前|选中)?(?:图片|图像|候选图|页面图)/iu.test(text);
  const directEnglish = /\b(?:generate|create|redraw|edit|revise)\b.{0,28}\b(?:image|visual|slide|candidate)\b/i.test(text);
  const hasVisualAnchor = (Array.isArray(referenceImages) && referenceImages.length > 0)
    || /(?:风格定位图|视觉参考图|参考图)/u.test(text);
  const anchoredRedraw = hasVisualAnchor
    && /(?:重做|重新做|再做(?:一次|一遍)?|照着|参考|沿用|按这个风格)/u.test(text)
    && (pageLabels(text).length > 0 || requestedPageCount(text));
  const deckWideRedraw = deckWideScope(text)
    && /(?:做一遍|重新做|重做|生成|制作|出图|作图|生图)/u.test(text)
    && (
      (Array.isArray(referenceImages) && referenceImages.length > 0)
      || /(?:风格定位图|参考图|图片|配图|视觉|页面图|候选图)/u.test(text)
    );
  if (!explicitPipeline && !directChinese && !directEnglish && !anchoredRedraw && !deckWideRedraw) return null;
  return {
    kind: "image",
    mode_hint: modeHint || "image_generation",
    title: taskTitle(text, modeHint),
  };
}
