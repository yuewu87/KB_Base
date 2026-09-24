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

  // **初始位置：右下角，离两边各 24px。**
  //
  // ⚠️ **`position: fixed` 的元素不给 left/top 会停在文档流里那个位置**——
  // 也就是它写成 HTML 的那个地方（几个 `.overlay` 后面），页面上会看着像
  // 飘在半空。所以这一句不能省。位置持久化在 Task 5 接上，那时它换成
  // 从 `localStorage` 读。
  pet.style.left = (window.innerWidth - SIZE - 24) + 'px';
  pet.style.top = (window.innerHeight - SIZE - 24) + 'px';

  // 拖动那半在 Task 5 接上；这一版先只做点击。
  pet.addEventListener('click', onPetClick);

  window.addEventListener('resize', function () {
    if (!bubble.hidden) placeBubble();
  });
})();
