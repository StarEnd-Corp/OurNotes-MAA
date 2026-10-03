// MaaFramework 挂机脚本（Node 驱动，绕开交互式 MaaPiCli）
// 用法：node run.js [循环次数，默认无限]
const path = require('path');
const { MAA_BIN, ADB_PATH, ADB_ADDR, PROJECT } = require('./tools/config');

// MaaNode.node 依赖同目录 DLL，需先切工作目录
process.chdir(MAA_BIN);
const maa = require(path.join(MAA_BIN, 'MaaNode.node'));

console.log('[MaaFramework]', maa.Global?.version ?? maa.version);

async function main() {
    const maxRounds = parseInt(process.argv[2] || '0', 10); // 0 = 无限

    // 创建 ADB 控制器：截图 Encode(4)=screencap -p，输入 AdbShell(1)，兼容性最佳
    const ctrl = new maa.AdbController(ADB_PATH, ADB_ADDR, "4", "1", "{}");
    ctrl.add_sink((_, msg) => {
        if (typeof msg === 'object' && msg) {
            const level = msg.level ?? '';
            const text = msg.message ?? JSON.stringify(msg);
            if (['Error', 'Fatal'].includes(level)) console.error('[Ctrl-ERR]', text);
            else if (['Debug', 'Trace'].includes(level)) {}
            else console.log('[Ctrl]', text);
        }
    });

    console.log('[连接] 正在连接', ADB_ADDR, '...');
    const conn = await ctrl.post_connection().wait();
    // Node 绑定 job 无 .success 属性，用 status 判断：3000=Succeeded
    if (conn.status !== 3000) { console.error('[连接失败] status=', conn.status); process.exit(1); }
    console.log('[连接] 成功');

    // 加载资源
    const res = new maa.Resource();
    res.add_sink((_, msg) => {
        if (typeof msg === 'object' && msg && msg.level === 'Error') console.error('[Res-ERR]', msg.message ?? JSON.stringify(msg));
    });
    const bundle = await res.post_bundle(path.join(PROJECT, 'resource')).wait();
    if (bundle.status !== 3000) { console.error('[资源加载失败] status=', bundle.status); process.exit(1); }
    console.log('[资源] 加载成功');

    // 创建实例并绑定
    const tskr = new maa.Tasker();
    tskr.add_sink((_, msg) => {
        if (typeof msg === 'object' && msg) {
            const level = msg.level ?? '';
            const text = msg.message ?? JSON.stringify(msg);
            if (['Error', 'Fatal'].includes(level)) console.error('[Task-ERR]', text);
            else if (!['Debug', 'Trace'].includes(level)) console.log('[Task]', text);
        }
    });
    tskr.controller = ctrl;
    tskr.resource = res;
    console.log('[实例] 初始化:', tskr.inited);

    // 执行挂机循环
    let round = 0;
    while (maxRounds === 0 || round < maxRounds) {
        round++;
        const t0 = Date.now();
        console.log(`\n===== 第 ${round} 轮开始 ${new Date().toLocaleTimeString()} =====`);
        const r = await tskr.post_task('GrindStart').wait();
        const used = ((Date.now() - t0) / 1000).toFixed(1);
        if (r.status === 3000) {
            console.log(`===== 第 ${round} 轮完成（${used}s）=====`);
        } else {
            console.error(`===== 第 ${round} 轮失败（${used}s）=====`);
            break;
        }
    }
    console.log('\n[结束] 挂机已停止');
    process.exit(0);
}

main().catch(e => { console.error('[异常]', e); process.exit(1); });
