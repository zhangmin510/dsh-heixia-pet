# 黑侠 · DeepSeek Harness 宠物

本定制基于 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 0.4.5（基线 `60bb2eb4113eca92b2636ab906f8e6c9c934ae13`），沿用其插件加载、动作切换、拖拽、右键菜单、会话状态联动、聊天与余额接口。没有使用本地喵伴项目。

![黑侠](pet/heixia-avatar.png)

黑侠是一只黑白短毛猫。宠物素材来自真实照片和视频，经本机前景分割形成透明 VP9 WebM；保留不对称脸纹、白胸、白爪和黑尾，不生成新的身体动作。三份照片用于待机、香箱工作与仰躺揣爪，另有八个自然视频动作；取景、输入哈希与处理参数见 [素材清单](pet/media_manifest.json)。

## 已配置行为

- 插件图标使用紧贴黑侠头脸的方形头像，去掉整身画布的大面积留白；浅色底衬让黑白脸纹在深色界面中也清楚可辨。
- 宠物名“黑侠”，显示在 Harness 页面右下方；可拖拽、点击回应、右键点播与切换睡觉。
- 共 11 种动作与姿态：待机、思考、工作、等你、庆祝、困困、回应、巡视、洗脸、轻摆尾巴、仰躺揣爪。真实会话的思考、工具调用、工具结果、等待、成功和错误映射到对应动作。
- **自动聊天已开启**：默认每 300 秒一句，使用黑侠人设，跟随 Harness 当前模型。余额每 1800 秒刷新；上游在启动时立即查一次。语音与点击音效默认关闭。
- **余额查询已开启**：保留上游 DeepSeek 等已支持通道；若已安装 `model-quota` 插件，桥接其已配置服务商的查询结果。不同账户、币种和套餐窗口分别展示，不合并或拿 Token 用量估算账户余额。服务商不支持、未登录或查询失败时保留明确状态。
- 黑侠包强制保持实拍方向，包括手动菜单、API 指令及 Q 弹恢复；其他宠物保留上游镜像行为。固定位置关闭随机翻向与走位，仍可主动拖拽。

## 支持的动作与姿态

当前黑侠定制包支持 **11 种动作与姿态**：8种真实视频动作、3种静态照片姿态。视频动作使用循环GIF，直接在README中播放；3个静态照片姿态保留PNG图片，全部使用干净浅色背景。

| 预览 | 动作 | 类型 | 表现 |
| --- | --- | --- | --- |
| <img src="pet/action-previews/idle.png" height="128" alt="黑侠待机预览"> | 待机 | 静态照片 | 歪头端坐，白胸白爪与绕在身前的黑尾。 |
| <img src="pet/action-previews/thinking.gif" height="128" alt="黑侠思考预览"> | 思考 | GIF动图 | 自然端坐，抬眼并轻轻转头。 |
| <img src="pet/action-previews/working.png" height="128" alt="黑侠工作预览"> | 工作 | 静态照片 | 安静的香箱卧姿，陪你认真做事。 |
| <img src="pet/action-previews/waiting.gif" height="128" alt="黑侠等你预览"> | 等你 | GIF动图 | 户外趴卧，轻抬头看向身旁。 |
| <img src="pet/action-previews/success.gif" height="128" alt="黑侠庆祝预览"> | 庆祝 | GIF动图 | 身体自然翻滚，露出白色肚皮。 |
| <img src="pet/action-previews/sleep.gif" height="128" alt="黑侠困困预览"> | 困困 | GIF动图 | 蜷卧休息，保留自然细微动作。 |
| <img src="pet/action-previews/pet.gif" height="128" alt="黑侠回应预览"> | 回应 | GIF动图 | 侧卧舒展身体与四肢。 |
| <img src="pet/action-previews/play.gif" height="128" alt="黑侠巡视预览"> | 巡视 | GIF动图 | 背向镜头，朝门口走动。 |
| <img src="pet/action-previews/belly_rest.png" height="128" alt="黑侠仰躺揣爪预览"> | 仰躺揣爪 **新增** | 静态照片 | 仰躺露腹，双前爪自然弯曲；保留照片的静态姿态。 |
| <img src="pet/action-previews/wash_face.gif" height="128" alt="黑侠洗脸预览"> | 洗脸 **新增** | GIF动图 | 侧卧举起白前爪，从耳侧轻擦脸颊。 |
| <img src="pet/action-previews/tail_sway.gif" height="128" alt="黑侠轻摆尾巴预览"> | 轻摆尾巴 **新增** | GIF动图 | 身体安静侧卧，尾尖自然小幅弯摆。 |

右键黑侠 → 动作，可按分类点播。洗脸位于“梳洗”，轻摆尾巴与仰躺揣爪位于“放松”。尾摆保留真实小幅动作，没有加速或放大。

GIF/PNG预览与对应WebM的哈希、帧数/时长、循环及裁边参数见[图片清单](pet/action-previews/preview_manifest.json)。开发时可运行 `python3 -B heixia/scripts/build_action_previews.py` 重建GIF/PNG预览（从仓库根目录执行，需要FFmpeg）；实际WebM保持不变。

## 本次新增精选

| 名称 | 实际表现与来源 | 区别 |
| --- | --- | --- |
| 洗脸 | V002 / IMG_3971.MOV，25.50–27.50秒，白前爪从耳侧擦过脸颊 | 动作中心是前爪洗脸，不是原来的翻滚或伸展；主体完整、简单地面背景 |
| 轻摆尾巴 | V028 / IMG_6725.MOV，29.40–32.00秒，安静侧卧、尾尖小幅弯摆 | 保留真实的小动作，没有加速或放大尾摆；完整主体、简单地面背景 |
| 仰躺揣爪 | P0235 / IMG_20200612_001132.jpg，仰躺露腹、双前爪自然弯曲 | 独特静态姿态；木地板背景简洁，不生成新的身体动作 |

对36段视频进行了分时抽帧审阅，并对照既有8种动作筛选。杂乱桌面、人手或衣物干扰、明显模糊、重复行为的候选未采用；另一段洗脸与本次洗脸重复，未计为新动作。不同来源时间窗与输出SHA见清单，姿态差异经实际图像审阅确认。

克隆仓库后在浏览器打开[动作预览页文件](preview.html)，点击“播放当前”查看新增3种，也可切换全部11种。该页使用同目录相对媒体路径，不依赖网络或fetch；下载时需保留整个heixia目录。

## 本地准备与安装

需要 Python 3、Node.js 24，以及已初始化的 DeepSeek Harness。播放已经制作好的宠物包无需 Swift 或 FFmpeg。

```sh
git clone https://github.com/zhangmin510/dsh-pet.git
cd dsh-pet
python3 -B heixia/scripts/prepare_runtime.py --install-deps
node heixia/scripts/verify-pack.mjs heixia/runtime heixia/pet
node heixia/scripts/install-pack.mjs --plugin-dir heixia/runtime --home ~/.dsh
```

准备脚本从 npm 获取固定 `dsh-pet@0.4.5`，核验 SHA-512 后只应用已记录的黑侠镜像补丁与余额桥接，不运行上游发布前的构建脚本；构建后的目录为 `heixia/runtime`。如已下载发布 tarball，可传 `--tarball /path/dsh-pet-0.4.5.tgz`。输出目录已存在时脚本拒绝覆盖，可用 `--output` 指定新目录。

桌面应用请使用 **Plugins → Add plugin**，填入上述 `heixia/runtime` 的绝对路径并安装；成功后按应用提示重新加载，再在“桌宠配置”中查看黑侠。实测 Desktop 0.2.1-rc.5 的 `desktop` profile 由 Electron 应用独占管理，普通 npm 全局 CLI 会直接拒绝该 profile，退出应用也不会解除这项保护；不要手改 profile 或设置内部标记绕过。

浏览器版可用 `dsh plugin --profile web add link:/absolute/path/to/dsh-pet/heixia/runtime --ignore-scripts --workspace-root`，随后 `dsh web`。本地链接目录应保留。安装宠物数据只写所选 `DSH_HOME/dsh-pet/pet/heixia-*`，替换前会备份；其他宠物与宿主模型设置不改动。首次配置隐藏内置蓝鱼，只显示黑侠；已有用户自定义主宠物偏好继续生效。

要在系统桌面显示，可在上游设置中把黑侠“显示位置”改成桌面或两者；上游此模式可能需要另外准备 Electron Helper，本定制默认使用 Harness 内浮层。

## 验证

```sh
node --test heixia/tests/pack.test.mjs heixia/tests/quota-bridge.test.mjs
python3 -B heixia/customization/apply_mirror_patch.py --runtime heixia/runtime --check
node --test heixia/customization/test_mirror_patch.mjs
```

本批新增3份已在实际隔离Harness中由右键菜单逐项点播，3项均成功播放且控制台无error；预览页全部11份媒体加载成功。

配置验证调用真正的上游 Host 合并与客户端投影函数，拒绝默默回退成蓝鱼配置；安装前检查所有引用素材存在。镜像回归执行发布包的浏览器与桌面播放路径。代码测试、完整媒体解码和实际 Harness 界面检查的范围在交付记录中分别标明，不把源码单元测试当作真实模型或所有服务商的成功查询。

## 素材与限制

仅公开定制所需的透明派生素材与制作说明；不包含原始照片/视频、宿主凭据、聊天记录或用户配置。原件保持完整。头脸、脚爪、毛发边缘受实拍清晰度与本机分割精度限制，自然视频首尾可能有跳变。照片来源是静态姿态，不冒称新拍动作或骨骼动画。

上游代码继续采用 [MIT](../LICENSE)；黑侠派生媒体仅供本仓库的个人宠物演示与定制使用，不以代码 MIT 许可转授原始宠物照片或视频权利。
