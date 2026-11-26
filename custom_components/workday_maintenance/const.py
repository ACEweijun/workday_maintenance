"""workday_maintenance 合并版常量：工作日、待办、维护台账共用一个集成。"""
from __future__ import annotations

DOMAIN = "workday_maintenance"
NAME = "workday_maintenance"
STORAGE_KEY = "workday_maintenance.merged"
STORAGE_VERSION = 1
# 设置独立存储：提醒规则 / magicpush 配置 / 推送去重，不进业务存档
SETTINGS_KEY = "workday_maintenance.settings"
SETTINGS_VERSION = 1
# 新增服务名
SERVICE_GET_SETTINGS = "get_settings"
SERVICE_SET_SETTINGS = "set_settings"
SERVICE_TEST_PUSH = "test_push"

PANEL_URL = "/workday_maintenance"
PANEL_WORKDAY = "workday.html"
PANEL_MAINTENANCE = "maintenance.html"
PANEL_MAINTENANCE_PATH = "workday_maintenance_panel"
EVENT_UPDATED = "workday_maintenance_updated"

DEFAULT_HOLIDAY_URL = "https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json"
# 多源兜底：依次尝试，任一成功即用；全部失败再用内置快照。
# 用户可通过选项 CONF_HOLIDAY_URL 自定义第一优先级源。
HOLIDAY_FALLBACK_URLS = (
    "https://ghproxy.net/https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json",
    "https://gh-proxy.com/https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json",
    "https://gcore.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json",
    "https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json",
)
CONF_HOLIDAY_URL = "holiday_url"
CONF_SYNC_DUE_TO_TODOS = "sync_due_to_todos"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_SOON_DAYS = "soon_days"
DEFAULT_SOON_DAYS = 7
KEEP_DAYS = 500

MODE_WORK = "work"
MODE_REST = "rest"
MODE_AUTO = "auto"

STATUS_DUE = "due"
STATUS_SOON = "soon"
STATUS_OK = "ok"
STATUS_UNSET = "unset"
STATUS_DISABLED = "disabled"

SCOPE_WORKDAY = "workday"
SCOPE_MAINTENANCE = "maintenance"
SCOPE_ALL = "all"

ENTITY_TODAY = "binary_sensor.workday_maintenance_today"
ENTITY_TOMORROW = "binary_sensor.workday_maintenance_tomorrow"
ENTITY_TODAY_DATE = "sensor.workday_maintenance_today_date"
ENTITY_TODAY_WEEKDAY = "sensor.workday_maintenance_today_weekday"
ENTITY_LEFT = "sensor.workday_maintenance_left"
ENTITY_TOTAL = "sensor.workday_maintenance_total"
ENTITY_PROGRESS = "sensor.workday_maintenance_month_progress"
ENTITY_NEXT_HOLIDAY = "sensor.workday_maintenance_next_holiday"
ENTITY_DUE_MAINTENANCE = "sensor.workday_maintenance_due_maintenance"
ENTITY_TODAY_TASKS = "sensor.workday_maintenance_today_tasks"
ENTITY_CALENDAR = "calendar.workday_maintenance"

SERVICE_GET_SNAPSHOT = "get_snapshot"
SERVICE_SET_DAY = "set_day"
SERVICE_SET_CUSTOM = "set_custom"
SERVICE_CLEAR_CUSTOM = "clear_custom"
SERVICE_REFRESH = "refresh_data"
SERVICE_SET_YEAR = "set_year_data"
SERVICE_SET_TODOS = "set_todos"
SERVICE_SET_ANNIVERSARIES = "set_anniversaries"
SERVICE_ADD_PROJECT = "add_project"
SERVICE_UPDATE_PROJECT = "update_project"
SERVICE_DELETE_PROJECT = "delete_project"
SERVICE_LIST_PROJECTS = "list_projects"
SERVICE_SET_COUNTER = "set_counter"
SERVICE_ADD_ITEM = "add_item"
SERVICE_UPDATE_ITEM = "update_item"
SERVICE_DELETE_ITEM = "delete_item"
SERVICE_SET_BASELINE = "set_baseline"
SERVICE_LOG_SERVICE = "log_service"
SERVICE_UPDATE_RECORD = "update_record"
SERVICE_DELETE_RECORD = "delete_record"
SERVICE_EXPORT = "export_markdown"
SERVICE_EXPORT_ALL = "export_all"
SERVICE_SYNC_TODOS = "sync_maintenance_todos"
SERVICE_IMPORT_PROJECTS = "import_projects"

PRESETS = {
    "vehicle": ("车辆", True, "公里", "里程", [
        ("机油 + 机油滤芯", 180, 10000), ("空调滤芯", 365, 20000),
        ("空气滤芯", 365, 20000), ("轮胎换位", 365, 20000),
        ("刹车油", 730, None), ("冷却液", 730, None),
    ]),
    "appliance": ("家电", False, "", "", [
        ("清洗筒内 / 过滤器", 90, None), ("清理排水口 / 滤网", 90, None),
        ("检查密封圈与水管", 180, None), ("机身内外擦拭", 30, None),
    ]),
    "furniture": ("家具", False, "", "", [
        ("清洗坐垫与靠背", 180, None), ("检查气压杆升降", 365, None),
        ("紧固螺丝与检查脚轮", 365, None), ("扶手与头枕除尘", 30, None),
    ]),
    "area": ("区域", False, "", "", [
        ("刷洗马桶", 7, None), ("擦洗玻璃与镜面", 30, None),
        ("清理地漏与下水口", 30, None), ("除霉与通风", 30, None),
    ]),
    "custom": ("自己建", False, "", "", [("例行检查", 180, None)]),
}
