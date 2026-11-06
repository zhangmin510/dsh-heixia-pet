/** Extend dsh-pet's public balance registry using the installed model-quota service, without handling credentials. */
export const name = 'heixia-model-quota-bridge';
/** Services owned by Harness and dsh-pet; modelQuota remains optional and is resolved at query time. */
export const inject = ['petApi7340', 'llm'];

const MONEY_LABELS = { balance: '账户余额', bonus: '赠送余额', keyRemaining: 'Key剩余额度', usage: 'Key已用金额' };
const PERCENT_LABELS = { primary: '主窗口剩余', secondary: '次窗口剩余', fiveHour: '5小时剩余',
  weekly: '周剩余', toolsMonthly: '工具月剩余', rolling: '滚动窗口剩余' };
const PERIOD_UNITS = { Hour: '小时', Day: '日', Week: '周', Month: '月' };
const CURRENCIES = new Set(['CNY', 'USD']);

function failure(provider, reason, message) {
  return { ok: false, provider, reason, message };
}

function configOf(input = {}) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('quota bridge: invalid configuration');
  if (Object.keys(input).some(key => !['requestTimeoutMs', 'maxMetrics'].includes(key))) throw new Error('quota bridge: unknown configuration field');
  const config = { requestTimeoutMs: 18000, maxMetrics: 20, ...input };
  // The upstream registry stops waiting after 20 seconds. Abort our service call before that boundary.
  if (!Number.isInteger(config.requestTimeoutMs) || config.requestTimeoutMs < 100 || config.requestTimeoutMs > 19000) throw new Error('quota bridge: requestTimeoutMs must be 100–19000');
  if (!Number.isInteger(config.maxMetrics) || config.maxMetrics < 1 || config.maxMetrics > 20) throw new Error('quota bridge: maxMetrics must be 1–20');
  return config;
}

function numericText(value) {
  if ((typeof value !== 'string' && typeof value !== 'number') || typeof value === 'boolean') return undefined;
  const text = String(value).trim();
  if (text.length === 0 || text.length > 64 || !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(text)) return undefined;
  return Number.isFinite(Number(text)) ? text : undefined;
}

function normalizeMetric(metric) {
  if (!metric || typeof metric !== 'object') return undefined;
  const money = CURRENCIES.has(metric.unit) && Object.hasOwn(MONEY_LABELS, metric.label);
  const percent = metric.unit === '%' && Object.hasOwn(PERCENT_LABELS, metric.label);
  // Token/request counts and unknown units are not balances and are never used to infer one.
  if (!money && !percent) return undefined;
  const value = numericText(metric.value);
  if (value === undefined) throw new Error('invalid metric');
  if (percent && (typeof metric.remainingPercent !== 'number' || !Number.isFinite(metric.remainingPercent)
    || metric.remainingPercent < 0 || metric.remainingPercent > 100 || Number(value) !== metric.remainingPercent)) throw new Error('invalid percentage');
  let label = money ? MONEY_LABELS[metric.label] : PERCENT_LABELS[metric.label];
  if (metric.label === 'rolling' && metric.periodCount !== undefined) {
    if (!Number.isInteger(metric.periodCount) || metric.periodCount <= 0 || !Object.hasOwn(PERIOD_UNITS, metric.periodUnit)) throw new Error('invalid period');
    label = `${metric.periodCount}${PERIOD_UNITS[metric.periodUnit]}窗口剩余`;
  }
  let reset;
  if (metric.resetAt !== undefined) {
    if (typeof metric.resetAt !== 'string' || !Number.isFinite(Date.parse(metric.resetAt))) throw new Error('invalid reset');
    reset = new Date(metric.resetAt).toISOString();
  }
  return { label, value, unit: metric.unit, reset, isRemaining: metric.label !== 'usage',
    identity: JSON.stringify([metric.label, metric.unit, metric.periodCount, metric.periodUnit, metric.windowSeconds]) };
}

function resultOf(snapshot, provider, maxMetrics) {
  if (!snapshot || !Array.isArray(snapshot.providers)) return failure(provider, 'fetch-error', '模型余量返回格式不完整。');
  const hits = snapshot.providers.filter(row => row?.provider === provider);
  if (hits.length === 0) return failure(provider, 'unsupported', '当前服务商未提供可查询的余额或套餐额度。');
  if (hits.length !== 1) return failure(provider, 'fetch-error', '当前服务商返回多个账户记录，未合并或猜测余额。');
  const row = hits[0];
  if (row.status === 'unsupported' || row.status === 'noQuota') return failure(provider, 'unsupported', '当前服务商未提供可查询的余额或套餐额度。');
  if (row.status === 'missingCredential' || (row.status === 'setupRequired' && row.reason === 'consoleLoginRequired')) return failure(provider, 'credential-missing', '模型余量的账户授权不可用，请到模型余量设置检查。');
  if (row.status === 'setupRequired') return failure(provider, 'unsupported', '当前服务商的额度查询尚未完成设置。');
  if (row.status !== 'ready') return failure(provider, 'fetch-error', '模型余量未完成查询，请在模型余量设置查看状态。');
  if (!Array.isArray(row.metrics)) return failure(provider, 'fetch-error', '模型余量未返回有效指标。');
  if (row.metrics.length > maxMetrics) return failure(provider, 'fetch-error', '额度指标过多，请在模型余量设置查看完整结果。');
  let metrics;
  try { metrics = row.metrics.map(normalizeMetric).filter(Boolean); }
  catch { return failure(provider, 'fetch-error', '模型余量的数值、单位或周期格式无效。'); }
  if (!metrics.some(metric => metric.isRemaining)) return failure(provider, 'unsupported', '服务商未返回剩余额度；消费金额或Token数量不能代替余额。');
  if (new Set(metrics.map(metric => metric.identity)).size !== metrics.length) return failure(provider, 'fetch-error', '额度指标重复，未累加或猜测账户余额。');
  const title = typeof row.name === 'string' && row.name.trim() ? row.name.trim().slice(0, 60) : provider.slice(0, 60);
  const children = [{ tag: 'strong', text: title }, ...metrics.map(metric => ({ tag: 'div', children: [
    { tag: 'span', text: `${metric.label}：` }, { tag: 'strong', text: `${metric.value} ${metric.unit}` },
    ...(metric.reset ? [{ tag: 'div', text: `重置：${metric.reset}` }] : []),
  ] }))];
  if (row.note === 'noKeyLimit' || row.note === 'keyLimitOnly') children.push({ tag: 'div', text: 'Key额度与消费，不代表账户总余额。' });
  else if (row.note === 'consoleAccountQuota') children.push({ tag: 'div', text: '来源：已登录控制台账户，请确认与推理账户相同。' });
  else children.push({ tag: 'div', text: '来源：模型余量；共享账户额度，币种与窗口分别显示。' });
  if (row.available === false) children.push({ tag: 'div', text: '服务商报告当前请求不可用。' });
  // No currency aggregation and no inferred percentage: each number retains its original unit and window.
  return { ok: true, provider, shape: 'custom', data: { rows: { tag: 'div', children } } };
}

/**
 * Register supported query adapters for currently registered non-builtin provider IDs.
 * @param ctx - Cordis context with public petApi7340 and llm services.
 * @param input - Optional timeout and output-capacity configuration.
 */
export function apply(ctx, input) {
  const config = configOf(input);
  const lifetime = new AbortController();
  const pending = new Set();
  ctx.effect(() => async () => {
    lifetime.abort();
    await Promise.allSettled([...pending]);
  });

  async function query(provider) {
    if (lifetime.signal.aborted) return failure(provider, 'fetch-error', '余额桥接已卸载。');
    let service;
    try { service = ctx.get('modelQuota', false); }
    catch { return failure(provider, 'unsupported', '模型余量服务当前不可用。'); }
    if (!service || typeof service.snapshot !== 'function') return failure(provider, 'unsupported', '未启用模型余量服务，当前服务商暂不支持余额查询。');
    const deadline = new AbortController();
    const timer = setTimeout(() => deadline.abort(), config.requestTimeoutMs);
    const signal = AbortSignal.any([lifetime.signal, deadline.signal]);
    let onAbort;
    try {
      const stopped = new Promise((_, reject) => {
        onAbort = () => reject(new Error('stopped'));
        if (signal.aborted) onAbort(); else signal.addEventListener('abort', onAbort, { once: true });
      });
      const operation = Promise.resolve().then(() => {
        signal.throwIfAborted();
        return service.snapshot(signal);
      });
      const snapshot = await Promise.race([operation, stopped]);
      if (signal.aborted) return failure(provider, 'fetch-error', '额度查询已取消或超时。');
      return resultOf(snapshot, provider, config.maxMetrics);
    } catch {
      // Exceptions may contain credentials or upstream response bodies; only fixed messages cross this bridge.
      return failure(provider, 'fetch-error', signal.aborted ? '额度查询已取消或超时。' : '模型余量查询失败，请在模型余量设置查看状态。');
    } finally {
      clearTimeout(timer);
      if (onAbort) signal.removeEventListener('abort', onAbort);
    }
  }

  const existing = ctx.petApi7340.balance.list();
  const reserved = new Set([...existing.builtin, ...existing.external]);
  for (const provider of ctx.llm.listProviders()) {
    if (reserved.has(provider.id)) continue;
    reserved.add(provider.id);
    ctx.effect(() => ctx.petApi7340.balance.register({ id: provider.id, fetch({ provider: selected }) {
      const operation = query(selected);
      pending.add(operation);
      operation.then(() => pending.delete(operation), () => pending.delete(operation));
      return operation;
    } }));
  }
}
