# 黑侠余额桥接

本功能通过dsh-pet公开`petApi7340.balance.register()`接入已安装的`modelQuota.snapshot(signal)`服务，只使用它返回的规范化结果。沿用dsh-pet的MIT许可；不引入猫伴/喵伴代码，不读取Key、不修改模型配置、不直接发送余额HTTP请求或启动CLI。

## 接入

在fork包的`exports`增加`"./heixia-quota-bridge": "./heixia/src/model-quota-bridge.js"`，把`quota-bridge.patch.yml`中的entry合并进根bundle patch。插件只注入`petApi7340`和`llm`；`modelQuota`在实际查询时软获取，因此它晚于本插件加载也能生效。依赖安装完成后用实际Harness安装该fork；单独本文件夹不是完整可安装插件。

| 配置 | 默认 | 范围 |
| --- | --- | --- |
| requestTimeoutMs | 18000 | 100–19000毫秒，必须早于上游20秒第三方等待上限 |
| maxMetrics | 20 | 1–20项；超限显式失败，不截掉账户金额或窗口 |

黑侠实例的`balanceEnabled=true`开启自动显示；余额刷新周期仍由main配置`eventsRefreshSec.balance`控制，默认1800秒，启动时先查一次。原版插件按`agentDefaultModel.currentSelection().provider`查询当前默认模型服务商；本桥接扩大这个服务商的支持范围，不将所有账户加总成一个余额。

## 数据口径

- 上游四个内置provider保持优先：`opencode-go`、`commandcode`、`deepseek-official`、`deepseek-account`。已有第三方注册也不覆盖。只为加载时已注册的其他provider ID贡献适配；新增provider后重载本桥接。
- 查询严格匹配当前provider的一行，找不到返回unsupported，多行拒绝；不会取第一行代替，也不合并同账户别名。
- 当前已安装model-quota适配器返回的CNY/USD分别展示，保留小数字符串精度；Key剩余、Key已用和账户余额不同标签。只有消费金额或Token/请求数量时返回unsupported，不据此估余额或认为额度无限。
- 百分比必须明确是`remainingPercent`，和value一致且在0–100。不同窗口分别标注；控制台Token Plan的窗口保留“控制台账户需与推理账户核对”提醒。重置时刻显示规范化UTC时间。
- 输出使用上游`shape: custom`的声明式文本气泡，通过真实`toBalanceState`解析验证。不跨币种相加，不推算满额基准或统一百分比；因此这些桥接结果只显示余额气泡，不凭空驱动某个余额消耗档位动画。
- modelQuota当前公开snapshot会读取其全部已配置provider，再由桥接选出当前provider。查询由已有model-quota模块掌管凭据与访问权限；本桥接不扩大凭据读取能力。
- 服务缺失、无额度、无可用指标返回unsupported；授权缺失返回credential-missing；查询失败/格式非法/重复指标返回fetch-error。异常正文不进入气泡，避免泄露凭据。不会把失败显示为0余额。

## 取消与卸载

传入的AbortSignal同时受请求期限和插件生命周期控制。超时或卸载后停止等待、丢弃迟到结果；实际HTTP/CLI取消由model-quota持有并执行。卸载注销本插件拥有的provider，不删除其他注册。没有新增后台轮询或缓存，复用上游余额调度。

## 自动聊天边界

自动聊天沿用上游`whisperEnabled=true`和`eventsRefreshSec.whisper`（默认300秒，启动立即排队），通过Harness现有`ctx.llm.stream()`与已配置模型调用，确实消耗推理额度。人设及指定`whisperModel/chatModel`由黑侠配置控制；指定模型失败时回落当前默认模型并记录原因。隐藏、睡眠或持锁的宠物跳过自动碎碎念。余额桥接不负责启停聊天，也不自行调用模型。

## 验证

从fork根执行`node --test heixia/tests/quota-bridge.test.mjs`（开发验证Node24，原生TypeScript支持用于读取上游纯解析/注册模块）。同一测试也可在完整发布runtime树运行。全部使用合成余额数据；覆盖真实上游注册和客户端解析、内置优先、精确provider匹配、失败状态、多币种/多窗口、脱敏、超时和卸载取消。未访问真实账户或发起模型请求。
