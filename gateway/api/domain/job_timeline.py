"""Pure rendering logic for the Job Timeline admin page.

Turns a `Job` queryset (with `job_events` prefetched) into the HTML/SVG strings the
`admin/api/job/timeline.html` template needs. Ported from a standalone CSV-based tool that
builds the same visualization from an exported CSV instead of live `Job`/`JobEvent` rows.

The page's behaviour lives in the static file `admin/js/job_timeline.js`: the Content Security
Policy of this project forbids inline `<script>` blocks and inline `style` attributes, so the
markup built here carries CSS classes and `data-*` attributes only.
"""

import calendar
import html
from datetime import timedelta

from django.utils import timezone
from django.utils.safestring import mark_safe

from core.model_managers.job_events import JobEventType
from core.models import Job

# Same palette and names as the job list's status badges (`.qs-status-badge` in
# api/static/admin/css/carbon_theme.css), so a status reads the same color in both places.
STATUS_COLOR = {
    "QUEUED": "#8a3ffc",
    "PENDING": "#f0ad4e",
    "RUNNING": "#5bc0de",
}
# Text color for a label drawn on top of a STATUS_COLOR segment, matching the badges' own choice
# of dark text on the lighter PENDING/RUNNING backgrounds.
STATUS_TEXT_COLOR = {
    "QUEUED": "#ffffff",
    "PENDING": "#1c1c1c",
    "RUNNING": "#1c1c1c",
}
OUTCOME_LABEL = {
    "SUCCEEDED": ("SUCCEEDED", "#00aa00"),
    "FAILED": ("FAILED", "#cc0000"),
    "STOPPED": ("STOPPED", "#888888"),
}
# Filler jobs (Job.filler) get a hatched overlay on their segments (see FILLER_HATCH_PATTERN below)
# and their texts in this grey instead of the usual status/outcome colors, so they read as
# "not real demand" at a glance without needing a separate legend row per status.
FILLER_TEXT_COLOR = "#888888"
FILLER_HATCH_PATTERN = (
    '<defs><pattern id="qs-filler-hatch" width="6" height="6" patternUnits="userSpaceOnUse" '
    'patternTransform="rotate(45)">'
    '<line x1="0" y1="0" x2="0" y2="6" stroke="#525252" stroke-width="3" stroke-opacity="0.55"/>'
    "</pattern></defs>"
)


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
                "runner": job.runner,
                "filler": job.filler,
                "profile": job.compute_profile_id or "-",
                "created": job.created,
                "updated": job.updated,
                "running_started_at": job.running_started_at,
                "status_events": status_events,
                "author": job.author.username,
                "business_model": job.business_model or "-",
                "account_id": job.account_id or "-",
                "instance_crn": job.instance_crn or "-",
                "fleet_id": job.fleet_id or "-",
                "ce_project_name": job.ce_project_name or "-",
                "ce_region": job.ce_region or "-",
            }
        )
    return jobs


def compute_timeline(job):
    """Compute timeline segments and timestamps from job events."""
    events = sorted(job["status_events"], key=lambda e: e[0])

    # unique points in chronological order: (time the status was reached, status)
    seen = set()
    points = []
    if "QUEUED" not in {st for _, st in events} and job["created"]:
        points.append((job["created"], "QUEUED"))
        seen.add("QUEUED")
    for ts, st in events:
        if st not in seen:
            seen.add(st)
            points.append((ts, st))

    # a job that has not finished yet is still in its last known status, so close its timeline
    # at "now": segments are built between consecutive points, and without this the current
    # status would get no segment, no duration and no weight in the concurrency chart. The
    # comparison keeps the points in chronological order if an event carries a future timestamp.
    now = timezone.now()
    if points and job["status"] not in Job.TERMINAL_STATUSES and now > points[-1][0]:
        points.append((now, job["status"]))

    job["points"] = points
    # segments [start, end) colored by the status in force during the segment
    job["segments"] = [(points[i][0], points[i + 1][0], points[i][1]) for i in range(len(points) - 1)]

    durations = {}
    for seg_start, seg_end, seg_status in job["segments"]:
        durations[seg_status] = durations.get(seg_status, 0.0) + (seg_end - seg_start).total_seconds()
    job["durations"] = durations

    # first occurrence wins: the synthetic "now" point above repeats the current status, and the
    # time a status was reached is the time of its first point, never of that repetition
    by_status = {}
    for ts, status in points:
        by_status.setdefault(status, ts)
    job["t_queue"] = by_status.get("QUEUED", job["created"])
    job["t_run"] = by_status.get("RUNNING", job["running_started_at"])
    job["t_end"] = points[-1][0] if points else job["updated"]
    return job


def sort_jobs(jobs):
    """Sort jobs by creation date, oldest first."""
    return sorted(jobs, key=lambda j: j["created"])


def find_overlaps(jobs):
    """For every job with a RUNNING segment, how many other jobs overlap that segment.

    Only jobs on the same runner can overlap: Ray and Fleets run on separate infrastructure, so
    two jobs racing on different runners are not a real resource conflict. A job whose running
    window is not a forward interval (inconsistent data, e.g. a `running_started_at` later than
    the job's last event) is left out instead of corrupting the overlap math.
    """
    running = [j for j in jobs if j["t_run"] and j["t_end"] and j["t_run"] < j["t_end"]]
    overlaps = {j["id"]: set() for j in running}
    for i, a in enumerate(running):
        for b in running[i + 1 :]:
            if a["runner"] != b["runner"]:
                continue
            if a["t_run"] < b["t_end"] and b["t_run"] < a["t_end"]:
                overlaps[a["id"]].add(b["id"])
                overlaps[b["id"]].add(a["id"])
    return overlaps


def concurrency_series(jobs):
    """Step series (time, number of jobs RUNNING at the same time).

    Jobs without a forward running window are skipped, so a bad timestamp cannot push the
    count below zero.
    """
    points = []
    for j in jobs:
        if j["t_run"] and j["t_end"] and j["t_run"] < j["t_end"]:
            points.append((j["t_run"], 1))
            points.append((j["t_end"], -1))
    points.sort(key=lambda p: p[0])
    series = []
    running = 0
    for ts, delta in points:
        running += delta
        series.append((ts, running))
    return series


def _merge_series_max(series_list):
    """Combine several step series into one, taking the max value across them at every timestamp.

    Used to combine per-runner concurrency series into a single curve: Ray and Fleets run on
    separate infrastructure (the same rule `find_overlaps` already applies), so a job on one
    runner never contends with a job on the other, and their counts must never be added
    together. Comparing them instant-by-instant instead keeps the concurrency chart's "peak
    overlap" consistent with the per-job overlap badges, which also never count cross-runner
    pairs.
    """
    if not series_list:
        return []
    events = sorted(
        ((ts, idx, count) for idx, series in enumerate(series_list) for ts, count in series),
        key=lambda e: e[0],
    )
    current = [0] * len(series_list)
    merged = []
    for ts, idx, count in events:
        current[idx] = count
        merged.append((ts, max(current)))
    return merged


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


def build_concurrency_path(series, t_min, t_max, x, cy):
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


def build_svg(jobs, overlaps):  # pylint: disable=too-many-locals,too-many-statements,too-many-branches
    """Build SVG timeline visualization."""
    margin_left, margin_right = 260, 260
    margin_top, margin_bottom = 20, 60
    row_h = 16
    row_gap = 3
    chart_w = 2200
    concurrency_h = 90

    all_starts = [j["t_queue"] for j in jobs if j["t_queue"]]
    all_ends = [j["t_end"] for j in jobs if j["t_end"]]
    # the real bounds of the selected jobs, returned as-is for the "range X to Y" display text
    real_t_min = min(all_starts)
    real_t_max = max(all_ends)
    span = (real_t_max - real_t_min).total_seconds() or 1
    pad = span * 0.02
    # the chart itself gets a little breathing room on each side; this padded range drives the
    # chart geometry only, never the displayed range text
    t_min = real_t_min - timedelta(seconds=pad)
    t_max = real_t_max + timedelta(seconds=pad)
    span = (t_max - t_min).total_seconds()

    def x(dt):
        return margin_left + (dt - t_min).total_seconds() / span * chart_w

    jobs_sorted = sort_jobs(jobs)
    n = len(jobs_sorted)
    gantt_h = n * (row_h + row_gap)
    total_h = margin_top + concurrency_h + 30 + gantt_h + margin_bottom
    total_w = margin_left + chart_w + margin_right

    profiles = sorted({j["profile"] for j in jobs})

    # the hover cursor needs the chart geometry and time range in the browser; the datetimes
    # travel as "plain" UTC milliseconds so that no browser time zone shifts the hour shown
    t_min_ms = calendar.timegm(t_min.timetuple()) * 1000 + t_min.microsecond // 1000
    span_ms = span * 1000

    svg = []
    svg.append(
        f'<svg id="timeline-svg" width="{total_w}" height="{total_h}" viewBox="0 0 {total_w} {total_h}" '
        f'data-margin-left="{margin_left}" data-chart-w="{chart_w}" '
        f'data-t-min-ms="{t_min_ms}" data-span-ms="{span_ms}" '
        f'xmlns="http://www.w3.org/2000/svg" font-family="ui-monospace, Menlo, monospace" font-size="10">'
    )
    svg.append(FILLER_HATCH_PATTERN)
    svg.append(f'<rect x="0" y="0" width="{total_w}" height="{total_h}" class="qs-svg-bg"/>')

    top_of_chart = margin_top
    bottom_of_gantt = margin_top + concurrency_h + 30 + gantt_h

    # --- very faint lines, one per exact hour ---
    # the loop below is driven by wall-clock span, not by job count, so a selection spanning
    # weeks/months (still well within MAX_TIMELINE_JOBS) could otherwise emit thousands of lines;
    # widen the step so the total stays bounded regardless of how wide the selection is
    total_hours = max(span / 3600, 1)
    hour_step = max(1, int(total_hours // 500) + 1)
    hour = t_min.replace(minute=0, second=0, microsecond=0)
    if hour < t_min:
        hour += timedelta(hours=1)
    while hour <= t_max:
        hx = x(hour)
        svg.append(
            f'<line x1="{hx:.1f}" y1="{top_of_chart}" x2="{hx:.1f}" y2="{bottom_of_gantt}" '
            f'class="qs-hour-line" stroke-width="0.5" opacity="0.06"/>'
        )
        hour += timedelta(hours=hour_step)

    # --- time gridlines (shared by both charts) ---
    n_ticks = 16
    tick_step = span / n_ticks
    for i in range(n_ticks + 1):
        t = t_min + timedelta(seconds=tick_step * i)
        xx = x(t)
        svg.append(
            f'<line x1="{xx:.1f}" y1="{top_of_chart}" x2="{xx:.1f}" y2="{bottom_of_gantt}" '
            f'class="qs-grid-line" stroke-width="1"/>'
        )
        svg.append(
            f'<text x="{xx:.1f}" y="{bottom_of_gantt + 14}" class="qs-muted-text" '
            f'text-anchor="middle" transform="rotate(35 {xx:.1f} {bottom_of_gantt + 14})">'
            f"{html.escape(t.strftime('%d-%b %H:%M'))}</text>"
        )

    # --- concurrency chart (overlaps), one area for "All" plus one per compute profile ---
    # Ray and Fleets never contend for the same resource (see `find_overlaps`), so a runner's own
    # concurrency series is computed independently and merged with `_merge_series_max`, never by
    # summing counts across runners: that keeps this chart's "peak overlap" consistent with the
    # per-job overlap badges, which also never count a Ray/Fleets pair as overlapping. Note the
    # compute profile buttons pick which of these areas is shown, but the runner buttons only
    # filter the gantt rows below, so an area always reflects every runner in the selection.
    def cy(count, max_count):
        return margin_top + concurrency_h - (count / max_count) * (concurrency_h - 10)

    runners_present = sorted({j["runner"] for j in jobs_sorted})

    def runner_scoped_series(job_subset):
        return _merge_series_max(
            [concurrency_series([j for j in job_subset if j["runner"] == r]) for r in runners_present]
        )

    series_all = runner_scoped_series(jobs_sorted)
    real_max_conc = max((c for _, c in series_all), default=0)
    max_conc = real_max_conc or 1  # avoid a division by zero in cy() below; the heading uses real_max_conc

    svg.append(
        f'<text x="{margin_left}" y="{margin_top - 6}" class="qs-heading" font-weight="bold">'
        f"Concurrent RUNNING jobs (peak overlap: {real_max_conc})</text>"
    )

    def append_concurrency_area(job_subset, profile_attr, visible):
        """Draw one profile's concurrency area, with the filler jobs stacked at the bottom of it.

        Filler jobs hold the compute profile for real, so the area is the whole count, filler jobs
        included, and its top edge is the "peak overlap" in the heading. What a single area cannot
        say is how much of a peak is real demand, so the filler jobs' own count is drawn over the
        bottom of it with the hatch pattern the gantt bars use: below the hatch top edge the jobs
        are filler, above it they are real. A subset with no filler job gets the plain area alone,
        exactly as the chart looked before.
        """
        visible_class = " is-visible" if visible else ""
        total_path = build_concurrency_path(
            runner_scoped_series(job_subset), t_min, t_max, x, lambda c: cy(c, max_conc)
        )
        if total_path:
            svg.append(
                f'<path class="conc-path{visible_class}" data-profile="{profile_attr}" d="{total_path}" '
                f'fill="#3b82f6" opacity="0.35" stroke="#60a5fa" stroke-width="1.5"/>'
            )
        filler_path = build_concurrency_path(
            runner_scoped_series([j for j in job_subset if j["filler"]]),
            t_min,
            t_max,
            x,
            lambda c: cy(c, max_conc),
        )
        if filler_path:
            svg.append(
                f'<path class="conc-path{visible_class}" data-profile="{profile_attr}" d="{filler_path}" '
                f'fill="url(#qs-filler-hatch)" stroke="#60a5fa" stroke-width="1.5" stroke-dasharray="4 2"/>'
            )

    append_concurrency_area(jobs_sorted, "__all__", visible=True)
    for profile in profiles:
        append_concurrency_area(
            [j for j in jobs_sorted if j["profile"] == profile], html.escape(profile), visible=False
        )
    for c in range(0, max_conc + 1):
        yy = cy(c, max_conc)
        svg.append(f'<text x="{margin_left - 8}" y="{yy + 3:.1f}" class="qs-muted-text" text-anchor="end">{c}</text>')

    # --- gantt ---
    gantt_top = margin_top + concurrency_h + 30
    svg.append(
        f'<text x="{margin_left}" y="{gantt_top - 8}" class="qs-heading" font-weight="bold">'
        "Jobs sorted by start time (color = status during each segment)</text>"
    )

    for idx, job in enumerate(jobs_sorted):
        y = gantt_top + idx * (row_h + row_gap)
        cy_mid = y + row_h / 2
        short_id = job["id"][:8]
        overlap_ids = overlaps.get(job["id"], set())
        left_label = f"{short_id} · {job['profile']}"
        if overlap_ids:
            left_label += f"  ⧉{len(overlap_ids)}"

        d = job["durations"]
        total_dur = (job["t_end"] - job["t_queue"]).total_seconds() if job["t_queue"] and job["t_end"] else None
        # a job whose current status isn't a terminal one has no real outcome to show yet, so the
        # fallback just names that status again, in its own STATUS_COLOR rather than a generic gray
        outcome_text, outcome_color = OUTCOME_LABEL.get(
            job["status"], (job["status"], STATUS_COLOR.get(job["status"], "#94a3b8"))
        )
        if job["filler"]:
            outcome_color = FILLER_TEXT_COLOR

        tooltip = (
            f"job_id: {job['id']}\n"
            f"status: {job['status']}\n"
            f"compute_profile: {job['profile']}\n"
            f"queued: {fmt_dt(job['t_queue'])}\n"
            f"running: {fmt_dt(job['t_run'])}\n"
            f"end: {fmt_dt(job['t_end'])}\n"
            f"time in queue (QUEUED): {fmt_dur(d.get('QUEUED'))}\n"
            f"time in PENDING: {fmt_dur(d.get('PENDING'))}\n"
            f"time in RUNNING: {fmt_dur(d.get('RUNNING'))}\n"
            f"total time (queue included): {fmt_dur(total_dur)}\n"
            f"overlaps with {len(overlap_ids)} job(s)"
        )

        overlaps_attr = ",".join(html.escape(i) for i in overlap_ids)
        svg.append(
            f'<g class="job-row" data-profile="{html.escape(job["profile"])}" '
            f'data-runner="{html.escape(job["runner"])}" data-job-id="{html.escape(job["id"])}" '
            f'data-overlaps="{overlaps_attr}">'
        )
        # the tooltip has to be the first child of the group: SVG uses the first <title> it finds
        svg.append(f"<title>{html.escape(tooltip)}</title>")

        bar_end_x = x(job["t_queue"]) if job["t_queue"] else margin_left
        overflow_parts = []
        for seg_start, seg_end, seg_status in job["segments"]:
            sx1, sx2 = x(seg_start), x(seg_end)
            color = STATUS_COLOR.get(seg_status, "#64748b")
            svg.append(
                f'<rect x="{sx1:.1f}" y="{y}" width="{max(sx2 - sx1, 1.5):.1f}" height="{row_h}" '
                f'class="qs-seg-border qs-seg-{html.escape(seg_status.lower())}" fill="{color}"/>'
            )
            if job["filler"]:
                svg.append(
                    f'<rect x="{sx1:.1f}" y="{y}" width="{max(sx2 - sx1, 1.5):.1f}" height="{row_h}" '
                    f'fill="url(#qs-filler-hatch)" pointer-events="none"/>'
                )
            # the segment's own status and duration, drawn inside it when they fit; otherwise
            # they join the other segments that didn't fit in a summary drawn after the bar
            seg_time = fmt_dur((seg_end - seg_start).total_seconds())
            inline_text = f"{seg_status} {seg_time}"
            if len(inline_text) * 5.4 + 4 <= sx2 - sx1:
                seg_text_color = FILLER_TEXT_COLOR if job["filler"] else STATUS_TEXT_COLOR.get(seg_status, "#0b1020")
                svg.append(
                    f'<text x="{(sx1 + sx2) / 2:.1f}" y="{cy_mid + 3:.1f}" fill="{seg_text_color}" '
                    f'text-anchor="middle" font-size="9">{html.escape(inline_text)}</text>'
                )
            else:
                overflow_parts.append(f"{seg_status}: {seg_time}")
            bar_end_x = sx2

        svg.append(
            f'<text x="{margin_left - 10:.1f}" y="{cy_mid + 3:.1f}" class="qs-muted-text" text-anchor="end">'
            f"{html.escape(left_label)}</text>"
        )
        outside_prefix = f"{' - '.join(overflow_parts)}  " if overflow_parts else ""
        svg.append(
            f'<text x="{bar_end_x + 6:.1f}" y="{cy_mid + 3:.1f}" class="qs-fg-text" text-anchor="start">'
            f'{html.escape(outside_prefix)}<tspan fill="{outcome_color}" font-weight="bold">'
            f"{html.escape(outcome_text)}</tspan></text>"
        )
        svg.append("</g>")

    # --- hover cursor: thin vertical bar plus a label with the time under the pointer ---
    svg.append(
        '<g id="hover-cursor" pointer-events="none">'
        f'<rect id="hover-cursor-bar" x="0" y="{top_of_chart}" width="2" '
        f'height="{bottom_of_gantt - top_of_chart}" fill="#93c5fd" opacity="0.35"/>'
        f'<rect id="hover-cursor-label-bg" x="0" y="{top_of_chart - 16}" width="1" height="14" '
        f'rx="3" class="qs-panel-bg"/>'
        f'<text id="hover-cursor-label" x="0" y="{top_of_chart - 6}" class="qs-fg-text" text-anchor="middle">'
        "</text>"
        "</g>"
    )

    svg.append("</svg>")
    return "\n".join(svg), real_t_min, real_t_max, profiles


def build_legend():
    """Build HTML legend for timeline colors.

    The swatch colors live in `admin/css/job_timeline.css` (one class per swatch), because the
    Content Security Policy of this project rejects inline `style` attributes. Keep those classes
    in sync with `STATUS_COLOR` and `OUTCOME_LABEL`.
    """
    parts = []
    for label in ("QUEUED", "PENDING", "RUNNING"):
        swatch = f'<span class="qs-swatch qs-swatch--{label.lower()}"></span>'
        parts.append(f'<span class="qs-legend-item">{swatch}{html.escape(label)}</span>')
    for outcome_status, (text, _color) in OUTCOME_LABEL.items():
        parts.append(
            f'<span class="qs-legend-item qs-outcome qs-outcome--{outcome_status.lower()}">'
            f"{html.escape(text)}</span>"
        )
    parts.append('<span class="qs-legend-item"><span class="qs-swatch qs-swatch--filler"></span>Filler job</span>')
    parts.append('<span class="qs-legend-item">⧉N = overlaps N other jobs, click a job to see which</span>')
    return "".join(parts)


def _detail_rows(pairs):
    """Render a label/value pair per row for a job details panel, escaping every value."""
    return "".join(
        f'<div class="qs-detail-row"><span class="qs-detail-label">{html.escape(label)}</span>'
        f'<span class="qs-detail-value">{html.escape(value)}</span></div>'
        for label, value in pairs
    )


def build_job_details(jobs):
    """Build one hidden details panel per job, shown by `job_timeline.js` on click.

    Starts with a placeholder panel (visible until a job row is clicked) plus one panel per job,
    each carrying the job's id in `data-job-id` so the click handler can match it to the row.
    """
    panels = [
        '<div class="qs-job-details is-visible" data-placeholder="1">'
        "Click a job in the chart to see its details.</div>"
    ]
    for job in jobs:
        main_rows = _detail_rows(
            [
                ("id", job["id"]),
                ("author", job["author"]),
                ("business model", job["business_model"]),
                ("account id", job["account_id"]),
                ("instance crn", job["instance_crn"]),
            ]
        )
        fleets_rows = _detail_rows(
            [
                ("filler", "yes" if job["filler"] else "no"),
                ("fleet id", job["fleet_id"]),
                ("compute profile", job["profile"]),
                ("ce project name", job["ce_project_name"]),
                ("region", job["ce_region"]),
            ]
        )
        panels.append(
            f'<div class="qs-job-details" data-job-id="{html.escape(job["id"])}">'
            f"<h3>Job</h3>{main_rows}"
            f"<h3>Fleets</h3>{fleets_rows}"
            "</div>"
        )
    return "".join(panels)


def build_filter_bar(profiles):
    """Build HTML filter buttons for compute profiles."""
    buttons = ['<button class="filter-btn active" data-profile="__all__">All</button>']
    for p in profiles:
        buttons.append(f'<button class="filter-btn" data-profile="{html.escape(p)}">{html.escape(p)}</button>')
    return "".join(buttons)


def build_runner_filter_bar(runners):
    """Build HTML filter buttons for the runner (ray/fleets)."""
    buttons = ['<button class="filter-btn active" data-runner="__all__">All</button>']
    for r in runners:
        buttons.append(f'<button class="filter-btn" data-runner="{html.escape(r)}">{html.escape(r.title())}</button>')
    return "".join(buttons)


def render_job_timeline(jobs_qs):
    """Build the full template context for the Job Timeline admin page.

    `jobs_qs` must be non-empty; the empty-selection case is the caller's responsibility
    (see `JobAdmin.job_timeline_view`), so this function does not special-case it.
    """
    jobs = [compute_timeline(j) for j in _jobs_from_queryset(jobs_qs)]
    overlaps = find_overlaps(jobs)
    svg, t_min, t_max, profiles = build_svg(jobs, overlaps)
    runners = sorted({j["runner"] for j in jobs})
    return {
        "timeline_jobs_count": len(jobs),
        "timeline_range": f"{fmt_dt(t_min)} to {fmt_dt(t_max)}",
        "timeline_svg": mark_safe(svg),
        "timeline_legend": mark_safe(build_legend()),
        "timeline_filter_bar": mark_safe(build_filter_bar(profiles)),
        "timeline_runner_filter_bar": mark_safe(build_runner_filter_bar(runners)),
        "timeline_job_details": mark_safe(build_job_details(jobs)),
    }
