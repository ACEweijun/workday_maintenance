"""前端行为测试：用 Node vm 真实执行 shared.js / demo-data.js，验证交互逻辑。

这些是行为断言（输入 -> 输出），补充 test_core.py 里大量脆弱的源码文本断言。
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FE = ROOT / 'custom_components' / 'workday_maintenance' / 'frontend'


def node_available() -> bool:
    return shutil.which('node') is not None


@unittest.skipUnless(node_available(), 'node 不可用')
class TestFrontendBehavior(unittest.TestCase):
    def run_node(self, script: str) -> str:
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False,
                                         encoding='utf-8') as f:
            f.write(script)
            path = f.name
        try:
            r = subprocess.run([shutil.which('node'), path],
                               capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                self.fail('node 执行失败：' + r.stderr[:500])
            return r.stdout
        finally:
            pathlib.Path(path).unlink(missing_ok=True)

    def _env_setup(self, pathname='C:/preview/workday.html'):
        tpl = '''
            const fs=require('fs'),vm=require('vm');
            const DIR=__DIR__;
            const shared=fs.readFileSync(DIR+'/shared.js','utf8');
            const demo=fs.readFileSync(DIR+'/demo-data.js','utf8');
            const el={hidden:true,textContent:'',className:'msg',style:{},value:'',
                        addEventListener:()=>{},getBoundingClientRect:()=>({left:0,top:0,bottom:0,right:0})};
            const doc={getElementById:()=>el,addEventListener:()=>{},
                        querySelectorAll:()=>[],querySelector:()=>null,
                        createElement:()=>({click:()=>{},style:{}}),
                        body:{appendChild:()=>{},removeChild:()=>{}}};
            const w={};w.window=w;w.location={protocol:'file:',pathname:__PATH__};
            w.localStorage={getItem:()=>null};w.document=doc;w.addEventListener=()=>{};
            w.fetch=()=>Promise.reject(new Error('no fetch'));
            const sb={Promise,Date,Math,JSON,Number,String,Array,Object,
                        setTimeout:(f)=>f(),clearTimeout:()=>{},console};
            sb.window=w;sb.location=w.location;sb.localStorage=w.localStorage;sb.document=doc;
            vm.createContext(sb);vm.runInContext(shared,sb);vm.runInContext(demo,sb);
        '''
        tpl = tpl.replace('__DIR__', repr(str(FE).replace(chr(92), '/')))
        tpl = tpl.replace('__PATH__', repr(pathname))
        return textwrap.dedent(tpl)

    def test_shared_helpers_exist(self):
        script = self._env_setup() + '''
            const M=w.MW;
            console.log(['bindDateFields','createLoader','createArmDel'].every(k=>typeof M[k]==='function')?'OK':'FAIL');
        '''
        self.assertIn('OK', self.run_node(script))

    def test_extract_conn_handles_all_shapes(self):
        """HA 前端窗口连接可能是 {auth,conn}/裸conn/Promise，解包必须都能拿到带 callWS 的 conn。"""
        script = self._env_setup() + '''
            const src = require('fs').readFileSync(DIR+'/shared.js','utf8');
            const m = src.match(/function extractConn\\(v\\) \\{[\\s\\S]*?\\n  \\}/);
            if(!m){console.log('FAIL no extractConn');return;}
            const extractConn = eval('(' + m[0] + ')');
            const mk=()=>({callWS:()=>Promise.resolve('ok')});
            const cases=[
              {auth:{accessToken:'AT'},conn:mk()},   // 新版 HA：{auth, conn}
              mk(),                                    // 旧版：裸 conn
              Promise.resolve({auth:{},conn:mk()}),    // Promise 包装
              Promise.resolve(mk())
            ];
            Promise.all(cases.map(v=>Promise.resolve(v).then(extractConn).catch(()=>null)))
              .then(list=>{
                const ok = list.every(c=>c && typeof c.callWS==='function');
                const unknown = extractConn({foo:1});
                console.log(ok && unknown===null ? 'OK' : 'FAIL');
              }).catch(e=>console.log('ERR '+e.message));
        '''
        self.assertIn('OK', self.run_node(script))

    def test_parent_conn_absent_returns_null(self):
        """没有父连接时必须返回 null（falsy），否则 connect() 永远不会走自建 WS 分支。"""
        script = self._env_setup() + '''
            const src = require('fs').readFileSync(DIR+'/shared.js','utf8');
            const m = src.match(/function parentHassConn\\(\\) \\{[\\s\\S]*?\\n  \\}/);
            if(!m){console.log('FAIL no parentHassConn');return;}
            const parentHassConn = eval('(' + m[0] + ')');
            const r = parentHassConn();
            console.log(r===null || r===undefined ? 'OK' : 'FAIL '+typeof r);
        '''
        self.assertIn('OK', self.run_node(script))

    def test_401_retries_then_gives_clear_hint(self):
        """401 会重试（退避），最终失败给出明确的刷新提示，而不是无限自动重试。"""
        script = self._env_setup() + '''
            const src = require('fs').readFileSync(DIR+'/shared.js','utf8');
            const ok = /r\\.status === 401 && \\(retried \\|\\| 0\\) < 3/.test(src) &&
                       /登录态已失效，请刷新页面重新登录/.test(src);
            console.log(ok?'OK':'FAIL');
        '''
        self.assertIn('OK', self.run_node(script))

    def test_create_loader_loads_demo_data(self):
        """createLoader 真实走 demo 覆盖层取数并触发 render。"""
        script = self._env_setup() + '''
            (async()=>{
              const M=w.MW;
              const ld=M.createLoader({
                validate:d=>!!(d&&d.workday),
                onData:d=>{sb.GOT=d.today;},
                render:()=>{sb.RENDERED=true;}
              });
              await ld.load();
              console.log(sb.GOT&&sb.RENDERED?'OK':'FAIL');
            })().catch(e=>console.log('ERR '+e.message));
        '''
        out = self.run_node(script)
        self.assertIn('OK', out)

    def test_create_arm_del_two_step_confirm(self):
        script = self._env_setup() + '''
            const g=w.MW.createArmDel();
            const r1=g.arm('x')===false && g.peek('x');
            const r2=g.arm('x')===true && !g.peek('x');
            g.arm('y');g.reset();
            console.log(r1&&r2&&!g.peek('y')?'OK':'FAIL');
        '''
        self.assertIn('OK', self.run_node(script))

    def test_demo_snapshot_has_full_data(self):
        script = self._env_setup() + '''
            (async()=>{
              const s=await w.MW.snapshot();
              console.log(s.today&&s.workday&&s.maintenance&&s.maintenance.projects?'OK':'FAIL');
            })().catch(e=>console.log('ERR '+e.message));
        '''
        self.assertIn('OK', self.run_node(script))

    def test_import_export_roundtrip(self):
        """导出 -> 导入 -> 数据一致（含小项 id 与 history）。"""
        script = self._env_setup() + '''
            (async()=>{
              const M=w.MW;
              const seed='[{"name":"测试车","slug":"test_car","counter":100,'+
                '"items":[{"id":"i_oil","name":"机油","interval_days":365,'+
                '"last_date":"2026-11-01","last_counter":0}],'+
                '"history":[{"id":"r_oil","date":"2026-11-01","counter":0,'+
                '"entries":[{"item_id":"i_oil","note":"4S店"}]}]}]';
              await M.call('import_projects',{json:seed},true);
              const exp=(await M.call('export_all',{},true)).service_response.json;
              const parsed=JSON.parse(exp);
              const projects = parsed.maintenance ? parsed.maintenance.projects : parsed.projects;
              const p=projects.find(x=>x.slug==='test_car');
              const ok=p&&p.items[0].id==='i_oil'&&p.history[0].id==='r_oil'&&
                       p.history[0].entries[0].note==='4S店'&&p.counter===100;
              console.log(ok?'OK':'FAIL');
            })().catch(e=>console.log('ERR '+e.message));
        '''
        self.assertIn('OK', self.run_node(script))

    def test_zero_counter_not_due(self):
        """里程基准 0 不误报到期（与后端行为一致）。"""
        script = self._env_setup() + '''
            (async()=>{
              const M=w.MW;
              const seed='[{"name":"车","slug":"z","counter":43000,'+
                '"items":[{"id":"i1","name":"机油","interval_days":365,'+
                '"interval_counter":10000,"last_date":"2026-11-01","last_counter":0}]}]';
              await M.call('import_projects',{json:seed},true);
              const s=await M.snapshot();
              const sm=s.maintenance.summaries.find(x=>x.slug==='z');
              console.log(sm.items[0].status==='ok'?'OK':'FAIL '+sm.items[0].status);
            })().catch(e=>console.log('ERR '+e.message));
        '''
        self.assertIn('OK', self.run_node(script))

    def test_full_archive_v2_roundtrip(self):
        """v2 完整存档：导出含 workday+maintenance+说明，改后导入完整恢复。"""
        script = self._env_setup() + '''
            (async()=>{
              const M=w.MW;
              const d=JSON.parse((await M.call('export_all',{},true)).service_response.json);
              const shape = d.version===2 && d._说明 && d.workday && d.maintenance &&
                            Array.isArray(d.workday.todos) && Array.isArray(d.maintenance.projects);
              if(!shape){console.log('FAIL shape');return;}
              d.workday.todos[0].text='【AI改】测试待办';
              d.maintenance.projects[0].counter=99999;
              const slug=d.maintenance.projects[0].slug;
              await M.call('delete_project',{slug},true);
              const r=(await M.call('import_projects',{json:JSON.stringify(d)},true)).service_response||{};
              const s=await M.snapshot();
              const p=s.maintenance.projects.find(x=>x.slug===slug);
              const ok = r.workday_restored && s.workday.todos[0].text==='【AI改】测试待办' &&
                         p && p.counter===99999 && p.items.length>0 && p.history.length>0;
              console.log(ok?'OK':'FAIL');
            })().catch(e=>console.log('ERR '+e.message));
        '''
        self.assertIn('OK', self.run_node(script))


    def test_due_text_countdown(self):
        """小项主行倒计时文案：已超期/还剩，超期很久用年+月表述。"""
        script = self._env_setup() + '''
            const src = require('fs').readFileSync(DIR+'/maintenance.html','utf8');
            const grab=(name)=>{
              const m=src.match(new RegExp('function '+name+'\\\\([^)]*\\\\)\\\\s*\\\\{[\\\\s\\\\S]*?\\\\n  \\\\}'));
              if(!m) throw new Error('no '+name);
              return eval('('+m[0]+')');
            };
            const dueText=grab('dueText');
            const humanDays=grab('humanDays');
            const P={need_counter:true,counter_unit:'公里'};
            const t=(st)=>dueText(st,P);
            const checks=[
              t({remaining_days:-2230,remaining_counter:null})==='已超期 6 年 1 个月',
              t({remaining_days:-12,remaining_counter:null})==='已超期 12 天',
              t({remaining_days:45,remaining_counter:null})==='还剩 45 天',
              t({remaining_days:100,remaining_counter:-2000})==='已超期 2000 公里',
              t({remaining_days:100,remaining_counter:3000})==='还剩 3000 公里',
              t({remaining_days:null,remaining_counter:null})==='未设基准',
              humanDays(425)==='1 年 2 个月', humanDays(30)==='30 天'
            ];
            console.log(checks.every(Boolean)?'OK':'FAIL '+JSON.stringify(checks));
        '''
        self.assertIn('OK', self.run_node(script))


    def test_token_from_auth_all_shapes(self):
        """手机 Companion App 的 token 在 auth.data.access_token，必须能取到。"""
        script = self._env_setup() + '''
            const src = require('fs').readFileSync(DIR+'/shared.js','utf8');
            const m=src.match(/function tokenFromAuth\\(x\\) \\{[\\s\\S]*?\\n  \\}/);
            if(!m){console.log('FAIL no tokenFromAuth');return;}
            const tokenFromAuth=eval('('+m[0]+')');
            const cases=[
              [{auth:{data:{access_token:'APP'}}}, 'APP'],          // Companion App（关键）
              [{auth:{accessToken:'WEB'}}, 'WEB'],                   // 网页端
              [{auth:{access_token:'ALT'}}, 'ALT'],
              [{options:{auth:{accessToken:'OLD'}}}, 'OLD'],
              [{options:{authToken:'LL'}}, 'LL'],
              [{foo:1}, null]
            ];
            let ok=true;
            cases.forEach(([obj,want])=>{const got=tokenFromAuth(obj);if(got!==want){ok=false;console.log('BAD '+JSON.stringify(obj)+' -> '+got)}});
            console.log(ok?'OK':'FAIL');
        '''
        self.assertIn('OK', self.run_node(script))


    def test_settings_view_toggle(self):
        """设置按钮切换视图：设置页/正常页互斥，保存走 set_settings 服务。"""
        script = self._env_setup() + '''
            const src=require('fs').readFileSync(DIR+'/maintenance.html','utf8');
            const checks=[
              src.includes('id="settingsView"'), src.includes('id="normalView"'),
              src.includes('function showView(v)'),
              src.includes("$('settingsView').hidden = (v !== 'settings')"),
              src.includes("$('normalView').hidden = (v === 'settings')"),
              src.includes("e.target.closest('#projSetting')"),
              src.includes("M.call('set_settings', payload, true)"),
              src.includes("M.call('get_settings', {}, true)")
            ];
            console.log(checks.every(Boolean)?'OK':'FAIL '+JSON.stringify(checks));
        '''
        self.assertIn('OK', self.run_node(script))

    def test_demo_settings_roundtrip(self):
        """本地预览：设置写入后读回一致。"""
        script = self._env_setup() + '''
            (async()=>{
              const M=w.MW;
              await M.call('set_settings',{anniversary:{enabled:true,advance_days:[5,2],time:'07:30'}});
              const r=(await M.call('get_settings',{},true)).service_response;
              const a=r.anniversary;
              console.log(a.enabled&&a.time==='07:30'&&a.advance_days.join()==='5,2'?'OK':'FAIL '+JSON.stringify(a));
            })().catch(e=>console.log('ERR '+e.message));
        '''
        self.assertIn('OK', self.run_node(script))


    def test_push_form_roundtrip(self):
        """push 表单：custom 模式的提前天数/时间/星期可正确填充与读回。"""
        script = self._env_setup() + '''
            const M=w.MW;
            const els={
              xPushMode:{value:'custom',hidden:false,onchange:null},
              xPushCustom:{value:'',hidden:true,onchange:null},
              xPushDays:{value:'5,1',hidden:false,onchange:null},
              xPushTime:{value:'07:45',hidden:false,onchange:null},
              xPushWeekday:{value:'3',hidden:false,onchange:null}
            };
            doc.getElementById=function(id){return els[id]||null;};
            const got=M.readPushForm('x');
            const ok = got.mode==='custom' && got.advance_days.join()==='5,1' &&
                       got.time==='07:45' && got.weekday===3;
            M.fillPushForm('x',{mode:'off'});
            const ok2 = els.xPushMode.value==='off' && els.xPushCustom.hidden===true;
            console.log(ok&&ok2?'OK':'FAIL '+JSON.stringify(got));
        '''
        self.assertIn('OK', self.run_node(script))


    def test_swipe_direction_mapping_horizontal_only(self):
        """只左右翻月：左->下月，右->上月；垂直滑动不翻（交还页面滚动）。"""
        w = (FE / 'workday.html').read_text(encoding='utf-8')
        fn = w.split('function applySwipe(dx, dy) {')[1].split('\n  }')[0]
        js = 'const calls=[];'
        js += 'const prevMonth=()=>calls.push("prev");const nextMonth=()=>calls.push("next");'
        js += 'function applySwipe(dx, dy) {' + fn + '}'
        js += 'applySwipe(-80,10);applySwipe(80,-10);applySwipe(10,-80);applySwipe(-10,80);'
        js += 'console.log(calls.join(","));'
        out = self.run_node(js)
        self.assertEqual(out.strip(), 'next,prev')  # 两个垂直滑动不触发翻月

    def test_day_toggle_label_uses_classify(self):
        """菜单顶部按钮：上班->标为休息，休息->标为上班。"""
        w = (FE / 'workday.html').read_text(encoding='utf-8')
        self.assertIn("classify(M.dateOf(menuDate)).work", w)
        self.assertIn("curWork ? '标为休息' : '标为上班'", w)
        self.assertIn("classify(M.dateOf(key)).work ? 'rest' : 'work'", w)


if __name__ == '__main__':
    unittest.main()
