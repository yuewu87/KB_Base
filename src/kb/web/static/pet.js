// 悬浮桌宠：可点、可拖、可甩，在视口里反弹。
//
// **本项目第一个独立 .js 文件**（其余 JS 都在 base.html 的内联 <script> 里）。
// 单开是**有意**的：它自成一个东西——自己的物理循环、持久化状态、气泡。
//
// ⚠️ **颜色一律走 style.css 里的变量**，这里不碰颜色。style.css 有「变量块
// 之外不许出现十六进制」的防回潮测试守着，桌宠的样式同样归它管。
(function () {
  var pet = document.getElementById('pet');
  if (!pet) return;                    // 页面里没有就安静退出

  var BUBBLE_GAP = 8;                  // 气泡离桌宠多少
  var SIZE = 46;                       // 与 style.css 里的 .pet 尺寸一致
  var POS_KEY = 'kn.pet.pos';          // 位置存在 localStorage 的哪个键
  var EDGE = 24;                       // 初始位置离右下角多少
  var FLING_MIN = 2500;                // px/s，松手速度低于它就不飞
  var FRICTION = 0.985;                // 每帧衰减
  var BOUNCE = 0.62;                   // 撞边保留多少速度
  var STOP_AT = 0.02;                  // px/ms，低于它就停
  var DRAG_SLOP = 5;                   // 位移小于它算「点击」
  var HIDE_AFTER = 4000;               // 气泡多久自己收（毫秒）

  var bubble = document.getElementById('pet-bubble');
  var hideTimer = null;

  function showBubble(text, bad) {
    bubble.textContent = text;
    bubble.classList.toggle('bad', !!bad);
    bubble.hidden = false;
    placeBubble();
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hideBubble, HIDE_AFTER);
  }

  function hideBubble() {
    bubble.hidden = true;
    clearTimeout(hideTimer);
  }

  // **鼠标停在气泡上就不收**——正在看的时候被收走最烦人。
  bubble.addEventListener('mouseenter', function () { clearTimeout(hideTimer); });
  bubble.addEventListener('mouseleave', function () { restartHideTimer(); });

  function restartHideTimer() {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hideBubble, HIDE_AFTER);
  }

  function placeBubble() {
    var r = pet.getBoundingClientRect();
    var top = r.top - bubble.offsetHeight - BUBBLE_GAP;
    // **夹回可视区**：桌宠被甩到最上面时，气泡不能跑到屏幕外面去
    if (top < BUBBLE_GAP) top = r.bottom + BUBBLE_GAP;
    var left = Math.min(
      Math.max(r.left + r.width / 2 - bubble.offsetWidth / 2, BUBBLE_GAP),
      window.innerWidth - bubble.offsetWidth - BUBBLE_GAP
    );
    bubble.style.top = top + 'px';
    bubble.style.left = left + 'px';
  }

  function wobble() {
    pet.classList.remove('jelly');
    void pet.offsetWidth;              // 强制重排，动画才会重放
    pet.classList.add('jelly');
  }

  function describe(data) {
    if (!data.initialized) return '还没有知识库';
    return '库里 ' + data.counts.notes + ' 篇笔记 · 待整理 ' +
           data.counts.drafts + ' 条';
  }

  function onPetClick() {
    wobble();
    fetch('/setup/state')
      .then(function (r) { return r.json(); })
      .then(function (d) { showBubble(describe(d), false); })
      // **拉不到就如实说**，不装作 0 条——跟 /setup/remove 那条失败路径一个路子
      .catch(function (e) { showBubble('数不出来（' + e + '）', true); });
  }

  function savePos() {
    try {
      localStorage.setItem(
        POS_KEY, JSON.stringify({ x: pet.offsetLeft, y: pet.offsetTop })
      );
    } catch (e) {
      // **隐私模式下 localStorage 会抛。** 位置记不住是小事，别让它把整个
      // 桌宠搞死——那不就成了「点了一下什么都没发生」。
    }
  }

  function loadPos() {
    try {
      var raw = localStorage.getItem(POS_KEY);
      if (!raw) return null;
      var p = JSON.parse(raw);
      return (typeof p.x === 'number' && typeof p.y === 'number') ? p : null;
    } catch (e) {
      return null;
    }
  }

  function startPos() {
    var saved = loadPos();
    if (saved) return { x: clamp(saved.x, 0, maxX()), y: clamp(saved.y, 0, maxY()) };
    return { x: maxX() - EDGE, y: maxY() - EDGE };   // 初始右下角
  }

  // **初始位置：右下角，离两边各 24px**；有存过的就沿用存过的。
  //
  // ⚠️ **`position: fixed` 的元素不给 left/top 会停在文档流里那个位置**——
  // 也就是它写成 HTML 的那个地方（几个 `.overlay` 后面），页面上会看着像
  // 飘在半空。所以这一句不能省。
  var start = startPos();
  moveTo(start.x, start.y);

  // ---- 拖动 / 弹射 / 反弹 ----
  //
  // **点击和拖动靠位移分**：`pointerdown` 到 `pointerup` 之间挪了不到
  // `DRAG_SLOP` 像素就算点击。不分的话，拖完松手会顺带弹一次气泡——
  // 那正是「拖开它别挡着我看东西」的时候最不想要的。
  var drag = null;                     // {sx, sy, ox, oy, px, py, last, moved}
  var vx = 0, vy = 0;                  // px/ms
  var raf = null;

  function maxX() { return window.innerWidth - SIZE; }
  function maxY() { return window.innerHeight - SIZE; }
  function clamp(v, lo, hi) { return Math.min(Math.max(v, lo), hi); }

  function moveTo(x, y) {
    pet.style.left = x + 'px';
    pet.style.top = y + 'px';
    if (!bubble.hidden) placeBubble();
  }

  function fling() {
    if (raf) return;
    raf = requestAnimationFrame(function step() {
      raf = null;
      var x = pet.offsetLeft + vx * 16;
      var y = pet.offsetTop + vy * 16;

      // 撞视口边就反弹，保留 BOUNCE 那部分速度
      if (x <= 0) { x = 0; vx = -vx * BOUNCE; }
      if (x >= maxX()) { x = maxX(); vx = -vx * BOUNCE; }
      if (y <= 0) { y = 0; vy = -vy * BOUNCE; }
      if (y >= maxY()) { y = maxY(); vy = -vy * BOUNCE; }

      vx *= FRICTION; vy *= FRICTION;
      moveTo(x, y);

      if (Math.abs(vx) < STOP_AT && Math.abs(vy) < STOP_AT) {
        vx = vy = 0;
        // **停在哪儿就记哪儿。** 少了这一句，记下的永远是「松手那一刻」的
        // 位置——飞出老远才停下的，刷新一下会跳回半路。
        savePos();
        return;
      }
      raf = requestAnimationFrame(step);
    });
  }

  pet.addEventListener('pointerdown', function (e) {
    if (raf) { cancelAnimationFrame(raf); raf = null; }
    hideBubble();
    pet.setPointerCapture(e.pointerId);
    pet.classList.add('dragging');
    vx = vy = 0;
    drag = {
      sx: e.clientX, sy: e.clientY, ox: pet.offsetLeft, oy: pet.offsetTop,
      px: e.clientX, py: e.clientY, last: performance.now(), moved: false,
    };
    e.preventDefault();
  });

  pet.addEventListener('pointermove', function (e) {
    if (!drag) return;
    var dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
    if (Math.abs(dx) > DRAG_SLOP || Math.abs(dy) > DRAG_SLOP) drag.moved = true;

    moveTo(clamp(drag.ox + dx, 0, maxX()), clamp(drag.oy + dy, 0, maxY()));

    // 速度按「上一次 move 到这一次」算，不是从按下的那点算起
    var now = performance.now();
    var dt = Math.max(now - drag.last, 1);
    vx = (e.clientX - drag.px) / dt;
    vy = (e.clientY - drag.py) / dt;
    drag.px = e.clientX; drag.py = e.clientY; drag.last = now;
  });

  pet.addEventListener('pointerup', function () {
    pet.classList.remove('dragging');
    var moved = drag && drag.moved;
    drag = null;

    if (!moved) { onPetClick(); savePos(); return; }

    var pxPerSec = Math.hypot(vx, vy) * 1000;
    if (pxPerSec >= FLING_MIN) { fling(); } else { vx = vy = 0; }
    savePos();
  });

  window.addEventListener('resize', function () {
    // ⚠️ 取 `offsetTop`，**不是 `offsetY`**：`offsetY` 在 `position: fixed`
    // 的元素上不是相对视口的距离，拿它算会跑到屏幕外面去。
    moveTo(clamp(pet.offsetLeft, 0, maxX()), clamp(pet.offsetTop, 0, maxY()));
  });
})();
