/* ═══════════════════════════════════════════════════════════
   LANDING PAGE — Scroll-Driven Animations & Interactions
   AI Study Assistant
   ═══════════════════════════════════════════════════════════ */

(function () {
    'use strict';

    // ── Reduced-motion check ─────────────────────────────
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // ── Travelling Product ───────────────────────────────
    // Moves a fixed-position SVG across the page based on scroll position.
    // Keyframe stops expressed as viewport percentages for x/y.
    function initTravellingProduct() {
        const el = document.querySelector('.travelling-product');
        if (!el || prefersReducedMotion) {
            if (el) el.style.display = 'none';
            return;
        }

        // Keyframe stops: [scrollY (px), x (vw), y (vh), rotation (deg), scale, opacity]
        const isMobile = window.innerWidth <= 600;

const stops = isMobile
    ? [
        [0,     72, 24,  -6, 0.55, 0.75],
        [300,   74, 34,  -8, 0.52, 0.65],
        [700,   76, 44,  -3, 0.48, 0.55],
        [1200,  78, 38,   5, 0.44, 0.4],
        [1800,  80, 50,   8, 0.40, 0.2],
        [2400,  82, 60,  10, 0.35, 0],
      ]
    : [
        [0,     62, 18,  -8, 1.0, 0.95],
        [300,   58, 30, -12, 0.92, 0.9],
        [700,   52, 42,  -4, 0.85, 0.85],
        [1200,  68, 28,   6, 0.78, 0.7],
        [1800,  72, 50,  10, 0.7,  0.4],
        [2400,  76, 60,  14, 0.6,  0],
      ];

        function lerp(a, b, t) {
            return a + (b - a) * t;
        }

        function updateProduct() {
            const scrollY = window.scrollY;
            let i = 0;
            while (i < stops.length - 1 && stops[i + 1][0] <= scrollY) i++;

            if (i >= stops.length - 1) {
                el.style.opacity = '0';
                el.style.visibility = 'hidden';
                return;
            }

            const [s0, x0, y0, r0, sc0, o0] = stops[i];
            const [s1, x1, y1, r1, sc1, o1] = stops[i + 1];
            const t = Math.min(1, Math.max(0, (scrollY - s0) / (s1 - s0)));

            // Smooth easing
            const ease = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;

            const x = lerp(x0, x1, ease);
            const y = lerp(y0, y1, ease);
            const r = lerp(r0, r1, ease);
            const sc = lerp(sc0, sc1, ease);
            const o = lerp(o0, o1, ease);

            el.style.left = x + 'vw';
            el.style.top = y + 'vh';
            el.style.transform = `rotate(${r}deg) scale(${sc})`;
            el.style.opacity = o;
            el.style.visibility = o <= 0 ? 'hidden' : 'visible';
        }

       window.addEventListener('scroll', updateProduct, { passive: true });
       window.addEventListener('resize', updateProduct);
       updateProduct();
    }

    // ── Spread Wordmark Animation ────────────────────────
    // Letters spread apart from center on scroll.
    function initSpreadWordmark() {
        const wordmark = document.querySelector('.spread-wordmark');
        if (!wordmark || prefersReducedMotion) return;

        const letters = wordmark.querySelectorAll('span');
        const total = letters.length;
        const center = (total - 1) / 2;

        function updateSpread() {
            const scrollY = window.scrollY;
            // Start spreading after 100px, max at 600px
            const progress = Math.min(1, Math.max(0, (scrollY - 100) / 500));
            const ease = progress * progress; // quadratic ease-in

            letters.forEach(function (letter, i) {
                const dist = i - center;
                const spreadX = dist * ease * 12;  // px per unit from center
                const sinkY = Math.abs(dist) * ease * 4;
                letter.style.transform = `translate(${spreadX}px, ${sinkY}px)`;
                letter.style.opacity = 1 - ease * 0.3;
            });
        }

        window.addEventListener('scroll', updateSpread, { passive: true });
        updateSpread();
    }

    // ── SVG Draw Animation ───────────────────────────────
    // Draws SVG paths on entry using strokeDasharray/strokeDashoffset.
    function initSVGDraw() {
        const panel = document.querySelector('.demo-panel');
        if (!panel || prefersReducedMotion) return;

        let drawn = false;

        function drawPaths() {
            if (drawn) return;

            const paths = panel.querySelectorAll('.draw-path');
            paths.forEach(function (path, i) {
                const length = path.getTotalLength();
                path.style.strokeDasharray = length;
                path.style.strokeDashoffset = length;

                // Stagger each path slightly
                path.style.transition = `stroke-dashoffset ${1.8 + i * 0.3}s cubic-bezier(.22,1,.36,1) ${i * 0.15}s`;

                // Force reflow
                path.getBoundingClientRect();
                path.style.strokeDashoffset = '0';
            });

            drawn = true;
        }

        // Reset and redraw (for variant switching)
        window._redrawSVG = function () {
            drawn = false;
            const paths = panel.querySelectorAll('.draw-path');
            paths.forEach(function (path) {
                path.style.transition = 'none';
                const length = path.getTotalLength();
                path.style.strokeDasharray = length;
                path.style.strokeDashoffset = length;
            });
            // Trigger redraw after a tick
            requestAnimationFrame(function () {
                requestAnimationFrame(function () {
                    drawPaths();
                });
            });
        };

        const observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    drawPaths();
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.3 });

        observer.observe(panel);
    }

    // ── Variant Picker ───────────────────────────────────
    // Switches the SVG content and facts in the demo panel.
    function initVariantPicker() {
        const buttons = document.querySelectorAll('.variant-btn');
        if (!buttons.length) return;

        const svgContainer = document.getElementById('demo-svg');
        const factsContainer = document.querySelector('.demo-facts');

        const variants = {
            note: {
                svg: `<svg viewBox="0 0 600 300" xmlns="http://www.w3.org/2000/svg">
                    <!-- Notebook page -->
                    <rect class="draw-path" x="60" y="20" width="480" height="260" />
                    <!-- Margin line -->
                    <line class="draw-path draw-path--blue" x1="140" y1="20" x2="140" y2="280" />
                    <!-- Rule lines -->
                    <line class="draw-path" x1="160" y1="70" x2="500" y2="70" />
                    <line class="draw-path" x1="160" y1="110" x2="480" y2="110" />
                    <line class="draw-path" x1="160" y1="150" x2="520" y2="150" />
                    <line class="draw-path" x1="160" y1="190" x2="460" y2="190" />
                    <line class="draw-path" x1="160" y1="230" x2="490" y2="230" />
                    <!-- Title scribble -->
                    <path class="draw-path draw-path--blue" d="M168 46 Q220 38 280 46 Q340 54 400 46" />
                    <!-- Bullet points -->
                    <circle class="draw-path" cx="168" cy="110" r="3" />
                    <circle class="draw-path" cx="168" cy="150" r="3" />
                    <circle class="draw-path" cx="168" cy="190" r="3" />
                </svg>`,
                facts: [
                    { label: 'FORMAT', value: 'Markdown + Rich Text' },
                    { label: 'EXPORT', value: 'PDF Download' },
                    { label: 'STORAGE', value: 'Local SQLite' },
                ]
            },
            quiz: {
                svg: `<svg viewBox="0 0 600 300" xmlns="http://www.w3.org/2000/svg">
                    <!-- Quiz card -->
                    <rect class="draw-path" x="60" y="20" width="480" height="260" />
                    <!-- Question area -->
                    <path class="draw-path draw-path--blue" d="M100 55 Q200 48 340 55 Q420 62 500 55" />
                    <!-- Option boxes -->
                    <rect class="draw-path" x="100" y="90" width="400" height="34" />
                    <rect class="draw-path" x="100" y="138" width="400" height="34" />
                    <rect class="draw-path" x="100" y="186" width="400" height="34" />
                    <rect class="draw-path" x="100" y="234" width="400" height="34" />
                    <!-- Radio circles -->
                    <circle class="draw-path" cx="120" cy="107" r="7" />
                    <circle class="draw-path draw-path--blue" cx="120" cy="155" r="7" />
                    <circle class="draw-path" cx="120" cy="203" r="7" />
                    <circle class="draw-path" cx="120" cy="251" r="7" />
                    <!-- Check in selected -->
                    <path class="draw-path draw-path--blue" d="M115 155 L118 160 L127 148" />
                    <!-- Option text lines -->
                    <line class="draw-path" x1="140" y1="107" x2="380" y2="107" />
                    <line class="draw-path" x1="140" y1="155" x2="420" y2="155" />
                    <line class="draw-path" x1="140" y1="203" x2="360" y2="203" />
                    <line class="draw-path" x1="140" y1="251" x2="400" y2="251" />
                </svg>`,
                facts: [
                    { label: 'QUESTIONS', value: 'AI-Generated' },
                    { label: 'DIFFICULTY', value: '3 Levels' },
                    { label: 'SCORING', value: 'Instant Results' },
                ]
            },
            chat: {
                svg: `<svg viewBox="0 0 600 300" xmlns="http://www.w3.org/2000/svg">
                    <!-- Chat window -->
                    <rect class="draw-path" x="60" y="20" width="480" height="260" />
                    <!-- Header bar -->
                    <line class="draw-path" x1="60" y1="60" x2="540" y2="60" />
                    <!-- Header dot -->
                    <circle class="draw-path draw-path--blue" cx="90" cy="40" r="6" />
                    <line class="draw-path" x1="110" y1="40" x2="200" y2="40" />
                    <!-- User message bubble -->
                    <rect class="draw-path" x="280" y="80" width="230" height="36" />
                    <line class="draw-path" x1="300" y1="98" x2="480" y2="98" />
                    <!-- AI response bubble -->
                    <rect class="draw-path draw-path--blue" x="90" y="136" width="320" height="60" />
                    <line class="draw-path" x1="110" y1="154" x2="370" y2="154" />
                    <line class="draw-path" x1="110" y1="174" x2="340" y2="174" />
                    <!-- Input area -->
                    <line class="draw-path" x1="60" y1="240" x2="540" y2="240" />
                    <line class="draw-path" x1="90" y1="258" x2="300" y2="258" />
                    <!-- Send button -->
                    <rect class="draw-path draw-path--blue" x="470" y="248" width="40" height="22" />
                    <path class="draw-path" d="M483 259 L497 259 L490 252 Z" />
                </svg>`,
                facts: [
                    { label: 'MODEL', value: 'Llama 3.2 via Ollama' },
                    { label: 'LATENCY', value: 'Local Inference' },
                    { label: 'HISTORY', value: 'Full Conversation Log' },
                ]
            }
        };

        function setVariant(name) {
            // Update buttons
            buttons.forEach(function (btn) {
                btn.setAttribute('aria-pressed', btn.dataset.variant === name ? 'true' : 'false');
            });

            // Update SVG
            if (svgContainer && variants[name]) {
                svgContainer.innerHTML = variants[name].svg;
            }

            // Update facts
            if (factsContainer && variants[name]) {
                factsContainer.innerHTML = variants[name].facts.map(function (f) {
                    return '<div class="demo-fact"><strong>' + f.value + '</strong>' + f.label + '</div>';
                }).join('');
            }

            // Redraw SVG animation
            if (window._redrawSVG) {
                window._redrawSVG();
            }
        }

        buttons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                setVariant(btn.dataset.variant);
            });
        });

        // Initialize with note variant
        setVariant('note');
    }

    // ── Reveal on Scroll ─────────────────────────────────
    // One-shot reveals; elements don't un-reveal.
    function initReveals() {
        if (prefersReducedMotion) {
            // Show everything immediately
            document.querySelectorAll('.reveal').forEach(function (el) {
                el.classList.add('revealed');
            });
            return;
        }

        const observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add('revealed');
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.15, rootMargin: '0px 0px -40px 0px' });

        document.querySelectorAll('.reveal').forEach(function (el) {
            observer.observe(el);
        });
    }

    // ── Init everything on DOM ready ─────────────────────
    function init() {
        // Only run on landing page
        if (!document.body.classList.contains('landing-page')) return;

        initTravellingProduct();
        initSpreadWordmark();
        initSVGDraw();
        initVariantPicker();
        initReveals();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
