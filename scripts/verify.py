# -*- coding: utf-8 -*-
"""看板自检：语法检查 + 价格引擎断言 + 渲染健壮性冒烟测试。

用法：
    python verify.py                # 用当前目录已生成的 token-dashboard.html
    python verify.py --build        # 先生成再校验

依赖 Node.js（仅测试用，看板本身零依赖）。未装 Node 时只跑语法检查会跳过。
先给脚本本身做构造用例，确认它真能抓到断链/报错，再信它的"通过"。
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DOM_STUB = r"""
const CAPTURED={};
function mk(sel){return{_sel:sel,_html:'',textContent:'',value:'',style:{},dataset:{},clientWidth:800,
 classList:{toggle(){},add(){},remove(){},contains(){return false}},setAttribute(){},
 getAttribute(){return null},addEventListener(){},querySelector(){return mk('x')},
 querySelectorAll(){return []},closest(){return mk('c')},getBoundingClientRect(){return{height:300,width:800}},
 get innerHTML(){return this._html},set innerHTML(v){this._html=v;CAPTURED[this._sel]=v}};}
const CACHE={};
globalThis.document={body:mk('body'),querySelector(s){return CACHE[s]||(CACHE[s]=mk(s));},querySelectorAll(){return[];},addEventListener(){}};
globalThis.getComputedStyle=()=>({getPropertyValue:()=>'#000'});
globalThis.localStorage={getItem:()=>null,setItem(){}};
globalThis.ResizeObserver=class{observe(){}};
"""

ASSERTIONS = r"""
const at=(y,mo,d,h)=>(new Date(y,mo-1,d,h,0,0)).getTime();
let ok=0,bad=0,rb=0;
function eq(label,got,want){const pass=JSON.stringify(got)===JSON.stringify(want);pass?ok++:bad++;
 console.log((pass?'  \u2713 ':'  \u2717 ')+label+' \u2192 '+JSON.stringify(got)+(pass?'':'   期望 '+JSON.stringify(want)));}
function nanChk(label){const b=[];for(const k in CAPTURED)if(/NaN|undefined|Infinity/.test(CAPTURED[k]))b.push(k);rb++;
 console.log('  '+(b.length?'\u2717 ':'\u2713 ')+label+'：渲染 '+Object.keys(CAPTURED).length+' 容器，异常 '+(b.length?b.join(','):'无'));
 for(const k in CAPTURED)delete CAPTURED[k];return b.length;}

console.log('=== A. 价格匹配：最长前缀（不得依赖 key 顺序）===');
eq('glm-5.3-flash 应命中自身',priceRule('glm-5.3-flash',at(2026,9,11,15)).match,'glm-5.3-flash');
eq('glm-5.3',priceRule('glm-5.3',at(2026,9,11,15)).match,'glm-5.3');
eq('glm-5.2',priceRule('glm-5.2',at(2026,9,11,15)).match,'glm-5.2');
eq('glm-未知型号→glm 兜底',priceRule('glm-unknown-x',at(2026,9,11,15)).match,'glm');
eq('hy4-preview→hy4',priceRule('hy4-preview',at(2026,9,11,15)).match,'hy4');
eq('hy3-x→hy3',priceRule('hy3-x',at(2026,9,11,15)).match,'hy3');
eq('minimax-m3→minimax',priceRule('minimax-m3',at(2026,9,11,15)).match,'minimax');
eq('无匹配→全局兜底',priceRule('zzz-nope',at(2026,9,11,15)).match,undefined);

console.log('=== B. 按日期生效（flash 于北京时间 09-10 12:00 降价）===');
eq('09-05 走旧价',priceRule('deepseek-v4-flash',at(2026,9,5,3)).in,1.5);
eq('09-10 11:00 走旧价',priceRule('deepseek-v4-flash',at(2026,9,10,11)).in,1.5);
eq('09-10 13:00 走新价',priceRule('deepseek-v4-flash',at(2026,9,10,13)).in,1);
eq('09-11 走新价',priceRule('deepseek-v4-flash',at(2026,9,11,3)).in,1);
eq('旧价缓存读 0.05',priceRule('deepseek-v4-flash',at(2026,9,5,3)).cacheRead,0.05);

console.log('=== C. 峰谷分时（高峰 9-12 / 14-18）===');
eq('10:00 高峰',rateInfo('deepseek-v4-pro',at(2026,9,11,10)).peak,true);
eq('10:00 高峰输入价 9',rateInfo('deepseek-v4-pro',at(2026,9,11,10)).rate.in,9);
eq('13:00 空闲',rateInfo('deepseek-v4-pro',at(2026,9,11,13)).peak,false);
eq('13:00 空闲输入价 4.5',rateInfo('deepseek-v4-pro',at(2026,9,11,13)).rate.in,4.5);
eq('08:00 空闲',rateInfo('deepseek-v4-pro',at(2026,9,11,8)).peak,false);
eq('18:00 边界不算高峰',rateInfo('deepseek-v4-pro',at(2026,9,11,18)).peak,false);
eq('11:59 仍在高峰',rateInfo('deepseek-v4-pro',at(2026,9,11,11)).peak,true);
eq('GLM 无峰谷',rateInfo('glm-5.2',at(2026,9,11,10)).peak,false);

console.log('=== D. 成本计算 ===');
eq('GLM-5.2 命中1M+输出0.1M',+costOf(rateInfo('glm-5.2',at(2026,9,11,3)).rate,1e6,0,1e6,1e5).toFixed(4),4.8);
eq('DS-flash 空闲未命中1M+输出0.1M',+costOf(rateInfo('deepseek-v4-flash',at(2026,9,11,3)).rate,0,0,1e6,1e5).toFixed(4),1.4);

console.log('=== E. 健壮性：多窗口 + 会话下钻 ===');
let A=aggregate();
console.log('  30天：轮次 '+A.turns+' · 金额 ¥'+A.cost.toFixed(2)+' · 高峰 '+A.turnPeak+' 次 · 未核实价 '+A.estCount+' 次');
bad+=nanChk('默认 30 天窗口');
win=1;render();bad+=nanChk('1 天窗口');
win=0;customStart=(genMs/60000)+100000;customEnd=0;render();bad+=nanChk('空窗口（无数据）');
win=3650;customStart=0;render();bad+=nanChk('10 年超长窗口');
win=30;
try{
  const s=D.sess[0];state={ws:s.w,ses:s};
  renderPanel(aggregate());
  const rq=s.r.slice(0,50);
  drawScatter(rq);bad+=nanChk('会话下钻·散点');
  drawTable(rq);bad+=nanChk('会话下钻·明细表');
}catch(e){console.log('  \u2717 下钻异常 '+e.message);bad++;}

console.log('=== F. 使用习惯画像 ===');
win=30;render();
const hbAll=habitTiles(aggregate());
eq('画像卡片数',hbAll.length,6);
eq('无异常值',hbAll.filter(x=>/NaN|undefined|Infinity/.test(x.v+x.d)).length,0);
eq('连续天数 ≥ 最长连续',hbAll[0].v.match(/\d+/)[0]-0<=(hbAll[0].d.match(/最长连续 (\d+)/)||[0,0])[1]-0,true);
eq('活跃时段为 HH:00–HH:00',/^\d\d:00\u2013\d\d:00$/.test(hbAll[1].v),true);
eq('作息画像在四类内',['深夜党','上午型','午后型','晚间型'].indexOf(hbAll[2].v)>=0,true);
eq('会话节奏为中位口径',/^\d+ 轮 \/ 会话$/.test(hbAll[4].v),true);
win=0;customStart=(genMs/60000)+100000;customEnd=0;
const hbEmpty=habitTiles(aggregate());
eq('空窗口作息不给结论',hbEmpty[2].v,'—');
eq('空窗口活跃时段为占位',hbEmpty[1].v,'—');
eq('空窗口工作日/周末为占位',hbEmpty[3].v,'—');
win=30;customStart=0;

console.log('');
console.log(bad?('未通过：'+bad+' 项'):('全部通过（'+ok+' 项断言 + '+rb+' 组健壮性检查）'));
process.exit(bad?1:0);
"""


def find_node():
    for name in ("node", "/opt/homebrew/bin/node", "/usr/local/bin/node"):
        p = shutil.which(name) if not name.startswith("/") else (name if os.path.exists(name) else None)
        if p:
            return p
    base = os.path.expanduser("~/.workbuddy/binaries/node/versions")
    if os.path.isdir(base):
        for v in sorted(os.listdir(base), reverse=True):
            p = os.path.join(base, v, "bin", "node")
            if os.path.exists(p):
                return p
    return None


def main():
    ap = argparse.ArgumentParser(description="看板自检")
    ap.add_argument("--build", action="store_true", help="先生成看板再校验")
    ap.add_argument("--html", default=os.path.join(ROOT, "token-dashboard.html"))
    a = ap.parse_args()

    py = sys.executable
    if a.build:
        r = subprocess.run([py, os.path.join(HERE, "gen_dashboard.py"), "--out", a.html])
        if r.returncode:
            return r.returncode

    if not os.path.exists(a.html):
        sys.exit("找不到 %s，先跑 gen_dashboard.py 或加 --build" % a.html)

    with open(a.html, encoding="utf-8") as fh:
        html = fh.read()
    blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
    if len(blocks) != 2:
        sys.exit("预期 2 个 script 块，实际 %d 个" % len(blocks))

    node = find_node()
    if not node:
        sys.exit("未找到 Node.js，无法执行运行时自检（看板本身不需要 Node）")

    with tempfile.TemporaryDirectory() as td:
        js = os.path.join(td, "harness.js")
        with open(js, "w", encoding="utf-8") as fh:
            fh.write(DOM_STUB + "\n" + blocks[0] + "\n" + blocks[1] + "\n" + ASSERTIONS)
        # 语法检查（数据块与逻辑块分别校验，便于定位）
        for i, blk in enumerate(blocks):
            p = os.path.join(td, "blk%d.js" % i)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(blk)
            if subprocess.run([node, "--check", p]).returncode:
                sys.exit("第 %d 个 script 块语法错误" % (i + 1))
        print("语法检查：2 个 script 块均通过")
        return subprocess.run([node, js]).returncode


if __name__ == "__main__":
    sys.exit(main())
