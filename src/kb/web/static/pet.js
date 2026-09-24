// 悬浮桌宠：可点、可拖、可甩，在视口里反弹。
//
// **本项目第一个独立 .js 文件**（其余 JS 都在 base.html 的内联 <script> 里）。
// 单开是**有意**的：它自成一个东西——自己的物理循环、持久化状态、气泡。
//
// ⚠️ **颜色一律走 style.css 里的变量**，这里不碰颜色。style.css 有「变量块
// 之外不许出现十六进制」的防回潮测试守着，桌宠的样式同样归它管。
(function () {
  // **两个元素都得在才继续。** 只判 `pet` 的话，将来哪个页面写了 `#pet`
  // 却漏了 `#pet-bubble`，下面 `bubble.textContent` 那一串就在加载期当场抛错、
  // 整个文件停住——桌宠连拖都拖不动。而页面上只表现为「它不动了」，
  // 看不出是缺了个 div。
  var pet = document.getElementById('pet');
  var bubble = document.getElementById('pet-bubble');
  if (!pet || !bubble) return;

  var BUBBLE_GAP = 8;                  // 气泡离桌宠多少
  var POS_KEY = 'kn.pet.pos';          // 位置存在 localStorage 的哪个键
  var EDGE = 24;                       // 初始位置离右下角多少
  var FLING_MIN = 2500;                // px/s，松手速度低于它就不飞
  var FLING_IDLE_MS = 100;             // 松手前静了这么久就不算「甩」
  var FRICTION = 0.985;                // 每帧衰减
  var BOUNCE = 0.62;                   // 撞边保留多少速度
  var STOP_AT = 0.02;                  // px/ms，低于它就停
  var DRAG_SLOP = 5;                   // 位移小于它算「点击」
  var PUSH_GAP = 14;                   // 被手机弹开后，最终离它左边缘留多少
  var PUSH_OVERSHOOT = 1.18;           // 被弹开时，比「刚好让开」多冲出去多少
  var PUSH_MIN_SPEED = 2.0;            // px/ms，初速下限——低于它就成了「挪开」不是「弹开」
  var HIDE_AFTER = 4000;               // 气泡多久自己收（毫秒）

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

  // 拖动收尾：摘掉抓手光标、清状态、速度归零、记下位置。
  // `pointerup`(没挪动/没飞)、`pointercancel`、「没按着键的 pointermove」
  // 三条路共用一份。
  function endDrag() {
    pet.classList.remove('dragging');
    drag = null;
    vx = vy = 0;
    savePos();
  }

  // **尺寸从元素上读，不写死。** 写死 46 的话，style.css 里那个
  // `width/height: 46px` 和这里就成了同一个数的两处真相——改一处漏一处，
  // 而且漏了不会有任何东西报错。`offsetWidth` 是布局值，**不受果冻那个
  // `transform: scale()` 影响**，动画中途取也是 46。
  function maxX() { return window.innerWidth - pet.offsetWidth; }
  function maxY() { return window.innerHeight - pet.offsetHeight; }
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
    pet.classList.add('dragging');
    vx = vy = 0;
    drag = {
      sx: e.clientX, sy: e.clientY, ox: pet.offsetLeft, oy: pet.offsetTop,
      px: e.clientX, py: e.clientY, last: performance.now(), moved: false,
    };
    // **捕获放在状态摆好之后**：它若抛（`NotFoundError`），前面那些照旧生效，
    // 这一次拖动最坏只是「没捕获」；放在前面的话它一抛后面整段都不执行，
    // 这一次拖动会静默降级成「只能点」。
    pet.setPointerCapture(e.pointerId);
    e.preventDefault();
  });

  pet.addEventListener('pointermove', function (e) {
    if (!drag) return;
    // **没按着键就不是拖动。** 兜住「捕获没拿到、松手又发生在桌宠外面」那条路
    // ——那时 `pointerup` 压根收不到，`drag` 会一直留着，之后光标划过也会把
    // 桌宠拖走。症状跟 `pointercancel` 那段注释说的是同一个，只是入口不同。
    if (e.buttons === 0) { endDrag(); return; }
    var dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
    // **判合位移，不是单轴。** 按单轴判的话，斜着拖 4px/4px（合位移 5.7px）
    // 会被算成「没挪动」= 一次点击——明明拖了。
    if (Math.hypot(dx, dy) > DRAG_SLOP) drag.moved = true;

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
    // **松手前静了多久。** `vx/vy` 只在 `pointermove` 里更新——指针一停住，
    // 浏览器就不再派发事件，速度会**冻结在停住前那个值**。不判这一下，
    // 「快速拖过去 → 停住对准 → 松手」会拿几百毫秒前那个速度飞出去，
    // 而真实的松手速度其实是 0（看上去就是「我没甩它，它自己跑了」）。
    var idle = drag ? performance.now() - drag.last : 0;
    drag = null;

    if (!moved) { onPetClick(); savePos(); return; }

    var pxPerSec = Math.hypot(vx, vy) * 1000;
    if (idle > FLING_IDLE_MS || pxPerSec < FLING_MIN) { vx = vy = 0; } else { fling(); }
    savePos();
  });

  // **被打断也要收尾。** 指针被系统接管时（触摸端的系统手势、捕获丢失、
  // 元素被移除）**只有 `pointercancel`，不会有 `pointerup`**。不收尾的话
  // `drag` 一直非空——之后**没按着键**的 `pointermove` 也会让桌宠跟着光标跑，
  // `dragging` 那个抓手光标也一直留在身上，得再点一下才复位。
  //
  // 被打断就**停在原地**、不弹射：这一次拖动本来就没正常结束。
  pet.addEventListener('pointercancel', endDrag);

  // ---- 手机滑出来时把自己**弹射**出去 ----
  //
  // 用户原话：「手机弹出时桌宠会被弹开，也就是类似有碰撞体积，他们在同一层级」，
  // 看过真页面之后又明确了：要**弹射**，不是平滑地滑开。
  // 所以**不是盖住、也不是穿过**——而是被撞飞出去，飞一段、慢慢停。
  //
  // **收回去的时候不动它**：留在被弹到的地方。追着跑回去的话，
  // 一开一关它就在那儿来回抽。
  //
  // 手机那边只报「我开了没、我左边缘在哪」（`phone.js` 里的 `kb:phone`），
  // 剩下全归这里算——两个文件之间只有这一个接口，谁也不 import 谁。
  window.addEventListener('kb:phone', function (e) {
    if (!e.detail.open) return;                       // 收回去不追
    // **正拖着就不推。** 一只手拖着桌宠、另一只手点把手是能做到的——那时
    // 会让 `drag.ox/oy` 过期，下一次 `pointermove` 会拿旧起点算，桌宠当场跳一下。
    // 单指路径碰不到这条，纯粹是补个双指的洞。
    if (drag) return;
    var want = e.detail.left - PUSH_GAP - pet.offsetWidth;
    if (pet.offsetLeft <= want) return;               // 没挨上，别动它

    // **弹射出去，不是滑过去。** 用户原话「手机弹出时桌宠会被弹开」，
    // 看过真页面之后又明确了：要「弹射」。
    //
    // 桌宠本来就有一套物理（速度、摩擦、撞边反弹）——用它自己那套，
    // 比挂个 CSS 过渡像回事。
    //
    // 初速取**两者之大**：
    //
    // ① 「够让开」的下界——`fling()` 每帧走 `v * 16` 再 `v *= FRICTION`，
    //    等比数列求和下来总位移 ≈ `v * 16 / (1 - FRICTION)`，反解出
    //    「要走 d 那么远该给多少初速」。用常量算、不写死数字，
    //    以后改摩擦或帧步长这里自动跟着变。
    //    乘 `PUSH_OVERSHOOT` 是点富余：正好走满会贴着手机的边停下。
    //
    // ② **`PUSH_MIN_SPEED` 那个下限——第一版就是栽在这儿的。**
    //    只看①的话，这个场景算出来只有 **~340 px/s**（手甩一下是 2500），
    //    看着是「慢悠悠飘开」不是「被弹开」。原因是 `FRICTION` 取 0.985、
    //    每帧只掉 1.5%，也就是**滑得极远**；反过来讲，想让它**别滑太远**，
    //    ①就必然把初速压得很低——**「走得准」和「走得快」在这套摩擦下
    //    是同一根轴上的两头**。用户看到的就是这个后果。
    //
    //    所以定个下限：该快就快，宁可飞过头、撞左墙弹回来（那也是它自己的
    //    物理，看着更像回事），也不要慢。
    var travel = (pet.offsetLeft - want) * PUSH_OVERSHOOT;
    vx = -Math.max(travel * (1 - FRICTION) / 16, PUSH_MIN_SPEED);
    vy = 0;

    if (raf) { cancelAnimationFrame(raf); raf = null; }   // 别和上一次的弹射叠着跑
    fling();                                              // 剩下的交给物理
  });

  window.addEventListener('resize', function () {
    // ⚠️ **整套坐标都建立在「`position: fixed` 元素的 `offsetLeft/offsetTop`
    // 是相对视口的」之上**（这里、拖动起点、弹射基准、存档都靠它）。
    // 这是 offsetParent 为 null 时的行为——`html` / `body` / `.shell` 只要
    // 哪一个沾上 `transform` / `filter` / `will-change` / `contain`，
    // offsetParent 就不再是 null，坐标会整体偏掉，而**页面上不会报任何错**。
    // 加这类样式之前先想想这里。
    moveTo(clamp(pet.offsetLeft, 0, maxX()), clamp(pet.offsetTop, 0, maxY()));
  });
})();
