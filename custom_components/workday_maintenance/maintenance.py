"""维护项目、小项、历史的纯逻辑，不依赖 Home Assistant。"""
from __future__ import annotations

import datetime as dt
import hashlib
import re

from .const import PRESETS, STATUS_DISABLED, STATUS_DUE, STATUS_OK, STATUS_SOON, STATUS_UNSET
from .workday import parse_date


def slugify(name: str) -> str:
    text = str(name or "").strip()
    clean = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    if clean:
        return clean
    return "p_" + hashlib.md5(text.encode("utf-8")).hexdigest()[:8]


def _uid(prefix: str, *parts) -> str:
    raw = "|".join(str(p) for p in parts)
    return prefix + hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]


def preset_items(kind: str, today: dt.date) -> list[dict]:
    _label, _need, _unit, _lbl, rows = PRESETS.get(kind, PRESETS["custom"])
    return [
        {
            "id": _uid("i", today.isoformat(), name),
            "name": name,
            "interval_days": days,
            "interval_counter": interval,
            "last_date": None,
            "last_counter": None,
            "note": "",
        }
        for name, days, interval in rows
    ]


def make_project(slug: str, name: str, kind: str, need_counter: bool,
                 unit: str, label: str, counter, today: dt.date) -> dict:
    _label, preset_need, preset_unit, preset_label, _rows = PRESETS.get(kind, PRESETS["custom"])
    return {
        "slug": slug,
        "name": name,
        "type": kind,
        "need_counter": bool(need_counter),
        "counter_unit": unit or (preset_unit if preset_need else ""),
        "counter_label": label or (preset_label if preset_need else ""),
        "counter": int(counter) if counter not in (None, "") else None,
        "items": preset_items(kind, today),
        "history": [],
    }


def item_state(item: dict, project: dict, today: dt.date, soon_days: int) -> dict:
    # 禁用的小项：状态直接标 disabled，不参与到期/快到判断（但仍返回完整字段供界面显示）
    if item.get("disabled"):
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "status": STATUS_DISABLED,
            "remaining_days": None,
            "remaining_counter": None,
            "due_date": None,
            "last_date": item.get("last_date"),
            "last_counter": item.get("last_counter"),
            "interval_days": item.get("interval_days"),
            "interval_counter": item.get("interval_counter"),
            "note": item.get("note") or "",
            "disabled": True,
        }
    last_date = item.get("last_date")
    interval_days = item.get("interval_days")
    remaining_days = None
    if last_date and interval_days:
        try:
            remaining_days = int(interval_days) - (today - parse_date(last_date)).days
        except (ValueError, TypeError):
            remaining_days = None

    counter = project.get("counter")
    last_counter = item.get("last_counter")
    interval_counter = item.get("interval_counter")
    remaining_counter = None
    # 里程基准必须 > 0 才参与判断。last_counter=0 通常是"没填/占位"（没有车在 0 公里做保养），
    # 若按 0 计算，0 + 间隔 - 当前里程 必然为负，导致只填了天数的小项被误报"已到期"。
    # 用户后续在"记一次维护"里填了真实里程（>0）后，里程判断会自动恢复。
    last_counter_num = None
    if last_counter not in (None, ""):
        try:
            last_counter_num = int(last_counter)
        except (ValueError, TypeError):
            last_counter_num = None
    has_counter_base = last_counter_num is not None and last_counter_num > 0
    if project.get("need_counter") and counter is not None and has_counter_base and interval_counter:
        remaining_counter = last_counter_num + int(interval_counter) - int(counter)

    if not last_date and last_counter is None:
        status = STATUS_UNSET
    elif (remaining_days is not None and remaining_days <= 0) or \
         (remaining_counter is not None and remaining_counter <= 0):
        status = STATUS_DUE
    elif remaining_days is not None and remaining_days <= soon_days:
        status = STATUS_SOON
    else:
        status = STATUS_OK

    due_date = None
    if last_date and interval_days:
        try:
            due_date = (parse_date(last_date) + dt.timedelta(days=int(interval_days))).isoformat()
        except (ValueError, TypeError):
            due_date = None

    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "status": status,
        "remaining_days": remaining_days,
        "remaining_counter": remaining_counter,
        "due_date": due_date,
        "last_date": last_date,
        "last_counter": last_counter,
        "interval_days": interval_days,
        "interval_counter": interval_counter,
        "note": item.get("note") or "",
        "disabled": False,
    }


def project_summary(project: dict, today: dt.date, soon_days: int) -> dict:
    states = [item_state(i, project, today, soon_days) for i in project.get("items", [])]
    due = [s for s in states if s["status"] == STATUS_DUE]
    soon = [s for s in states if s["status"] == STATUS_SOON]
    unset = [s for s in states if s["status"] == STATUS_UNSET]
    ranked = due + soon
    next_item = ranked[0] if ranked else (unset[0] if unset else None)
    return {
        "slug": project.get("slug"),
        "name": project.get("name"),
        "due_count": len(due),
        "soon_count": len(soon),
        "unset_count": len(unset),
        "due_names": [s["name"] for s in due],
        "soon_names": [s["name"] for s in soon],
        "next": next_item,
        "items": states,
    }


def recompute_baselines(project: dict) -> None:
    records = sorted(project.get("history", []), key=lambda r: str(r.get("date") or ""))
    for item in project.get("items", []):
        last_date = None
        last_counter = None
        for rec in records:
            if any(e.get("item_id") == item.get("id") for e in rec.get("entries", [])):
                last_date = rec.get("date")
                last_counter = rec.get("counter")
        item["last_date"] = last_date
        item["last_counter"] = last_counter


def log_service(project: dict, item_ids: list[str], date: str, counter,
                notes: dict, today: dt.date) -> str:
    valid = [i for i in project.get("items", []) if i.get("id") in item_ids]
    if not valid:
        raise ValueError("没有选中任何维护小项")
    day = parse_date(date).isoformat()
    value = int(counter) if counter not in (None, "") else project.get("counter")
    record = {
        "id": _uid("r", project.get("slug"), day, len(project.get("history", []))),
        "date": day,
        "counter": value,
        "entries": [
            {"item_id": i.get("id"), "note": str((notes or {}).get(i.get("id"), ""))}
            for i in valid
        ],
    }
    project.setdefault("history", []).append(record)
    if value is not None:
        project["counter"] = value
    for item in valid:
        item["last_date"] = day
        item["last_counter"] = value
    return record["id"]


def update_record_entry(project: dict, record_id: str, item_id: str,
                        date, counter, note) -> None:
    rec = next((r for r in project.get("history", []) if r.get("id") == record_id), None)
    if not rec:
        raise ValueError("找不到这条记录")
    if date not in (None, ""):
        rec["date"] = parse_date(date).isoformat()
    if counter not in (None, ""):
        rec["counter"] = int(counter)
    for entry in rec.get("entries", []):
        if entry.get("item_id") == item_id and note is not None:
            entry["note"] = str(note)
    recompute_baselines(project)


def delete_record_entry(project: dict, record_id: str, item_id: str) -> None:
    rec = next((r for r in project.get("history", []) if r.get("id") == record_id), None)
    if not rec:
        raise ValueError("找不到这条记录")
    rec["entries"] = [e for e in rec.get("entries", []) if e.get("item_id") != item_id]
    if not rec["entries"]:
        project["history"] = [r for r in project["history"] if r.get("id") != record_id]
    recompute_baselines(project)


def all_due_items(projects: list[dict], today: dt.date, soon_days: int) -> list[dict]:
    out = []
    for project in projects:
        summary = project_summary(project, today, soon_days)
        for state in summary["items"]:
            if state["status"] in (STATUS_DUE, STATUS_SOON):
                out.append({
                    "slug": project.get("slug"),
                    "project": project.get("name"),
                    "item_id": state["id"],
                    "name": state["name"],
                    "status": state["status"],
                    "due_date": state["due_date"] or today.isoformat(),
                    "remaining_days": state["remaining_days"],
                })
    return out


def export_markdown(project: dict, today: dt.date, soon_days: int) -> str:
    summary = project_summary(project, today, soon_days)
    lines = [f"# {project.get('name', '')}", ""]
    if project.get("need_counter"):
        lines.append(f"当前{project.get('counter_label') or '计数'}：{project.get('counter')} "
                     f"{project.get('counter_unit') or ''}")
        lines.append("")
    lines.append("| 维护小项 | 状态 | 上次维护 | 还剩 |")
    lines.append("|---|---|---|---|")
    labels = {STATUS_DUE: "已到期", STATUS_SOON: "快到了",
              STATUS_OK: "正常", STATUS_UNSET: "未设基准",
              STATUS_DISABLED: "已禁用"}
    for s in summary["items"]:
        left = f"{s['remaining_days']} 天" if s["remaining_days"] is not None else "—"
        lines.append(f"| {s['name']} | {labels.get(s['status'], '')} | "
                     f"{s['last_date'] or '—'} | {left} |")
    lines.extend(["", "## 历史记录", ""])
    for rec in sorted(project.get("history", []), key=lambda r: r.get("date", ""), reverse=True):
        names = [i.get("name") for i in project.get("items", [])
                 if i.get("id") in [e.get("item_id") for e in rec.get("entries", [])]]
        lines.append(f"- {rec.get('date')} · {'、'.join(names)}")
    return "\n".join(lines)
