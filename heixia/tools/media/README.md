# 黑侠透明宠物素材处理

本工具把已授权的黑侠实拍素材转换成 dsh-pet 需要的 640×360 VP9-alpha WebM。Python 只负责路径、哈希、子进程和报告；Apple Vision/Core Image 在本机分割主体并合成透明像素，FFmpeg 完成媒体提取、等比缩放和编码。没有远程服务、图片上传或生成重绘。

## 依赖与运行

- macOS 14+，带 Vision/Core Image/Core ML 的系统框架；本次实际环境是 macOS 26、Xcode Swift 6.4.2。
- Xcode Command Line Tools、Python 3.9+、带 libvpx-vp9 的 FFmpeg/ffprobe。
- 私有原素材及计划所引用的本地工作副本；仓库只分发派生 WebM 与来源 SHA，不分发原照片、原视频或已有表情 GIF。

在包含 `tools/media/` 的包目录执行：

```sh
python3 -B tools/media/build_media.py --smoke-photo --project-root /local/HeiXiaModel --plan media_plan.public.json --output-root media-output --logs media-build-logs
python3 -B tools/media/build_media.py --smoke-video --project-root /local/HeiXiaModel --plan media_plan.public.json --output-root media-output --logs media-build-logs
python3 -B tools/media/build_media.py --all --project-root /local/HeiXiaModel --plan media_plan.public.json --output-root media-output --logs media-build-logs
```

本项目中脚本位于 `companion_heixia/tools/media/`，默认计划为 `companion_heixia/plans/assets.json`，默认来源根目录从脚本位置解析。公开计划保留原项目内的相对输入路径，迁移素材布局时须按实际位置更新输入路径并核对哈希，不猜测路径。

`--project-root` 指定授权素材根目录（`--source-root`仍是别名），`--plan` 指定外部完整计划JSON，`--output-root` 指定输出根目录。当前项目默认布局保持可用；迁移后显式传这三个参数即可，不需要个人绝对路径。`--all --resume`核对前次计划、输入SHA及现有WebM的透明/时长后，只读恢复完成项并保留SHA/mtime，补做未完成或改选项。

首次执行会使用 `swiftc -module-cache-path` 在工具目录编译辅助程序；二进制和模块缓存是本机构建产物，不应提交。`--all` 输出 `pet-pack/heixia-animation/` 下平铺 WebM；原计划默认仍处理8项。原素材及150个表情 GIF只读。

## 追加新动作计划

新计划的每项使用独立 `state` 和 `name`（或 `animation_name`）。只要计划含显式名称，`--all` 就处理该计划全部项，不再要求正好8项。`animation_name` 优先于 `name`，没有显式名称的原8个state仍可使用原中文默认名。旧12项参考计划不含显式名称时，继续只选择原8个生产状态；两种模式都保留既有 `--resume` 只读恢复行为。

名称是省略 `.webm` 的文件名主体，例如 `{"state":"tail_sweep","name":"摇尾巴","media_type":"video", ...}`。新项的 `input`、SHA、`source_clip`、焦点等字段与原公开计划同构；公开计划会保留 `name`/`animation_name`，公开与本地清单按实际照片/视频数量统计。state、文件名均拒绝路径分隔符、控制字符、设备保留名、危险格式字符，以及大小写/Unicode规范化后碰撞的重复项；在创建任何媒体输出前预检。

烟测仍优先找原 `idle`/`thinking`；显式新动作计划没有这些状态时，`--smoke-photo` 选择第一张照片，`--smoke-video` 选择第一个视频。因此可只放一项新动作做烟测，无须伪装成原state。

追加时使用独立输出根与日志目录：

```sh
python3 -B tools/media/build_media.py --all --project-root /local/HeiXiaModel --plan /local/new_actions.json --output-root /local/expansion_2026-11-07 --logs /local/actions_expansion/media
```

这个命令只写新输出根的 `pet-pack/heixia-animation/`、`work/` 和各份清单，不修改首批8项。若重跑已有输出根，使用同一计划与 `--resume`；改变名称或来源会重新处理该项，同名派生输出会被替换，先确认对应输出根是本次独占目录。

## 处理约定

- 使用本机 SDK 的 `VNGenerateForegroundInstanceMaskRequest`，生成高分辨率实例遮罩，再用 Core Image `CIBlendWithMask` 把背景替换为真实透明通道。焦点按实际大图审阅指定，避免选择旁边物品。
- 只在系统声明支持 CPU 设备时显式选择；未声明时交由系统默认设备。本机最终请求未广告 CPU 设备，不把成功结果称为 CPU 推理。
- 所有视频使用无字幕的原播放副本全幅，不从已加字 GIF 再推断身体；每个 clip 对全体分割帧取一个并集包围盒和统一缩放，避免逐帧缩放抖动。
- 画布 640×360、脚底基准 y=330、主体最大高310px，宽度最多600px。只作等比整数像素缩放，不镜像黑侠的不对称脸纹。
- 12fps，片长1.8–3秒；原8项的“待机”和“工作”来自不同真实照片，保持静态，其余6份来自自然视频。新计划的实际照片/视频数量按清单记录，不伪造呼吸、眨眼、吃食或身体动作。
- 宠物状态名是陪伴交互标签。“回应”是自然伸展，并非实拍被人手抚摸；不得写成实拍吃食、说话或操作电脑。

## 验证与限制

- 逐输入核对 SHA-256，处理结束再次核对输入不变。
- ffprobe 核对 VP9、640×360 与 `alpha_mode=1`；使用 `-c:v libvpx-vp9` 强制解码所有帧的 alpha，确认每帧同时存在透明与前景像素；另完整解码视频。
- 不使用 FFmpeg 原生 VP9 解码器来判定透明，因为它可能忽略 alpha。`media_manifest.json` 是本地完整报告；`media_manifest.public.json` 只保留源 ID/原文件名/SHA/秒点/处理参数和结果，不含个人绝对路径。
- 本机libvpx 1.9曾因默认编码延迟只输出13帧；后续生成加`-lag-in-frames 0`禁用延迟，并校验1.8–3秒实际时长。首批已有效素材仅只读恢复，时长以清单实际值为准，不把选片窗口长度当编码后长度。
- 技术检查通过后仍需实际查看透明合成图和片段，确认无误保留的背景物、断肢、糊边或实例切换。曾因 V018 粘连灰色鼠标腕托而弃选，V034/V011/V028近拍也因源画面截身被弃选；没有用颜色键或随意模糊遮掩问题。
- Vision 是逐帧前景分割，细毛边界、草遮挡或自然首尾循环仍有实拍与分割限制，不宣称骨骼动画或无缝循环。
- 本次默认沙箱执行报 Vision Code9/ANE 推理计划失败；按原处理命令获得窄范围系统机器学习服务访问后成功。错误与实际有效模式保存在本地日志中，无模型下载。

日志的 `run_info.json` 记录本机 PID、启动命令、活动子进程、输出位置和退出状态。公开发行时只提交 Swift/Python/本说明、公开计划/清单与已验收 WebM，不提交 `.module-cache/`、二进制、原素材、`work/` 或运行日志。
