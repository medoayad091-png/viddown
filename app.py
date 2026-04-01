import os
import uuid
import threading
import time
from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

DOWNLOAD_DIR = "/tmp/viddown"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Store job status
jobs = {}

def cleanup_file(path, delay=300):
    """Delete file after delay seconds"""
    def _delete():
        time.sleep(delay)
        try:
            os.remove(path)
        except:
            pass
    threading.Thread(target=_delete, daemon=True).start()

def do_download(job_id, url, fmt, quality):
    jobs[job_id]["status"] = "downloading"
    out_path = os.path.join(DOWNLOAD_DIR, job_id)

    ydl_opts = {
        "outtmpl": out_path + ".%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    if fmt == "mp3":
        ydl_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
    else:
        # Video quality map
        qmap = {"2160": "2160", "1080": "1080", "720": "720", "480": "480", "360": "360", "best": "best"}
        q = qmap.get(quality, "best")
        if q == "best":
            ydl_opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        else:
            ydl_opts["format"] = (
                f"bestvideo[height<={q}][ext=mp4]+bestaudio[ext=m4a]"
                f"/best[height<={q}][ext=mp4]/best[height<={q}]/best"
            )
        ydl_opts["merge_output_format"] = "mp4"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "video")
            ext = "mp3" if fmt == "mp3" else "mp4"
            filename = out_path + "." + ext
            jobs[job_id]["status"] = "done"
            jobs[job_id]["filename"] = filename
            jobs[job_id]["title"] = title
            jobs[job_id]["ext"] = ext
            cleanup_file(filename, 600)
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "رابط فارغ"}), 400

    ydl_opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get("formats", [])
            # Get available video heights
            heights = sorted(set(
                f.get("height") for f in formats
                if f.get("height") and f.get("vcodec") != "none"
            ), reverse=True)
            heights = [h for h in heights if h in [2160, 1440, 1080, 720, 480, 360, 240]]
            return jsonify({
                "title": info.get("title", ""),
                "thumbnail": info.get("thumbnail", ""),
                "duration": info.get("duration", 0),
                "uploader": info.get("uploader", ""),
                "platform": info.get("extractor_key", ""),
                "heights": heights or [720, 480, 360],
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.json
    url = data.get("url", "").strip()
    fmt = data.get("format", "mp4")
    quality = data.get("quality", "best")

    if not url:
        return jsonify({"error": "رابط فارغ"}), 400

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending"}
    threading.Thread(target=do_download, args=(job_id, url, fmt, quality), daemon=True).start()
    return jsonify({"job_id": job_id})

@app.route("/api/status/<job_id>")
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify(job)

@app.route("/api/file/<job_id>")
def serve_file(job_id):
    job = jobs.get(job_id)
    if not job or job.get("status") != "done":
        return jsonify({"error": "not ready"}), 400
    filename = job["filename"]
    title = job.get("title", "video")
    ext = job.get("ext", "mp4")
    safe_title = "".join(c for c in title if c.isalnum() or c in " _-")[:60]
    download_name = f"{safe_title}.{ext}"
    return send_file(filename, as_attachment=True, download_name=download_name)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
