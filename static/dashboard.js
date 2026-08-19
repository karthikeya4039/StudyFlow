/**
 * dashboard.js
 * Minimal dashboard helpers — metric card hover labels and greeting refresh.
 */
(function () {
    'use strict';

    // Animate metric value counters on load
    document.querySelectorAll('.metric-card .value').forEach(function (el) {
        var target = parseInt(el.textContent.trim(), 10);
        if (isNaN(target) || target === 0) return;

        var start = 0;
        var duration = 800;
        var startTime = null;

        function step(timestamp) {
            if (!startTime) startTime = timestamp;
            var progress = Math.min((timestamp - startTime) / duration, 1);
            var eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
            el.textContent = Math.round(eased * target);
            if (progress < 1) requestAnimationFrame(step);
            else el.textContent = target;
        }

        requestAnimationFrame(step);
    });
})();