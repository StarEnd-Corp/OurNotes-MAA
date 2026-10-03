// 通用「零点击」识别体检探针：只跑识别、绝不点击，一次跑完所有候选并输出 box/score
// 用法: node probe_nodes.js <入口节点> <候选节点1> <候选节点2> ...
// 链式设计：候选 i 命中后其 next 指向 i+1..N，于是整串候选都会被评估（不是命中第一个就结束）
const path = require('path');
const { MAA_BIN, ADB, ADDR, PROJECT } = require('./config');

process.chdir(MAA_BIN);
const maa = require(path.join(MAA_BIN, 'MaaNode.node'));

// 让框架把识别结果（含 OCR 文本 text / 匹配分数 score）写进项目 debug/ 目录，与 MFAAvalonia 跑时一致
maa.Global.log_dir = path.join(PROJECT, 'debug');
maa.Global.debug_mode = true;

const [entry, ...cands] = process.argv.slice(2);
if (!entry || !cands.length) { console.error('用法: node probe_nodes.js <入口> <候选...>'); process.exit(1); }

const seen = new Set();

function fmtDetail(d) {
    let out = '';
    if (Array.isArray(d.box) && d.box.some(v => v !== 0)) out += ` box=[${d.box.join(',')}]`;
    let det = d.detail;
    if (typeof det === 'string') { try { det = JSON.parse(det); } catch (e) { det = null; } }
    if (det && typeof det === 'object') {
        const cands2 = [det.best, det.best_result, ...(Array.isArray(det.all) ? det.all : []), ...(Array.isArray(det.filtered) ? det.filtered : [])].filter(Boolean);
        const best = cands2.find(x => typeof x.score === 'number' || typeof x.text === 'string') || cands2[0];
        if (best) {
            if (typeof best.score === 'number') out += ` score=${best.score.toFixed(4)}`;
            if (best.text) out += ` text="${best.text}"`;
        }
    }
    return out;
}

async function main() {
    const t0 = Date.now();
    const ctrl = new maa.AdbController(ADB, ADDR, '6', '7', '{}');
    const conn = await ctrl.post_connection().wait();
    console.log('连接 status=', conn.status, '(3000=成功)');
    const res = new maa.Resource();
    res.add_sink((_, m) => { if (m && m.level === 'Error') console.error('[资源解析错误]', m.message); });
    const b = await res.post_bundle(path.join(PROJECT, 'resource')).wait();
    console.log('资源 status=', b.status, '(3000=成功)');

    const tskr = new maa.Tasker();
    tskr.add_context_sink((_, m) => {
        if (!m || typeof m !== 'object' || !m.msg) return;
        if (m.msg !== 'Recognition.Succeeded' && m.msg !== 'Recognition.Failed') return;
        if (m.name === entry || seen.has(m.name + m.msg)) return;
        seen.add(m.name + m.msg);
        const t = ((Date.now() - t0) / 1000).toFixed(1).padStart(5);
        const mark = m.msg === 'Recognition.Succeeded' ? '✔ 命中  ' : '✘ 未命中';
        console.log(`  [+${t}s] ${mark} ${m.name}${m.msg === 'Recognition.Succeeded' ? fmtDetail(m.reco_details || {}) : ''}`);
    });
    tskr.controller = ctrl;
    tskr.resource = res;

    // 链式 override：每个候选只做识别(DoNothing)，next 指向后续候选，保证整串都被评估
    // 入口 timeout 收紧到 20s：否则无候选命中时入口会空转到原本的 300s
    const override = { [entry]: { next: cands, timeout: 20000 } };
    cands.forEach((n, i) => { override[n] = { action: 'DoNothing', timeout: 2000, enabled: true, next: cands.slice(i + 1) }; });

    console.log(`--- 入口=${entry}，候选 ${cands.length} 个（只识别不点击；链式评估全部候选） ---`);
    const r = await tskr.post_task(entry, override).wait();
    const hit = [...seen].filter(x => x.endsWith('Recognition.Succeeded')).length;
    console.log(`--- 任务 status=${r.status}，共 ${hit}/${cands.length} 个候选命中，用时 ${((Date.now() - t0) / 1000).toFixed(1)}s ---`);
    process.exit(0);
}
main().catch(e => { console.error('异常', e); process.exit(1); });
