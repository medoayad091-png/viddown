import os, uuid, threading, time, json, glob, hashlib, re
from flask import Flask, request, jsonify, send_file, render_template, Response, stream_with_context
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

DOWNLOAD_DIR = "/tmp/vd"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

jobs = {}   # job_id -> dict
cache = {}  # url_key -> job_id

def url_key(url, fmt, quality):
    return hashlib.md5(f"{url}|{fmt}|{quality}".encode()).hexdigest()

def delete_file_soon(path, delay=30):
    """Delete file shortly after serving — keeps server clean"""
    def _d():
        time.sleep(delay)
        try: os.remove(path)
        except: pass
    threading.Thread(target=_d, daemon=True).start()

def safe_filename(title):
    title = re.sub(r'[\\/*?:"<>|]', '', title or 'video')
    return title.strip()[:60] or 'video'

class _Logger:
    def __init__(self, jid): self.jid = jid
    def debug(self, m): pass
    def warning(self, m): pass
    def error(self, m): jobs.get(self.jid, {}).update({'_last_err': m})

def progress_hook(jid):
    def _h(d):
        j = jobs.get(jid)
        if not j: return
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            done  = d.get('downloaded_bytes', 0)
            pct   = round(done / total * 100, 1) if total else 0
            speed = (d.get('speed') or 0) / 1048576          # → MB/s
            eta   = int(d.get('eta') or 0)
            j.update(status='downloading', pct=pct, speed=round(speed,2), eta=eta)
        elif d['status'] == 'finished':
            j.update(status='merging', pct=96)
    return _h

def build_format(fmt, quality):
    if fmt == 'mp3':
        return 'bestaudio/best', None
    if quality == 'best':
        return 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best', 'mp4'
    q = int(quality)
    return (
        f'bestvideo[height={q}][ext=mp4]+bestaudio[ext=m4a]'
        f'/bestvideo[height<={q}][ext=mp4]+bestaudio[ext=m4a]'
        f'/bestvideo[height<={q}]+bestaudio/best[height<={q}]/best'
    ), 'mp4'

def do_download(jid, url, fmt, quality, ckey):
    out = os.path.join(DOWNLOAD_DIR, jid)
    fmt_str, merge_fmt = build_format(fmt, quality)

    opts = dict(
        outtmpl=out + '.%(ext)s',
        format=fmt_str,
        quiet=True, no_warnings=True, noplaylist=True,
        logger=_Logger(jid),
        progress_hooks=[progress_hook(jid)],
        concurrent_fragment_downloads=8,
        buffersize=16384,
        http_chunk_size=10485760,
        socket_timeout=30,
        retries=3,
    )
    if merge_fmt:
        opts['merge_output_format'] = merge_fmt
    if fmt == 'mp3':
        opts['postprocessors'] = [
            {'key':'FFmpegExtractAudio','preferredcodec':'mp3','preferredquality':'192'}
        ]

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'video')
            ext   = 'mp3' if fmt == 'mp3' else 'mp4'

            matches = glob.glob(out + '.*')
            if not matches:
                raise RuntimeError('لم يُنشأ الملف')
            src = matches[0]
            dst = out + '.' + ext
            if src != dst:
                try: os.rename(src, dst)
                except: dst = src

            jobs[jid].update(status='done', pct=100, filename=dst,
                             title=title, ext=ext)
            cache[ckey] = jid
            delete_file_soon(dst, 120)   # delete 2 min after ready
    except Exception as e:
        err = str(e)
        # Friendly Arabic messages
        if 'Unsupported URL' in err or 'Unable to extract' in err:
            err = 'الرابط غير مدعوم أو غير صحيح'
        elif 'Private video' in err:
            err = 'الفيديو خاص ولا يمكن تحميله'
        elif 'removed' in err.lower():
            err = 'الفيديو محذوف من المنصة'
        elif 'HTTP Error 429' in err:
            err = 'طلبات كثيرة، حاول بعد دقيقة'
        elif 'ffmpeg' in err.lower():
            err = 'خطأ في معالجة الفيديو (ffmpeg)'
        jobs[jid].update(status='error', error=err)

# ── ROUTES ──────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/download', methods=['POST'])
def api_download():
    data = request.json or {}
    url     = (data.get('url') or '').strip()
    fmt     = data.get('format', 'mp4')
    quality = data.get('quality', 'best')

    if not url:
        return jsonify(error='الرجاء إدخال رابط'), 400
    if not url.startswith(('http://', 'https://')):
        return jsonify(error='الرابط غير صحيح، تأكد من نسخه كاملاً'), 400

    ckey = url_key(url, fmt, quality)
    cached = cache.get(ckey)
    if cached and jobs.get(cached, {}).get('status') == 'done':
        if os.path.exists(jobs[cached].get('filename', '')):
            return jsonify(job_id=cached, cached=True)

    jid = str(uuid.uuid4())
    jobs[jid] = dict(status='pending', pct=0, speed=0, eta=0)
    threading.Thread(target=do_download, args=(jid, url, fmt, quality, ckey),
                     daemon=True).start()
    return jsonify(job_id=jid, cached=False)

@app.route('/api/progress/<jid>')
def api_progress(jid):
    def gen():
        prev = None
        for _ in range(720):   # max 12 min
            j = jobs.get(jid)
            if not j:
                yield f'data:{json.dumps(dict(error="not found"))}\n\n'; break
            snap = {k:v for k,v in j.items() if k != 'filename'}
            if snap != prev:
                yield f'data:{json.dumps(snap)}\n\n'
                prev = snap.copy()
            if j.get('status') in ('done','error'): break
            time.sleep(1)
    return Response(stream_with_context(gen()), mimetype='text/event-stream',
                    headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

@app.route('/api/status/<jid>')
def api_status(jid):
    j = jobs.get(jid)
    if not j: return jsonify(error='not found'), 404
    return jsonify({k:v for k,v in j.items() if k != 'filename'})

@app.route('/api/file/<jid>')
def api_file(jid):
    j = jobs.get(jid)
    if not j or j.get('status') != 'done':
        return jsonify(error='الملف غير جاهز'), 400
    fn = j.get('filename','')
    if not os.path.exists(fn):
        return jsonify(error='انتهت صلاحية الملف، أعد التحميل'), 410
    ext   = j.get('ext','mp4')
    title = safe_filename(j.get('title','video'))
    resp  = send_file(fn, as_attachment=True, download_name=f'{title}.{ext}')
    # Schedule immediate deletion after file is served
    delete_file_soon(fn, 5)
    return resp

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, threaded=True)
