# workday_maintenance（工作日 · 维护台账）

一个 Home Assistant 集成，帮你把**上班/休息日、待办、纪念日、设备维护**都放进一个月历里管，手机电脑都能看。

## 它帮你做什么

- **月历**：自动显示法定节假日和调休（蓝底=上班、灰底=休息、红边=你手动改过）
- **待办和纪念日**：逾期的排前面，能打勾完成；纪念日支持每周/每月/每季度/每年重复
- **维护台账**：记家里的灯、空调、车、净水器……多久该保养一次，到期自动提醒
- **自动提醒**：到期的事通过「魔法推送」发到你手机
- **实时同步**：两个网页共用一个连接，这边改了那边立刻看到

## 安装（3 步）

1. HACS → 自定义存储库 → 填 `https://github.com/ACEweijun/workday_maintenance` → 类型选「集成」→ 搜索 `workday_maintenance` → 下载
2. **完整重启 Home Assistant**（不能只点"重新加载"）
3. 设置 → 设备与服务 → 添加集成 → 搜 `workday_maintenance` → 提交

手动安装：把 `custom_components/workday_maintenance` 整个文件夹复制到 `/config/custom_components/`，重启后做第 3 步。

## 两个页面

侧栏多出两个入口，切换请用侧边栏：

| 入口 | 你能做什么 |
|---|---|
| **我的工作日** | 月历、统计卡、待办、纪念日、自定义工作日、维护到期 |
| **维护台账** | 加项目、加维护小项（间隔天数+计数）、记一次维护、看历史、导出 |

### 我的工作日页面怎么用（重点）

- **改某天上班还是休息**：在那个格子上 **点右键**（手机**长按**）→ 菜单最顶上会出现「标为上班」或「标为休息」→ 点它。
  （注意：**单击格子只是选中，不会改班休**——这是故意的，防误触）
- **翻月份**：手指或鼠标**按住日历左右拖**（左滑下个月、右滑上个月），或点上方的 ← → 箭头。上下滑是滚动页面，不会翻月。
- **新增待办/纪念日**：点格子弹出菜单里的「+ 新增」。
- **收起下面那一堆内容**：点日历下方的「**更多设置**」按钮，待办/纪念日/自定义工作日/维护到期四块一起收起或展开。
- **改格子颜色**：见下面「前端定制」。

## 配置提醒（魔法推送）

在「我的工作日」页面往下找到设置区，填魔法推送的**服务地址**和**Token**，点「发送测试推送」能收到消息就说明配好了。纪念日提醒和维护提醒都靠它发。

---

# 以下是维护信息

## 面向 AI / 开发者：接手前必读

> 人是看上面那段就能用的；这一段是给"下一次接手修改的 AI"看的，改代码前务必读完再动手。

### 数据模型

只有一份 `.storage` 键 `workday_maintenance.merged`：

```
workday:     自定义班休 / 待办 / 纪念日
maintenance: 全部维护项目（小项 + 历史）
```

运行态（magicpush token、推送去重）在独立的 `settings` 键，**不进导出 JSON**——这是有意的，别改。

另一份 `.storage` 键存设置（`soon_days` / `holiday_url` / 自动同步开关等）。

放假数据来自 [holiday-cn](https://github.com/NateScarlet/holiday-cn)（jsDelivr），每年自动拉当年与次年；**最终兜底**是 `holidays_snapshot/` 里的本地 json。

### 实体

| 实体 ID | 说明 |
|---|---|
| `binary_sensor.workday_maintenance_today` / `tomorrow` | 今天 / 明天是否上班（真/假） |
| `sensor.workday_maintenance_left` / `total` / `month_progress` | 本月剩余 / 总数 / 进度 |
| `sensor.workday_maintenance_next_holiday` | 距下个节假日 |
| `sensor.workday_maintenance_due_maintenance` | 到期维护项数，属性带到期清单 |
| `sensor.workday_maintenance_today_tasks` | 今天要做的事：待办 + 已到期维护 |
| `calendar.workday_maintenance` | 班休、节假日、维护到期事件 |

曾经有个 `..._today_rest`（今天是否休息日）已删除——它只是"是否工作日"取反，冗余。**别再加回来。**

### 服务

统一命名空间 `workday_maintenance.*`，全部支持 `response_variable`。共 **27 个**：

| 分组 | 服务 |
|---|---|
| 读取 | `get_snapshot`、`get_settings`、`list_projects`、`export_markdown`、`export_all` |
| 工作日 | `set_day`、`set_custom`、`clear_custom`、`refresh_data`、`set_year_data` |
| 待办 / 纪念日 | `set_todos`、`set_anniversaries` |
| 维护项目 | `add_project`、`update_project`、`delete_project`、`import_projects`、`set_counter` |
| 维护小项 | `add_item`、`update_item`、`delete_item`、`set_baseline` |
| 维护记录 | `log_service`、`update_record`、`delete_record` |
| 联动 / 推送 | `sync_maintenance_todos`、`test_push`、`set_settings` |

`set_todos` / `set_anniversaries` 可直接传数组以保留记录 ID。`test_push` 用调用方传入的 url/token 发测试消息，不写设置、不影响已保存配置。

### 代码地图

```
__init__.py       setup / 侧栏面板 / WebSocket / 每分钟调度（不含业务逻辑）
   ├─ services.py      全部 workday_maintenance.* 服务 handler（27 个）
   ├─ coordinator.py   唯一协调器：读数据、算快照、广播变更、持锁写入
   │    └─ store.py        .storage 读写（merged + settings 两个独立键）
   ├─ notify.py         提醒：取设置、逐项判断、推 magicpush、去重、test_push
   ├─ push_rule.py      push 规则解析（纯函数，无 HA 依赖）
   ├─ workday.py        工作日 / 节假日 / 待办 / 纪念日纯逻辑（无 HA 依赖）
   ├─ maintenance.py    项目 / 小项 / 历史纯逻辑（无 HA 依赖）
   ├─ sensor.py / binary_sensor.py / calendar.py   HA 实体（薄封装，读 coordinator.data）
   └─ config_flow.py    集成选项（soon_days / holiday_url / 同步开关）
const.py             所有常量。被几乎所有模块依赖，改一个名字要全局搜。
```

`workday.py` / `maintenance.py` / `push_rule.py` 是**纯函数层**，不 import HA——
这是刻意设计，方便 `tests/` 用桩模块直接测。别往里加 `homeassistant.*` 依赖。

### 删前必读（看着像垃圾，其实要命）

| 文件 | 为什么不能删 |
|---|---|
| `frontend/demo-data.js` | 本地预览的虚拟数据层。两页 HTML 都 `<script src>` 引它，`__init__.py` 的前端白名单也列了它——删了页面 404、控制台报错 |
| `holidays_snapshot/2026.json`、`2027.json` | 节假日网络源全挂时的最终兜底；`coordinator.py` 跨年补年份也读这里。删了断网就按周末规则降级 |
| `services.yaml` | 服务的字段文档。服务名与 `const.py` 的 `SERVICE_*` 一一对应，测试会校验两者一致（现在 27 个） |
| `translations/*.json`、`strings.json` | 集成选项界面的多语言文案 |
| `brand/icon.png` | 集成图标 |
| `tests/test_*.py` | 含 DOM 嵌套、服务对齐、竞态、push 规则、手势方向等契约测试。**改完必须全跑**，它们抓过好几次真 bug |

### 历史踩过的坑（别再踩）

1. **读路径不能写盘**：`_async_update_data` 只读；写盘全在 `coordinator.async_mutate` 的锁内。
   以前在读路径清理 todo 并写盘，刷新与用户保存并发时会静默吞掉用户数据。
2. **HTML 闭合标签要成对**：`normalView` 曾经提前闭合，导致切到设置页时小项和历史仍显示。
   改完 HTML 结构跑 `TestViewDomStructure`（栈式校验）。
3. **`window.hassConnection` 是 `{auth, conn}`**，不是裸 conn；手机 App 的 token 在 `auth.data.access_token`，
   且 App 的 localStorage 里**没有** `hassTokens`——认证逻辑别退回只读 localStorage。
4. **服务实现在 services.py**：`__init__.py` 里找不到 `async def set_todos` 是正常的，别以为丢了。
5. **导出的存档不含运行态**：`magicpush` token 和去重记录存独立的 `settings` 键，不进导出 JSON——这是有意的，
   别为了让存档"更全"把它们塞进去。
6. **日历交互是刻意设计的**：单击只选中；切班休在菜单顶部按钮（`data-mdayset`）；翻月**只左右**——上下滑必须留给页面滚动，
   否则手机上滑翻月会带着整页滚。四个折叠项收在 `morePanel` 里由 `moreToggle` 统一控制。改手势前先看 `TestCalendarGestures`。
7. **mijia 相关 md 是一次性快照**：`mijia_*.md` 是米家重配时的快照/方案，不是集成运行时文件，别当依赖。

### 前端定制

- **格子颜色**：`frontend/shared.css` 顶部「日历格子颜色配置区」——上班 / 休息 / 标休 / 标班四组 + 红边色，浅色 / 深色主题各一份。
- **本地预览**：`frontend/demo-data.js` 是虚拟数据层，非 HA 环境打开页面时自动加载，部署到 HA 后自动失效。改排版 → 刷新即见效果。
- **移动端**：620px 断点；日历只左右滑翻月，上下滑滚页面；"更多设置"收纳次要区块。

### 改完自检

```bash
python -m unittest discover -s tests -v   # 必须全绿
```

tests 用桩模块加载纯逻辑，不需要安装 Home Assistant。改前端再确认两页内联脚本语法。
CI 每次提交自动跑单测 + hassfest + HACS 校验。

## 许可

MIT
