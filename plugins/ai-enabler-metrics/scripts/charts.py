#!/usr/bin/env python3
"""Self-contained HTML reports with inline SVG charts. No dependencies, no JavaScript.

Used by usage_report.py and the delivery-flow reports. A report is a list of
blocks (tiles, charts, tables, notes) rendered into one HTML file that works
offline, in light and dark mode, and when printed.

Chart conventions
- One hue for a single series; categorical hues in a fixed order for several.
- Thin bars with a rounded data end, one baseline, hairline grid, values in
  text colour (never in the series colour).
- Every mark carries a native tooltip (<title>) with its exact value.
- A bucket with too little data is drawn faded and says so in its tooltip.
- Every chart is followed or accompanied by a table, so no value is only a colour.
"""

import html
import math

# Categorical order is fixed: a series keeps its colour whatever else is shown.
SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]

CSS = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);--good:#0ca30c;--warn:#fab219;--crit:#d03b3b;
%(light)s}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--page:#0d0d0d;
--surface:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;
--border:rgba(255,255,255,.10);%(dark)s}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;
--muted:#898781;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);%(dark)s}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1120px;margin:0 auto;padding:32px 16px 72px}
h1{font-size:28px;line-height:1.2;margin:0 0 6px}
h2{font-size:19px;margin:44px 0 4px;padding-top:14px;border-top:1px solid var(--grid)}
h3{font-size:14px;margin:0 0 2px;font-weight:600}
.meta{color:var(--ink2);font-size:13px;margin:0}
.note{color:var(--ink2);font-size:13px;max-width:78ch;margin:4px 0 12px}
.lede{font-size:15px;max-width:78ch;margin:14px 0 0}
.lede li{margin:4px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:12px;margin:22px 0 4px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.tile b{display:block;font-size:26px;line-height:1.15;font-weight:600}
.tile span{display:block;color:var(--ink2);font-size:12px;margin-top:2px}
.tile small{display:block;color:var(--muted);font-size:11px;margin-top:4px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%%,440px),1fr));gap:14px;margin:14px 0}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px 16px 10px;min-width:0}
.card .sub{color:var(--ink2);font-size:12px;margin:0 0 8px}
svg{display:block;width:100%%;max-width:620px;height:auto;overflow:visible}
svg text{font:11px system-ui,-apple-system,"Segoe UI",sans-serif;fill:var(--ink2)}
svg .val{fill:var(--ink);font-weight:600}
svg .tick{fill:var(--muted)}
svg .lbl{fill:var(--ink)}
svg .low{opacity:.6}
svg rect.bar:hover,svg path.bar:hover{filter:brightness(1.12)}
.legend{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px;color:var(--ink2);margin:6px 0 2px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.legend .faded i{opacity:.6}
.wrap{overflow-x:auto;background:var(--surface);border:1px solid var(--border);border-radius:10px;margin:12px 0}
table{border-collapse:collapse;width:100%%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:7px 10px;text-align:left;border-bottom:1px solid var(--grid);white-space:nowrap}
td.num,th.num{text-align:right}
td:first-child{white-space:normal;min-width:118px}
table.wrapcells td{white-space:normal;vertical-align:top}table.wrapcells td:first-child{white-space:nowrap;font-weight:600}
th{color:var(--ink2);font-weight:600;font-size:12px}
tr:last-child td{border-bottom:0}
tr.low td{color:var(--muted)}
.flag{display:inline-block;font-size:11px;border:1px solid var(--border);border-radius:99px;padding:0 7px;color:var(--ink2);margin-left:6px}
details{margin:10px 0}summary{cursor:pointer;color:var(--ink2);font-size:13px}
footer{margin-top:48px;color:var(--muted);font-size:12px}
a{color:var(--ink);text-decoration:underline;text-underline-offset:2px}
@media print{body{background:#fff}.card,.tile,.wrap{break-inside:avoid}}
""" % {
    "light": "".join("--s%d:%s;" % (i + 1, c) for i, c in enumerate(SERIES_LIGHT)),
    "dark": "".join("--s%d:%s;" % (i + 1, c) for i, c in enumerate(SERIES_DARK)),
}

e = html.escape


def series_color(i):
    return "var(--s%d)" % (i % len(SERIES_LIGHT) + 1)


def nice_max(value):
    """A round axis maximum at or above `value`."""
    if value <= 0:
        return 1.0
    exp = math.floor(math.log10(value))
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if value <= m * 10 ** exp * 1.0000001:
            return m * 10 ** exp
    return 10 ** (exp + 1)


def fmt_num(v, digits=None):
    if v is None:
        return "–"
    if digits is None:
        digits = 0 if abs(v) >= 100 or float(v).is_integer() else 1
    s = "{:,.{d}f}".format(v, d=digits)
    return s


def _bar_path(x, y, w, h, r, horizontal=False):
    """A bar square at the baseline and rounded at the data end."""
    r = max(0.0, min(r, w / 2.0, h / 2.0) if not horizontal else min(r, h / 2.0, w / 2.0))
    if horizontal:   # grows to the right from x
        return ("M%.1f,%.1f h%.1f a%.1f,%.1f 0 0 1 %.1f,%.1f v%.1f a%.1f,%.1f 0 0 1 -%.1f,%.1f h-%.1f z"
                % (x, y, w - r, r, r, r, r, h - 2 * r, r, r, r, r, w - r))
    return ("M%.1f,%.1f v-%.1f a%.1f,%.1f 0 0 1 %.1f,-%.1f h%.1f a%.1f,%.1f 0 0 1 %.1f,%.1f v%.1f z"
            % (x, y + h, h - r, r, r, r, r, w - 2 * r, r, r, r, r, h - r))


def columns(points, unit="", height=230, color_index=0, digits=None):
    """Vertical bars, one per category (weeks, sprints).

    points: [{"label", "value", "low": bool, "n": text, "lo", "hi", "tip"}]
    `lo`/`hi` draw a confidence whisker; `low` fades the bar.
    """
    pts = [p for p in points if p.get("value") is not None]
    if not pts:
        return "<p class='note'>No data.</p>"
    width, left, right, top, bottom = 560, 44, 12, 22, 44
    plot_w, plot_h = width - left - right, height - top - bottom
    # The axis follows the bars. A confidence whisker far above every bar would
    # flatten them all, so it is clipped at the top of the plot and marked.
    tallest = max(p["value"] for p in pts)
    top_value = max(max(p["value"], p.get("hi") or 0) for p in pts)
    ymax = nice_max(min(top_value, max(tallest * 3.0, 1e-9)) if tallest > 0 else top_value)
    slot = plot_w / len(points)
    bar_w = min(24.0, slot * 0.6)
    out = ["<svg viewBox='0 0 %d %d' role='img'>" % (width, height)]
    step = ymax / 4.0
    tick_digits = 0
    while tick_digits < 4 and abs(step * 10 ** tick_digits - round(step * 10 ** tick_digits)) > 1e-9:
        tick_digits += 1    # as many decimals as the gridline values really have
    for i in range(5):
        v = ymax * i / 4
        y = top + plot_h - plot_h * i / 4
        out.append("<line x1='%d' x2='%d' y1='%.1f' y2='%.1f' stroke='var(--%s)' stroke-width='1'/>"
                   % (left, width - right, y, y, "axis" if i == 0 else "grid"))
        out.append("<text class='tick' x='%d' y='%.1f' text-anchor='end'>%s</text>"
                   % (left - 6, y + 4, e(fmt_num(v, tick_digits))))
    for i, p in enumerate(points):
        cx = left + slot * (i + 0.5)
        label = str(p["label"])
        out.append("<text class='tick' x='%.1f' y='%d' text-anchor='middle'>%s</text>"
                   % (cx, height - bottom + 15, e(label)))
        if p.get("n"):
            out.append("<text class='tick' x='%.1f' y='%d' text-anchor='middle'>%s</text>"
                       % (cx, height - bottom + 29, e(str(p["n"]))))
        if p.get("value") is None:
            continue
        h = plot_h * p["value"] / ymax
        y = top + plot_h - h
        tip = p.get("tip") or "%s: %s %s" % (label, fmt_num(p["value"], digits), unit)
        if p.get("low"):
            tip += " — little data, read with care"
        out.append("<path class='bar%s' d='%s' fill='%s'><title>%s</title></path>"
                   % (" low" if p.get("low") else "", _bar_path(cx - bar_w / 2, y, bar_w, max(h, 0.5), 4),
                      series_color(color_index), e(tip)))
        if p.get("lo") is not None and p.get("hi") is not None:
            clipped = p["hi"] > ymax
            y1 = top + plot_h - plot_h * min(p["hi"], ymax) / ymax
            y2 = top + plot_h - plot_h * min(p["lo"], ymax) / ymax
            cap = ("<path d='M%.1f,%.1f l4,6 h-8 z' fill='var(--ink2)' stroke='none'/>" % (cx, y1 - 5) if clipped
                   else "<line x1='%.1f' x2='%.1f' y1='%.1f' y2='%.1f'/>" % (cx - 4, cx + 4, y1, y1))
            out.append("<g stroke='var(--ink2)' stroke-width='1.5'><line x1='%.1f' x2='%.1f' y1='%.1f' y2='%.1f'/>"
                       "%s<line x1='%.1f' x2='%.1f' y1='%.1f' y2='%.1f'/><title>%s</title></g>"
                       % (cx, cx, y1, y2, cap, cx - 4, cx + 4, y2, y2,
                          e("90 %% CI %s – %s %s%s" % (fmt_num(p["lo"], digits), fmt_num(p["hi"], digits), unit,
                                                      " (runs past the top of the chart)" if clipped else ""))))
        if len(points) <= 14:
            ly = (top + plot_h - plot_h * min(p["hi"], ymax) / ymax - 6 if p.get("hi") is not None else y) - 5
            out.append("<text class='val' x='%.1f' y='%.1f' text-anchor='middle'>%s</text>"
                       % (cx, max(ly, 10), e(fmt_num(p["value"], digits))))
    out.append("</svg>")
    return "".join(out)


def hbars(rows, unit="", color_index=0, digits=None, max_rows=20):
    """Horizontal bars, one per name (developer, area, agent), already sorted.

    rows: [{"label", "value", "note": text right of the value, "low": bool, "tip"}]
    """
    rows = [r for r in rows if r.get("value") is not None][:max_rows]
    if not rows:
        return "<p class='note'>No data.</p>"
    width, row_h, bar_h, top = 560, 28, 14, 6
    label_w = min(220, 14 + 6.4 * max(len(str(r["label"])) for r in rows))
    value_w = 150
    plot_w = width - label_w - value_w
    xmax = nice_max(max(r["value"] for r in rows))
    height = top + row_h * len(rows) + 4
    out = ["<svg viewBox='0 0 %d %d' role='img'>" % (width, height),
           "<line x1='%.1f' x2='%.1f' y1='%d' y2='%d' stroke='var(--axis)' stroke-width='1'/>"
           % (label_w, label_w, top, height - 4)]
    for i, r in enumerate(rows):
        y = top + row_h * i + (row_h - bar_h) / 2
        w = max(plot_w * r["value"] / xmax, 1.0)
        tip = r.get("tip") or "%s: %s %s" % (r["label"], fmt_num(r["value"], digits), unit)
        if r.get("low"):
            tip += " — little data, read with care"
        label = str(r["label"])
        if len(label) > 32:
            label = label[:31] + "…"
        out.append("<text class='lbl' x='%.1f' y='%.1f' text-anchor='end'>%s</text>"
                   % (label_w - 8, y + bar_h - 3, e(label)))
        out.append("<path class='bar%s' d='%s' fill='%s'><title>%s</title></path>"
                   % (" low" if r.get("low") else "", _bar_path(label_w, y, w, bar_h, 4, horizontal=True),
                      series_color(color_index), e(tip)))
        text = "%s %s" % (fmt_num(r["value"], digits), unit)
        out.append("<text x='%.1f' y='%.1f'><tspan class='val'>%s</tspan>%s</text>"
                   % (label_w + w + 6, y + bar_h - 3, e(text.strip()),
                      " <tspan class='tick'> · %s</tspan>" % e(str(r["note"])) if r.get("note") else ""))
    out.append("</svg>")
    return "".join(out)


def stacked(rows, series, unit="", normalize=False, digits=None):
    """Horizontal stacked bars: a few parts of a whole, per row.

    rows: [{"label", "values": [v per series], "low": bool}]; series: [names].
    """
    rows = [r for r in rows if sum(v or 0 for v in r["values"]) > 0]
    if not rows:
        return "<p class='note'>No data.</p>"
    width, row_h, bar_h, top = 560, 30, 16, 4
    label_w = min(200, 14 + 6.4 * max(len(str(r["label"])) for r in rows))
    total_w = 86
    plot_w = width - label_w - total_w
    xmax = 1.0 if normalize else nice_max(max(sum(v or 0 for v in r["values"]) for r in rows))
    height = top + row_h * len(rows) + 2
    out = ["<svg viewBox='0 0 %d %d' role='img'>" % (width, height)]
    for i, r in enumerate(rows):
        y = top + row_h * i + (row_h - bar_h) / 2
        total = sum(v or 0 for v in r["values"])
        out.append("<text class='lbl' x='%.1f' y='%.1f' text-anchor='end'>%s</text>"
                   % (label_w - 8, y + bar_h - 4, e(str(r["label"]))))
        x = label_w
        for k, v in enumerate(r["values"]):
            if not v:
                continue
            share = v / total
            w = plot_w * (share if normalize else v / xmax)
            tip = "%s — %s: %s %s (%d%%)" % (r["label"], series[k], fmt_num(v, digits), unit, round(share * 100))
            # A 2px gap in the surface colour separates touching segments.
            out.append("<rect class='bar%s' x='%.1f' y='%.1f' width='%.1f' height='%d' fill='%s'><title>%s</title></rect>"
                       % (" low" if r.get("low") else "", x, y, max(w - 2, 0.5), bar_h, series_color(k), e(tip)))
            x += w
        out.append("<text class='val' x='%.1f' y='%.1f'>%s</text>"
                   % (x + 4, y + bar_h - 4, e(("%s %s" % (fmt_num(total, digits), unit)).strip())))
    out.append("</svg>")
    legend = "".join("<span><i style='background:%s'></i>%s</span>" % (series_color(k), e(s))
                     for k, s in enumerate(series))
    return "".join(out) + "<div class='legend'>%s</div>" % legend


# ------------------------------------------------------------------- blocks

def tiles(items):
    """items: [(label, value, small note or None)]"""
    return "<div class='tiles'>%s</div>" % "".join(
        "<div class='tile'><b>%s</b><span>%s</span>%s</div>"
        % (e(str(v)), e(str(k)), "<small>%s</small>" % e(str(n)) if n else "") for k, v, n in items)


def card(title, body, sub=None):
    return "<div class='card'><h3>%s</h3>%s%s</div>" % (
        e(title), "<p class='sub'>%s</p>" % e(sub) if sub else "", body)


def grid(*cards):
    return "<div class='grid2'>%s</div>" % "".join(c for c in cards if c)


def table(headers, rows, numeric=(), low_rows=(), wrap=False):
    """rows: lists of cells; `numeric` column indexes are right-aligned."""
    if not rows:
        return "<p class='note'>No data.</p>"
    head = "".join("<th%s>%s</th>" % (" class='num'" if i in numeric else "", e(str(h)))
                   for i, h in enumerate(headers))
    body = []
    for r, row in enumerate(rows):
        cells = "".join("<td%s>%s</td>" % (" class='num'" if i in numeric else "", e(str(c)))
                        for i, c in enumerate(row))
        body.append("<tr%s>%s</tr>" % (" class='low'" if r in low_rows else "", cells))
    return "<div class='wrap'><table%s><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>" % (
        " class='wrapcells'" if wrap else "", head, "".join(body))


def section(title, *parts, note=None):
    return "<h2>%s</h2>%s%s" % (e(title), "<p class='note'>%s</p>" % e(note) if note else "",
                                "".join(p for p in parts if p))


def bullets(items):
    items = [i for i in items if i]
    return "<ul class='lede'>%s</ul>" % "".join("<li>%s</li>" % e(i) for i in items) if items else ""


def definitions(pairs):
    return "<details open><summary>Definitions</summary>%s</details>" % table(
        ["Term", "Meaning"], [[k, v] for k, v in pairs], wrap=True)


def collapsible(summary, body):
    return "<details><summary>%s</summary>%s</details>" % (e(summary), body)


def page(title, meta, *parts, footer=None):
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>%s</title><style>%s</style></head><body><main><h1>%s</h1><p class='meta'>%s</p>%s"
            "<footer>%s</footer></main></body></html>"
            % (e(title), CSS, e(title), " · ".join(e(str(m)) for m in meta if m),
               "".join(p for p in parts if p), e(footer or "")))
