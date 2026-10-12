// 카드형 릴스 전용: 제목(h1·h2)이 타자 치듯 한 글자씩 나오고 커서가 깜빡인다.
// cardnews-video 키트(git 밖)는 고치지 않고, card_reel.py가 릴스용 cards.html 복사본에만 이 스크립트를 넣는다.
// 키트가 window.__cardnewsStage에 무대를 넣는 순간 seek/seekCard를 감싸, 키트가 프레임을 맞춘 뒤 제목 글자 수만 줄인다.
// 시각 → 글자 수가 정해져 있어 같은 입력이면 같은 그림(키트와 같은 원칙).
(() => {
  const CPS = 12;            // 초당 글자
  const DELAY = 0.15;        // 장이 들어오고 나서 치기 시작할 때까지(초)
  const BLINK = 0.5;         // 커서 깜빡임 반주기(초)
  const HOLD_CURSOR = 0.6;   // 다 친 뒤 커서를 남겨 두는 시간(초)
  const originals = new Map();

  const style = document.createElement('style');
  style.textContent = '.tw-cursor{display:inline-block;width:0.08em;height:0.9em;margin-left:0.06em;vertical-align:-0.05em;background:currentColor;border-radius:2px}';
  document.head.append(style);

  // 글자 단위 잎(텍스트 노드·줄바꿈)을 문서 순서대로
  function leaves(root) {
    const out = [];
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    while (walk.nextNode()) {
      const node = walk.currentNode;
      if (node.nodeType === 3 || node.tagName === 'BR') out.push(node);
    }
    return out;
  }

  function type(el, elapsed) {
    if (!originals.has(el)) originals.set(el, { html: el.innerHTML, height: el.offsetHeight });
    const saved = originals.get(el);
    el.innerHTML = saved.html;
    el.style.minHeight = `${saved.height}px`; // 줄이 늘어나며 아래 요소가 흔들리지 않게 자리를 잡아 둔다
    const total = leaves(el).reduce((n, node) => n + (node.nodeType === 3 ? [...node.textContent.replace(/\s/g, '')].length : 0), 0);
    let left = Math.floor(Math.max(0, elapsed - DELAY) * CPS);
    const typing = left < total;
    let last = null;
    for (const node of leaves(el)) {
      if (left <= 0 && last) {
        if (node.nodeType === 3) node.textContent = '';
        else node.remove();
        continue;
      }
      if (node.nodeType === 3) {
        const chars = [...node.textContent];
        let keep = 0;
        for (const ch of chars) {
          if (left <= 0) break;
          keep += 1;
          if (!/\s/.test(ch)) left -= 1;
        }
        node.textContent = chars.slice(0, keep).join('');
        if (keep) last = node;
      } else {
        last = node;
      }
    }
    // 아직 글자가 없는 강조 상자(표지의 흰 띠 등)는 숨긴다
    el.querySelectorAll('mark, em, b, span').forEach((box) => { box.style.visibility = box.textContent ? '' : 'hidden'; });
    const showCursor = typing || elapsed - DELAY - total / CPS < HOLD_CURSOR;
    if (showCursor && Math.floor(elapsed / BLINK) % 2 === 0 || typing) {
      const cursor = document.createElement('i');
      cursor.className = 'tw-cursor';
      if (last && last.nodeType === 3) last.after(cursor);
      else el.append(cursor);
    }
  }

  function typeCard(card, elapsed) {
    card.querySelectorAll('h1, h2').forEach((el) => type(el, elapsed));
  }

  function wrap(stage) {
    const { seek, seekCard } = stage;
    stage.seek = (time, timeline) => {
      const result = seek(time, timeline);
      [...document.querySelectorAll('section.card')].forEach((card, index) => {
        const schedule = timeline.cards[index];
        if (schedule && card.style.visibility !== 'hidden') typeCard(card, time - schedule.start);
      });
      return result;
    };
    stage.seekCard = (index, time, schedule) => {
      const result = seekCard(index, time, schedule);
      const card = document.querySelectorAll('section.card')[index];
      if (card) typeCard(card, time - (schedule.start || 0));
      return result;
    };
    return stage;
  }

  let current;
  Object.defineProperty(window, '__cardnewsStage', {
    configurable: true,
    get: () => current,
    set: (value) => { current = value ? wrap(value) : value; },
  });
})();
