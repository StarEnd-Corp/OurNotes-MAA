// 零副作用验证：把候选节点的 action 覆盖为 DoNothing，只跑识别，看当前画面命中哪个节点
const path = require('path');
const { MAA_BIN, ADB, ADDR, PROJECT } = require('./config');

process.chdir(MAA_BIN);
const maa = require(path.join(MAA_BIN, 'MaaNode.node'));

const CANDIDATES = ['ClickTapToStart', 'ClickLiveEntry', 'ClickFreeLive', 'ClickStart',
                    'ClickTeamFlow', 'ClickRecommendTeam', 'ClickLiveStart', 'ClickResultScreen',
                    'ClickStampClose', 'ClickNext', 'ClickRankUpOK'];

async function main() {
    const ctrl = new maa.AdbController(ADB, ADDR, '6', '7', '{}');
    const conn = await ctrl.post_connection().wait();
    console.log('连接 status=', conn.status, '(3000=成功)');

    const res = new maa.Resource();
    const b = await res.post_bundle(path.join(PROJECT, 'resource')).wait();
    console.log('资源 status=', b.status);

    const tskr = new maa.Tasker();
    tskr.add_sink((_, msg) => {
        if (typeof msg === 'object' && msg) {
            const lvl = msg.level || '';
            const txt = msg.message || JSON.stringify(msg);
            if (['Debug', 'Trace'].includes(lvl)) return;
            console.log(`  [${lvl}] ${txt}`);
        }
    });
    tskr.add_context_sink((_, msg) => {
        if (typeof msg === 'object' && msg && msg.msg && !['Debug','Trace'].includes(msg.level||'')) {
            console.log(`  [CTX] ${msg.msg}  name=${msg.name ?? ''}  ${msg.detail ? JSON.stringify(msg.detail).slice(0,200) : ''}`);
        }
    });
    tskr.controller = ctrl;
    tskr.resource = res;

    // 覆盖：候选节点只识别不点击，且不往下走；GrindStart 依次尝试
    const override = { GrindStart: { next: CANDIDATES } };
    for (const n of CANDIDATES) override[n] = { action: 'DoNothing', next: [] };

    console.log('\n--- 仅识别模式启动（不会点击） ---');
    const r = await tskr.post_task('GrindStart', override).wait();
    console.log('任务 status=', r.status, '(3000=成功即有节点命中)');
    process.exit(0);
}
main().catch(e => { console.error('异常', e); process.exit(1); });
