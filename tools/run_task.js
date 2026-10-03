// 真实执行一个任务（会点击），打印每个节点的命中过程
// 用法: node run_task.js <入口节点>
const path = require('path');
const { MAA_BIN, ADB, ADDR, PROJECT } = require('./config');

process.chdir(MAA_BIN);
const maa = require(path.join(MAA_BIN, 'MaaNode.node'));

// 让框架把识别结果（含 OCR 文本 text / 匹配分数 score）写进项目 debug/ 目录，与 MFAAvalonia 跑时一致；
// save_draw 额外把命中的识别框画在截图上存进日志目录（可视战报）
maa.Global.log_dir = path.join(PROJECT, 'debug');
maa.Global.debug_mode = true;
maa.Global.save_draw = true;

const entry = process.argv[2];
if (!entry) { console.error('用法: node run_task.js <入口节点>'); process.exit(1); }

async function main() {
    const t0 = Date.now();
    const ctrl = new maa.AdbController(ADB, ADDR, '6', '7', '{}');
    const conn = await ctrl.post_connection().wait();
    if (conn.status !== 3000) { console.error('连接失败 status=', conn.status); process.exit(1); }
    const res = new maa.Resource();
    res.add_sink((_, m) => { if (m && m.level === 'Error') console.error('[资源错误]', m.message); });
    const b = await res.post_bundle(path.join(PROJECT, 'resource')).wait();
    if (b.status !== 3000) { console.error('资源加载失败 status=', b.status); process.exit(1); }

    const tskr = new maa.Tasker();
    let last = null;
    tskr.add_context_sink((_, m) => {
        if (!m || typeof m !== 'object' || !m.msg) return;
        if (m.msg === 'Recognition.Succeeded' && m.name !== last) {
            const t = ((Date.now() - t0) / 1000).toFixed(1);
            console.log(`  [+${t}s] ✔ 命中节点 ${m.name}`);
            last = m.name;
        }
    });
    tskr.controller = ctrl;
    tskr.resource = res;

    console.log(`--- 开始执行任务 ${entry} ---`);
    const r = await tskr.post_task(entry).wait();
    const used = ((Date.now() - t0) / 1000).toFixed(1);
    console.log(`--- 任务结束 status=${r.status}（3000=成功） 用时 ${used}s ---`);
    process.exit(r.status === 3000 ? 0 : 1);
}
main().catch(e => { console.error('异常', e); process.exit(1); });
