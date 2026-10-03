// 探测 maa-node API + 实测不同 screencap/input 方式能否取到画面
const path = require('path');
const { MAA_BIN, ADB, ADDR, PROJECT } = require('./config');

process.chdir(MAA_BIN);
const maa = require(path.join(MAA_BIN, 'MaaNode.node'));

console.log('=== 版本 ===', maa.Global?.version ?? maa.version);
console.log('=== AdbController 原型方法 ===');
for (const m of Object.getOwnPropertyNames(maa.AdbController.prototype)) console.log('  ', m);

async function testOne(name, screencap, input) {
    const t0 = Date.now();
    try {
        const ctrl = new maa.AdbController(ADB, ADDR, String(screencap), String(input), '{}');
        let connectOk = null;
        ctrl.add_sink((_, msg) => {
            if (msg && typeof msg === 'object' && msg.msg === 'Action.Succeeded' && msg.action === 'connect') connectOk = true;
        });
        const conn = await ctrl.post_connection().wait();
        if (conn.status !== 3000) { console.log(`[${name}] 连接失败 status=${conn.status}`); return; }
        // 尝试截图
        const job = ctrl.post_screencap();
        const r = await job.wait();
        let info = `status=${r.status}`;
        try {
            const img = typeof r.get === 'function' ? r.get() : (r.image ?? r.data);
            if (img) {
                const buf = Buffer.isBuffer(img) ? img : Buffer.from(img);
                info += ` bytes=${buf.length} head=${buf.slice(0, 8).toString('hex')}`;
            } else {
                info += ` (无图像数据字段, keys=${Object.keys(r).join(',')})`;
            }
        } catch (e) { info += ` imgErr=${e.message}`; }
        console.log(`[${name}] screencap=${screencap} input=${input} 连接OK 截图: ${info}  用时=${((Date.now()-t0)/1000).toFixed(1)}s`);
        try { ctrl.post_destroy?.(); } catch (e) {}
    } catch (e) {
        console.log(`[${name}] 异常: ${e.message}`);
    }
}

async function main() {
    // 64=EmulatorExtras(MFAAvalonia 自动选的), 2=Encode, 4=RawWithGzip, 6=Encode|RawWithGzip, 7=1|2|4
    const cases = [
        ['EmulatorExtras', 64, 1],
        ['Encode', 2, 1],
        ['RawWithGzip', 4, 1],
        ['Encode|RawWithGzip', 6, 1],
        ['EncodeToFileAndPull', 1, 1],
    ];
    for (const [n, s, i] of cases) await testOne(n, s, i);
    process.exit(0);
}
main().catch(e => { console.error('异常', e); process.exit(1); });
