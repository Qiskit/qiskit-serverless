"""Pure rendering logic for the Job Timeline admin page.

Turns a `Job` queryset (with `job_events` prefetched) into the HTML/SVG strings the
`admin/api/job/timeline.html` template needs. Ported from a standalone CSV-based tool that
builds the same visualization from an exported CSV instead of live `Job`/`JobEvent` rows.
"""

import calendar
import html
from datetime import timedelta

from django.utils.safestring import mark_safe

from core.model_managers.job_events import JobEventType

STATUS_COLOR = {
    "QUEUED": "#94a3b8",
    "PENDING": "#a855f7",
    "RUNNING": "#3b82f6",
    "SUCCEEDED": "#22c55e",
    "FAILED": "#ef4444",
    "STOPPED": "#f59e0b",
}
OVERLAP_STROKE = "#dc2626"
OUTCOME_LABEL = {
    "SUCCEEDED": ("OK", "#22c55e"),
    "FAILED": ("FAIL", "#ef4444"),
    "STOPPED": ("STOPPED", "#a16207"),
}


def _jobs_from_queryset(jobs_qs):
    """Build the "job dict" shape every function below expects, from live Job/JobEvent rows."""
    jobs = []
    for job in jobs_qs:
        status_events = []
        for event in job.job_events.all():
            if event.event_type != JobEventType.STATUS_CHANGE:
                continue
            status = event.data.get("status")
            if status and event.created:
                status_events.append((event.created, status))
        jobs.append(
            {
                "id": str(job.id),
                "status": job.status,
                "profile": job.compute_profile or "-",
                "created": job.created,
                "updated": job.updated,
                "running_started_at": job.running_started_at,
                "status_events": status_events,
            }
        )
    return jobs


def compute_timeline(job):
    """Compute timeline segments and timestamps from job events."""
    events = sorted(job["status_events"], key=lambda e: e[0])

    # puntos únicos en orden cronológico: (tiempo en que se alcanzó ese estado, estado)
    seen = set()
    points = []
    if "QUEUED" not in {st for _, st in events} and job["created"]:
        points.append((job["created"], "QUEUED"))
        seen.add("QUEUED")
    for ts, st in events:
        if st not in seen:
            seen.add(st)
            points.append((ts, st))

    job["points"] = points
    # tramos [inicio, fin) coloreados por el estado vigente en ese tramo
    job["segments"] = [(points[i][0], points[i + 1][0], points[i][1]) for i in range(len(points) - 1)]

    durations = {}
    for seg_start, seg_end, seg_status in job["segments"]:
        durations[seg_status] = durations.get(seg_status, 0.0) + (seg_end - seg_start).total_seconds()
    job["durations"] = durations

    by_status = {status: ts for ts, status in points}
    job["t_queue"] = by_status.get("QUEUED", job["created"])
    job["t_run"] = by_status.get("RUNNING", job["running_started_at"])
    job["t_end"] = points[-1][0] if points else job["updated"]
    job["t_span_start"] = job["t_run"] or job["t_queue"]
    return job


def sort_jobs(jobs):
    """Sort jobs by timeline span start."""
    return sorted(jobs, key=lambda j: j["t_span_start"])


def find_overlaps(jobs):
    """Para cada job con tramo RUNNING, con cuántos otros se solapa en ese tramo."""
    running = [j for j in jobs if j["t_run"] and j["t_end"]]
    overlaps = {j["id"]: set() for j in running}
    for i, a in enumerate(running):
        for b in running[i + 1 :]:
            if a["t_run"] < b["t_end"] and b["t_run"] < a["t_end"]:
                overlaps[a["id"]].add(b["id"])
                overlaps[b["id"]].add(a["id"])
    return overlaps


def concurrency_series(jobs):
    """Serie escalonada (tiempo, nº de jobs RUNNING simultáneos)."""
    points = []
    for j in jobs:
        if j["t_run"] and j["t_end"]:
            points.append((j["t_run"], 1))
            points.append((j["t_end"], -1))
    points.sort(key=lambda p: p[0])
    series = []
    running = 0
    for ts, delta in points:
        running += delta
        series.append((ts, running))
    return series


def fmt_dt(dt):
    """Format datetime for display."""
    return dt.strftime("%d-%b %H:%M:%S") if dt else "-"


def fmt_dur(seconds):
    """Format duration in seconds as human-readable string."""
    if seconds is None:
        return "-"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def build_concurrency_path(  # pylint: disable=too-many-positional-arguments,unused-argument
    series, t_min, t_max, x, cy, max_conc
):
    """Build SVG path for concurrency series."""
    if not series:
        return None
    path_d = f"M {x(t_min):.1f} {cy(0):.1f} L {x(series[0][0]):.1f} {cy(0):.1f} "
    prev_count = 0
    for ts, count in series:
        xx = x(ts)
        path_d += f"L {xx:.1f} {cy(prev_count):.1f} L {xx:.1f} {cy(count):.1f} "
        prev_count = count
    path_d += f"L {x(t_max):.1f} {cy(prev_count):.1f} L {x(t_max):.1f} {cy(0):.1f} Z"
    return path_d


def build_svg(jobs, overlaps):  # pylint: disable=too-many-locals,too-many-statements
    """Build SVG timeline visualization."""
    margin_left, margin_right = 260, 260
    margin_top, margin_bottom = 20, 60
    row_h = 16
    row_gap = 3
    chart_w = 2200
    concurrency_h = 90

    all_starts = [j["t_queue"] for j in jobs if j["t_queue"]]
    all_ends = [j["t_end"] for j in jobs if j["t_end"]]
    t_min = min(all_starts)
    t_max = max(all_ends)
    span = (t_max - t_min).total_seconds() or 1
    pad = span * 0.02
    t_min -= timedelta(seconds=pad)
    t_max += timedelta(seconds=pad)
    span = (t_max - t_min).total_seconds()

    def x(dt):
        return margin_left + (dt - t_min).total_seconds() / span * chart_w

    jobs_sorted = sort_jobs(jobs)
    n = len(jobs_sorted)
    gantt_h = n * (row_h + row_gap)
    total_h = margin_top + concurrency_h + 30 + gantt_h + margin_bottom
    total_w = margin_left + chart_w + margin_right

    profiles = sorted({j["profile"] for j in jobs})

    svg = []
    svg.append(
        f'<svg id="timeline-svg" width="{total_w}" height="{total_h}" viewBox="0 0 {total_w} {total_h}" '
        f'xmlns="http://www.w3.org/2000/svg" font-family="ui-monospace, Menlo, monospace" font-size="10">'
    )
    svg.append(f'<rect x="0" y="0" width="{total_w}" height="{total_h}" fill="#0b1020"/>')

    top_of_chart = margin_top
    bottom_of_gantt = margin_top + concurrency_h + 30 + gantt_h

    # --- líneas muy suaves, una por cada hora exacta ---
    hour = t_min.replace(minute=0, second=0, microsecond=0)
    if hour < t_min:
        hour += timedelta(hours=1)
    while hour <= t_max:
        hx = x(hour)
        svg.append(
            f'<line x1="{hx:.1f}" y1="{top_of_chart}" x2="{hx:.1f}" y2="{bottom_of_gantt}" '
            f'stroke="#e2e8f0" stroke-width="0.5" opacity="0.06"/>'
        )
        hour += timedelta(hours=1)

    # --- gridlines de tiempo (comunes a ambos gráficos) ---
    n_ticks = 16
    tick_step = span / n_ticks
    for i in range(n_ticks + 1):
        t = t_min + timedelta(seconds=tick_step * i)
        xx = x(t)
        svg.append(
            f'<line x1="{xx:.1f}" y1="{top_of_chart}" x2="{xx:.1f}" y2="{bottom_of_gantt}" '
            f'stroke="#1e2740" stroke-width="1"/>'
        )
        svg.append(
            f'<text x="{xx:.1f}" y="{bottom_of_gantt + 14}" fill="#94a3b8" '
            f'text-anchor="middle" transform="rotate(35 {xx:.1f} {bottom_of_gantt + 14})">'
            f"{html.escape(t.strftime('%d-%b %H:%M'))}</text>"
        )

    # --- gráfico de concurrencia (solapes), una serie por "Todos" + una por perfil ---
    def cy(count, max_count):
        return margin_top + concurrency_h - (count / max_count) * (concurrency_h - 10)

    series_all = concurrency_series(jobs_sorted)
    max_conc = max((c for _, c in series_all), default=0) or 1

    svg.append(
        f'<text x="{margin_left}" y="{margin_top - 6}" fill="#e2e8f0" font-weight="bold">'
        f"Jobs RUNNING simultáneos (máximo solapado: {max_conc})</text>"
    )
    path_d = build_concurrency_path(series_all, t_min, t_max, x, lambda c: cy(c, max_conc), max_conc)
    if path_d:
        svg.append(
            f'<path class="conc-path" data-profile="__all__" style="display:block" d="{path_d}" '
            f'fill="#3b82f6" opacity="0.35" stroke="#60a5fa" stroke-width="1.5"/>'
        )
    for profile in profiles:
        series_p = concurrency_series([j for j in jobs_sorted if j["profile"] == profile])
        path_d = build_concurrency_path(series_p, t_min, t_max, x, lambda c: cy(c, max_conc), max_conc)
        if path_d:
            svg.append(
                f'<path class="conc-path" data-profile="{html.escape(profile)}" style="display:none" d="{path_d}" '
                f'fill="#3b82f6" opacity="0.35" stroke="#60a5fa" stroke-width="1.5"/>'
            )
    for c in range(0, max_conc + 1):
        yy = cy(c, max_conc)
        svg.append(f'<text x="{margin_left - 8}" y="{yy + 3:.1f}" fill="#64748b" text-anchor="end">{c}</text>')

    # --- gantt ---
    gantt_top = margin_top + concurrency_h + 30
    svg.append(
        f'<text x="{margin_left}" y="{gantt_top - 8}" fill="#e2e8f0" font-weight="bold">'
        "Jobs — ordenados por inicio (color = estado en cada tramo)</text>"
    )

    for idx, job in enumerate(jobs_sorted):
        y = gantt_top + idx * (row_h + row_gap)
        cy_mid = y + row_h / 2
        short_id = job["id"][:8]
        overlap_ids = overlaps.get(job["id"], set())
        left_label = f"{idx + 1:>2} {short_id} · {job['profile']}"
        if overlap_ids:
            left_label += f"  ⧉{len(overlap_ids)}"

        svg.append(f'<g class="job-row" data-profile="{html.escape(job["profile"])}">')

        bar_end_x = x(job["t_queue"]) if job["t_queue"] else margin_left
        for seg_start, seg_end, seg_status in job["segments"]:
            sx1, sx2 = x(seg_start), x(seg_end)
            color = STATUS_COLOR.get(seg_status, "#64748b")
            is_running_overlap = seg_status == "RUNNING" and overlap_ids
            stroke = OVERLAP_STROKE if is_running_overlap else "#0b1020"
            stroke_w = 2 if is_running_overlap else 0.5
            svg.append(
                f'<rect x="{sx1:.1f}" y="{y}" width="{max(sx2 - sx1, 1.5):.1f}" height="{row_h}" '
                f'fill="{color}" stroke="{stroke}" stroke-width="{stroke_w}"/>'
            )
            bar_end_x = sx2

        d = job["durations"]
        total_dur = (job["t_end"] - job["t_queue"]).total_seconds() if job["t_queue"] and job["t_end"] else None
        right_prefix = f"PENDING: {fmt_dur(d.get('PENDING'))} - RUNNING: {fmt_dur(d.get('RUNNING'))} "
        outcome_text, outcome_color = OUTCOME_LABEL.get(job["status"], (job["status"], "#94a3b8"))

        tooltip = (
            f"job_id: {job['id']}\n"
            f"status: {job['status']}\n"
            f"compute_profile: {job['profile']}\n"
            f"queued: {fmt_dt(job['t_queue'])}\n"
            f"running: {fmt_dt(job['t_run'])}\n"
            f"end: {fmt_dt(job['t_end'])}\n"
            f"duración en cola (QUEUED): {fmt_dur(d.get('QUEUED'))}\n"
            f"duración en PENDING: {fmt_dur(d.get('PENDING'))}\n"
            f"duración en RUNNING: {fmt_dur(d.get('RUNNING'))}\n"
            f"duración total (con cola): {fmt_dur(total_dur)}\n"
            f"solapa con {len(overlap_ids)} job(s)"
        )

        svg.append(f"<title>{html.escape(tooltip)}</title>")
        svg.append(
            f'<text x="{margin_left - 10:.1f}" y="{cy_mid + 3:.1f}" fill="#94a3b8" text-anchor="end">'
            f"{html.escape(left_label)}</text>"
        )
        svg.append(
            f'<text x="{bar_end_x + 6:.1f}" y="{cy_mid + 3:.1f}" fill="#e2e8f0" text-anchor="start">'
            f'{html.escape(right_prefix)}<tspan fill="{outcome_color}" font-weight="bold">'
            f"{html.escape(outcome_text)}</tspan></text>"
        )
        svg.append("</g>")

    # --- cursor de hover: barrita vertical + etiqueta con la hora ---
    svg.append(
        f'<g id="hover-cursor" style="display:none" pointer-events="none">'
        f'<rect id="hover-cursor-bar" x="0" y="{top_of_chart}" width="2" '
        f'height="{bottom_of_gantt - top_of_chart}" fill="#93c5fd" opacity="0.35"/>'
        f'<rect id="hover-cursor-label-bg" x="0" y="{top_of_chart - 16}" width="1" height="14" '
        f'rx="3" fill="#1e2740"/>'
        f'<text id="hover-cursor-label" x="0" y="{top_of_chart - 6}" fill="#e2e8f0" text-anchor="middle">'
        "</text>"
        "</g>"
    )

    svg.append("</svg>")
    geometry = {
        "margin_left": margin_left,
        "chart_w": chart_w,
        "top": top_of_chart,
        "bottom": bottom_of_gantt,
        "total_w": total_w,
        "total_h": total_h,
    }
    return "\n".join(svg), t_min, t_max, profiles, geometry


def build_legend():
    """Build HTML legend for timeline colors."""
    items = [
        ("QUEUED", STATUS_COLOR["QUEUED"]),
        ("PENDING", STATUS_COLOR["PENDING"]),
        ("RUNNING", STATUS_COLOR["RUNNING"]),
    ]
    parts = []
    for label, color in items:
        swatch = (
            f'<span style="display:inline-block;width:12px;height:12px;background:{color};'
            'border-radius:2px;margin-right:6px;vertical-align:middle"></span>'
        )
        parts.append(f'<span style="margin-right:16px">{swatch}{html.escape(label)}</span>')
    for _outcome_status, (text, color) in OUTCOME_LABEL.items():
        parts.append(f'<span style="margin-right:16px;color:{color};font-weight:bold">{html.escape(text)}</span>')
    parts.append(
        '<span style="margin-right:16px">'
        f'<span style="display:inline-block;width:12px;height:12px;background:{STATUS_COLOR["RUNNING"]};'
        f'border:2px solid {OVERLAP_STROKE};border-radius:2px;margin-right:6px;vertical-align:middle"></span>'
        "tramo RUNNING solapado con otro job</span>"
    )
    return "".join(parts)


def build_overlap_summary(jobs, overlaps):
    """Build HTML summary of overlapping jobs."""
    seen_pairs = set()
    for job in jobs:
        for other_id in overlaps.get(job["id"], ()):
            pair = tuple(sorted((job["id"], other_id)))
            seen_pairs.add(pair)
    by_job = {j["id"]: j for j in jobs}
    lines = []
    for a, b in sorted(seen_pairs, key=lambda p: by_job[p[0]]["t_run"]):
        ja, jb = by_job[a], by_job[b]
        lines.append(
            f"<li><code>{a[:8]}</code> ({html.escape(ja['profile'])}, {fmt_dt(ja['t_run'])}–{fmt_dt(ja['t_end'])}) "
            f"solapa con <code>{b[:8]}</code> ({html.escape(jb['profile'])}, "
            f"{fmt_dt(jb['t_run'])}–{fmt_dt(jb['t_end'])})</li>"
        )
    if not lines:
        return "<p>No se detectaron solapes entre tramos RUNNING.</p>"
    return f"<p>{len(seen_pairs)} pares de jobs se solapan en ejecución:</p><ul>{''.join(lines)}</ul>"


def build_filter_bar(profiles):
    """Build HTML filter buttons for compute profiles."""
    buttons = ['<button class="filter-btn active" data-profile="__all__">Todos</button>']
    for p in profiles:
        buttons.append(f'<button class="filter-btn" data-profile="{html.escape(p)}">{html.escape(p)}</button>')
    return "".join(buttons)


def build_hover_js(t_min, t_max, geometry):
    """Build JavaScript code for hover tooltips."""
    # trata los datetimes en UTC como milisegundos "puros", solo para poder llevarlos a JS
    # y volver sin que ningún reloj de zona horaria (navegador) altere la hora mostrada
    t_min_ms = calendar.timegm(t_min.timetuple()) * 1000
    span_ms = (t_max - t_min).total_seconds() * 1000
    return f"""
(function () {{
  var svg = document.getElementById('timeline-svg');
  var cursor = document.getElementById('hover-cursor');
  var bar = document.getElementById('hover-cursor-bar');
  var labelBg = document.getElementById('hover-cursor-label-bg');
  var label = document.getElementById('hover-cursor-label');
  var marginLeft = {geometry["margin_left"]};
  var chartW = {geometry["chart_w"]};
  var tMinMs = {t_min_ms};
  var spanMs = {span_ms};
  var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

  function pad(n) {{ return String(n).padStart(2, '0'); }}
  function fmtTime(ms) {{
    var d = new Date(ms);
    return pad(d.getUTCDate()) + '-' + months[d.getUTCMonth()] + ' ' +
      pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ':' + pad(d.getUTCSeconds());
  }}

  svg.addEventListener('mousemove', function (evt) {{
    var rect = svg.getBoundingClientRect();
    var scaleX = svg.viewBox.baseVal.width / rect.width;
    var xUser = (evt.clientX - rect.left) * scaleX;
    if (xUser < marginLeft || xUser > marginLeft + chartW) {{
      cursor.style.display = 'none';
      return;
    }}
    var frac = (xUser - marginLeft) / chartW;
    var text = fmtTime(tMinMs + frac * spanMs);
    bar.setAttribute('x', xUser.toFixed(1));
    label.textContent = text;
    label.setAttribute('x', xUser.toFixed(1));
    var labelWidth = text.length * 6.2 + 10;
    labelBg.setAttribute('x', (xUser - labelWidth / 2).toFixed(1));
    labelBg.setAttribute('width', labelWidth.toFixed(1));
    cursor.style.display = 'block';
  }});
  svg.addEventListener('mouseleave', function () {{
    cursor.style.display = 'none';
  }});
}})();
"""


FILTER_JS = """
document.querySelectorAll('.filter-btn').forEach(function (btn) {
  btn.addEventListener('click', function () {
    document.querySelectorAll('.filter-btn').forEach(function (b) { b.classList.remove('active'); });
    btn.classList.add('active');
    var profile = btn.dataset.profile;
    document.querySelectorAll('.job-row').forEach(function (row) {
      row.style.opacity = (profile === '__all__' || row.dataset.profile === profile) ? '1' : '0.08';
    });
    document.querySelectorAll('.conc-path').forEach(function (p) {
      p.style.display = (p.dataset.profile === profile) ? 'block' : 'none';
    });
  });
});
"""


def render_job_timeline(jobs_qs):
    """Build the full template context for the Job Timeline admin page.

    `jobs_qs` must be non-empty; the empty-selection case is the caller's responsibility
    (see `JobAdmin.job_timeline_view` in Task 2), so this function does not special-case it.
    """
    jobs = [compute_timeline(j) for j in _jobs_from_queryset(jobs_qs)]
    overlaps = find_overlaps(jobs)
    svg, t_min, t_max, profiles, geometry = build_svg(jobs, overlaps)
    return {
        "timeline_jobs_count": len(jobs),
        "timeline_range": f"{fmt_dt(t_min)} a {fmt_dt(t_max)}",
        "timeline_svg": mark_safe(svg),
        "timeline_legend": mark_safe(build_legend()),
        "timeline_filter_bar": mark_safe(build_filter_bar(profiles)),
        "timeline_overlap_summary": mark_safe(build_overlap_summary(jobs, overlaps)),
        "timeline_filter_js": mark_safe(FILTER_JS),
        "timeline_hover_js": mark_safe(build_hover_js(t_min, t_max, geometry)),
    }
