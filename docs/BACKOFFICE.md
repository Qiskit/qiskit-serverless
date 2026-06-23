# Job Admin Pages

The backoffice is at `/backoffice/` (not `/admin/`), configured in `main/urls.py`.

## Pages and URLs

Each job has four sub-pages reachable via tab navigation:

| Tab | URL | Template |
|-----|-----|----------|
| Edit Job | `/backoffice/api/job/<id>/change/` | `admin/api/job/change_form.html` |
| Events | `/backoffice/api/job/<id>/events/` | `admin/api/job/events.html` |
| Storage Files | `/backoffice/api/job/<id>/files/` | `admin/api/job/files.html` |
| History | `/backoffice/api/job/<id>/history/` | `admin/api/job/object_history.html` |

Edit Job and History are standard Django admin views. Events and Storage Files are custom views registered in `JobAdmin.get_urls()`.

## Files

```
gateway/
  api/
    admin.py                          # JobAdmin, JobEventInline, custom views
    static/admin/css/
      job_admin.css                   # tabs + subtitle styles (Carbon vars)
      admin_job_event_inline.css      # event badges + JSON block styles
  templates/admin/api/job/
    change_form.html                  # extends admin/change_form.html
    events.html                       # extends admin/base_site.html
    files.html                        # extends admin/base_site.html
    object_history.html               # extends admin/object_history.html
    _job_subtitle.html                # shared include: program/runner/id/author line
```

## Tab Navigation

All four pages share the same `div.job-nav` with four `<a>` links. The active tab has `class="active"` and no `href`. The CSS (`job_admin.css`) uses Carbon Design System variables:

- Inactive: `border: 1px solid var(--object-tools-fg, #0f62fe)`, transparent background
- Active/hover: `background: var(--object-tools-hover-bg, #0f62fe)`, white text

The subtitle line below the tabs comes from `{% include "admin/api/job/_job_subtitle.html" with job_instance=<var> %}`. The variable name differs per page: `job` (Events, Files), `object` (History), `original` (Edit Job).

### Adding a new tab

1. Register a URL in `JobAdmin.get_urls()` using `<path:job_id>/` (not `<uuid:>`).
2. Add a view method on `JobAdmin`, wrap it with `self.admin_site.admin_view(...)`.
3. Pass `**self.admin_site.each_context(request)`, `"job"`, `"opts"`, `"app_label"` in context.
4. Create a template extending `admin/base_site.html`; copy the `job-nav` block from another page and set `class="active"` on the new tab.
5. Add the new `<a href="...">` to all four existing templates.

## CSS Constraint: no inline `<style>`

The server sends `Content-Security-Policy: style-src-elem 'self'`, which blocks all inline `<style>` tags. All CSS must be in static files loaded via `<link rel="stylesheet">` inside `{% block extrastyle %}`.

## Django Admin Template Blocks

- `change_form.html`: overrides `object-tools` (tab nav), `content_subtitle` (hidden), `extrastyle` (CSS).
- `object_history.html`: overrides `content` (prepends nav before `{{ block.super }}`), `content_title` (shows "Change history" without the job repr), `extrastyle`.
- `files.html` / `events.html`: full custom `content` block, `extrastyle`.

Django automatically picks up `admin/api/job/object_history.html` for the history view based on `admin/<app_label>/<model_name>/object_history.html` lookup order. No override needed in `admin.py`.

## Key Models

```python
Job
  .id             # UUID primary key
  .runner         # "ray" | "fleets"  -- get_runner_display() -> "Ray" | "Fleets"
  .program        # FK to Program (null=True); None for custom jobs
  .author         # FK to User
  .job_events     # reverse relation to JobEvent (related_name="job_events")

Program
  .title          # str
  .provider       # FK to Provider (null=True); None for custom/user-owned functions
  .__str__()      # returns "provider.name/title" if provider, else title

JobEvent
  .event_type     # JobEventType str enum: STATUS_CHANGE, SUB_STATUS_CHANGE, ...
  .data           # JSONField; for STATUS_CHANGE: {"status": "STOPPED"}, etc.
  .origin         # e.g. "API", "BACKOFFICE"
  .context        # e.g. "RUN_PROGRAM", "SAVE_MODEL"
  .created        # datetime
```

Job subtitle logic (in `_job_subtitle.html`):
- Has provider: `{provider.name}/{program.title} ({runner}) {id} by {author.username}`
- No provider or no program: `Custom job ({runner}) {id} by {author.username}`
