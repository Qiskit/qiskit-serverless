// Behaviour of the Job Timeline admin page.
//
// This file exists because the project's Content Security Policy forbids inline <script> blocks
// and inline style attributes, so nothing here may be generated server side and nothing may set
// a style attribute: visibility is driven by the CSS classes in admin/css/job_timeline.css, and
// the chart geometry travels in data-* attributes on the <svg> element.

// --- compute profile filter buttons ---
(function () {
    document.querySelectorAll(".filter-btn").forEach(function (btn) {
        btn.addEventListener("click", function () {
            document.querySelectorAll(".filter-btn").forEach(function (other) {
                other.classList.remove("active");
            });
            btn.classList.add("active");
            const profile = btn.dataset.profile;
            document.querySelectorAll(".job-row").forEach(function (row) {
                row.style.opacity = profile === "__all__" || row.dataset.profile === profile ? "1" : "0.08";
            });
            document.querySelectorAll(".conc-path").forEach(function (path) {
                path.classList.toggle("is-visible", path.dataset.profile === profile);
            });
        });
    });
})();

// --- hover cursor: vertical bar plus the time under the pointer ---
(function () {
    const svg = document.getElementById("timeline-svg");
    const cursor = document.getElementById("hover-cursor");
    const bar = document.getElementById("hover-cursor-bar");
    const labelBg = document.getElementById("hover-cursor-label-bg");
    const label = document.getElementById("hover-cursor-label");
    if (!svg || !cursor || !bar || !labelBg || !label) return;

    const marginLeft = parseFloat(svg.dataset.marginLeft);
    const chartW = parseFloat(svg.dataset.chartW);
    const tMinMs = parseFloat(svg.dataset.tMinMs);
    const spanMs = parseFloat(svg.dataset.spanMs);
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

    function pad(n) {
        return String(n).padStart(2, "0");
    }

    // the server sends the range as "plain" UTC milliseconds, so read it back with getUTC* to
    // show the same hour it computed, whatever time zone the browser is in
    function fmtTime(ms) {
        const d = new Date(ms);
        return (
            pad(d.getUTCDate()) +
            "-" +
            months[d.getUTCMonth()] +
            " " +
            pad(d.getUTCHours()) +
            ":" +
            pad(d.getUTCMinutes()) +
            ":" +
            pad(d.getUTCSeconds())
        );
    }

    svg.addEventListener("mousemove", function (evt) {
        const rect = svg.getBoundingClientRect();
        const scaleX = svg.viewBox.baseVal.width / rect.width;
        const xUser = (evt.clientX - rect.left) * scaleX;
        if (xUser < marginLeft || xUser > marginLeft + chartW) {
            cursor.classList.remove("is-visible");
            return;
        }
        const frac = (xUser - marginLeft) / chartW;
        const text = fmtTime(tMinMs + frac * spanMs);
        bar.setAttribute("x", xUser.toFixed(1));
        label.textContent = text;
        label.setAttribute("x", xUser.toFixed(1));
        const labelWidth = text.length * 6.2 + 10;
        labelBg.setAttribute("x", (xUser - labelWidth / 2).toFixed(1));
        labelBg.setAttribute("width", labelWidth.toFixed(1));
        cursor.classList.add("is-visible");
    });

    svg.addEventListener("mouseleave", function () {
        cursor.classList.remove("is-visible");
    });
})();
