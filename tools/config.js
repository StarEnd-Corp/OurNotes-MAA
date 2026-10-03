// ============================================================
//  运行环境配置（提交到仓库的通用版）
//
//  优先级：环境变量  >  tools/config.local.js（本机私有，已被 .gitignore 排除）  >  下面的默认值
//
//  为什么这么设计：仓库里不能出现任何本机路径/设备地址，
//  但每个人（包括原开发机）的运行参数又各不相同，所以把本机值放到未跟踪的
//  tools/config.local.js 里，仓库内只保留可移植的默认值。
//
//  首次使用建议：把 tools/config.local.js.example 复制成 tools/config.local.js 再改。
// ============================================================
const path = require('path');
const fs = require('fs');

const PROJECT = path.resolve(__dirname, '..');

/** 返回第一个存在的路径；都不存在则返回最后一个（便于报错时显示预期位置） */
function firstExisting(paths) {
    for (const p of paths) {
        try {
            if (fs.existsSync(p)) return p;
        } catch (e) { /* 忽略 */ }
    }
    return paths[paths.length - 1];
}

// 可移植默认值。
// 兼容两种布局：发行包（框架/ adb 在项目内）与开发环境（在项目同级）
const DEFAULTS = {
    MAA_BIN: firstExisting([
        path.resolve(PROJECT, 'MaaFramework', 'bin'),
        path.resolve(PROJECT, '..', 'MaaFramework', 'bin'),
    ]),
    ADB_PATH: firstExisting([
        path.resolve(PROJECT, 'platform-tools', 'adb.exe'),
        path.resolve(PROJECT, '..', 'platform-tools', 'platform-tools', 'adb.exe'),
        'adb',
    ]),
    ADB_ADDR: '127.0.0.1:16384',
};

// 本机私有配置（不提交）
let local = {};
const LOCAL = path.join(__dirname, 'config.local.js');
if (fs.existsSync(LOCAL)) {
    try {
        local = require(LOCAL);
    } catch (e) {
        console.warn('[config] tools/config.local.js 读取失败，改用默认值:', e.message);
    }
}

const cfg = Object.assign({}, DEFAULTS, local);

// 环境变量优先级最高
if (process.env.MAA_BIN) cfg.MAA_BIN = process.env.MAA_BIN;
if (process.env.ADB_PATH) cfg.ADB_PATH = process.env.ADB_PATH;
if (process.env.ADB_ADDR) cfg.ADB_ADDR = process.env.ADB_ADDR;

module.exports = {
    PROJECT,
    MAA_BIN: cfg.MAA_BIN,
    ADB_PATH: cfg.ADB_PATH,
    ADB_ADDR: cfg.ADB_ADDR,
    // 兼容旧脚本里的命名
    ADB: cfg.ADB_PATH,
    ADDR: cfg.ADB_ADDR,
};
