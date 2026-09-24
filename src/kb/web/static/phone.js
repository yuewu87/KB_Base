// 右侧栏的手机：抽屉开合、主页 ↔ 应用、顶部时间。
//
// **本项目第二个独立 .js 文件**（第一个是 `pet.js`）。同样是**有意**单开的：
// 它自成一个东西——自己的开合状态、自己的面板切换、还要往外广播位置。
//
// ⚠️ **颜色一律走 style.css 里的变量**，这里不碰颜色。style.css 有「变量块
// 之外不许出现十六进制」的防回潮测试守着，手机的样式同样归它管。
(function () {
  var phone = document.getElementById('phone');
  if (!phone) return;                    // 页面里没有就安静退出

  var handle = document.getElementById('phone-handle');
  var homeBtn = document.getElementById('phone-home-btn');
  var timeBox = document.getElementById('phone-time');
  var homeScreen = document.getElementById('phone-home');
  var views = phone.querySelectorAll('.phone-view');

  // ---- 顶部时间 ----
  //
  // 用**浏览器自己的钟**：手机显示的就该是「现在几点」，而不是服务端渲染那一刻。
  // 每 30 秒对一次，跨分钟时不会一直停在旧时间上。
  function tick() {
    if (!timeBox) return;
    var d = new Date();
    timeBox.textContent =
      (d.getHours() < 10 ? '0' : '') + d.getHours() + ':' +
      (d.getMinutes() < 10 ? '0' : '') + d.getMinutes();
  }
  tick();
  setInterval(tick, 30000);

  // ---- 主页 ↔ 应用 ----
  function showHome() {
    homeScreen.hidden = false;
    views.forEach(function (v) { v.hidden = true; });
  }

  function showApp(id) {
    homeScreen.hidden = true;
    views.forEach(function (v) { v.hidden = v.dataset.app !== id; });
    phone.querySelector('.phone-screen').scrollTop = 0;
  }

  phone.querySelectorAll('.phone-app[data-app]').forEach(function (btn) {
    btn.addEventListener('click', function () { showApp(btn.dataset.app); });
  });
  phone.querySelectorAll('.phone-back').forEach(function (btn) {
    btn.addEventListener('click', showHome);
  });
  if (homeBtn) homeBtn.addEventListener('click', showHome);
  showHome();

  // ---- 抽屉开合 ----
  //
  // **手机左边缘要广播出去**：桌宠靠它算自己该被顶到哪儿（`pet.js` 里
  // `kb:phone` 那段）。**用事件而不是互相 import**——两个独立的文件之间
  // 只有这一个接口，谁也不用知道对方的内部。
  //
  // ⚠️ 报的是**展开后的**位置（`innerWidth - offsetWidth`），不是当前动画到哪，
  // 好让桌宠和手机同时开始动；不这样的话手机会先压上去、桌宠再弹开，看着像穿模。
  //
  // `offsetWidth` 是**布局宽**，不受 `transform` 影响——抽屉滑到一半时取，
  // 拿到的也是它最终那个宽度，不是当下露出来的那一截。
  function setOpen(open) {
    phone.classList.toggle('open', open);
    if (handle) handle.setAttribute('aria-expanded', open ? 'true' : 'false');
    window.dispatchEvent(new CustomEvent('kb:phone', {
      detail: { open: open, left: window.innerWidth - phone.offsetWidth },
    }));
  }

  if (handle) {
    handle.addEventListener('click', function () {
      setOpen(!phone.classList.contains('open'));
    });
  }
})();
