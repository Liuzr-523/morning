/* 晨间学习台 · 自实现账号与进度同步接口
   运行位置：腾讯云开发 CloudBase 云函数（HTTP 访问服务）
   数据落点：CloudBase PostgreSQL（study_users / study_progress）
   鉴权：scrypt 存密码 + HMAC 签名令牌，密钥全部放在云函数环境变量里，不进前端 */
const crypto = require('crypto');

const ENV = process.env.TCB_ENV_ID || 'morning-d4g806jmr239b8c5b';
const APIKEY = process.env.CB_API_KEY || '';
const SECRET = process.env.APP_SECRET || '';
const BASE = 'https://' + ENV + '.api.tcloudbasegateway.com/v1/rdb/rest';
const MAX_PAYLOAD = 400 * 1024;

const ALLOWED_ORIGINS = [
  'https://liuzr-523.github.io',
  'https://morning-study.app.workbuddy.host',
  'http://127.0.0.1:8765',
  'http://127.0.0.1:8123',
  'http://localhost:8765'
];

function corsOrigin(origin) {
  if (!origin) return '*';
  if (ALLOWED_ORIGINS.indexOf(origin) >= 0) return origin;
  if (/^https:\/\/[\w-]+\.app\.workbuddy\.host$/.test(origin)) return origin;
  if (/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(origin)) return origin;
  return '';
}

function out(status, obj, origin) {
  const ao = corsOrigin(origin);
  const headers = {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store'
  };
  if (ao) {
    headers['Access-Control-Allow-Origin'] = ao;
    headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization';
    headers['Access-Control-Allow-Methods'] = 'POST,GET,OPTIONS';
    headers['Access-Control-Max-Age'] = '86400';
  }
  return { statusCode: status, headers: headers, body: JSON.stringify(obj) };
}

/* ---------- 数据库（postgREST 风格 HTTP API，走 service_role 钥匙） ---------- */
async function db(method, path, body, extraHeaders) {
  const headers = {
    'Authorization': 'Bearer ' + APIKEY,
    'apikey': APIKEY,
    'Content-Type': 'application/json'
  };
  if (extraHeaders) Object.keys(extraHeaders).forEach(function (k) { headers[k] = extraHeaders[k]; });
  const res = await fetch(BASE + path, {
    method: method,
    headers: headers,
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  const text = await res.text();
  let data = null;
  try { data = JSON.parse(text); } catch (e) { data = text; }
  if (!res.ok) {
    const err = new Error('db ' + res.status + ' ' + text);
    err.status = res.status;
    throw err;
  }
  return data;
}

const q = function (s) { return encodeURIComponent(String(s)); };

async function findUser(uname) {
  const r = await db('GET', '/study_users?uname=eq.' + q(uname) + '&select=uid,uname,pass,nick');
  return r && r.length ? r[0] : null;
}

async function findProgress(uid) {
  const r = await db('GET', '/study_progress?owner_id=eq.' + q(uid) + '&select=owner_id,payload,learned,streak,days,nick,saved_at');
  return r && r.length ? r[0] : null;
}

async function upsertProgress(uid, fields) {
  const body = Object.assign({ owner_id: uid }, fields);
  const r = await db('POST', '/study_progress?on_conflict=owner_id', [body], {
    'Prefer': 'resolution=merge-duplicates,return=representation'
  });
  return r && r[0] ? r[0] : null;
}

/* ---------- 密码与令牌 ---------- */
function hashPass(pass, salt) {
  const s = salt || crypto.randomBytes(16).toString('hex');
  const h = crypto.scryptSync(String(pass), s, 48).toString('hex');
  return s + ':' + h;
}
function verifyPass(pass, stored) {
  try {
    const parts = String(stored).split(':');
    if (parts.length !== 2) return false;
    const h = crypto.scryptSync(String(pass), parts[0], 48).toString('hex');
    return crypto.timingSafeEqual(Buffer.from(h, 'hex'), Buffer.from(parts[1], 'hex'));
  } catch (e) { return false; }
}
function b64url(buf) {
  return Buffer.from(buf).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function signToken(uid) {
  const payload = { uid: uid, iat: Math.floor(Date.now() / 1000), exp: Math.floor(Date.now() / 1000) + 60 * 60 * 24 * 180 };
  const head = b64url(Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })));
  const bodySeg = b64url(Buffer.from(JSON.stringify(payload)));
  const sig = b64url(crypto.createHmac('sha256', SECRET).update(head + '.' + bodySeg).digest());
  return head + '.' + bodySeg + '.' + sig;
}
function readToken(t) {
  if (!t) return null;
  const p = String(t).split('.');
  if (p.length !== 3) return null;
  const expect = b64url(crypto.createHmac('sha256', SECRET).update(p[0] + '.' + p[1]).digest());
  if (expect !== p[2]) return null;
  try {
    const obj = JSON.parse(Buffer.from(p[1].replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString());
    if (obj.exp && obj.exp < Math.floor(Date.now() / 1000)) return null;
    return obj;
  } catch (e) { return null; }
}

/* ---------- 业务逻辑 ---------- */
function cleanName(s) {
  return String(s || '').trim().toLowerCase();
}
function validName(s) {
  return /^[a-z0-9_]{3,20}$/.test(s);
}

async function actRegister(d, origin) {
  const uname = cleanName(d.user);
  const pass = String(d.pass || '');
  if (!validName(uname)) return out(400, { ok: false, msg: '用户名需 3-20 位字母、数字或下划线' }, origin);
  if (pass.length < 6 || pass.length > 64) return out(400, { ok: false, msg: '密码需 6-64 位' }, origin);
  const exist = await findUser(uname);
  if (exist) return out(409, { ok: false, msg: '这个用户名已经被占用了' }, origin);
  const uid = 'u_' + crypto.randomBytes(6).toString('hex');
  await db('POST', '/study_users', [{
    uid: uid, uname: uname, pass: hashPass(pass), nick: String(d.nick || uname).slice(0, 20)
  }], { 'Prefer': 'return=minimal' });
  await upsertProgress(uid, { payload: {}, learned: 0, streak: 0, days: 0, nick: String(d.nick || uname).slice(0, 20) });
  return out(200, { ok: true, token: signToken(uid), uid: uid, nick: String(d.nick || uname).slice(0, 20) }, origin);
}

async function actLogin(d, origin) {
  const uname = cleanName(d.user);
  const pass = String(d.pass || '');
  if (!uname || !pass) return out(400, { ok: false, msg: '请填写用户名和密码' }, origin);
  const u = await findUser(uname);
  if (!u || !verifyPass(pass, u.pass)) return out(401, { ok: false, msg: '用户名或密码不对' }, origin);
  return out(200, { ok: true, token: signToken(u.uid), uid: u.uid, nick: u.nick || uname }, origin);
}

async function actPull(uid, origin) {
  const p = await findProgress(uid);
  if (!p) return out(200, { ok: true, exists: false, payload: null, savedAt: null }, origin);
  return out(200, {
    ok: true, exists: true, payload: p.payload,
    savedAt: p.saved_at, learned: p.learned || 0, streak: p.streak || 0, days: p.days || 0, nick: p.nick || ''
  }, origin);
}

async function actPush(uid, d, origin) {
  const payload = d.payload === undefined ? null : d.payload;
  const size = JSON.stringify(payload === null ? {} : payload).length;
  if (size > MAX_PAYLOAD) return out(413, { ok: false, msg: '数据太大了（上限 400KB）' }, origin);

  const cur = await findProgress(uid);
  const serverTs = cur && cur.saved_at ? new Date(cur.saved_at).getTime() : 0;
  const basedAt = Number(d.basedAt || 0);
  if (serverTs && basedAt && serverTs > basedAt + 3000) {
    return out(409, {
      ok: false, conflict: true, msg: '云端数据比你这台设备新',
      server: { payload: cur.payload, savedAt: cur.saved_at, learned: cur.learned || 0, streak: cur.streak || 0, days: cur.days || 0 }
    }, origin);
  }
  const fields = {
    saved_at: new Date().toISOString()
  };
  if (payload !== null) fields.payload = payload;
  if (d.learned !== undefined) fields.learned = Number(d.learned) || 0;
  if (d.streak !== undefined) fields.streak = Number(d.streak) || 0;
  if (d.days !== undefined) fields.days = Number(d.days) || 0;
  if (d.nick !== undefined) fields.nick = String(d.nick).slice(0, 20);
  const r = await upsertProgress(uid, fields);
  return out(200, { ok: true, savedAt: r && r.saved_at ? r.saved_at : fields.saved_at }, origin);
}

/* ---------- 入口 ---------- */
exports.main = async function (event) {
  const origin = (event.headers && (event.headers.origin || event.headers.Origin)) || '';
  try {
    if (!APIKEY || !SECRET || SECRET === 'change-me') {
      return out(500, { ok: false, msg: '服务端密钥未配置' }, origin);
    }
    const method = (event.httpMethod || event.method || 'POST').toUpperCase();
    if (method === 'OPTIONS') return out(204, {}, origin);
    if (method !== 'POST') return out(405, { ok: false, msg: '只支持 POST' }, origin);

    let d = {};
    if (event.body) {
      try { d = typeof event.body === 'string' ? JSON.parse(event.body) : event.body; }
      catch (e) { return out(400, { ok: false, msg: '请求格式不对' }, origin); }
    }
    const action = String(d.action || '');

    if (action === 'ping') return out(200, { ok: true, time: new Date().toISOString() }, origin);
    if (action === 'register') return await actRegister(d, origin);
    if (action === 'login') return await actLogin(d, origin);

    const authHeader = (event.headers && (event.headers.authorization || event.headers.Authorization)) || '';
    const token = d.token || String(authHeader).replace(/^Bearer\s+/i, '');
    const sess = readToken(token);
    if (!sess || !sess.uid) return out(401, { ok: false, msg: '登录状态已失效，请重新登录' }, origin);

    if (action === 'pull') return await actPull(sess.uid, origin);
    if (action === 'push') return await actPush(sess.uid, d, origin);
    if (action === 'me') return out(200, { ok: true, uid: sess.uid }, origin);
    return out(400, { ok: false, msg: '未知操作' }, origin);
  } catch (e) {
    return out(500, { ok: false, msg: '服务器出错：' + (e && e.message ? e.message : 'unknown') }, origin);
  }
};
