#!/usr/bin/env python3
import json
import os
import re
import shutil
import sys
from pathlib import Path
from datetime import datetime, timezone

GOLDEN_WARNING = "\033[38;5;179m"
RESET_COLOR = "\033[0m"


def slugify(ref: str) -> str:
    s = ref.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s[:63]).strip("-") or "ref"


def parse_lines_percent(summary_file: Path):
    if not summary_file.exists():
        return None
    for line in summary_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip().startswith("lines"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].endswith("%"):
                try:
                    return float(parts[1].strip("%"))
                except Exception:
                    return None
    return None


def load_manifest(path: Path):
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_manifest(path: Path, rows):
    path.write_text(json.dumps(rows, ensure_ascii=True, indent=2), encoding="utf-8")


def normalize_created_at(value: str) -> str:
    if not value:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return value


def load_coverage_targets_from_env():
    raw = os.environ.get("COVERAGE_TARGETS", "").strip()
    warnings = []
    valid = []

    if not raw:
        print("ERROR: COVERAGE_TARGETS env var is not set or empty.", file=sys.stderr)
        return valid, warnings

    try:
        parsed = json.loads(raw)
    except Exception as e:
        print(f"ERROR: COVERAGE_TARGETS is not valid JSON: {e}", file=sys.stderr)
        return valid, warnings

    if not isinstance(parsed, list):
        print("ERROR: COVERAGE_TARGETS must be a JSON array.", file=sys.stderr)
        return valid, warnings

    required = ("app", "name", "job_name")
    for i, item in enumerate(parsed):
        if not isinstance(item, dict):
            warnings.append(f"Target #{i + 1}: expected object, got {type(item).__name__}. Skipped.")
            continue
        missing = [k for k in required if not isinstance(item.get(k), str) or not item.get(k).strip()]
        if missing:
            warnings.append(f"Target #{i + 1}: missing/empty required fields: {', '.join(missing)}. Skipped.")
            continue
        valid.append(
            {
                "app": item["app"].strip(),
                "name": item["name"].strip(),
                "job_name": item["job_name"].strip(),
            }
        )
    return valid, warnings


def update_with_current_run(unit: str, unit_job_name: str, branch: str, commit: str, short: str, pipeline_id: str,
                            project_url: str, reports_dir: Path, manifests_dir: Path, created_at: str):
    src = Path(f"build/coverage_html_{unit_job_name}")
    if not (src / "index.html").exists():
        return

    slug = slugify(branch)
    dst = reports_dir / unit / slug / pipeline_id
    shutil.rmtree(dst, ignore_errors=True)
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)

    cov = parse_lines_percent(Path(f"build/coverage-summary_{unit_job_name}.txt"))
    manifest = manifests_dir / f"{unit}.json"
    rows = load_manifest(manifest)
    rows = [r for r in rows if not (r.get("branch") == branch and r.get("pipeline_id") == pipeline_id)]
    rows.append(
        {
            "branch": branch,
            "slug": slug,
            "commit": commit,
            "short": short,
            "pipeline_id": pipeline_id,
            "pipeline_url": f"{project_url}/-/pipelines/{pipeline_id}",
            "commit_url": f"{project_url}/-/commit/{commit}",
            "created_at": created_at,
            "coverage": cov,
            "report_dir": f"{unit}/{slug}/{pipeline_id}",
        }
    )
    save_manifest(manifest, rows)


def build_models(unit: str, reports_dir: Path, manifests_dir: Path, public_dir: Path):
    manifest = manifests_dir / f"{unit}.json"
    rows = load_manifest(manifest)
    valid = []

    for r in rows:
        report_dir = r.get("report_dir")
        if not report_dir:
            old = r.get("report_url", "")
            report_dir = old[:-11] if old.endswith("/index.html") else old
            r["report_dir"] = report_dir
        if not report_dir:
            continue

        src_dir = reports_dir / report_dir
        if not (src_dir / "index.html").exists():
            continue

        dst_dir = public_dir / report_dir
        dst_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)
        valid.append(r)

    save_manifest(manifest, valid)

    by_branch = {}
    for r in valid:
        by_branch.setdefault(r["branch"], []).append(r)

    latest_rows = []
    history_by_branch = {}
    for branch, arr in by_branch.items():
        arr.sort(key=lambda x: int(x.get("pipeline_id", 0)), reverse=True)
        history = []
        for i, row in enumerate(arr):
            current = dict(row)
            prev_cov = arr[i + 1].get("coverage") if i + 1 < len(arr) else None
            cov = current.get("coverage")
            current["prev"] = prev_cov
            current["diff"] = None if cov is None or prev_cov is None else cov - prev_cov
            history.append(current)
        history_by_branch[branch] = history

        latest = dict(arr[0])
        prev_cov = history[0].get("prev")
        cov = latest.get("coverage")
        latest["prev"] = prev_cov
        latest["diff"] = None if cov is None or prev_cov is None else cov - prev_cov
        latest_rows.append(latest)

    latest_rows.sort(key=lambda x: (x.get("coverage") is None, -(x.get("coverage") or 0.0), x.get("branch", "")))
    return latest_rows, history_by_branch


def fmt_cov(v):
    return "N/A" if v is None else f"{v:.2f}%"


def fmt_diff(v):
    if v is None:
        return "N/A"
    return f"{'+' if v >= 0 else ''}{v:.2f}%"


def render_unit_page(unit_name: str, nav_targets, rows, default_branch: str):
    master_latest = next((r for r in rows if r.get("branch") == default_branch), None)
    master_cov = master_latest.get("coverage") if master_latest else None
    master_pipeline_id = master_latest.get("pipeline_id") if master_latest else None
    lines = []
    for r in rows:
        branch_slug = slugify(r["branch"])
        vs_master = None if r.get("coverage") is None or master_cov is None else r["coverage"] - master_cov
        master_cell = f"{fmt_cov(master_cov)} (#{master_pipeline_id})" if master_pipeline_id else "N/A"
        lines.append(
            "<tr>"
            f"<td><a href='./branches/{branch_slug}/index.html'>{r['branch']}</a></td>"
            f"<td>{r.get('created_at', 'N/A')}</td>"
            f"<td><a href='{r['commit_url']}'>{r['short']}</a></td>"
            f"<td><a href='{r['pipeline_url']}'>#{r['pipeline_id']}</a></td>"
            f"<td><a href='../{r['report_dir']}/index.html'>Report</a></td>"
            f"<td>{fmt_cov(r['coverage'])}</td>"
            f"<td>{fmt_cov(r['prev'])}</td>"
            f"<td>{fmt_diff(r['diff'])}</td>"
            f"<td>{master_cell}</td>"
            f"<td>{fmt_diff(vs_master)}</td>"
            "</tr>"
        )

    nav_links = ['<a class="btn" href="../">Home</a>']
    for t in nav_targets:
        nav_links.append(f'<a class="btn" href="../{t["app"]}/">{t["name"]} Coverage</a>')

    return f"""<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>{unit_name} Coverage</title>
<style>
body{{font-family:ui-sans-serif,-apple-system,Segoe UI,Roboto,Arial;margin:24px;background:#0b1220;color:#e6edf7}}
.card{{max-width:1200px;margin:0 auto;border:1px solid #25314a;border-radius:14px;padding:20px;background:#111a2b}}
.muted{{color:#9fb0c9}} a{{color:#3ddc97;text-decoration:none;font-weight:700}} a:hover{{text-decoration:underline}}
.nav{{display:flex;gap:10px;flex-wrap:wrap;margin:8px 0 14px}} .btn{{display:inline-block;border:1px solid #25314a;border-radius:10px;padding:8px 12px;background:rgba(17,26,43,.65)}}
table{{width:100%;border-collapse:collapse;margin-top:14px}} th,td{{border-bottom:1px solid #25314a;padding:10px 8px;text-align:left}} th{{color:#9fb0c9;font-weight:600}}
th.sortable{{cursor:pointer}}
</style></head><body><div class=\"card\"><h1>{unit_name} Coverage</h1>
<div class=\"nav\">{''.join(nav_links)}</div>
<p class=\"muted\">Branches with available coverage reports. Click branch to open the collected report.</p>
<table id="summary-table"><thead><tr><th class="sortable" data-sort-type="string">Branch</th><th class="sortable" data-sort-type="date">Run Date</th><th>Commit</th><th>Pipeline</th><th>Report</th><th>Coverage</th><th>Prev</th><th>Diff</th><th>{default_branch}</th><th>Vs {default_branch}</th></tr></thead><tbody>
{''.join(lines) if lines else f'<tr><td colspan="10">No {unit_name} reports found.</td></tr>'}
</tbody></table></div>
<script>
(function(){{
  const table = document.getElementById("summary-table");
  if (!table) return;
  const tbody = table.tBodies[0];
  const dirs = {{}};
  function valueFromCell(cell, type) {{
    const raw = (cell.innerText || "").trim();
    if (type === "date") {{
      const t = Date.parse(raw);
      return Number.isNaN(t) ? -Infinity : t;
    }}
    return raw.toLowerCase();
  }}
  table.querySelectorAll("th.sortable").forEach((th, idx) => {{
    th.addEventListener("click", () => {{
      const type = th.dataset.sortType || "string";
      dirs[idx] = dirs[idx] === "asc" ? "desc" : "asc";
      const factor = dirs[idx] === "asc" ? 1 : -1;
      const rows = Array.from(tbody.querySelectorAll("tr"));
      rows.sort((a, b) => {{
        const av = valueFromCell(a.cells[idx], type);
        const bv = valueFromCell(b.cells[idx], type);
        if (av < bv) return -1 * factor;
        if (av > bv) return 1 * factor;
        return 0;
      }});
      rows.forEach(r => tbody.appendChild(r));
    }});
  }});
}})();
</script>
</body></html>"""


def render_branch_history_page(unit_name: str, branch: str, rows):
    lines = []
    for r in rows:
        lines.append(
            "<tr>"
            f"<td>{r.get('created_at', 'N/A')}</td>"
            f"<td><a href='{r['commit_url']}'>{r['short']}</a></td>"
            f"<td><a href='{r['pipeline_url']}'>#{r['pipeline_id']}</a></td>"
            f"<td><a href='../../../{r['report_dir']}/index.html'>Report</a></td>"
            f"<td>{fmt_cov(r['coverage'])}</td>"
            f"<td>{fmt_cov(r['prev'])}</td>"
            f"<td>{fmt_diff(r['diff'])}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>{unit_name} Branch History: {branch}</title>
<style>
body{{font-family:ui-sans-serif,-apple-system,Segoe UI,Roboto,Arial;margin:24px;background:#0b1220;color:#e6edf7}}
.card{{max-width:1200px;margin:0 auto;border:1px solid #25314a;border-radius:14px;padding:20px;background:#111a2b}}
a{{color:#3ddc97;text-decoration:none;font-weight:700}} a:hover{{text-decoration:underline}}
.nav{{display:flex;gap:10px;flex-wrap:wrap;margin:8px 0 14px}} .btn{{display:inline-block;border:1px solid #25314a;border-radius:10px;padding:8px 12px;background:rgba(17,26,43,.65)}}
table{{width:100%;border-collapse:collapse;margin-top:14px}} th,td{{border-bottom:1px solid #25314a;padding:10px 8px;text-align:left}} th{{color:#9fb0c9;font-weight:600}}
th.sortable{{cursor:pointer}}
</style></head><body><div class=\"card\"><h1>{unit_name} Branch History: {branch}</h1>
<div class=\"nav\"><a class=\"btn\" href=\"../../\">Back to Summary</a></div>
<table id="history-table"><thead><tr><th class="sortable" data-sort-type="date">Run Date</th><th>Commit</th><th>Pipeline</th><th>Report</th><th>Coverage</th><th>Prev</th><th>Diff</th></tr></thead><tbody>
{''.join(lines) if lines else '<tr><td colspan="7">No branch history found.</td></tr>'}
</tbody></table></div>
<script>
(function(){{
  const table = document.getElementById("history-table");
  if (!table) return;
  const tbody = table.tBodies[0];
  const dirs = {{}};
  function valueFromCell(cell, type) {{
    const raw = (cell.innerText || "").trim();
    if (type === "date") {{
      const t = Date.parse(raw);
      return Number.isNaN(t) ? -Infinity : t;
    }}
    return raw.toLowerCase();
  }}
  table.querySelectorAll("th.sortable").forEach((th, idx) => {{
    th.addEventListener("click", () => {{
      const type = th.dataset.sortType || "string";
      dirs[idx] = dirs[idx] === "asc" ? "desc" : "asc";
      const factor = dirs[idx] === "asc" ? 1 : -1;
      const rows = Array.from(tbody.querySelectorAll("tr"));
      rows.sort((a, b) => {{
        const av = valueFromCell(a.cells[idx], type);
        const bv = valueFromCell(b.cells[idx], type);
        if (av < bv) return -1 * factor;
        if (av > bv) return 1 * factor;
        return 0;
      }});
      rows.forEach(r => tbody.appendChild(r));
    }});
  }});
}})();
</script>
</body></html>"""


def render_home_page(targets):
    buttons = "".join(
        f"<a class=\"btn\" href=\"{t['app']}/\">{t['name']} Coverage</a>" for t in targets
    )
    names = "/".join(t["name"] for t in targets)
    return """<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Coverage Home</title>
<style>
body{font-family:ui-sans-serif,-apple-system,Segoe UI,Roboto,Arial;margin:24px;background:#0b1220;color:#e6edf7}
.card{max-width:980px;margin:0 auto;border:1px solid #25314a;border-radius:14px;padding:20px;background:#111a2b}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}
.btn{display:block;text-decoration:none;color:#061018;background:#3ddc97;font-weight:700;padding:12px 14px;border-radius:10px;text-align:center}
.desc{color:#9fb0c9;margin:6px 0 14px}
</style></head><body><div class=\"card\"><h1>Coverage Home</h1>
<p class=\"desc\">Single Pages deployment with links to """ + names + """ reports.</p>
<div class=\"grid\">""" + buttons + """</div>
</div></body></html>"""


def main():
    project_url = os.environ.get("CI_PROJECT_URL", "")
    branch = os.environ.get("CI_COMMIT_REF_NAME", "unknown")
    commit = os.environ.get("CI_COMMIT_SHA", "")
    short = os.environ.get("CI_COMMIT_SHORT_SHA", commit[:8] if commit else "")
    pipeline_id = os.environ.get("CI_PIPELINE_ID", "0")
    created_at = normalize_created_at(os.environ.get("CI_PIPELINE_CREATED_AT", ""))
    default_branch = os.environ.get("CI_DEFAULT_BRANCH", "master")
    coverage_targets, target_warnings = load_coverage_targets_from_env()
    if not coverage_targets:
        print("ERROR: no valid coverage targets found. Job failed.", file=sys.stderr)
        raise SystemExit(1)

    cache_dir = Path(".pages-cache")
    reports_dir = cache_dir / "reports"
    manifests_dir = cache_dir / "manifests"
    public_dir = Path("public")

    for p in [reports_dir, manifests_dir, *[public_dir / t["app"] for t in coverage_targets]]:
        p.mkdir(parents=True, exist_ok=True)

    for target in coverage_targets:
        update_with_current_run(
            target["app"],
            target["job_name"],
            branch,
            commit,
            short,
            pipeline_id,
            project_url,
            reports_dir,
            manifests_dir,
            created_at,
        )

    latest_rows_by_app = {}
    history_by_app = {}
    for target in coverage_targets:
        latest_rows, history_by_branch = build_models(target["app"], reports_dir, manifests_dir, public_dir)
        latest_rows_by_app[target["app"]] = latest_rows
        history_by_app[target["app"]] = history_by_branch

    (public_dir / "index.html").write_text(render_home_page(coverage_targets), encoding="utf-8")
    for target in coverage_targets:
        nav_targets = [t for t in coverage_targets if t["app"] != target["app"]]
        app_dir = public_dir / target["app"]
        (app_dir / "index.html").write_text(
            render_unit_page(target["name"], nav_targets, latest_rows_by_app[target["app"]], default_branch),
            encoding="utf-8",
        )
        for branch_name, branch_rows in history_by_app[target["app"]].items():
            branch_dir = app_dir / "branches" / slugify(branch_name)
            branch_dir.mkdir(parents=True, exist_ok=True)
            (branch_dir / "index.html").write_text(
                render_branch_history_page(target["name"], branch_name, branch_rows),
                encoding="utf-8",
            )

    if target_warnings:
        print(f"{GOLDEN_WARNING}WARNING: some COVERAGE_TARGETS were skipped:{RESET_COLOR}")
        for msg in target_warnings:
            print(f"{GOLDEN_WARNING}- {msg}{RESET_COLOR}")


if __name__ == "__main__":
    main()
