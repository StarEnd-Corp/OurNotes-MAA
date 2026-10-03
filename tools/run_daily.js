// 依次执行多个任务（默认 = 开机自检 + 三个每日领取），逐任务打印命中序列与状态，最后给汇总
// 用法: node tools/run_daily.js                      // 默认 LaunchGame TWGPoints TWGDaily TWGLiveBonus
//       node tools/run_daily.js TWGPoints TWGDaily   // 只跑指定任务
const path = require('path');
const { MAA_BIN, ADB, ADDR, PROJECT } = require('./config');

process.chdir(MAA_BIN);
const maa = require(path.join(MAA_BIN, 'MaaNode.node'));

// 识别结果（含 OCR 文本/匹配分数）写进项目 debug/，与 GUI 一致
maa.Global.log_dir = path.join(PROJECT, 'debug');
maa.Global.debug_mode = true;

const DEFAULT_TASKS = ['LaunchGame', 'TWGPoints', 'TWGDaily', 'TWGLiveBonus'];
const tasks = process.argv.slice(2).length ? process.argv.slice(2) : DEFAULT_TASKS;

const STATUS = { 3000: '成功', 4000: '失败', 2000: '运行中' };

async function main() {
    const ctrl = new maa.AdbController(ADB, ADDR, '6', '7', '{}');
    const conn = await ctrl.post_connection().wait();
    if (conn.status !== 3000) { console.error('连接失败 status=', conn.status); process.exit(1); }
    const res = new maa.Resource();
    const b = await res.post_bundle(path.join(PROJECT, 'resource')).wait();
    if (b.status !== 3000) { console.error('资源加载失败 status=', b.status); process.exit(1); }

    const summary = [];
    for (const entry of tasks) {
        const t0 = Date.now();
        const tskr = new maa.Tasker();
        const hits = [];
        tskr.add_context_sink((_, m) => {
            if (!m || typeof m !== 'object' || !m.msg) return;
            if (m.msg === 'Recognition.Succeeded' && m.name !== hits[hits.length - 1]) hits.push(m.name);
        });
        tskr.controller = ctrl;
        tskr.resource = res;
        console.log(`\n===== 任务 ${entry} =====`);
        const r = await tskr.post_task(entry).wait();
        const used = ((Date.now() - t0) / 1000).toFixed(1);
        hits.forEach((n, i) => console.log(`  ${String(i + 1).padStart(2)}. ${n}`));
        console.log(`  → status=${r.status} (${STATUS[r.status] || '?'}) 用时 ${used}s`);
        summary.push({ entry, status: r.status, hits: hits.length, used });
    }

    console.log('\n===== 汇总 =====');
    for (const s of summary) {
        const mark = s.status === 3000 ? '✅' : '❌';
        console.log(`  ${mark} ${s.entry.padEnd(14)} status=${s.status} 命中节点 ${s.hits} 个 用时 ${s.used}s`);
    }
    const failed = summary.filter(s => s.status !== 3000).length;
    console.log(`\n结果：${summary.length - failed}/${summary.length} 个任务成功`);
    process.exit(failed ? 1 : 0);
}
main().catch(e => { console.error('异常', e); process.exit(1); });
