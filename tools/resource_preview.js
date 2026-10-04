const path = require('path');
const { MAA_BIN, ADB, ADDR, PROJECT } = require('./config');
process.chdir(MAA_BIN);
const maa = require(path.join(MAA_BIN, 'MaaNode.node'));
maa.Global.log_dir = path.join(PROJECT, 'debug');
maa.Global.debug_mode = true;
maa.Global.save_draw = true;
const STATUS = {3000: '成功', 4000: '失败'};
async function main() {
  const ctrl = new maa.AdbController(ADB, ADDR, '6', '7', '{}');
  const conn = await ctrl.post_connection().wait();
  if (conn.status !== 3000) throw new Error(`ADB 连接失败 status=${conn.status}`);
  const res = new maa.Resource();
  const bundle = await res.post_bundle(path.join(PROJECT, 'resource')).wait();
  if (bundle.status !== 3000) throw new Error(`资源加载失败 status=${bundle.status}`);
  const tasker = new maa.Tasker();
  const hits = [];
  tasker.add_context_sink((_, m) => {
    if (!m || typeof m !== 'object') return;
    if (m.msg === 'Recognition.Succeeded' && m.name && m.name !== hits[hits.length - 1]) {
      hits.push(m.name);
      console.log(`命中 ${m.name}`);
    }
  });
  tasker.controller = ctrl; tasker.resource = res;
  console.log('只读资源预览开始（不会点击）');
  const r = await tasker.post_task('ResourcePreview').wait();
  console.log(`资源预览结束 status=${r.status}（${STATUS[r.status] || '?'}）`);
  console.log(`识别节点：${hits.join(' → ') || '无'}`);
  process.exit(r.status === 3000 ? 0 : 1);
}
main().catch(e => { console.error(e.stack || e); process.exit(1); });
