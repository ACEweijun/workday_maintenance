"""纯逻辑与仓库一致性单测，不需要安装 Home Assistant。"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import pathlib
import re
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / 'custom_components' / 'workday_maintenance'

_pkg = types.ModuleType('workday_maintenance')
_pkg.__path__ = [str(PKG)]
sys.modules['workday_maintenance'] = _pkg


def _load(name):
    spec = importlib.util.spec_from_file_location('workday_maintenance.' + name, PKG / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules['workday_maintenance.' + name] = module
    spec.loader.exec_module(module)
    return module


const = _load('const')
wd = _load('workday')
mnt = _load('maintenance')


class TestWorkday(unittest.TestCase):
    def setUp(self):
        self.h = {'off': set(), 'makeup': set(), 'names': {}}

    def test_weekend_and_weekday(self):
        self.assertTrue(wd.classify(dt.date(2026, 11, 13), self.h, set(), set())[0])
        self.assertFalse(wd.classify(dt.date(2026, 11, 14), self.h, set(), set())[0])

    def test_makeup_day(self):
        self.h['makeup'].add('2026-11-14')
        work, label = wd.classify(dt.date(2026, 11, 14), self.h, set(), set())
        self.assertTrue(work)
        self.assertEqual(label, '补班')

    def test_custom_overrides_holiday(self):
        self.h['off'].add('2026-11-13')
        self.assertFalse(wd.classify(dt.date(2026, 11, 13), self.h, set(), set())[0])
        self.assertTrue(wd.classify(dt.date(2026, 11, 13), self.h,
                                    {'2026-11-13'}, set())[0])
        self.assertFalse(wd.classify(dt.date(2026, 11, 13), self.h,
                                     {'2026-11-13'}, {'2026-11-13'})[0])

    def test_month_stats(self):
        stats = wd.month_stats(2026, 11, dt.date(2026, 11, 1), self.h, set(), set())
        self.assertGreater(stats['total'], 15)
        self.assertEqual(stats['left'], stats['total'])
        self.assertEqual(stats['passed'], 0)

    def test_todos_roundtrip(self):
        text = '2026-11-13 交月度报表\n[x] 2026-11-10 提交巡检记录'
        items = wd.parse_todos(text)
        self.assertEqual(len(items), 2)
        self.assertTrue(items[1]['done'])
        self.assertEqual(wd.parse_todos(wd.todos_text(items)), items)

    def test_anniversaries(self):
        items = wd.parse_anniversaries('生日: 05-20\n项目上线: 2026-12-01')
        self.assertTrue(items[0]['repeat'])
        self.assertFalse(items[1]['repeat'])

    def test_year_text_range(self):
        parsed = wd.parse_year_text('2026-10-01~2026-10-03 国庆放假\n2026-10-11 补班')
        self.assertEqual(len(parsed['off']), 3)
        self.assertIn('2026-10-11', parsed['makeup'])

    def test_holiday_payload(self):
        payload = {'2026': {'01-01': {'name': '元旦', 'isOffDay': True},
                            '02-07': {'name': '补班', 'isOffDay': False}}}
        parsed = wd.holiday_payload_to_holidays(payload, 2026)
        self.assertIn('2026-01-01', parsed['off'])
        self.assertIn('2026-02-07', parsed['makeup'])

    def test_holiday_payload_new_holiday_cn_format(self):
        """holiday-cn 新版 days 列表格式也应正确解析。"""
        payload = {'year': 2027, 'days': [
            {'name': '元旦', 'date': '2027-01-01', 'isOffDay': True},
            {'name': '补班', 'date': '2027-01-04', 'isOffDay': False},
        ]}
        parsed = wd.holiday_payload_to_holidays(payload, 2027)
        self.assertIn('2027-01-01', parsed['off'])
        self.assertIn('2027-01-04', parsed['makeup'])

    def test_holiday_snapshot_exists_and_parses(self):
        """内置节假日快照必须存在且能解析出数据（网络全失败的兜底）。"""
        snapshot_dir = PKG / 'holidays_snapshot'
        for year in (2026, 2027):
            p = snapshot_dir / f'{year}.json'
            self.assertTrue(p.is_file(), f'缺少内置快照 {year}.json')
            payload = json.loads(p.read_text(encoding='utf-8'))
            parsed = wd.holiday_payload_to_holidays(payload, year)
            self.assertGreater(len(parsed['off']), 0, f'{year} 快照解析无放假日期')
            self.assertGreater(len(parsed['makeup']), 0, f'{year} 快照解析无补班日期')

    def test_next_holiday(self):
        self.h['off'].update({'2026-12-25', '2026-12-26'})
        self.h['names']['2026-12-25'] = '圣诞'
        found = wd.next_holiday(dt.date(2026, 12, 1), self.h)
        self.assertEqual(found['name'], '圣诞')
        self.assertEqual(found['total_days'], 2)

    def test_clean_todos(self):
        items = [{'id': 'a', 'date': '2020-01-01', 'text': '旧', 'done': True},
                 {'id': 'b', 'date': '2026-11-13', 'text': '新', 'done': False}]
        self.assertEqual(len(wd.clean_todos(items, dt.date(2026, 11, 13))), 1)


class TestMaintenance(unittest.TestCase):
    def setUp(self):
        self.today = dt.date(2026, 11, 13)
        self.project = mnt.make_project('corolla', '卡罗拉', 'vehicle', True,
                                        '公里', '里程', 82000, self.today)

    def test_preset_items(self):
        self.assertGreater(len(self.project['items']), 3)
        self.assertTrue(self.project['need_counter'])

    def test_unset_status(self):
        state = mnt.item_state(self.project['items'][0], self.project, self.today, 7)
        self.assertEqual(state['status'], 'unset')

    def test_log_and_due(self):
        item = self.project['items'][0]
        rid = mnt.log_service(self.project, [item['id']], '2026-05-12', 80000,
                              {item['id']: '4S 店'}, self.today)
        self.assertTrue(rid)
        self.assertEqual(item['last_date'], '2026-05-12')
        self.assertEqual(len(self.project['history']), 1)
        item['interval_days'] = 30
        state = mnt.item_state(item, self.project, self.today, 7)
        self.assertEqual(state['status'], 'due')

    def test_delete_recomputes_baseline(self):
        item = self.project['items'][0]
        rid = mnt.log_service(self.project, [item['id']], '2026-10-01', 81000, {}, self.today)
        mnt.delete_record_entry(self.project, rid, item['id'])
        self.assertIsNone(item['last_date'])
        self.assertEqual(self.project['history'], [])

    def test_zero_counter_base_ignores_mileage(self):
        """里程基准为 0（没填/占位）时不应按里程误报到期，只按天数判断。"""
        item = self.project['items'][0]
        item['last_date'] = '2026-11-01'
        item['interval_days'] = 365
        item['last_counter'] = 0
        item['interval_counter'] = 10000
        self.project['counter'] = 43000
        state = mnt.item_state(item, self.project, self.today, 7)
        self.assertIsNone(state['remaining_counter'])  # 0 基准不参与里程判断
        self.assertEqual(state['status'], 'ok')        # 天数还剩很多 -> 正常，不误报

    def test_real_counter_base_still_applies(self):
        """填了真实里程（>0）时，里程判断照常生效。"""
        item = self.project['items'][0]
        item['last_date'] = '2026-11-01'
        item['interval_days'] = 365
        item['last_counter'] = 40000
        item['interval_counter'] = 10000
        self.project['counter'] = 82000
        state = mnt.item_state(item, self.project, self.today, 7)
        self.assertEqual(state['remaining_counter'], 40000 + 10000 - 82000)  # -32000
        self.assertEqual(state['status'], 'due')  # 里程已超 -> 到期

    def test_summary_counts(self):
        item = self.project['items'][0]
        item['last_date'] = '2026-11-01'
        item['interval_days'] = 5
        summary = mnt.project_summary(self.project, self.today, 7)
        self.assertEqual(summary['due_count'], 1)
        self.assertIn(item['name'], summary['due_names'])

    def test_all_due_items(self):
        self.project['items'][0]['last_date'] = '2026-01-01'
        self.project['items'][0]['interval_days'] = 30
        items = mnt.all_due_items([self.project], self.today, 7)
        self.assertTrue(any(i['slug'] == 'corolla' for i in items))

    def test_export(self):
        text = mnt.export_markdown(self.project, self.today, 7)
        self.assertIn('卡罗拉', text)
        self.assertIn('维护小项', text)


class TestRepo(unittest.TestCase):
    def test_manifest(self):
        manifest = json.loads((PKG / 'manifest.json').read_text(encoding='utf-8'))
        for key in ('domain', 'name', 'version', 'config_flow', 'documentation',
                    'issue_tracker', 'codeowners', 'requirements', 'dependencies'):
            self.assertIn(key, manifest)
        self.assertEqual(manifest['domain'], 'workday_maintenance')

    def test_services_match_yaml(self):
        declared = set(re.findall(r'^SERVICE_[A-Z_]+\s*=\s*"([^"]+)"',
                                  (PKG / 'const.py').read_text(encoding='utf-8'), re.M))
        defined = set(re.findall(r'^([a-z_]+):\s*$',
                                 (PKG / 'services.yaml').read_text(encoding='utf-8'), re.M))
        self.assertEqual(declared, defined)

    def test_handlers_register_every_declared_service(self):
        """结构化契约：handlers 元组必须覆盖 const 里声明的每个服务，且无遗漏文档。"""
        c = (PKG / 'const.py').read_text(encoding='utf-8')
        services = (PKG / 'services.py').read_text(encoding='utf-8')
        svc = (PKG / 'services.yaml').read_text(encoding='utf-8')
        declared = dict(re.findall(r'^SERVICE_([A-Z_]+)\s*=\s*"([^"]+)"', c, re.M))
        doc = set(re.findall(r'^([a-z_]+):\s*$', svc, re.M))
        # 从 handlers 元组里提取实际注册的常量名
        registered = set(re.findall(r'\(SERVICE_([A-Z_]+),\s*\w+\)', services))
        self.assertEqual(set(declared), registered,
                         '服务常量与 handlers 注册不一致')
        self.assertEqual(set(declared.values()), doc,
                         '服务实现与 services.yaml 文档不一致')

    def test_all_entity_ids_well_formed(self):
        """结构化契约：所有 ENTITY_* 常量必须是合法 HA 实体 ID 且平台前缀正确。"""
        c = (PKG / 'const.py').read_text(encoding='utf-8')
        ids = re.findall(r'^ENTITY_[A-Z_]+\s*=\s*"([^"]+)"', c, re.M)
        self.assertGreater(len(ids), 5)
        for eid in ids:
            self.assertRegex(eid, r'^(sensor|binary_sensor|calendar)\.workday_maintenance[a-z0-9_]*$',
                             f'实体 ID 格式异常：{eid}')
        self.assertEqual(len(ids), len(set(ids)), '实体 ID 有重复')

    def test_entity_ids_referenced_by_platforms(self):
        """每个实体 ID 常量都应被对应平台文件真正使用。"""
        c = (PKG / 'const.py').read_text(encoding='utf-8')
        pairs = re.findall(r'^(ENTITY_[A-Z_]+)\s*=\s*"([^"]+)"', c, re.M)
        platforms = ''.join(
            (PKG / f).read_text(encoding='utf-8')
            for f in ('sensor.py', 'binary_sensor.py', 'calendar.py')
        )
        for const_name, _eid in pairs:
            self.assertIn(const_name, platforms, f'{const_name} 未被任何平台使用')

    def test_two_pages_share_layer(self):
        for page in ('workday.html', 'maintenance.html'):
            html = (PKG / 'frontend' / page).read_text(encoding='utf-8')
            self.assertIn('shared.js', html)
            self.assertIn('shared.css', html)
            self.assertIn('M.onUpdate', html)
        shared = (PKG / 'frontend' / 'shared.js').read_text(encoding='utf-8')
        self.assertIn('subscribe_events', shared)
        self.assertIn('workday_maintenance_updated', shared)

    def test_no_inline_page_links(self):
        for page in ('workday.html', 'maintenance.html'):
            html = (PKG / 'frontend' / page).read_text(encoding='utf-8')
            self.assertNotIn('href="workday.html"', html)
            self.assertNotIn('href="maintenance.html"', html)
            self.assertNotIn('dueBadge', html)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertNotIn('.link{', css)

    def test_refresh_guard_present(self):
        shared = (PKG / 'frontend' / 'shared.js').read_text(encoding='utf-8')
        for token in ('setReady', 'installGuards', 'beforeunload',
                      "addEventListener('click', guard, true)"):
            self.assertIn(token, shared)
        # 加载骨架已抽到 shared.js 的 createLoader；页面只需调用它。
        self.assertIn('function createLoader', shared)
        self.assertIn('api.setReady(true)', shared)
        self.assertIn('api.setReady(false)', shared)
        self.assertIn('retryLoad()', shared)
        for page in ('workday.html', 'maintenance.html'):
            html = (PKG / 'frontend' / page).read_text(encoding='utf-8')
            self.assertIn('M.createLoader(', html)
            self.assertIn('function load() { return loader.load(); }', html)

    def test_project_tab_reset(self):
        html = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertIn('resetForms()', html)
        self.assertIn('if (target === slug)', html)
        self.assertIn('renderRecEntries(', html)
        self.assertIn("openRecForm(null)", html)
        self.assertNotIn('Number(this.value)', html)

    def test_item_name_vs_blank_click(self):
        html = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        # 点名称=编辑小项；点行空白=给该小项记一次新维护
        self.assertIn('data-itemname', html)
        self.assertIn("var nm = t.closest && t.closest('[data-itemname]')", html)
        self.assertIn("openItemForm(title.dataset.item)", html)
        self.assertIn("openRecForm(null, title.dataset.item)", html)
        # 聚焦单小项时标题不再叫“记录多项维护”
        self.assertIn('记录维护 · ', html)

    def test_options_flow_constructor(self):
        src = (PKG / 'config_flow.py').read_text(encoding='utf-8')
        self.assertIn('return MyWorkdayOptionsFlow()', src)
        self.assertIn('async_get_entry(self.handler)', src)

    def test_service_response_unwrap(self):
        shared = (PKG / 'frontend' / 'shared.js').read_text(encoding='utf-8')
        self.assertIn('x.service_response', shared)
        self.assertIn('x.response', shared)

    def test_workday_legacy_ui(self):
        html = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('FOLD_KEY', 'data-fold="todos"', 'applyFolds', 'contextmenu',
                      'touchstart', 'calYear', 'data-donegroup', 'cellMenu',
                      'todoSummary', 'customSummary'):
            self.assertIn(token, html)

    def test_maintenance_legacy_ui(self):
        html = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for token in ('id="projMask"', 'id="itemMask"', 'id="recMask"',
                      'id="unitBox"', 'syncUnit', 'autoSlug', 'data-item=',
                      '记录多项维护', 'mt-side', 'counterValue',
                      'data-recheck=', 'renderRecEntries(', 'id="recDelete"'):
            self.assertIn(token, html)
        for gone in ('projStep1', 'projStep2', 'projNext', 'projUnitLabel',
                     'data-baseline=', 'data-logone=', 'data-edit=', 'set_baseline',
                     'id="projMenu"', 'data-pm=', 'renderMenu(',
                     'id="logMask"', 'renderLogItems(', 'data-lognote',
                     'data-history=', 'expanded['):
            self.assertNotIn(gone, html)

    def test_layout_css_fixes(self):
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.mt-layout{display:flex;flex-direction:row;', css)
        self.assertIn('#overview{grid-template-columns:repeat(2,', css)
        self.assertNotIn('#overview{grid-template-columns:repeat(4,', css)

    def test_stats_follow_month_and_jump_today(self):
        html = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('function monthStats()', 'function jumpToday()',
                      'data-jump-today', '<div class="lbl">进度</div>',
                      'renderStats(); renderCal();'):
            self.assertIn(token, html)
        self.assertNotIn('dateLabel', html)
        self.assertNotIn('剩余/总数', html)
        self.assertNotIn('本月工作日', html)

    def test_next_special_day_merges_holidays_and_anniversaries(self):
        html = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('function nextSpecialDay()', '>距离 - ',
                      'S.workday.anniversaries', 'h.off || []'):
            self.assertIn(token, html)
        self.assertNotIn('next_holiday', html)

    def test_day_label_and_menu_modes(self):
        html = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('function dayLabel(', 'function baseWork(', 'function customMode('):
            self.assertIn(token, html)
        for gone in ('data-mday=', '算上班</button>',
                     '算休息</button>', '恢复安排</button>', 'function inlineEdit('):
            self.assertNotIn(gone, html)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertNotIn('.stat .sub2', css)
        self.assertIn('.stat .lbl.ellip', css)
        self.assertIn('.cell .d{font-size:19px', css)
        self.assertIn('.cal-head div{font-size:13px', css)

    def test_delete_project_confirmation_works(self):
        html = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertIn("armDel('project')", html)
        self.assertIn("$('projDelete').textContent = '确认删除这个项目'", html)
        self.assertIn("write('delete_project', { slug: target })", html)
        self.assertNotIn('var armed = deleteArmed;', html)

    def test_backend_next_special_day(self):
        h = {'off': {'2027-01-01'}, 'names': {'2027-01-01': '元旦'}, 'makeup': set()}
        anns = [{'name': '结婚纪念日', 'date': '11-16', 'repeat': True}]
        found = wd.next_special_day(dt.date(2026, 11, 15), h, anns)
        self.assertEqual(found['name'], '结婚纪念日')
        self.assertEqual(found['days'], 1)
        self.assertEqual(found['kind'], '纪念日')
        self.assertIn('next_event', (PKG / 'coordinator.py').read_text(encoding='utf-8'))
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        self.assertIn('workday.next_event', w)

    def test_menu_add_opens_modal_directly(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('data-madd', 'openAddForm(', 'switchAddType(', 'bindAddTypes(',
                      'data-addtype', 'id="todoTypes"', 'id="annTypes"',
                      'menu-existing', 'menu-add'):
            self.assertIn(token, w)
        self.assertNotIn('menuAdding', w)
        self.assertNotIn('data-mtype', w)
        self.assertNotIn('收起新增', w)
        self.assertLess(w.index('+ 新增</button>'), w.index('menu-existing'))
        self.assertNotIn('这天还没有安排', w)
        self.assertNotIn('id="thisM"', w)
        self.assertNotIn('<header class="bar">', w)

    def test_top_bars_removed_and_modal(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for token in ('id="projMask"', 'class="modal"', 'id="projClose"',
                      "$('projMask').hidden = false", 'projMask', 'resetForms'):
            self.assertIn(token, m)
        self.assertNotIn('<header class="bar">', m)
        self.assertNotIn('taskLabel', m)
        self.assertNotIn("$('projForm')", m)
        self.assertIn('.modal-mask', (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8'))

    def test_guards_and_validations(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for token in ('fingerprint(', '数据已被其他页面修改', 'armDel(', 'customDirty',
                      '请用日期控件选择日期'):
            self.assertIn(token, w)
        for token in ('请填写有效的计数值', '间隔天数要填', '维护日期要填',
                      'btn.disabled = true', '确认删除'):
            self.assertIn(token, m)

    def test_font_and_mobile_css(self):
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        for token in ('--fs:', '--tap:', 'var(--fs)', 'month-nav', 'month-center',
                      'nav-arrow', '@media (max-width:620px)', 'stat[data-jump-today]:hover'):
            self.assertIn(token, css)
        self.assertIn('.mt-side .tab.add', css)

    def test_workday_add_modals(self):
        html = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('id="todoMask"', 'id="annMask"', 'function openTodo(',
                      'function openAnn(', 'id="todoSave"', 'id="annSave"',
                      'closeTodo()', 'closeAnn()'):
            self.assertIn(token, html)
        self.assertNotIn('id="todoForm"', html)
        self.assertNotIn('id="annForm"', html)

    def test_slugify_cjk_fallback(self):
        mnt = _load('maintenance')
        self.assertTrue(mnt.slugify('卡罗拉').startswith('p_'))
        self.assertEqual(mnt.slugify('Corolla'), 'corolla')

    def test_todo_list_flat_sorted_and_click_to_edit(self):
        html = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('function todoWhen(', 'function todoRow(', 'class="sub todo-when"',
                      'data-todo-edit=', 'function openTodo(', 'editingTodo',
                      'data-donegroup'):
            self.assertIn(token, html)
        self.assertNotIn("groups = [['逾期'", html)
        self.assertNotIn("'未来 7 天'", html)
        self.assertIn('.todo-when', (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8'))

    def test_unified_edit_paths(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('data-mtodo-open=', 'data-mann-open=', 'data-ann-edit=',
                      'function openAnn(id, date)', 'function openTodo(id, date)',
                      'function saveAnn()'):
            self.assertIn(token, w)
        for gone in ('menuInput', 'menu-x', 'data-mclose', 'data-mtodo-done=',
                     'data-mtodo-edit=', 'data-mann-edit=',
                     'inlineEdit(', 'saveAnns('):
            self.assertNotIn(gone, w)
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertIn('id="projDelete"', m)
        for gone in ('id="projEdit"', 'data-pm="edit"', 'data-pm="log"', '导出 JSON 备份',
                     '导出当前项目 JSON', '导出 Markdown', 'projExportJson', 'projExportMd'):
            self.assertNotIn(gone, m)

    def test_backend_anniversary_repeat_types(self):
        today = dt.date(2026, 11, 15)
        cases = [
            ({'name': '周会', 'date': '2026-11-02', 'repeat': 'week'}, dt.date(2026, 11, 16)),
            ({'name': '月结', 'date': '2026-10-05', 'repeat': 'month'}, dt.date(2026, 12, 5)),
            ({'name': '季检', 'date': '2026-08-15', 'repeat': 'quarter'}, dt.date(2026, 11, 15)),
            ({'name': '结婚', 'date': '2026-11-16', 'repeat': 'year'}, dt.date(2026, 11, 16)),
            ({'name': '交付', 'date': '2027-03-18', 'repeat': 'none'}, dt.date(2027, 3, 18)),
            ({'name': '旧格式', 'date': '11-16', 'repeat': True}, dt.date(2026, 11, 16)),
        ]
        for item, expect in cases:
            self.assertEqual(wd.anniversary_next(item, today), expect, item['name'])

    def test_anniversary_form_controls(self):
        html = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('type="date" id="annDate"', '重复类型',
                      '<option value="week">每周</option>',
                      '<option value="month">每月</option>',
                      '<option value="quarter">每季度</option>',
                      '<option value="year">每年</option>',
                      'ANN_TYPES', 'function annNext(', 'function annOn('):
            self.assertIn(token, html)
        self.assertNotIn('每年重复', html)
        self.assertNotIn("value=\"1\">是</option>", html)

    def test_third_stat_jumps_to_next_event(self):
        html = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('data-jump-event', 'function jumpToEvent()', 'selectedCell = ev.date'):
            self.assertIn(token, html)
        self.assertIn('.stat[data-jump-event]:hover',
                      (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8'))

    def test_project_name_click_edits_and_modal_has_delete(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for token in ("if (target === slug) { if (view === 'settings') showView('normal'); else openForm(true); return; }",
                      'openForm(true)', 'id="projDelete"', 'function deleteProject()',
                      'id="projExtra"', 'function renderCounter()'):
            self.assertIn(token, m)
        for gone in ('id="projMenu"', 'contextmenu', 'id="projectHead"',
                     'id="projectType"', 'id="overview"', 'data-del=',
                     'id="projExportJson"', 'id="projExportMd"'):
            self.assertNotIn(gone, m)

    def test_history_rows_open_record_modal(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for token in ("$('history').onclick", 'data-rec=', 'function openRecForm(recordId, focusItem)',
                      'id="recEntries"', 'data-renote=', 'data-recheck=',
                      'function saveRecForm()', 'rec-row', '一次维护一行',
                      'function deleteRec()', 'renderRecEntries('):
            self.assertIn(token, m)
        for gone in ('data-redit=', 'data-rdel=', 'id="recItem"', 'id="recNote"',
                     '整次维护的流水，只读', 'data-renotedel=', 'data-history='):
            self.assertNotIn(gone, m)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.proj-title:hover', css)
        self.assertIn('.rec-row:hover', css)
        self.assertIn('.rec-ent', css)

    def test_removed_hints_and_menu_close_button(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for gone in ('sourceLabel', '放假数据：', 'holiday-cn 自动获取',
                     'menu-x', 'data-mclose'):
            self.assertNotIn(gone, w)
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertNotIn('离开输入框自动保存', m)
        self.assertIn('document.addEventListener(\'click\'', w)

    def test_project_tabs_horizontal_top(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertLess(m.index('class="mt-side"'), m.index('class="mt-main"'))
        self.assertIn('data-tab=', m)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        for token in ('.mt-layout{flex-direction:column}',
                      '.mt-side{width:100%;flex:none;flex-direction:row',
                      '.mt-side .tab.on{',
                      '.mt-side .tab{min-width:84px}'):
            self.assertIn(token, css)

    def test_interval_counter_hidden_without_project_counter(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertIn('id="itemIntervalBox" hidden', m)
        self.assertIn("$('itemIntervalBox').hidden = !p.need_counter", m)
        self.assertIn("p.need_counter && i && i.interval_counter != null", m)

    def test_unified_record_modal_modes(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for token in ("var fItem = focusItem ? (p.items || []).filter(function (x) { return x.id === focusItem; })[0] : null;",
                      "记录维护 · ", "M.call('log_service', data)", 'function collectRecForm()',
                      'function deleteRec()', '本次未记录', '取消勾选即从这次记录中移除'):
            self.assertIn(token, m)
        self.assertIn("openRecForm(null)", m)
        self.assertIn("openRecForm(row.dataset.rec)", m)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.rec-check', css)
        self.assertIn('.modal-actions', css)

    def test_single_item_record_hides_redundant_checkbox(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        # 聚焦单小项新记录：不再为那唯一的小项显示勾选框
        self.assertIn('var singleNew = focusItem && !rec;', m)
        self.assertIn("'<div class=\"rec-name\">' + M.esc(i.name) + '</div>'", m)
        # 收集逻辑改为按行遍历，无勾选框即视为已勾选
        self.assertIn("row.getAttribute('data-renoterow')", m)
        self.assertIn('var checked = cb ? cb.checked : true;', m)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.rec-name', css)

    def test_date_picker_whole_row_clickable(self):
        # 整行点击逻辑已集中在 shared.js 的 bindDateFields；页面只调用它。
        shared = (PKG / 'frontend' / 'shared.js').read_text(encoding='utf-8')
        self.assertIn('if (typeof el.showPicker ===', shared)
        self.assertNotIn('if (e.target === el) return;', shared)
        self.assertNotIn("el.addEventListener('click', open)", shared)
        for f in ('workday.html', 'maintenance.html'):
            html = (PKG / 'frontend' / f).read_text(encoding='utf-8')
            self.assertIn('M.bindDateFields()', html)

    def test_workday_stat_labels_simplified(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        # 今天卡片：只显示「今天」，不再带日期与星期
        self.assertIn("'<div class=\"lbl\">今天</div></div>'", w)
        self.assertNotIn("'今天 · ' + S.today", w)
        # 距离卡片：只显示名称，日期移到 title
        self.assertIn("M.esc(ev.name) + '</div>'", w)

    def test_project_plus_menu_and_export(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertIn('id="projPlus"', m)
        self.assertIn('id="pmMenu"', m)
        self.assertNotIn('id="projAdd"', m)
        self.assertNotIn('id="projImport"', m)
        self.assertIn("M.call('export_all'", m)
        # 导入/导出已移到设置页，＋菜单不再有这两项
        self.assertIn('id="setExport"', m)
        self.assertIn('id="setImport"', m)
        self.assertIn('导出全部数据 (.json)', m)
        self.assertNotIn('data-menu-act="export"', m)
        self.assertNotIn('data-menu-act="import"', m)
        # ＋ 直接新建，不再弹菜单
        self.assertIn("if (plus) { openForm(false); return; }", m)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.proj-menu', css)
        self.assertIn('.mt-side .tab.setting{', css)

    def test_import_projects_interface(self):
        init = (PKG / 'services.py').read_text(encoding='utf-8')
        self.assertIn('async def import_projects', init)
        self.assertIn('proj["history"] = histories', init)
        self.assertIn('isinstance(p.get("history"), list)', init)  # 全量 history 原样还原
        self.assertIn('it.get("id")', init)  # item id 原样保留
        self.assertIn('if isinstance(raw_projects, dict):', init)
        self.assertIn('(SERVICE_IMPORT_PROJECTS, import_projects)', init)
        sv = (PKG / 'services.yaml').read_text(encoding='utf-8')
        self.assertIn('import_projects:', sv)
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertIn("M.call('import_projects', { json: text }, true)", m)
        self.assertIn('id="importMask"', m)
        self.assertIn('id="importText"', m)
        self.assertIn('id="projPlus"', m)

    def test_delete_labels_are_explicit(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for token in ('删除这个项目', '删除这个小项', '删除这次记录'):
            self.assertIn(token, m)

    def test_menu_todo_checkbox_and_delete(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        self.assertIn("if (e && e.stopPropagation) e.stopPropagation();", w)
        for token in ('data-mtodo-check=', 'data-mtodo-del=', 'data-mann-del=',
                      "$('cellMenu').onchange", 'menu-check', 'saveTodos('):
            self.assertIn(token, w)
        self.assertIn('.menu .mrow input[type=checkbox]',
                      (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8'))

    def test_due_items_open_record_modal(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('id="dueMask"', 'id="dueInfo"', 'function openDueForm(pslug, itemId)',
                      'function saveDue()', 'data-mdueslug=', 'data-dueitem=',
                      "write('log_service', data)", "dueList').onclick",
                      'due-click', 'due-row'):
            self.assertIn(token, w)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.due-info', css)
        self.assertIn('.due-row:hover', css)

    def test_item_delete_moved_into_edit_modal(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for token in ('id="itemDelete" hidden', 'function deleteItem()',
                      "$('itemDelete').hidden = !id", '确认删除这个小项'):
            self.assertIn(token, m)
        self.assertNotIn("data-del=", m)

    def test_project_card_header_stripped(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for gone in ('id="projectHead"', 'id="projectType"', 'id="overview"',
                     'renderOverview(', '已到期</div>', '快到了</div>'):
            self.assertNotIn(gone, m)
        self.assertIn('function renderCounter()', m)

    def test_action_buttons_moved_to_items_head(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertNotIn('id="logOpen"', m)
        self.assertEqual(m.count('id="itemAdd"'), 1)
        self.assertIn('id="itemsHead"', m)
        self.assertIn('class="card-head items-head" id="itemsHead"', m)
        self.assertIn("$('itemsHead').onclick", m)
        self.assertIn("closest('#itemAdd')", m)
        self.assertIn('openRecForm(null)', m)

    def test_history_collapsed_by_default(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertIn('id="histHead"', m)
        self.assertIn('id="histBody" hidden', m)
        self.assertIn('id="histArrow"', m)
        self.assertIn('$(\'histHead\').onclick', m)
        self.assertIn('histOpen = !histOpen', m)
        self.assertIn("histOpen ? '▾' : '▸'", m)

    def test_date_field_picker_indicator(self):
        # bindDateFields 已抽到 shared.js；页面只需调用公共助手。
        shared = (PKG / 'frontend' / 'shared.js').read_text(encoding='utf-8')
        self.assertIn('function bindDateFields', shared)
        self.assertIn('el.showPicker()', shared)
        self.assertNotIn('if (e.target === el) return;', shared)
        for f in ('workday.html', 'maintenance.html'):
            h = (PKG / 'frontend' / f).read_text(encoding='utf-8')
            self.assertIn('M.bindDateFields()', h)
            self.assertNotIn('function bindDateFields', h)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('::-webkit-calendar-picker-indicator', css)
        self.assertIn('width:100%;height:100%', css)

    def test_item_own_records_clickable(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for token in ('function itemRecords(', 'data-recitem=', 'item-records',
                      'data-rectoggle=', 'itemOpen',
                      'item-meta-toggle', 'dueText(st, p)', '暂无维护记录',
                      'openRecForm(recordId, focusItem)', 'id="recFocus"',
                      '编辑这条维护记录', '移除这条记录', 'renderRecEntries(p, rec, focusItem)',
                      'if (!focus || e.item_id === focus)'):
            self.assertIn(token, m)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.item-records{', css)
        self.assertIn('.item-note{', css)
        self.assertNotIn('维护记录 (', m)

    def test_cell_tooltip_multiline(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('id="cellTip"', 'data-tip=', "parts.join('\\n')",
                      'function showTip(', 'function positionTip(',
                      "'mouseover'", "'mousemove'", "'mouseout'", 'tip-todo'):
            self.assertIn(token, w)
        self.assertNotIn("parts.join(' / ')", w)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.cell-tip{', css)
        self.assertIn('.cell-tip div+div{', css)

    def test_frontend_routing_and_ws_snapshot(self):
        init = (PKG / '__init__.py').read_text(encoding='utf-8')
        self.assertIn('FrontendFileView', init)
        self.assertNotIn('StaticPathConfig', init)
        self.assertIn('workday_maintenance/snapshot', init)
        shared = (PKG / 'frontend' / 'shared.js').read_text(encoding='utf-8')
        self.assertIn("type: 'workday_maintenance/snapshot'", shared)
        self.assertIn('snapshotViaWS', shared)
        manifest = json.loads((PKG / 'manifest.json').read_text(encoding='utf-8'))
        self.assertIn('websocket_api', manifest['dependencies'])

    def test_static_responses_set_correct_mime(self):
        """静态资源必须带正确 Content-Type，否则浏览器拒绝加载 CSS/JS（曾导致整页裸奔）。"""
        init = (PKG / '__init__.py').read_text(encoding='utf-8')
        self.assertIn('mime = "text/css" if filename.endswith(".css")', init)
        self.assertIn('else "application/javascript"', init)
        self.assertIn('content_type=mime', init)

    def test_add_modal_type_switch(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('openAddForm(date,', "openAddForm(S.today, 'todo')",
                      "openAddForm(S.today, 'ann')", '$(\'todoTypes\').hidden = !!id',
                      '$(\'annTypes\').hidden = !!id', "if (type === 'ann')"):
            self.assertIn(token, w)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.add-types{', css)
        self.assertIn('.add-types button.on{', css)

    def test_tooltip_flips_near_viewport_edge(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ("el.style.left = '0px'", 'if (left > maxLeft) left = px - w - 14;',
                      'if (top > maxTop) top = py - h - 14;', 'e.relatedTarget && cell.contains'):
            self.assertIn(token, w)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        for token in ('width:max-content', 'max-height:min(60vh,420px)',
                      'box-sizing:border-box', 'overflow:hidden'):
            self.assertIn(token, css)

    def test_item_notes_hidden_in_list(self):
        """列表页不显示小项备注与最近维护备注（数据仍在，编辑弹窗可查看）。"""
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for token in ('var last = recs[0] || null', 'dueText(st, p)',
                      '暂无维护记录', 'item-meta-static'):
            self.assertIn(token, m)
        self.assertNotIn('lastEntry', m)
        self.assertNotIn('lastNote', m)
        self.assertNotIn('item-note', m)
        # 备注输入仍保留在编辑弹窗里（数据可编辑）
        self.assertIn("id=\"itemNote\"", m)
        self.assertIn("data-renote=", m)
        self.assertNotIn('上次维护：', m)
        self.assertNotIn('var left = st.remaining_days', m)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.item-meta-static{', css)


class TestNewDaySensors(unittest.TestCase):
    def test_entity_ids_declared(self):
        c = const
        self.assertEqual(c.ENTITY_TODAY_REST, 'binary_sensor.workday_maintenance_today_rest')
        self.assertEqual(c.ENTITY_TODAY_DATE, 'sensor.workday_maintenance_today_date')
        self.assertEqual(c.ENTITY_TODAY_WEEKDAY, 'sensor.workday_maintenance_today_weekday')

    def test_binary_sensor_registers_rest(self):
        b = (PKG / 'binary_sensor.py').read_text(encoding='utf-8')
        self.assertIn('class TodayRestSensor', b)
        self.assertIn('TodayRestSensor(coordinator, entry)', b)
        self.assertIn('return not bool(self.wd.get("today_work"))', b)
        self.assertIn('ENTITY_TODAY_REST', b)

    def test_sensor_registers_date_and_weekday(self):
        s = (PKG / 'sensor.py').read_text(encoding='utf-8')
        self.assertIn('class TodayDateSensor', s)
        self.assertIn('class TodayWeekdaySensor', s)
        self.assertIn('TodayDateSensor(coordinator, entry)', s)
        self.assertIn('TodayWeekdaySensor(coordinator, entry)', s)
        self.assertIn('ENTITY_TODAY_DATE', s)
        self.assertIn('ENTITY_TODAY_WEEKDAY', s)
        self.assertIn('_WEEKDAY_CN', s)
        self.assertIn('d.isoweekday()', s)

    def test_weekday_mapping(self):
        """星期映射应对 2026-11-17（周二）给出正确的中文与数字。"""
        names = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
        d = dt.date(2026, 11, 17)
        self.assertEqual(d.weekday(), 1)
        self.assertEqual(names[d.weekday()], "星期二")
        self.assertEqual(d.isoweekday(), 2)


class TestItemStatusDisplay(unittest.TestCase):
    def test_items_sorted_by_status(self):
        """小项按状态排序：已到期置顶，同状态保持原顺序。"""
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertIn('var priority = { due: 0, soon: 1, unset: 2, ok: 3 };', m)
        self.assertIn('sorted.map(function (entry)', m)
        self.assertIn('a.idx - b.idx', m)
        self.assertIn('stateOf(i.id).status', m)

    def test_status_pill_removed(self):
        """状态标签已从卡片移除，改由整卡底色表达状态。"""
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertNotIn('pill(st.status)', m)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        for token in ('.mt-item.st-due{background:var(--danger-soft)}',
                      '.mt-item.st-soon{background:var(--warn-soft)}',
                      '.mt-item.st-ok{background:var(--ok-soft)}'):
            self.assertIn(token, css)
        # 未设基准不着色：保持中性底，不占用状态色
        self.assertIn('.mt-item.st-unset{background:var(--inset)}', css)
        self.assertIn('.mt-item.st-unset::before{opacity:.3}', css)


class TestHolidayRollover(unittest.TestCase):
    def test_cross_year_snapshot_refresh(self):
        """跨年补年份：每次刷新确保当年+次年快照在缓存，缺则线程池补读。"""
        src = (PKG / 'coordinator.py').read_text(encoding='utf-8')
        warm = src.split('async def async_warm_snapshots')[1].split('@property')[0]
        self.assertIn('missing = [y for y in years if y not in self._snapshot_cache]', warm)
        self.assertIn('async_add_executor_job(self._load_snapshot_files', warm)
        ensure = src.split('async def _ensure_holidays')[1].split('def _holidays_for')[0]
        self.assertIn('await self.async_warm_snapshots((now.year, now.year + 1))', ensure)


class TestServiceSplit(unittest.TestCase):
    def test_services_module_is_self_contained(self):
        """服务拆分契约：__init__ 只 setup/调度，服务实现全在 services.py 且 import 齐全。"""
        init = (PKG / '__init__.py').read_text(encoding='utf-8')
        svc = (PKG / 'services.py').read_text(encoding='utf-8')
        const = (PKG / 'const.py').read_text(encoding='utf-8')
        # __init__ 不再定义服务 handler
        self.assertNotIn('async def _async_register_services', init)
        self.assertIn('from .services import async_register_services', init)
        self.assertIn('async_register_services(hass, coordinator, notifier)', init)
        # services.py 有全部 handler
        self.assertIn('def async_register_services(', svc)
        for name in ('snapshot', 'set_day', 'import_projects', 'set_settings',
                     'export_all', 'log_service'):
            self.assertIn('async def ' + name, svc)
        # const 里所有服务常量都在 services.py import 且使用
        declared = set(__import__('re').findall(r'^SERVICE_\w+(?=\s*=)', const, __import__('re').M))
        used = set(__import__('re').findall(r'\b(SERVICE_\w+)\b', svc))
        self.assertEqual(declared, used)
        self.assertLess(len(init.splitlines()), 300, '__init__.py 应保持精简')


class TestCalendarGestures(unittest.TestCase):
    def test_day_toggle_in_menu_not_double_click(self):
        """切换班休移到菜单顶部按钮，单击只选中；只左右翻月。"""
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        # 菜单顶部状态切换按钮：按当前状态取反
        self.assertIn('data-mdayset', w)
        self.assertIn('标为休息', w)
        self.assertIn('标为上班', w)
        # 双击切换逻辑已删除（原 mode/w/custom_rest 判断不在 onclick 里）
        self.assertNotIn("? 'auto' : (classify", w)
        # 只左右翻月；垂直滑动交还页面滚动
        for token in ('function applySwipe', 'function startSwipe', 'function moveSwipe',
                      'function endSwipe', 'swipeThreshold', 'prevMonth', 'nextMonth',
                      "addEventListener('mousedown'", "addEventListener('touchmove'"):
            self.assertIn(token, w)
        self.assertIn('Math.abs(dx) > Math.abs(dy)', w)  # 水平占优才翻月
        # 四个折叠项收进「更多设置」面板
        self.assertIn('id="moreToggle"', w)
        self.assertIn('id="morePanel"', w)
        self.assertLess(w.index('id="morePanel"'), w.index('data-fold="todos"'))
        self.assertLess(w.index('data-fold="due"'), w.index('/morePanel'))
        self.assertIn('function applyMore', w)


class TestViewDomStructure(unittest.TestCase):
    def test_normal_view_wraps_items_and_history(self):
        """normalView 必须包住小项与历史区，否则切设置页时它们不会隐藏。"""
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        # 用栈验证 div/section 嵌套：items 与 history 打开时 normalView 必须在栈里
        import re
        main = m.split('<div class="mt-main">')[1].split('</main>')[0]
        stack, inside_ok = [], []
        for mo in re.finditer(r'<(/?)(div|section)\b([^>]*)>', main):
            close, tag, attrs = mo.groups()
            idm = re.search(r'id="([^"]+)"', attrs)
            ident = idm.group(1) if idm else None
            if not close:
                if ident in ('items', 'history'):
                    inside_ok.append(any(x == 'normalView' for x in stack))
                stack.append(ident or tag)
            elif stack:
                stack.pop()
        self.assertTrue(inside_ok, '没找到 items/history 区')
        self.assertTrue(all(inside_ok), '小项或历史区不在 normalView 内，切设置页时会漏显')
        self.assertEqual(len(stack), 0, '存在未闭合标签')


class TestSettingsNavigation(unittest.TestCase):
    def test_setting_tab_fixed_left_projects_always_visible(self):
        """设置按钮固定在项目栏最左；进设置页时项目标签照常显示（与主视图一致）。"""
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        side = m.split('function renderSide()')[1].split('function renderCounter')[0]
        self.assertLess(side.index('settingTab'), side.index('list.map('))
        self.assertIn("view === 'settings' ? ' on' : ''", side)
        self.assertNotIn('innerHTML = settingTab; return;', side)
        # 从设置页点项目标签应回台账
        self.assertIn("if (view === 'settings') showView('normal');", m)

    def test_import_returns_to_ledger(self):
        """从设置页发起导入，成功后回台账让用户看到结果。"""
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertIn("if (view === 'settings') showView('normal');", m)


class TestWritePathSafety(unittest.TestCase):
    def test_read_path_never_writes(self):
        """读路径零写盘：刷新不能覆盖用户并发写入（P0 竞态契约）。"""
        src = (PKG / 'coordinator.py').read_text(encoding='utf-8')
        read_fn = src.split('async def _async_update_data')[1].split('async def async_force_refresh')[0]
        self.assertNotIn('async_save', read_fn, '读路径不得写盘')
        self.assertIn('只在内存里过滤掉', read_fn)
        write_fn = src.split('async def async_mutate')[1].split('async def async_sync_due_todos')[0]
        self.assertIn('async with self._lock', write_fn)
        self.assertIn('await self.store.async_save(raw)', write_fn)
        self.assertIn('cleaned = wd.clean_todos', write_fn)


class TestReminderSettings(unittest.TestCase):
    def test_settings_store_isolated_from_archive(self):
        """提醒设置存独立 key，不进导出存档（密钥/去重不随存档外带）。"""
        store = (PKG / 'store.py').read_text(encoding='utf-8')
        self.assertIn('SETTINGS_KEY = "workday_maintenance.settings"', (PKG / 'const.py').read_text(encoding='utf-8'))
        self.assertIn('class SettingsStore', store)
        self.assertIn('def normalize_settings', store)
        self.assertIn('"advance_days": [7, 3, 1]', store)
        self.assertIn('"weekday": 6', store)
        self.assertIn('"time": "09:00"', store)

    def test_services_registered_and_declared(self):
        init = (PKG / 'services.py').read_text(encoding='utf-8')
        yaml = (PKG / 'services.yaml').read_text(encoding='utf-8')
        const = (PKG / 'const.py').read_text(encoding='utf-8')
        self.assertIn('SERVICE_GET_SETTINGS = "get_settings"', const)
        self.assertIn('SERVICE_SET_SETTINGS = "set_settings"', const)
        self.assertIn('(SERVICE_GET_SETTINGS, get_settings)', init)
        self.assertIn('(SERVICE_SET_SETTINGS, set_settings)', init)
        self.assertIn('get_settings:', yaml)
        self.assertIn('set_settings:', yaml)

    def test_notify_module_logic(self):
        n = (PKG / 'notify.py').read_text(encoding='utf-8')
        for token in ('class NotifyManager', 'async def check_anniversaries',
                      'async def check_maintenance', 'wd.anniversary_next',
                      'mnt.project_summary', 'pr.resolve_push', 'push_fingerprint',
                      '/api/push', 'Authorization',
                      'def _should_send', 'def _mark_sent'):
            self.assertIn(token, n)

    def test_schedule_scans_every_minute(self):
        """细项可覆盖时间，调度器不再按全局时间拦截，每分钟扫描下放判断。"""
        init = (PKG / '__init__.py').read_text(encoding='utf-8')
        self.assertIn('async def _check_reminders', init)
        self.assertIn('await notifier.check_anniversaries(now)', init)
        self.assertIn('await notifier.check_maintenance(now)', init)
        self.assertIn('get("anniversary") or {}).get("enabled")', init)
        self.assertIn('get("maintenance") or {}).get("enabled")', init)
        self.assertIn('async_track_time_change(hass, _check_reminders, second=0)', init)


if __name__ == '__main__':
    unittest.main()
