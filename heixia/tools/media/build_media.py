"""Prepare real HeiXia footage as local Vision-segmented VP9-alpha pet clips.

Python handles paths, hashes, subprocesses and reports only. Foreground
segmentation/compositing is Swift Vision/Core Image; FFmpeg handles media IO.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
COMPANION = HERE.parents[1]
ROOT = COMPANION.parent
DEFAULT_LOGS = ROOT / 'docs/任务追踪/2026-11-07/logs/2026-11-07-DeepSeek黑侠宠物定制/media'
BIN = HERE / 'segment_foreground'
FPS = 12
NAMES = {'idle': '待机', 'thinking': '思考', 'working': '工作', 'waiting': '等你',
         'success': '庆祝', 'sleep': '困困', 'pet': '回应', 'play': '巡视'}


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for part in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(part)
    return digest.hexdigest()


def main():
    global ROOT, COMPANION
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--smoke-photo', action='store_true')
    mode.add_argument('--smoke-video', action='store_true')
    mode.add_argument('--all', action='store_true')
    parser.add_argument('--logs', type=Path, default=DEFAULT_LOGS)
    parser.add_argument('--project-root', '--source-root', dest='project_root', type=Path, default=ROOT,
                        help='Local project containing the private source photos/videos')
    parser.add_argument('--plan', type=Path, default=COMPANION / 'plans/assets.json')
    parser.add_argument('--output-root', type=Path, default=COMPANION,
                        help='Companion output root containing pet-pack/ and local build work/')
    parser.add_argument('--resume', action='store_true', help='Restore completed files from the preceding run without overwriting them')
    args = parser.parse_args()
    ROOT = args.project_root.resolve()
    COMPANION = args.output_root.resolve()
    logs = args.logs.resolve(); logs.mkdir(parents=True, exist_ok=True)
    kind = 'smoke_photo' if args.smoke_photo else 'smoke_video' if args.smoke_video else 'all'
    work = COMPANION / 'work/media' / kind
    work.mkdir(parents=True, exist_ok=True)
    source_root = ROOT
    plan = json.loads(args.plan.resolve().read_text())
    selected = [r for r in plan['items'] if r['state'] in (['idle'] if args.smoke_photo else ['thinking'] if args.smoke_video else NAMES)]
    assert len(selected) == (1 if kind != 'all' else 8)
    ffmpeg, ffprobe, swiftc = [shutil.which(name) for name in ['ffmpeg', 'ffprobe', 'swiftc']]
    assert all([ffmpeg, ffprobe, swiftc]), 'FFmpeg, ffprobe and Xcode Swift required'
    run = {'pid': os.getpid(), 'started_at': now(), 'host': socket.gethostname(), 'mode': kind,
           'cwd': str(ROOT), 'command': [sys.executable, *sys.argv], 'status': 'running',
           'selected_samples': selected, 'output_directory': str(COMPANION / 'pet-pack/heixia-animation' if args.all else work),
           'log_directory': str(logs), 'active': None, 'completed': [], 'failures': []}
    run_path = logs / 'run_info.json'
    previous = json.loads(run_path.read_text()) if args.resume and run_path.is_file() else {}
    previous_items = {r['state']: r for r in previous.get('selected_samples', [])}
    save(run_path, run)

    def command(values, label, binary_output=False):
        logfile = logs / (kind + '_' + label + '.log')
        with logfile.open('ab') as handle:
            handle.write((now() + '\n' + shlex.join(list(map(str, values))) + '\n').encode())
            process = subprocess.Popen(list(map(str, values)), cwd=ROOT,
                                       stdout=subprocess.PIPE if binary_output else handle, stderr=handle)
            run['active'] = {'pid': process.pid, 'command': list(map(str, values)), 'log': str(logfile)}
            save(run_path, run)
            stdout, _ = process.communicate()
        run['active'] = None
        save(run_path, run)
        if process.returncode:
            raise RuntimeError(f'{label}: exit {process.returncode}; see {logfile}')
        return stdout

    def inspect_video(path, state):
        probe = json.loads(command([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path], state + '_probe_output', True))
        stream = probe['streams'][0]
        assert stream['codec_name'] == 'vp9' and [stream['width'], stream['height']] == [640, 360], 'Wrong codec or dimensions'
        assert 1.8 <= float(probe['format']['duration']) <= 3.0, 'Output clip duration outside 1.8–3s'
        assert any(k.lower() == 'alpha_mode' and str(v) == '1' for k, v in stream.get('tags', {}).items()), 'VP9 alpha tag missing'
        alpha = command([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-c:v', 'libvpx-vp9', '-i', path,
                         '-vf', 'alphaextract', '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1'], state + '_alpha_decode', True)
        plane = 640 * 360
        assert len(alpha) % plane == 0 and len(alpha) >= plane * 18, 'Fewer than 18 decoded alpha frames'
        ranges = [(min(alpha[offset:offset + plane]), max(alpha[offset:offset + plane])) for offset in range(0, len(alpha), plane)]
        assert all(low == 0 and high >= 200 for low, high in ranges), 'A VP9 frame lost meaningful alpha'
        command([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-c:v', 'libvpx-vp9', '-i', path, '-f', 'null', '-'], state + '_full_decode')
        return probe, alpha, ranges

    def restore(item, output_path, folder):
        state = item['state']; before = output_path.stat().st_mtime_ns; output_sha = sha(output_path)
        seg_path = folder / 'segmentation.json'; seg = json.loads(seg_path.read_text()); sequence = seg['frames']
        assert all(f['alphaMin'] == 0 and f['alphaMax'] >= 200 for f in sequence)
        min_x = max(0, min(f['bbox'][0] for f in sequence) - 5); min_y = max(0, min(f['bbox'][1] for f in sequence) - 5)
        max_x = min(sequence[0]['width'], max(f['bbox'][0] + f['bbox'][2] for f in sequence) + 5)
        max_y = min(sequence[0]['height'], max(f['bbox'][1] + f['bbox'][3] for f in sequence) + 5)
        cw, ch = max_x - min_x, max_y - min_y; scale = min(310 / ch, 600 / cw)
        dw, dh = max(2, round(cw * scale) // 2 * 2), max(2, round(ch * scale) // 2 * 2)
        if item['media_type'] == 'photo':
            input_path = source_root / item['input']; expected = item['input_sha256']
            provenance = {'photo_id': item['photo_id'], 'original_filename': item['photo_filename'], 'original_sha256': item['original_sha256'], 'start_s': None, 'duration_s': 2.4, 'motion': f'Still photograph held as {state}; no generated body motion'}
        else:
            source_clip = item['source_clip']; input_path = source_root / source_clip['input']; expected = source_clip['sha256']
            provenance = dict(source_clip, video_id=item['video_id'], sampled_midframe_only=False)
        assert sha(input_path) == expected, 'Resume input differs from selected source'
        probe, alpha, ranges = inspect_video(output_path, state)
        assert output_path.stat().st_mtime_ns == before and sha(output_path) == output_sha, 'Restored file was overwritten'
        return {'state': state, 'name': NAMES[state], 'filename': str(output_path.relative_to(COMPANION)), 'sha256': output_sha,
                'bytes': output_path.stat().st_size, 'width':640, 'height':360, 'fps':FPS, 'duration_s':float(probe['format']['duration']),
                'source_frames':len(sequence), 'input_path':str(input_path.relative_to(source_root)), 'input_sha256':expected, 'source':provenance,
                'segmentation_engine':seg['engine'], 'segmentation_report':str(seg_path.relative_to(COMPANION)),
                'configured_compute_devices':sequence[0].get('configuredComputeDevices', {}),
                'effective_device_selection':'System default; exact compute hardware not asserted', 'focus_point':item.get('segmentation_focus',[.5,.5]),
                'uniform_bbox_px':[min_x,min_y,cw,ch], 'uniform_scale':scale, 'display_dimensions_px':[dw,dh],
                'canvas':{'width':640,'height':360,'feet_y':330,'max_cat_height':310}, 'no_mirror':True,'no_stretch':True,'no_subtitles':True,'no_generated_body_motion':True,
                'alpha_validation':{'mode_tag':True,'forced_libvpx_decode':True,'minimum':min(alpha),'maximum':max(alpha),'transparent_pixels_first_frame':alpha[:640*360].count(0),'all_decoded_frames_checked':len(ranges),'every_frame_has_transparency_and_foreground':True},
                'preview_png':str((folder/'canvas/000001.png').relative_to(COMPANION)), 'segmented_png':str((folder/'cutout/000001.png').relative_to(COMPANION)),
                'full_decode_passed':True,'restored_without_overwrite':True,'preserved_mtime_ns':before}

    results = []
    try:
        source = HERE / 'segment_foreground.swift'
        signature_file = HERE / 'segment_foreground.build.json'
        if not BIN.is_file() or not signature_file.is_file() or json.loads(signature_file.read_text()).get('source_sha256') != sha(source):
            command([swiftc, '-module-cache-path', HERE / '.module-cache', '-O', source, '-o', BIN], 'compile')
            save(signature_file, {'source_sha256': sha(source), 'binary_sha256': sha(BIN), 'built_at': now()})
        for item in selected:
            state = item['state']; folder = work / state
            existing = COMPANION / 'pet-pack/heixia-animation' / (NAMES[state] + '.webm')
            if args.resume and args.all and state in previous.get('completed', []) and previous_items.get(state) == item and existing.is_file():
                restored = restore(item, existing, folder); results.append(restored)
                run['completed'].append(state); save(folder/'item.json',restored); save(run_path,run)
                print(state, 'restored unchanged', existing, flush=True)
                continue
            frames = folder / 'input'; cutouts = folder / 'cutout'; canvas = folder / 'canvas'
            for directory in [frames, cutouts, canvas]:
                directory.mkdir(parents=True, exist_ok=True)
            # Source changes require a new task-specific work directory to avoid
            # stale frames; plans in this task are fixed before batch processing.
            for directory in [frames, cutouts, canvas]:
                for old in directory.glob('*.png'):
                    old.unlink()
            duration = 2.4 if item['media_type'] == 'photo' else item['source_clip']['duration_s']
            filters = []
            if item['media_type'] == 'photo':
                input_path = source_root / item['input']; expected = item['input_sha256']
                input_args = ['-i', input_path]
                frame_args = ['-frames:v', '1']
                provenance = {'photo_id': item['photo_id'], 'original_filename': item['photo_filename'],
                              'original_sha256': item['original_sha256'], 'start_s': None,
                              'duration_s': duration, 'motion': f'Still photograph held as {state}; no generated body motion'}
            else:
                source_clip = item['source_clip']; input_path = source_root / source_clip['input']; expected = source_clip['sha256']
                start = source_clip['start_s'] + (duration / 2 if args.smoke_video else 0)
                input_args = ['-ss', str(start), '-t', str(duration), '-i', input_path]
                frame_args = ['-frames:v', '1'] if args.smoke_video else []
                probe = command([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'json', input_path], state + '_probe_input', True)
                dimensions = json.loads(probe)['streams'][0]
                crop = source_clip.get('crop_normalized')
                if crop is not None:
                    x, y, w, h = crop; width, height = dimensions['width'], dimensions['height']
                    cx, cy = int(x * width) // 2 * 2, int(y * height) // 2 * 2
                    cw, ch = int(w * width) // 2 * 2, int(h * height) // 2 * 2
                    filters.append(f'crop={cw}:{ch}:{cx}:{cy}')
                if source_clip.get('rotation_ccw_degrees') == 90:
                    filters.append('transpose=2')
                if not args.smoke_video:
                    filters.append(f'fps={FPS}')
                provenance = dict(source_clip, video_id=item['video_id'], sampled_midframe_only=bool(args.smoke_video))
            assert input_path.is_file() and sha(input_path) == expected, 'Input changed or missing'
            filters.append('scale=768:768:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos')
            command([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-threads', '2', *input_args,
                     '-vf', ','.join(filters), *frame_args, '-start_number', '1', '-y', frames / '%06d.png'], state + '_extract')
            assert list(frames.glob('*.png')), 'No frames extracted'
            segmentation_report = folder / 'segmentation.json'
            focus = item.get('segmentation_focus', [.5, .5])
            command([BIN, frames, cutouts, segmentation_report, str(focus[0]), str(focus[1])], state + '_segment')
            seg = json.loads(segmentation_report.read_text()); sequence = seg['frames']
            assert len(sequence) == len(list(frames.glob('*.png')))
            assert all(f['alphaMin'] == 0 and f['alphaMax'] >= 200 for f in sequence)
            min_x = min(f['bbox'][0] for f in sequence); min_y = min(f['bbox'][1] for f in sequence)
            max_x = max(f['bbox'][0] + f['bbox'][2] for f in sequence); max_y = max(f['bbox'][1] + f['bbox'][3] for f in sequence)
            # One union box and one scale for every frame: no per-frame zoom jitter.
            min_x, min_y = max(0, min_x - 5), max(0, min_y - 5)
            max_x, max_y = min(sequence[0]['width'], max_x + 5), min(sequence[0]['height'], max_y + 5)
            crop_width, crop_height = max_x - min_x, max_y - min_y
            scale = min(310 / crop_height, 600 / crop_width)
            target_width, target_height = max(2, round(crop_width * scale) // 2 * 2), max(2, round(crop_height * scale) // 2 * 2)
            compose = f'crop={crop_width}:{crop_height}:{min_x}:{min_y},scale={target_width}:{target_height}:flags=lanczos,format=rgba,pad=640:360:(ow-iw)/2:330-ih:color=0x00000000'
            command([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-framerate', str(FPS), '-i', cutouts / '%06d.png',
                     '-vf', compose, '-start_number', '1', '-y', canvas / '%06d.png'], state + '_canvas')
            output_folder = COMPANION / 'pet-pack/heixia-animation' if args.all else folder
            output_folder.mkdir(parents=True, exist_ok=True)
            output_path = output_folder / (NAMES[state] + '.webm')
            input_args = ['-loop', '1', '-framerate', str(FPS), '-i', canvas / '000001.png'] if len(sequence) == 1 else ['-framerate', str(FPS), '-i', canvas / '%06d.png']
            temporary = folder / 'encoding.partial.webm'
            command([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', *input_args,
                     '-t', str(duration), '-an', '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p',
                     '-lossless', '1', '-auto-alt-ref', '0', '-lag-in-frames', '0', '-threads', '2', '-row-mt', '1', '-y', temporary], state + '_encode')
            probe = json.loads(command([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', temporary], state + '_probe_output', True))
            stream = probe['streams'][0]
            assert stream['codec_name'] == 'vp9' and [stream['width'], stream['height']] == [640, 360]
            assert 1.8 <= float(probe['format']['duration']) <= 3.0, 'Output clip duration outside 1.8–3s'
            assert any(k.lower() == 'alpha_mode' and str(v) == '1' for k, v in stream.get('tags', {}).items()), 'VP9 alpha tag missing'
            # Force libvpx decoding: FFmpeg native VP9 decoding can silently drop alpha.
            alpha = command([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-c:v', 'libvpx-vp9', '-i', temporary,
                             '-vf', 'alphaextract', '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1'], state + '_alpha_decode', True)
            plane = 640 * 360
            assert len(alpha) % plane == 0 and len(alpha) >= plane * 18
            alpha_ranges = [(min(alpha[offset:offset + plane]), max(alpha[offset:offset + plane]))
                            for offset in range(0, len(alpha), plane)]
            assert all(low == 0 and high >= 200 for low, high in alpha_ranges), 'A VP9 frame lost meaningful alpha'
            command([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-c:v', 'libvpx-vp9', '-i', temporary,
                     '-f', 'null', '-'], state + '_full_decode')
            temporary.replace(output_path)
            assert sha(input_path) == expected, 'Read-only input was changed'
            result = {'state': state, 'name': NAMES[state], 'filename': str(output_path.relative_to(COMPANION)),
                      'sha256': sha(output_path), 'bytes': output_path.stat().st_size, 'width': 640, 'height': 360,
                      'fps': FPS, 'duration_s': float(probe['format']['duration']), 'source_frames': len(sequence),
                      'input_path': str(input_path.relative_to(source_root)), 'input_sha256': expected, 'source': provenance,
                      'segmentation_engine': seg['engine'], 'segmentation_report': str(segmentation_report.relative_to(COMPANION)),
                      'configured_compute_devices': sequence[0].get('configuredComputeDevices', {}),
                      'effective_device_selection': 'Explicit advertised CPU device, if present; otherwise system default (exact hardware not asserted)',
                      'focus_point': focus,
                      'uniform_bbox_px': [min_x, min_y, crop_width, crop_height], 'uniform_scale': scale,
                      'display_dimensions_px': [target_width, target_height], 'canvas': {'width':640,'height':360,'feet_y':330,'max_cat_height':310},
                      'no_mirror': True, 'no_stretch': True, 'no_subtitles': True, 'no_generated_body_motion': True,
                      'alpha_validation': {'mode_tag': True, 'forced_libvpx_decode': True, 'minimum': min(alpha), 'maximum': max(alpha),
                                           'transparent_pixels_first_frame': alpha[:plane].count(0),
                                           'all_decoded_frames_checked': len(alpha_ranges), 'every_frame_has_transparency_and_foreground': True},
                      'preview_png': str((canvas / '000001.png').relative_to(COMPANION)), 'segmented_png': str((cutouts / '000001.png').relative_to(COMPANION)),
                      'full_decode_passed': True}
            results.append(result); save(folder / 'item.json', result); run['completed'].append(state); save(run_path, run)
            print(state, output_path, result['bytes'], flush=True)
        report = {'generated_at': now(), 'mode': kind, 'status': 'technical_checks_passed_visual_review_pending',
                  'real_photo_or_video_only': True, 'remote_services': [], 'items': results,
                  'processing': 'Local Apple Vision foreground segmentation, Core Image alpha composition, fixed clip union box, FFmpeg VP9-alpha WebM'}
        destination = COMPANION / 'media_manifest.json' if args.all else work / 'smoke_manifest.json'
        save(destination, report)
        if args.all:
            public_items = []
            for item in results:
                source = item['source']
                public_items.append({
                    'state': item['state'], 'name': item['name'], 'filename': Path(item['filename']).name,
                    'sha256': item['sha256'], 'bytes': item['bytes'], 'width': 640, 'height': 360,
                    'fps': FPS, 'duration_s': item['duration_s'],
                    'source': {k: source[k] for k in ['photo_id', 'video_id', 'original_filename', 'original_sha256', 'start_s', 'duration_s', 'motion'] if k in source},
                    'working_input_sha256': item['input_sha256'],
                    'processing': {'engine': item['segmentation_engine'], 'device_selection': item['effective_device_selection'],
                                   'configured_devices': item['configured_compute_devices'], 'focus_point': item['focus_point'],
                                   'uniform_bbox_px': item['uniform_bbox_px'], 'uniform_scale': item['uniform_scale'],
                                   'display_dimensions_px': item['display_dimensions_px'], 'canvas': item['canvas'],
                                   'no_mirror': True, 'no_stretch': True, 'no_subtitles': True, 'no_generated_body_motion': True},
                    'validation': item['alpha_validation'], 'full_decode_passed': item['full_decode_passed'],
                })
            public = {'schema_version': 1, 'generated_at': now(), 'character': '黑侠', 'status': report['status'],
                      'media_type': 'VP9-alpha WebM; two still photographs and six natural video clips',
                      'items': public_items, 'remote_services': [],
                      'notes': ['Source originals, private paths, run logs and pre-existing GIFs are not distributed.',
                                'State names are companion interface labels, not evidence of eating or human-directed behavior.']}
            encoded = json.dumps(public, ensure_ascii=False)
            assert '/Users/' not in encoded and '/private/' not in encoded, 'Private path in public manifest'
            save(COMPANION / 'media_manifest.public.json', public)
            public_keys = {'state','label','media_type','input','input_sha256','photo_id','photo_filename','original_sha256','identity','source_clip','segmentation_focus'}
            public_plan = {'schema_version':1,'items':[{k:v for k,v in r.items() if k in public_keys} for r in selected]}
            assert '/Users/' not in json.dumps(public_plan) and '/private/' not in json.dumps(public_plan)
            save(COMPANION / 'media_plan.public.json', public_plan)
        run.update(status='complete', finished_at=now(), exit_code=0, manifest=str(destination))
        save(run_path, run); save(logs / (kind + '_completed_run.json'), run)
        return 0
    except Exception as error:
        run['failures'].append(str(error)); run.update(status='failed', finished_at=now(), exit_code=1)
        save(run_path, run); save(logs / (kind + '_failed_run.json'), run)
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
