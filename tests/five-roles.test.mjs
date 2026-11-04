import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { ROLES, RULES_VERSION, requirementsForDay, generatePeriod, calculateStats } from '../static/scheduler.js';
import { buildScheduleWorkbookBytes, buildScheduleWorkbook, MIME_TYPE } from '../static/excel.js';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const configContext = { window: {} };
vm.runInNewContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], configContext);
const config = JSON.parse(JSON.stringify(configContext.window.SCHEDULER_CONFIG));
const dateAt = i => new Date(Date.UTC(2026, 10, 1 + i)).toISOString().slice(0, 10);
const day = (i = 0, type = 'NORMAL', requirements = {}) => ({ date: dateAt(i), day_type: type, requirements });
const zeros = Object.fromEntries(ROLES.map(role => [role, 0]));
const unrestricted = n => ({ employees: Array.from({ length: n }, (_, i) => `員工${i}`) });
function checkResult(result, vacations, cfg) {
  for (const row of result.schedule) {
    const counts = { ...zeros };
    for (const [name, role] of Object.entries(row.assignment)) {
      assert.ok(ROLES.includes(role));
      assert.ok(!(vacations[name] || []).includes(row.date));
      assert.ok((cfg.restrictedRoles?.[name] || ROLES).includes(role));
      counts[role]++;
    }
    assert.deepEqual(counts, row.requirements);
  }
  for (const stat of result.stats.employees) {
    assert.equal(Object.values(stat.role_counts).reduce((a,b) => a+b, 0), stat.assigned_days);
    assert.equal(stat.assigned_days + stat.unassigned_days, stat.available_days);
    for (const role of ROLES) assert.ok(Number.isFinite(stat.role_percentages[role]));
  }
}

test('5–12 人逐一核對獨立需求；一般與大日相同', () => {
  const expected = {
    5: [1,0,0,2,2], 6: [1,1,0,2,2], 7: [1,1,1,2,2], 8: [1,1,2,2,2],
    9: [1,1,2,3,2], 10: [1,1,2,4,2], 11: [1,1,2,5,2], 12: [1,1,2,6,2],
  };
  for (const [n, values] of Object.entries(expected)) {
    for (const type of ['NORMAL','BIG']) {
      const cfg = unrestricted(Number(n));
      const result = generatePeriod([day(0,type)], {}, 1, cfg);
      assert.deepEqual(Object.values(result.schedule[0].requirements), values);
      assert.equal(Object.keys(result.schedule[0].assignment).length, Number(n));
      checkResult(result, {}, cfg);
    }
  }
});

test('0–4 人自動日提示改用其他；停爐與自訂仍可少於5人', () => {
  for (let n=0;n<5;n++) {
    for (const type of ['NORMAL','BIG']) assert.throws(() => generatePeriod([day(0,type)],{},1,unrestricted(n)), /少於 5 人.*其他/);
    assert.deepEqual(generatePeriod([day(0,'OFF')],{},1,unrestricted(n)).schedule[0].assignment, {});
    const custom = generatePeriod([day(0,'CUSTOM',{ a:n ? 1:0 })],{},1,unrestricted(n));
    checkResult(custom,{},unrestricted(n));
  }
});

test('自訂五崗位、留守與非法需求', () => {
  const cfg=unrestricted(8);
  const req={ A:1,a:1,B:1,C:1,D:1 };
  const result=generatePeriod([day(0,'CUSTOM',req)],{},7,cfg);
  assert.deepEqual(result.schedule[0].requirements,req);
  assert.equal(result.schedule[0].unassigned.length,3);
  checkResult(result,{},cfg);
  for (const invalid of [{a:-1},{D:1.5},{D:9}]) assert.throws(()=>requirementsForDay(day(0,'CUSTOM',invalid),8));
});

test('天立在慶排D合法，A及a均禁止；資格不足仍報無解', () => {
  for (const name of ['天立','在慶']) {
    assert.deepEqual(config.restrictedRoles[name],['B','C','D']);
    const cfg={...config,employees:[name]};
    assert.equal(generatePeriod([day(0,'CUSTOM',{D:1})],{},1,cfg).schedule[0].assignment[name],'D');
    for (const role of ['A','a']) assert.throws(()=>generatePeriod([day(0,'CUSTOM',{[role]:1})],{},1,cfg),/無法滿足/);
  }
});

test('一般員工前日C：A/a同優先，D其次，C懲罰；大日放大且受限員工不套用',()=>{
  const source=readFileSync(new URL('../static/scheduler.js',import.meta.url),'utf8').replace(/^export /gm,'');
  const ctx=vm.createContext({});vm.runInContext(source,ctx);
  const score=(role,type,restricted=false,previous='C')=>{
    ctx.input={name:'甲',role,dayType:type,previousAssignment:{甲:previous},roleCounts:{甲:{...zeros}},roleOpportunities:{甲:Object.fromEntries(ROLES.map(r=>[r,1]))},assignedCounts:{甲:0},availabilityCounts:{甲:1},customDay:false,tieNoise:0,config:restricted?{restrictedRoles:{甲:['B','C','D']}}:{}};
    return vm.runInContext('optionScore(input)',ctx);
  };
  for(const type of ['NORMAL','BIG']) {
    assert.equal(score('A',type),score('a',type));
    assert.ok(score('A',type)>score('D',type));
    assert.ok(score('D',type)>score('B',type));
    assert.ok(score('B',type)>score('C',type));
    assert.equal(score('C',type,true),-4);
  }
  assert.ok(score('A','BIG')>score('A','NORMAL'));
  assert.ok(score('C','BIG')<score('C','NORMAL'));
  for(const name of ['天立','在慶']) {
    assert.ok(config.rolePreferences[name].C>config.rolePreferences[name].B);
    assert.ok(config.rolePreferences[name].C>config.rolePreferences[name].D);
  }
  assert.ok(score('A','NORMAL',false,'B')>score('C','NORMAL',false,'B'));
  assert.ok(score('C','NORMAL',false,'B')>score('B','NORMAL',false,'B'));
});

let sample;
test('40個四週場景：輪休8/9/10天、跨月、大日、停爐、自訂、種子重現', () => {
  for (let scenario=0;scenario<40;scenario++) {
    const days=Array.from({length:28},(_,i)=>day(i));
    days[3].day_type='BIG'; days[9].day_type='OFF';
    days[18]=day(18,'CUSTOM',{B:1,D:1});
    const candidates=days.filter(d=>d.day_type!=='OFF').map(d=>d.date);
    const vacations=Object.fromEntries(config.employees.map((name,i)=>{
      const count=8+(scenario+i)%3;
      return [name,Array.from({length:count},(_,j)=>candidates[(i*2+scenario+j)%27])];
    }));
    const result=generatePeriod(days,vacations,1000+scenario,config);
    checkResult(result,vacations,config);
    assert.equal(result.rules_version,RULES_VERSION);
    assert.deepEqual(generatePeriod(days,vacations,1000+scenario,config),result);
    for(const name of ['天立','在慶']) {
      const stat=result.stats.employees.find(s=>s.name===name);
      assert.equal(stat.role_counts.A,0); assert.equal(stat.role_counts.a,0);
    }
    if(scenario===0) sample={result,vacations};
  }
});

test('A/a分開統計；休假、停爐、未排與其他崗位中斷連B', () => {
  const roles=['B','B','a','B',null,'B','OFF','B','A','D','C','B'];
  const schedule=roles.map((role,i)=>({...day(i,role==='OFF'?'OFF':'CUSTOM'),assignment: role && role!=='OFF'?{甲:role}:{}}));
  const stat=calculateStats(schedule,{}, {employees:['甲']}).employees[0];
  assert.equal(stat.role_counts.A,1);assert.equal(stat.role_counts.a,1);assert.equal(stat.role_counts.D,1);
  assert.equal(stat.consecutive_b_occurrences,1);assert.equal(stat.longest_b_streak,2);assert.equal(stat.ending_b_streak,1);
  const interrupted=calculateStats([day(0),day(1),day(2)].map((d,i)=>({...d,assignment:{甲:'B'}})),{甲:[dateAt(1)]},{employees:['甲']}).employees[0];
  assert.equal(interrupted.consecutive_b_occurrences,0);
});

test('連C：三連算兩次；休假、停爐、未排和轉崗均中斷',()=>{
  for(const separator of ['A','a','B','D','OFF',null,'VACATION']) {
    const values=['C','C','C',separator,'C'];
    const schedule=values.map((r,i)=>({...day(i,r==='OFF'?'OFF':'CUSTOM'),assignment:r&&r!=='OFF'&&r!=='VACATION'?{甲:r}:{}}));
    const vacations=separator==='VACATION'?{甲:[dateAt(3)]}:{};
    const stat=calculateStats(schedule,vacations,{employees:['甲']}).employees[0];
    assert.equal(stat.consecutive_c_occurrences,2);
    assert.equal(stat.longest_c_streak,3);
    assert.equal(stat.ending_c_streak,1);
  }
});

function appContext(saved) {
  const nodes=new Map();
  const node=()=>({value:'',innerHTML:'',textContent:'',disabled:true,hidden:true,style:{},dataset:{},classList:{add(){},remove(){},toggle(){}},addEventListener(){},scrollIntoView(){},querySelector(){return null;}});
  const element=id=>{ if(!nodes.has(id)) nodes.set(id,node()); return nodes.get(id); };
  const stored=new Map(saved?[['crematorium-scheduler-offline-v1',JSON.stringify(saved)]]:[]);
  const navigator={onLine:true};
  const window={SCHEDULER_CONFIG:config,navigator,addEventListener(){},setTimeout(){return 0;},clearTimeout(){}};
  const context=vm.createContext({window,navigator,document:{getElementById:element,querySelector:element},localStorage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v)},generatePeriod,ROLES,RULES_VERSION,buildScheduleWorkbook,MIME_TYPE,Date,console,Set,Blob});
  element('connection-status').parentElement=node();
  const source=readFileSync(new URL('../static/app.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'');
  vm.runInContext(source,context);
  return {context,nodes,stored};
}

test('舊版保存升級：保留日期休假、自訂舊需求補a/D零，清掉舊結果',()=>{
  const saved={version:1,employees:config.employees,days:Array.from({length:28},(_,i)=>({date:dateAt(i),dayType:i===18?'CUSTOM':'NORMAL',requirements:{A:0,B:2,C:0}})),vacations:{子紘:[dateAt(1)]},activeEmployee:'子紘',lastResult:{schedule:Array(28).fill({})},lastPayload:{seed:1}};
  const app=appContext(saved);
  assert.equal(vm.runInContext('state.days.length',app.context),28);
  assert.equal(vm.runInContext('state.vacations["子紘"].has("2026-11-02")',app.context),true);
  assert.equal(vm.runInContext('state.days[18].requirements.a + state.days[18].requirements.D',app.context),0);
  assert.equal(vm.runInContext('state.lastResult',app.context),null);
  assert.ok(app.nodes.get('toast').textContent.includes('重新產生'));
  assert.ok(app.nodes.get('days-grid').innerHTML.includes('data-role="a"'));
  assert.ok(app.nodes.get('days-grid').innerHTML.includes('data-role="D"'));
  assert.equal(app.nodes.get('export-btn').disabled,true);
});

test('新版結果還原、五張均衡卡、統計表頭與自訂加總',()=>{
  const saved={version:1,employees:config.employees,days:sample.result.schedule.map(d=>({date:d.date,dayType:d.day_type,requirements:d.requirements})),vacations:sample.vacations,lastResult:sample.result,lastPayload:{vacations:sample.vacations}};
  const app=appContext(saved);
  assert.equal((app.nodes.get('balance-cards').innerHTML.match(/class="balance-card"/g)||[]).length,5);
  const stats=app.nodes.get('stats-table').innerHTML;
  for(const role of ROLES) assert.ok(stats.includes(`<th>${role}</th>`));
  assert.equal(app.nodes.get('export-btn').disabled,false);
  assert.deepEqual(JSON.parse(JSON.stringify(vm.runInContext('roleCell({day_type:"NORMAL",vacations:[],assignment:{甲:"a"}},"甲")',app.context))),['a','role-small-a']);
  vm.runInContext('state.days[0].dayType="CUSTOM"; state.days[0].requirements={A:0,a:12,B:0,C:0,D:12}',app.context);
  assert.ok(vm.runInContext('customDayErrors().length',app.context)>0);
});

test('Excel包含五崗位與五種比例，產生供人工檢查的結果',()=>{
  const bytes=buildScheduleWorkbookBytes(sample.result,sample.vacations,config);
  const xml=new TextDecoder().decode(bytes);
  for(const label of ['a比例','D比例','連C次數','A1:U15','A1:Q29']) assert.ok(xml.includes(label),label);
  assert.ok(!xml.includes('undefined'));
  const output=new URL('../../work/five-roles-validation-20261104/',import.meta.url);
  mkdirSync(output,{recursive:true});
  writeFileSync(new URL('sample.xlsx',output),bytes);
  writeFileSync(new URL('sample.json',output),JSON.stringify(sample,null,2));
});
