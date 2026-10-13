/* SignBrush for Rust — site behaviour: language, cursor, painting hero, reveals. */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
  };

  /* ---------------------------------------------------------------- i18n */
  const EN = {
    "nav.gallery": "In game", "nav.modes": "Modes", "nav.how": "How it works", "nav.feedback": "Feedback", "nav.faq": "FAQ",
    "hero.beta": "Beta · your feedback needed",
    "hero.title": "Any picture&nbsp;— <span class=\"ink\">on a&nbsp;sign</span> in&nbsp;Rust",
    "hero.lead": "SignBrush moves the mouse in the sign editor for you and paints your art: large translucent strokes first, then an exact pixel touch-up. Usually 2–10 minutes instead of an hour by hand.",
    "hero.download": "Download for Windows", "hero.see": "See the results", "hero.hud": "Painting",
    "facts.modes": "painting modes", "facts.minutes": "minutes per picture", "facts.stop": "stop at any time",
    "notice.title": "The program is not fully optimized yet",
    "notice.text": "Speed, calibration and result checking still need manual tuning, and the game behaves differently on different PCs. To get automation to “press and forget”, we need your feedback: your FPS, resolution, sign type and what went wrong.",
    "notice.cta": "How to help",
    "gallery.eyebrow": "Result in game", "gallery.title": "Painted by SignBrush",
    "gallery.text": "A real screenshot from Rust: a sign on a wall. Click to see the whole frame.",
    "gallery.cap1": "Large wooden sign · pixels",
    "ba.eyebrow": "Before and after", "ba.title": "Source vs. sign",
    "ba.text": "Drag the divider. On the right is what SignBrush paints in game in hybrid mode: strokes cover the smooth areas, details are touched up exactly.",
    "ba.before": "Source", "ba.after": "Sign",
    "modes.eyebrow": "Three algorithms", "modes.title": "Choose between speed and accuracy", "modes.default": "Default",
    "modes.h1": "Hybrid", "modes.t1": "~1000 translucent strokes quickly cover the canvas, then a square brush repaints only the cells whose colour is still off.",
    "modes.h2": "Pixels", "modes.t2": "Every grid cell gets exactly its own colour: an exact copy with a palette fitted to the picture. The neatest and the slowest mode.",
    "modes.h3": "Strokes only", "modes.t3": "The whole picture made of translucent circles — a soft, painterly look without fine detail, one click per stroke.",
    "modes.q": "accuracy", "modes.s": "speed",
    "how.eyebrow": "How it works", "how.title": "Four steps to a finished sign",
    "how.s1": "Drop a picture", "how.t1": "PNG, JPG, GIF, WebP or straight from the clipboard. You see right away how it fits the sign.",
    "how.s2": "Calibrate once", "how.t2": "Open the sign editor, press F9 and mark the canvas, the HEX field and the brush on a frozen screenshot. About a minute per screen resolution.",
    "how.s3": "Measure brush and speed", "how.t3": "The program paints a couple of test dots, checks them on a screenshot and tunes the pauses to your FPS — no gaps, no “tails”.",
    "how.s4": "Press “Paint”", "how.t4": "Switch to the game during the countdown and leave the mouse alone. F7 pauses, F8 stops. Afterwards a screenshot is compared with the plan and misses are repainted.",
    "safe.eyebrow": "Fair and safe", "safe.title": "Just the screen and the mouse",
    "safe.h1": "No injection", "safe.t1": "Only screen capture and input emulation. No game memory access, hooks, drivers or anti-cheat bypass.",
    "safe.h2": "F8 always works", "safe.t2": "Emergency stop within milliseconds, even mid-stroke: the mouse button is released at once.",
    "safe.h3": "Pauses by itself", "safe.t3": "Moved the mouse or left Rust — painting freezes. Progress is saved.",
    "safe.h4": "No network", "safe.t4": "No accounts, no telemetry, no player tracking. Open source under the MIT license.",
    "fb.eyebrow": "Beta", "fb.title": "Help us finish the automation",
    "fb.text": "SignBrush is not fully optimized yet: on some PCs it paints perfectly, on others the game drops strokes or the speed needs manual tuning. Every report helps make the setup automatic.",
    "fb.l1": "In-game FPS with the editor open, and your screen resolution", "fb.l2": "Sign type, algorithm and detail",
    "fb.l3": "What went wrong: gaps, “tails”, misses, chat opening", "fb.l4": "The program log (the “Copy” button) and a screenshot of the result",
    "fb.cta": "Write a report on GitHub", "fb.all": "All discussions",
    "faq.eyebrow": "Questions", "faq.title": "FAQ",
    "faq.q1": "Will I get banned for this?", "faq.a1": "There are no guarantees. SignBrush does not touch game memory and only emulates the mouse, but a particular server's rules may forbid automation. Use it at your own risk and check the server rules.",
    "faq.q2": "Why does it take someone 5 minutes and me 15?", "faq.a2": "The game reads the mouse once per frame, so the time depends almost directly on your FPS with the sign editor open. At 144 FPS painting is about twice as fast as at 60. Run the “Speed test” — it picks the pause for you.",
    "faq.q3": "Which signs are supported?", "faq.a3": "Wooden signs of all sizes, picture frames, banners and neon signs. Pick the type by hand or take the proportions straight from the canvas on screen.",
    "faq.q4": "Can I keep the sign's background?", "faq.a4": "Yes. Transparent areas and margins can be left unpainted — whatever is on the sign stays, and painting gets faster.",
    "faq.q5": "Does it need the internet?", "faq.a5": "No. The program never touches the network: everything runs on your PC.",
    "final.title": "Ready to hang your art?", "final.text": "Free and open source, for Windows 10 and 11.",
    "footer.legal": "An independent fan project, not affiliated with Facepunch Studios. “Rust” is a trademark of Facepunch Studios Ltd.",
    "footer.license": "Code — MIT. Fonts Onest and JetBrains Mono — SIL OFL 1.1.",
  };
  const RU = {};
  $$("[data-i18n]").forEach((el) => { RU[el.dataset.i18n] = el.textContent; });
  $$("[data-i18n-html]").forEach((el) => { RU[el.dataset.i18nHtml] = el.innerHTML; });

  function setLang(lang) {
    const dict = lang === "en" ? EN : RU;
    $$("[data-i18n]").forEach((el) => { const t = dict[el.dataset.i18n]; if (t) el.textContent = t; });
    $$("[data-i18n-html]").forEach((el) => { const t = dict[el.dataset.i18nHtml]; if (t) el.innerHTML = t; });
    document.documentElement.lang = lang;
    $$(".lang button").forEach((b) => b.classList.toggle("on", b.dataset.lang === lang));
    const shot = $("#uiShot");
    if (shot) shot.src = lang === "en" ? "site/img/ui-en.webp" : "site/img/ui-ru.webp";
    store.set("sb-lang", lang);
  }
  $$(".lang button").forEach((b) => b.addEventListener("click", () => setLang(b.dataset.lang)));
  const nav = (navigator.language || "en").toLowerCase();
  setLang(store.get("sb-lang") || (/^(ru|uk|be|kk)/.test(nav) ? "ru" : "en"));

  /* ------------------------------------------------- scroll progress, nav */
  const bar = $(".progress span");
  const header = $(".nav");
  const sections = $$("main section[id]");
  const links = $$(".links a");
  function onScroll() {
    const h = document.documentElement;
    const p = h.scrollTop / Math.max(1, h.scrollHeight - h.clientHeight);
    bar.style.transform = `scaleX(${p})`;
    header.classList.toggle("scrolled", h.scrollTop > 10);
    let current = "";
    for (const s of sections) if (s.getBoundingClientRect().top < 160) current = s.id;
    links.forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "#" + current));
  }
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* --------------------------------------------------------- reveal */
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
  }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
  $$(".reveal").forEach((el, i) => { el.style.transitionDelay = `${(i % 4) * 70}ms`; io.observe(el); });
  // A jump to an anchor (#gallery) can land before the observer's first pass:
  // show whatever is already on screen right away.
  const revealVisible = () => $$(".reveal:not(.in)").forEach((el) => {
    const r = el.getBoundingClientRect();
    if (r.top < innerHeight && r.bottom > 0) { el.classList.add("in"); io.unobserve(el); }
  });
  addEventListener("load", revealVisible);
  addEventListener("hashchange", () => setTimeout(revealVisible, 50));

  /* ------------------------------------------------ cursor + paint trail */
  const fine = matchMedia("(pointer: fine)").matches;
  if (fine && !reduced) {
    document.documentElement.classList.add("has-cursor");
    const cur = $(".cursor"), ring = $(".cursor-ring"), dot = $(".cursor-dot");
    const trail = $(".trail"), tctx = trail.getContext("2d");
    const colors = ["#86C04A", "#A6D873", "#D4F59C", "#F2A541", "#7DB7E8"];
    let mx = innerWidth / 2, my = innerHeight / 2, rx = mx, ry = my, color = 0;
    const pts = [];
    function size() {
      const d = devicePixelRatio || 1;
      trail.width = innerWidth * d; trail.height = innerHeight * d; tctx.setTransform(d, 0, 0, d, 0, 0);
    }
    size(); addEventListener("resize", size);
    addEventListener("pointermove", (e) => {
      mx = e.clientX; my = e.clientY;
      pts.push({ x: mx, y: my, t: performance.now(), c: colors[color] });
    }, { passive: true });
    addEventListener("pointerdown", () => { cur.classList.add("down"); color = (color + 1) % colors.length; });
    addEventListener("pointerup", () => cur.classList.remove("down"));
    document.addEventListener("pointerover", (e) => {
      cur.classList.toggle("hover", !!e.target.closest("a, button, summary, [data-full], .compare, input"));
    });
    document.addEventListener("pointerleave", () => { cur.style.opacity = 0; });
    document.addEventListener("pointerenter", () => { cur.style.opacity = 1; });
    (function frame() {
      rx += (mx - rx) * 0.18; ry += (my - ry) * 0.18;
      ring.style.transform = `translate(${rx}px, ${ry}px) translate(-50%, -50%)`;
      dot.style.transform = `translate(${mx}px, ${my}px) translate(-50%, -50%)`;
      const now = performance.now(), life = 520;
      while (pts.length && now - pts[0].t > life) pts.shift();
      tctx.clearRect(0, 0, innerWidth, innerHeight);
      tctx.lineCap = "round";
      for (let i = 1; i < pts.length; i++) {
        const a = pts[i - 1], b = pts[i], k = 1 - (now - b.t) / life;
        tctx.strokeStyle = b.c; tctx.globalAlpha = k * 0.55; tctx.lineWidth = 2 + k * 7;
        tctx.beginPath(); tctx.moveTo(a.x, a.y); tctx.lineTo(b.x, b.y); tctx.stroke();
      }
      tctx.globalAlpha = 1;
      requestAnimationFrame(frame);
    })();
  }

  /* ------------------------------------------------------------ tilt */
  if (fine && !reduced) {
    $$(".tilt").forEach((el) => {
      el.addEventListener("pointermove", (e) => {
        const r = el.getBoundingClientRect();
        const x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
        el.style.transform = `perspective(900px) rotateY(${x * 6}deg) rotateX(${-y * 6}deg)`;
      });
      el.addEventListener("pointerleave", () => { el.style.transform = ""; });
    });
  }

  /* -------------------------------------------------------- lightbox */
  const lb = $("#lightbox"), lbImg = $("#lightbox img");
  $$("[data-full]").forEach((f) => f.addEventListener("click", () => {
    lbImg.src = f.dataset.full; lbImg.alt = $("img", f).alt; lb.hidden = false;
  }));
  const closeLb = () => { lb.hidden = true; lbImg.src = ""; };
  lb.addEventListener("click", closeLb);
  addEventListener("keydown", (e) => { if (e.key === "Escape" && !lb.hidden) closeLb(); });

  /* ------------------------------------------------- before / after */
  const cmp = $("#compare");
  if (cmp) {
    const top = $(".compare-top", cmp), handle = $(".compare-handle", cmp);
    const set = (p) => {
      p = Math.max(0, Math.min(100, p));
      top.style.clipPath = `inset(0 ${100 - p}% 0 0)`; handle.style.left = p + "%";
      cmp.setAttribute("aria-valuenow", Math.round(p));
    };
    let drag = false;
    const at = (e) => { const r = cmp.getBoundingClientRect(); set(((e.clientX - r.left) / r.width) * 100); };
    cmp.addEventListener("pointerdown", (e) => { drag = true; cmp.setPointerCapture(e.pointerId); at(e); });
    cmp.addEventListener("pointermove", (e) => { if (drag) at(e); });
    cmp.addEventListener("pointerup", () => { drag = false; });
    cmp.addEventListener("keydown", (e) => {
      const v = Number(cmp.getAttribute("aria-valuenow"));
      if (e.key === "ArrowLeft") set(v - 5); if (e.key === "ArrowRight") set(v + 5);
    });
    set(50);
  }

  /* --------------------------------------- hero: paint the sample sign */
  const canvas = $("#paint");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const brush = $(".brush"), hudNum = $("#hudNum"), hudBar = $("#hudBar");
  const W = canvas.width, H = canvas.height, CELL = 4, COLS = W / CELL, ROWS = H / CELL;
  const WOOD = "#A89383";
  const img = new Image();
  img.src = "site/img/sample.webp";
  img.onload = () => {
    const off = document.createElement("canvas");
    off.width = COLS; off.height = ROWS;
    const o = off.getContext("2d");
    o.drawImage(img, 0, 0, COLS, ROWS);
    const px = o.getImageData(0, 0, COLS, ROWS).data;
    // quantize a little so it reads as a painted palette
    const q = (v) => Math.round(v / 24) * 24;
    const colorAt = (cx, cy) => {
      const i = (cy * COLS + cx) * 4;
      return `rgb(${q(px[i])},${q(px[i + 1])},${q(px[i + 2])})`;
    };
    // stroke phase: translucent dabs from big to small
    const dabs = [];
    for (let i = 0; i < 260; i++) {
      const r = 46 * Math.pow(1 - i / 260, 1.6) + 5;
      const x = Math.random() * W, y = Math.random() * H;
      dabs.push({ x, y, r, c: colorAt(Math.min(COLS - 1, x / CELL | 0), Math.min(ROWS - 1, y / CELL | 0)) });
    }
    // touch-up phase: snake through the cells
    const cells = [];
    for (let y = 0; y < ROWS; y++) for (let k = 0; k < COLS; k++) cells.push([y % 2 ? COLS - 1 - k : k, y]);

    const total = dabs.length + cells.length;
    let step = 0, hold = 0, visible = true;
    const moveBrush = (x, y) => {
      const s = canvas.clientWidth / W;
      brush.style.transform = `translate(${16 + x * s}px, ${16 + y * s}px)`;
    };
    const reset = () => { ctx.globalAlpha = 1; ctx.fillStyle = WOOD; ctx.fillRect(0, 0, W, H); step = 0; hold = 0; };
    const progress = () => {
      // strokes are the quick first third of a real run, the touch-up the rest
      const p = Math.round(step < dabs.length ? (step / dabs.length) * 35
        : 35 + ((step - dabs.length) / cells.length) * 65);
      hudNum.textContent = p + "%"; hudBar.style.width = p + "%";
    };
    reset();
    if (reduced) {
      cells.forEach(([x, y]) => { ctx.fillStyle = colorAt(x, y); ctx.fillRect(x * CELL, y * CELL, CELL, CELL); });
      step = total; progress(); brush.style.opacity = 0;
      return;
    }
    new IntersectionObserver((e) => { visible = e[0].isIntersecting; }).observe(canvas);
    (function tick() {
      if (visible) {
        if (step < dabs.length) {
          for (let n = 0; n < 3 && step < dabs.length; n++, step++) {
            const d = dabs[step];
            ctx.globalAlpha = 0.55; ctx.fillStyle = d.c;
            ctx.beginPath(); ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2); ctx.fill();
            moveBrush(d.x, d.y);
          }
          ctx.globalAlpha = 1;
        } else if (step < total) {
          let last;
          for (let n = 0; n < 34 && step < total; n++, step++) {
            last = cells[step - dabs.length];
            ctx.fillStyle = colorAt(last[0], last[1]);
            ctx.fillRect(last[0] * CELL, last[1] * CELL, CELL, CELL);
          }
          moveBrush(last[0] * CELL + CELL / 2, last[1] * CELL + CELL / 2);
        } else if (++hold > 200) {
          reset();
        }
        brush.style.opacity = step < total ? 1 : 0;
        progress();
      }
      requestAnimationFrame(tick);
    })();
  };
})();
