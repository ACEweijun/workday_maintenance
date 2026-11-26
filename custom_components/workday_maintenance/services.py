"""服务注册：所有 workday_maintenance 域服务的 handler 与注册。

从 __init__.py 拆出，逻辑不变。__init__ 只负责 setup / 面板 / WebSocket / 调度。
"""
from __future__ import annotations

import datetime as dt
import json
import logging

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from . import maintenance as mnt
from . import workday as wd
from . import push_rule as _pr
from .const import (
    DOMAIN, EVENT_UPDATED, MODE_AUTO, MODE_REST, MODE_WORK,
    SCOPE_ALL, SCOPE_MAINTENANCE, SCOPE_WORKDAY,
    SERVICE_ADD_ITEM, SERVICE_ADD_PROJECT, SERVICE_CLEAR_CUSTOM,
    SERVICE_DELETE_ITEM, SERVICE_DELETE_PROJECT, SERVICE_DELETE_RECORD,
    SERVICE_EXPORT, SERVICE_EXPORT_ALL, SERVICE_GET_SETTINGS, SERVICE_GET_SNAPSHOT,
    SERVICE_TEST_PUSH,
    SERVICE_IMPORT_PROJECTS, SERVICE_LIST_PROJECTS, SERVICE_LOG_SERVICE,
    SERVICE_REFRESH, SERVICE_SET_ANNIVERSARIES, SERVICE_SET_BASELINE,
    SERVICE_SET_COUNTER, SERVICE_SET_CUSTOM, SERVICE_SET_DAY, SERVICE_SET_SETTINGS,
    SERVICE_SET_TODOS, SERVICE_SET_YEAR, SERVICE_SYNC_TODOS,
    SERVICE_UPDATE_ITEM, SERVICE_UPDATE_PROJECT, SERVICE_UPDATE_RECORD,
)
from .coordinator import MergedCoordinator
from .notify import NotifyManager

_LOGGER = logging.getLogger(__name__)


def _today() -> dt.date:
    return dt_util.now().date()


def _project(raw: dict, slug: str) -> dict:
    for project in raw["maintenance"]["projects"]:
        if project.get("slug") == slug:
            return project
    raise HomeAssistantError(f"找不到维护项目：{slug}")


def _item(project: dict, item_id: str) -> dict:
    for item in project["items"]:
        if item.get("id") == item_id:
            return item
    raise HomeAssistantError(f"找不到维护小项：{item_id}")


def _iso(value) -> str:
    return wd.parse_date(value).isoformat()

def async_register_services(hass: HomeAssistant, coordinator: MergedCoordinator,
                             notifier: NotifyManager | None = None) -> None:
    def register(name, handler):
        if not hass.services.has_service(DOMAIN, name):
            hass.services.async_register(DOMAIN, name, handler,
                                         supports_response=SupportsResponse.OPTIONAL)

    async def snapshot(_call: ServiceCall) -> dict:
        if not coordinator.data:
            await coordinator.async_refresh()
        data = dict(coordinator.data or {})
        if not data:
            raise HomeAssistantError("快照为空：协调器尚未产生数据")
        return data

    async def set_day(call: ServiceCall) -> dict:
        day = _iso(call.data.get("date"))
        mode = str(call.data.get("mode") or MODE_WORK)

        def mutate(raw):
            work = set(raw["workday"]["custom_work"])
            rest = set(raw["workday"]["custom_rest"])
            work.discard(day)
            rest.discard(day)
            if mode == MODE_WORK:
                work.add(day)
            elif mode == MODE_REST:
                rest.add(day)
            elif mode != MODE_AUTO:
                raise HomeAssistantError(f"不认识的 mode：{mode}")
            raw["workday"]["custom_work"] = sorted(work)
            raw["workday"]["custom_rest"] = sorted(rest)

        await coordinator.async_mutate(SCOPE_WORKDAY, mutate)
        return {"date": day, "mode": mode, "month_left": (coordinator.data or {})["workday"]["stats"]["left"]}

    async def set_custom(call: ServiceCall) -> dict:
        work = wd.normalize_dates(call.data.get("work"))
        rest = wd.normalize_dates(call.data.get("rest"))
        both = work & rest
        if both:
            raise HomeAssistantError(f"同一天不能既算上班又算休息：{sorted(both)}")

        def mutate(raw):
            raw["workday"]["custom_work"] = sorted(work)
            raw["workday"]["custom_rest"] = sorted(rest)

        await coordinator.async_mutate(SCOPE_WORKDAY, mutate)
        return {"work": len(work), "rest": len(rest)}

    async def clear_custom(_call: ServiceCall) -> dict:
        def mutate(raw):
            raw["workday"]["custom_work"] = []
            raw["workday"]["custom_rest"] = []

        await coordinator.async_mutate(SCOPE_WORKDAY, mutate)
        return {"cleared": True}

    async def set_year(call: ServiceCall) -> dict:
        year = int(call.data.get("year") or _today().year)
        text = str(call.data.get("data") or "")

        def mutate(raw):
            overrides = raw["workday"]["year_override"]
            if text.strip():
                overrides[str(year)] = text
            else:
                overrides.pop(str(year), None)

        await coordinator.async_mutate(SCOPE_WORKDAY, mutate)
        await coordinator.async_force_refresh()
        return {"year": year, "set": bool(text.strip())}

    async def set_todos(call: ServiceCall) -> dict:
        supplied = call.data.get("todos")
        items = supplied if isinstance(supplied, list) else wd.parse_todos(call.data.get("data"))

        def mutate(raw):
            raw["workday"]["todos"] = items

        await coordinator.async_mutate(SCOPE_WORKDAY, mutate)
        return {"count": len(items)}

    async def set_anniversaries(call: ServiceCall) -> dict:
        supplied = call.data.get("anniversaries")
        items = supplied if isinstance(supplied, list) else wd.parse_anniversaries(call.data.get("data"))

        def mutate(raw):
            raw["workday"]["anniversaries"] = items

        await coordinator.async_mutate(SCOPE_WORKDAY, mutate)
        return {"count": len(items)}

    async def refresh(_call: ServiceCall) -> dict:
        return await coordinator.async_force_refresh()

    async def add_project(call: ServiceCall) -> dict:
        name = str(call.data.get("name") or "").strip()
        slug = str(call.data.get("slug") or mnt.slugify(name)).strip()
        if not name or not slug:
            raise HomeAssistantError("中文项目名必须提供英文标识 slug")
        kind = str(call.data.get("type") or "custom")

        def mutate(raw):
            projects = raw["maintenance"]["projects"]
            if any(p.get("slug") == slug for p in projects):
                raise HomeAssistantError(f"项目标识已存在：{slug}")
            projects.append(mnt.make_project(
                slug, name, kind, bool(call.data.get("need_counter")),
                str(call.data.get("counter_unit") or ""),
                str(call.data.get("counter_label") or ""),
                call.data.get("counter"), _today()))

        await coordinator.async_mutate(SCOPE_MAINTENANCE, mutate)
        return {"slug": slug, "name": name}

    async def import_projects(call: ServiceCall) -> dict:
        """导入存档：v2 完整存档（workday+maintenance）或旧格式项目数组/单对象。"""
        text = str(call.data.get("json") or "").strip()
        raw_projects = call.data.get("projects")
        archive = None  # v2 完整存档里的 workday 部分
        if raw_projects is None and text:
            try:
                parsed = json.loads(text)
            except ValueError as err:
                raise HomeAssistantError(f"json 不是合法 JSON：{err}") from err
            # v2 完整存档：顶层有 workday 或 maintenance 键
            if isinstance(parsed, dict) and ("workday" in parsed or "maintenance" in parsed):
                archive = (parsed.get("workday") or {}) if isinstance(parsed.get("workday"), dict) else {}
                raw_projects = ((parsed.get("maintenance") or {}).get("projects")
                                if isinstance(parsed.get("maintenance"), dict) else None) or []
            else:
                raw_projects = parsed
        if isinstance(raw_projects, dict):
            raw_projects = [raw_projects]
        if not isinstance(raw_projects, list):
            raw_projects = []
        added, errors = [], []

        def _num(v):
            if v in (None, ""):
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        def _item(idx, it):
            it = it if isinstance(it, dict) else {}
            # 全量备份带 id 时原样保留，保证 history.entries.item_id 引用不失效。
            item_id = str(it.get("id")) if it.get("id") else mnt._uid("i", _today().isoformat(), str(idx))
            return {
                "id": item_id,
                "name": str(it.get("name") or f"小项{idx + 1}"),
                "interval_days": _num(it.get("interval_days")),
                "interval_counter": _num(it.get("interval_counter")),
                "last_date": str(it.get("last_date")) if it.get("last_date") else None,
                "last_counter": _num(it.get("last_counter")),
                "note": str(it.get("note") or ""),
                # 方案甲：细项提醒规则随存档往返，缺省 inherit 不影响旧存档。
                "push": _pr.normalize_push(it.get("push")),
            }

        def mutate(raw):
            # v2 完整存档：先恢复工作日侧用户数据（覆盖式，存档即快照）。
            if archive is not None:
                for key in ("custom_work", "custom_rest", "todos", "anniversaries"):
                    if isinstance(archive.get(key), list):
                        raw["workday"][key] = archive[key]
                if isinstance(archive.get("year_override"), dict):
                    raw["workday"]["year_override"] = archive["year_override"]
            projects = raw["maintenance"]["projects"]
            for p in raw_projects:
                p = p if isinstance(p, dict) else {}
                name = str(p.get("name") or "").strip()
                slug = str(p.get("slug") or mnt.slugify(name)).strip()
                if not name or not slug:
                    errors.append("项目缺少名称：" + json.dumps(p, ensure_ascii=False)[:80])
                    continue
                if any(x.get("slug") == slug for x in projects):
                    errors.append("项目标识已存在：" + slug)
                    continue
                try:
                    kind = str(p.get("type") or "custom")
                    proj = mnt.make_project(
                        slug, name, kind, bool(p.get("need_counter")),
                        str(p.get("counter_unit") or ""),
                        str(p.get("counter_label") or ""),
                        p.get("counter"), _today())
                    if isinstance(p.get("items"), list) and p["items"]:
                        proj["items"] = [_item(i, it) for i, it in enumerate(p["items"])]
                    # 全量备份带 history 时原样还原（保留 id/date/counter/entries）；
                    # 旧格式没有 history 时，才按小项 last_date 生成流水。
                    if isinstance(p.get("history"), list) and p["history"]:
                        histories = []
                        for hi, hr in enumerate(p["history"]):
                            hr = hr if isinstance(hr, dict) else {}
                            entries = []
                            for e in (hr.get("entries") or []):
                                if isinstance(e, dict):
                                    entries.append({
                                        "item_id": str(e.get("item_id") or ""),
                                        "note": str(e.get("note") or ""),
                                    })
                            histories.append({
                                "id": str(hr.get("id")) if hr.get("id") else mnt._uid("r", slug, str(hi)),
                                "date": str(hr.get("date") or _today().isoformat()),
                                "counter": _num(hr.get("counter")),
                                "entries": entries,
                            })
                        histories.sort(key=lambda r: r.get("date") or "")
                    else:
                        histories = []
                        for it in proj["items"]:
                            if it.get("last_date"):
                                histories.append({
                                    "id": mnt._uid("r", slug, it["last_date"], it["id"]),
                                    "date": it["last_date"],
                                    "counter": it.get("last_counter"),
                                    "entries": [{"item_id": it["id"], "note": it.get("note") or ""}],
                                })
                        histories.sort(key=lambda r: r["date"])
                    proj["history"] = histories
                    projects.append(proj)
                    added.append({"slug": slug, "name": name, "items": len(proj["items"])})
                except Exception as err:  # noqa: BLE001
                    errors.append(f"{name or '?'}：{err}")

        await coordinator.async_mutate(SCOPE_ALL, mutate)
        result = {"added": added, "errors": errors}
        if archive is not None:
            result["workday_restored"] = True
        return result

    async def update_project(call: ServiceCall) -> dict:
        slug = str(call.data.get("slug") or "")

        def mutate(raw):
            project = _project(raw, slug)
            for key in ("name", "need_counter", "counter_unit", "counter_label"):
                if key in call.data:
                    project[key] = call.data[key]

        await coordinator.async_mutate(SCOPE_MAINTENANCE, mutate)
        return {"slug": slug}

    async def delete_project(call: ServiceCall) -> dict:
        slug = str(call.data.get("slug") or "")

        def mutate(raw):
            projects = raw["maintenance"]["projects"]
            _project(raw, slug)
            raw["maintenance"]["projects"] = [p for p in projects if p.get("slug") != slug]

        await coordinator.async_mutate(SCOPE_MAINTENANCE, mutate)
        return {"deleted": slug}

    async def list_projects(_call: ServiceCall) -> dict:
        return {"projects": (coordinator.data or {})["maintenance"]["summaries"]}

    async def set_counter(call: ServiceCall) -> dict:
        slug, value = str(call.data.get("slug") or ""), int(call.data.get("value") or 0)

        def mutate(raw):
            _project(raw, slug)["counter"] = value

        await coordinator.async_mutate(SCOPE_MAINTENANCE, mutate)
        return {"slug": slug, "value": value}

    async def add_item(call: ServiceCall) -> dict:
        slug = str(call.data.get("slug") or "")

        def mutate(raw):
            project = _project(raw, slug)
            item = {
                "id": mnt._uid("i", slug, call.data.get("name"), _today().isoformat()),
                "name": str(call.data.get("name") or "新小项"),
                "interval_days": int(call.data.get("interval_days") or 180),
                "interval_counter": call.data.get("interval_counter"),
                "last_date": None, "last_counter": None,
                "note": str(call.data.get("note") or ""),
                "push": _pr.normalize_push(call.data.get("push")),
                "disabled": bool(call.data.get("disabled", False)),
            }
            project["items"].append(item)
            return item["id"]

        item_id = await coordinator.async_mutate(SCOPE_MAINTENANCE, mutate)
        return {"slug": slug, "item_id": item_id}

    async def update_item(call: ServiceCall) -> dict:
        slug, item_id = str(call.data.get("slug") or ""), str(call.data.get("item_id") or "")

        def mutate(raw):
            item = _item(_project(raw, slug), item_id)
            for key in ("name", "interval_days", "interval_counter", "note", "push", "disabled"):
                if key in call.data:
                    if key == "push":
                        item[key] = _pr.normalize_push(call.data[key])
                    elif key == "disabled":
                        item[key] = bool(call.data[key])
                    else:
                        item[key] = call.data[key]

        await coordinator.async_mutate(SCOPE_MAINTENANCE, mutate)
        return {"slug": slug, "item_id": item_id}

    async def delete_item(call: ServiceCall) -> dict:
        slug, item_id = str(call.data.get("slug") or ""), str(call.data.get("item_id") or "")

        def mutate(raw):
            project = _project(raw, slug)
            _item(project, item_id)
            project["items"] = [i for i in project["items"] if i.get("id") != item_id]

        await coordinator.async_mutate(SCOPE_MAINTENANCE, mutate)
        return {"deleted": item_id}

    async def set_baseline(call: ServiceCall) -> dict:
        slug, item_id = str(call.data.get("slug") or ""), str(call.data.get("item_id") or "")

        def mutate(raw):
            item = _item(_project(raw, slug), item_id)
            if call.data.get("last_date") is not None:
                item["last_date"] = _iso(call.data.get("last_date"))
            if call.data.get("last_counter") is not None:
                item["last_counter"] = int(call.data["last_counter"])

        await coordinator.async_mutate(SCOPE_MAINTENANCE, mutate)
        return {"slug": slug, "item_id": item_id}

    async def log_service(call: ServiceCall) -> dict:
        slug = str(call.data.get("slug") or "")
        item_ids = call.data.get("item_ids") or []
        if isinstance(item_ids, str):
            item_ids = [x.strip() for x in item_ids.split(",") if x.strip()]
        date = _iso(call.data.get("date") or _today())
        notes = call.data.get("item_notes") or {}
        if call.data.get("note"):
            notes = {i: call.data["note"] for i in item_ids}

        def mutate(raw):
            return mnt.log_service(_project(raw, slug), list(item_ids), date,
                                   call.data.get("counter"), notes, _today())

        record_id = await coordinator.async_mutate(SCOPE_MAINTENANCE, mutate)
        return {"slug": slug, "record_id": record_id}

    async def update_record(call: ServiceCall) -> dict:
        slug = str(call.data.get("slug") or "")

        def mutate(raw):
            mnt.update_record_entry(
                _project(raw, slug), str(call.data.get("record_id") or ""),
                str(call.data.get("item_id") or ""), call.data.get("date"),
                call.data.get("counter"), call.data.get("note"))

        await coordinator.async_mutate(SCOPE_MAINTENANCE, mutate)
        return {"slug": slug}

    async def delete_record(call: ServiceCall) -> dict:
        slug = str(call.data.get("slug") or "")

        def mutate(raw):
            mnt.delete_record_entry(
                _project(raw, slug), str(call.data.get("record_id") or ""),
                str(call.data.get("item_id") or ""))

        await coordinator.async_mutate(SCOPE_MAINTENANCE, mutate)
        return {"slug": slug}

    async def export(call: ServiceCall) -> dict:
        slug = str(call.data.get("slug") or "")
        raw = await coordinator.store.async_load()
        project = _project(raw, slug)
        return {"markdown": mnt.export_markdown(project, _today(), coordinator.soon_days)}

    async def export_all(call: ServiceCall) -> dict:
        """导出全部用户数据（工作日 + 维护台账）为规范化存档，与 import_projects 对称。"""
        raw = await coordinator.store.async_load()
        wd_raw = raw.get("workday") or {}
        projects = (raw.get("maintenance") or {}).get("projects") or []
        # 深拷贝：嵌套结构浅拷贝会在并发写入时导出不一致快照。
        clone = lambda o: json.loads(json.dumps(o, ensure_ascii=False))
        data = {
            "format": "workday_maintenance",
            "version": 2,
            "exported_at": _today().isoformat(),
            "_说明": {
                "用途": "这是 workday_maintenance 的完整数据存档，可直接发回给 AI 编辑后重新导入。",
                "导入": "维护台账 -> 加号 -> 导入，整段粘贴即可恢复；同名项目会跳过，恢复前请先删除同名项目。",
                "workday": "工作日侧用户数据：待办、纪念日、自定义班休、整年覆盖。",
                "maintenance.projects": "维护项目，每项含小项 items 与历史记录 history。",
                "字段": {
                    "todos[].date": "YYYY-MM-DD", "todos[].text": "待办内容", "todos[].done": "是否完成",
                    "anniversaries[].date": "MM-DD 或 YYYY-MM-DD", "anniversaries[].repeat": "none/week/month/quarter/year",
                    "custom_work / custom_rest": "手动标记上班/休息的日期数组 YYYY-MM-DD",
                    "year_override": "年份 -> 放假安排文本（每行 日期 名称，'班'字表示补班）",
                    "projects[].need_counter": "是否需要里程/次数计数", "projects[].counter": "当前计数",
                    "items[].interval_days": "间隔天数", "items[].interval_counter": "间隔计数（里程）",
                    "items[].last_date": "上次维护日期", "items[].last_counter": "上次维护时的计数",
                    "history[].entries[]": "item_id + note，引用 items[].id",
                },
            },
            "workday": {
                "todos": clone(wd_raw.get("todos") or []),
                "anniversaries": clone(wd_raw.get("anniversaries") or []),
                "custom_work": clone(wd_raw.get("custom_work") or []),
                "custom_rest": clone(wd_raw.get("custom_rest") or []),
                "year_override": clone(wd_raw.get("year_override") or {}),
            },
            "maintenance": {"projects": clone(projects)},
        }
        return {"json": json.dumps(data, ensure_ascii=False, indent=2)}

    async def get_settings(_call: ServiceCall) -> dict:
        return await notifier.get_settings()

    async def set_settings(call: ServiceCall) -> dict:
        return await notifier.save_settings(dict(call.data))

    async def test_push(call: ServiceCall) -> dict:
        """用调用方传来的 url/token 发一条测试消息，不依赖已保存设置。"""
        return await notifier.test_push(
            str(call.data.get("url") or "").strip(),
            str(call.data.get("token") or "").strip(),
        )

    async def sync_todos(_call: ServiceCall) -> dict:
        added = await coordinator.async_sync_due_todos(True)
        await coordinator.async_refresh()
        hass.bus.async_fire(EVENT_UPDATED, {"scope": SCOPE_WORKDAY})
        return {"added": added}

    handlers = (
        (SERVICE_GET_SNAPSHOT, snapshot), (SERVICE_SET_DAY, set_day),
        (SERVICE_SET_CUSTOM, set_custom), (SERVICE_CLEAR_CUSTOM, clear_custom),
        (SERVICE_REFRESH, refresh), (SERVICE_SET_YEAR, set_year),
        (SERVICE_SET_TODOS, set_todos), (SERVICE_SET_ANNIVERSARIES, set_anniversaries),
        (SERVICE_ADD_PROJECT, add_project), (SERVICE_UPDATE_PROJECT, update_project),
        (SERVICE_IMPORT_PROJECTS, import_projects),
        (SERVICE_DELETE_PROJECT, delete_project), (SERVICE_LIST_PROJECTS, list_projects),
        (SERVICE_SET_COUNTER, set_counter), (SERVICE_ADD_ITEM, add_item),
        (SERVICE_UPDATE_ITEM, update_item), (SERVICE_DELETE_ITEM, delete_item),
        (SERVICE_SET_BASELINE, set_baseline), (SERVICE_LOG_SERVICE, log_service),
        (SERVICE_UPDATE_RECORD, update_record), (SERVICE_DELETE_RECORD, delete_record),
        (SERVICE_EXPORT, export), (SERVICE_EXPORT_ALL, export_all),
        (SERVICE_SYNC_TODOS, sync_todos),
        (SERVICE_GET_SETTINGS, get_settings), (SERVICE_SET_SETTINGS, set_settings),
        (SERVICE_TEST_PUSH, test_push),
    )
    for name, handler in handlers:
        register(name, handler)
