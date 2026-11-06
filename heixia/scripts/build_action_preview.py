"""Build a local-file friendly action gallery from the reviewed public catalog."""
import argparse
import html
import json
from pathlib import Path
from urllib.parse import quote


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--media-prefix', default='pet-pack/heixia-animation/')
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text())
    cards = []
    for item in catalog['items']:
        name = html.escape(item['name'])
        kind = 'photo' if item['media_type'] == 'photo' else 'video'
        label = '静态姿态' if kind == 'photo' else '真实视频'
        new = item.get('added_in') == '2026-11-07-expansion'
        url = html.escape(args.media_prefix + quote(item['name'] + '.webm'))
        cards.append(f'''<article data-kind="{kind}" data-new="{str(new).lower()}">
          <div class="stage"><video aria-label="{name}" src="{url}" muted loop playsinline controls preload="auto"></video>
          {'<span class="badge">新增</span>' if new else ''}</div>
          <div class="caption"><h2>{name}</h2><span>{label}</span></div>
          <p>{html.escape(item['description'])}</p></article>''')
    total = len(catalog['items'])
    new_count = sum(r.get('added_in') == '2026-11-07-expansion' for r in catalog['items'])
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>黑侠的日常 · 动作预览</title>
<style>
:root{color-scheme:light;font-family:ui-sans-serif,system-ui,-apple-system,"PingFang SC",sans-serif;color:#23382e;background:#f5f7f2}*{box-sizing:border-box}
body{margin:0}main{max-width:1200px;margin:auto;padding:52px 24px 64px}.eyebrow{font-size:13px;letter-spacing:.16em;color:#6a7e6e}h1{font-size:clamp(30px,5vw,48px);font-weight:650;margin:12px 0}
.intro{color:#627166;line-height:1.8;max-width:750px}.toolbar{display:flex;flex-wrap:wrap;gap:9px;align-items:center;margin:28px 0 24px}button{font:inherit;font-size:14px;cursor:pointer;border:1px solid #d7dfd5;background:#fff;color:#3c5142;border-radius:22px;padding:9px 16px}button[aria-pressed=true]{background:#284f3b;color:white;border-color:#284f3b}.spacer{flex:1}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:20px}article{background:white;border:1px solid #dfe6db;border-radius:20px;overflow:hidden}article[hidden]{display:none}.stage{position:relative;background:#edf1e9;aspect-ratio:16/9}.checker .stage{background:repeating-conic-gradient(#dce4d8 0 25%,#f4f7ef 0 50%) 50%/24px 24px}video{width:100%;height:100%;object-fit:contain}.badge{position:absolute;left:14px;top:13px;background:#fffdf1;color:#547044;font-size:12px;padding:4px 10px;border-radius:14px;pointer-events:none}.caption{padding:18px 20px 0;display:flex;align-items:center;justify-content:space-between;gap:10px}h2{font-size:18px;margin:0}.caption span{font-size:12px;color:#71806e}article p{font-size:14px;line-height:1.7;color:#6c786a;margin:10px 20px 20px}footer{color:#7b8677;font-size:13px;line-height:1.8;margin-top:30px}#status{font-size:13px;color:#657961;min-height:20px}
</style><main><div class="eyebrow">HEIXIA / 黑白小日常</div><h1>黑侠的日常</h1>
<p class="intro">精选清楚、背景简洁的真实素材。保留黑侠原本的脸纹和自然动作。照片保持静态，视频按原动作播放。</p>
<div class="toolbar" role="group" aria-label="筛选动作">
<button data-filter="new" aria-pressed="true">本次新增 __NEW__</button><button data-filter="all" aria-pressed="false">全部 __TOTAL__</button>
<button data-filter="video" aria-pressed="false">视频动作</button><button data-filter="photo" aria-pressed="false">静态姿态</button><span class="spacer"></span>
<button id="play">播放当前</button><button id="pause">暂停</button><button id="background" aria-pressed="false">检查透明背景</button></div>
<div id="status" aria-live="polite"></div><section class="grid" aria-label="黑侠动作">__CARDS__</section>
<footer>照片与视频都来自黑侠已有素材；没有镜像、加速、倒放或生成新身体动作。<br>直接打开此 HTML 即可预览，请将它与旁边的素材目录一同保留。</footer></main>
<script>
const cards=[...document.querySelectorAll('article')],status=document.querySelector('#status');
function filter(kind){let n=0;cards.forEach(c=>{const visible=kind==='all'||(kind==='new'?c.dataset.new==='true':c.dataset.kind===kind);c.hidden=!visible;if(!visible)c.querySelector('video').pause();else n++;});document.querySelectorAll('[data-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.filter===kind)));status.textContent=`正在显示 ${n} 种姿态与动作`;}
document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>filter(b.dataset.filter));
document.querySelector('#play').onclick=async()=>{const videos=cards.filter(c=>!c.hidden).map(c=>c.querySelector('video'));const results=await Promise.allSettled(videos.map(v=>v.play()));status.textContent=results.some(r=>r.status==='rejected')?'请使用卡片中的播放按钮开始播放。':`正在播放 ${videos.length} 个预览`;};
document.querySelector('#pause').onclick=()=>cards.forEach(c=>c.querySelector('video').pause());
document.querySelector('#background').onclick=e=>{const on=document.body.classList.toggle('checker');e.currentTarget.setAttribute('aria-pressed',String(on));};
document.querySelectorAll('video').forEach(v=>v.addEventListener('error',()=>{status.textContent=`“${v.getAttribute('aria-label')}”加载失败，请确认素材目录与本页放在一起。`;}));filter('new');
</script></html>'''
    page = page.replace('__NEW__', str(new_count)).replace('__TOTAL__', str(total)).replace('__CARDS__', '\n'.join(cards))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(page)
    print(json.dumps({'page': str(args.output), 'total': total, 'added': new_count}, ensure_ascii=False))


if __name__ == '__main__':
    main()
