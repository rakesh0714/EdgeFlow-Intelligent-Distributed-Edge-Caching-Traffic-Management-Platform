"""
CDN Web Application - Final Version
ONLY communicates with Traffic Manager (GSLB)
No direct access to Origin or Edge Nodes!
"""

from flask import Flask, render_template, request, jsonify, Response, redirect, url_for
import requests
import time
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'cdn-secret-key-2024'

# ==================== CONFIGURATION ====================
# ONLY ONE PUBLIC ENDPOINT - The Traffic Manager (GSLB)
GSLB_URL = "http://localhost:8080"

# Cache for files list (from GSLB)
files_cache = []
cache_timestamp = 0
CACHE_DURATION = 30

# Access logs
access_logs = []
upload_history = []
UPLOAD_HISTORY_MAX = 50
ACCESS_LOGS_MAX = 100

# ==================== HELPER FUNCTIONS ====================

def detect_location(request):
    """Detect user location from request headers"""
    custom_location = request.headers.get('X-Client-Location', '').lower()
    if custom_location in ['asia', 'europe', 'america']:
        return custom_location
    
    accept_lang = request.headers.get('Accept-Language', '').lower()
    
    asian_langs = ['ja', 'zh', 'ko', 'th', 'vi', 'id', 'ms']
    for lang in asian_langs:
        if lang in accept_lang:
            return 'asia'
    
    european_langs = ['de', 'fr', 'it', 'es', 'nl', 'sv', 'pl', 'ru']
    for lang in european_langs:
        if lang in accept_lang:
            return 'europe'
    
    return 'america'

def get_available_files():
    """Get list of files from GSLB (which gets from origin internally)"""
    global files_cache, cache_timestamp
    
    current_time = time.time()
    if current_time - cache_timestamp < CACHE_DURATION and files_cache:
        return files_cache
    
    try:
        # Get file list from GSLB's status endpoint
        response = requests.get(f"{GSLB_URL}/files", timeout=5)
        if response.status_code == 200:
            files_cache = response.json().get('files', [])
            cache_timestamp = current_time
            return files_cache
    except Exception as e:
        print(f"Error fetching files: {e}")
    
    # Fallback sample files
    files_cache = [
        {'name': 'welcome.txt', 'size': 42, 'type': 'text'},
        {'name': 'sample.jpg', 'size': 1900, 'type': 'image'},
        {'name': 'sample.mp4', 'size': 3800, 'type': 'video'},
        {'name': 'sample.pdf', 'size': 2850, 'type': 'document'}
    ]
    return files_cache

def get_file_size_str(size_bytes):
    """Convert bytes to human readable format"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"

def get_file_icon(filename):
    """Get icon based on file extension"""
    ext = filename.split('.')[-1].lower() if '.' in filename else ''
    
    icons = {
        'jpg': '🖼️', 'jpeg': '🖼️', 'png': '🖼️', 'gif': '🖼️',
        'mp4': '🎬', 'avi': '🎬', 'mov': '🎬',
        'mp3': '🎵', 'wav': '🎵',
        'pdf': '📄', 'doc': '📄', 'docx': '📄',
        'txt': '📝', 'md': '📝',
        'zip': '📦', 'rar': '📦',
        'html': '🌐', 'css': '🎨', 'js': '⚡'
    }
    return icons.get(ext, '📁')

def log_access(filename, region, cache_status, response_time, user_agent, ip):
    """Log file access"""
    log = {
        'filename': filename,
        'region': region,
        'cache_status': cache_status,
        'response_time_ms': response_time,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'user_agent': user_agent[:50],
        'ip': ip
    }
    access_logs.insert(0, log)
    while len(access_logs) > ACCESS_LOGS_MAX:
        access_logs.pop()

def log_upload(filename, size, status, message=""):
    """Log file upload"""
    log = {
        'filename': filename,
        'size': size,
        'size_str': get_file_size_str(size),
        'status': status,
        'message': message,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    upload_history.insert(0, log)
    while len(upload_history) > UPLOAD_HISTORY_MAX:
        upload_history.pop()

def refresh_file_cache():
    """Force refresh of file cache"""
    global files_cache, cache_timestamp
    files_cache = []
    cache_timestamp = 0


# Add this function to detect file type
def get_file_type(filename):
    """Detect file type from extension"""
    ext = filename.split('.')[-1].lower() if '.' in filename else ''
    
    image_types = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg']
    video_types = ['mp4', 'webm', 'ogg', 'mov', 'avi', 'mkv']
    audio_types = ['mp3', 'wav', 'ogg', 'm4a', 'flac']
    document_types = ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx']
    text_types = ['txt', 'md', 'json', 'xml', 'html', 'css', 'js', 'py']
    
    if ext in image_types:
        return 'image'
    elif ext in video_types:
        return 'video'
    elif ext in audio_types:
        return 'audio'
    elif ext in document_types:
        return 'document'
    elif ext in text_types:
        return 'text'
    else:
        return 'binary'
    

# ==================== MAIN ROUTES ====================

@app.route('/')
def index():
    """Home page - Browse files"""
    files = get_available_files()
    location = detect_location(request)
    
    return render_template('index.html',
                         files=files,
                         location=location,
                         get_file_size_str=get_file_size_str,
                         get_file_icon=get_file_icon)


@app.route('/file/<filename>')
def view_file(filename):
    """View a file - ONLY through GSLB"""
    location = detect_location(request)
    user_agent = request.headers.get('User-Agent', 'Unknown')
    ip = request.remote_addr
    
    start_time = time.time()
    
    try:
        headers = {'X-Client-Location': location}
        response = requests.get(
            f"{GSLB_URL}/?file={filename}",
            headers=headers,
            timeout=30
        )
        
        elapsed = (time.time() - start_time) * 1000
        
        if response.status_code == 200:
            cache_status = response.headers.get('X-Cache-Status', 'MISS')
            edge_region = response.headers.get('X-Edge-Region', location)
            content_type = response.headers.get('Content-Type', 'application/octet-stream')
            
            log_access(filename, edge_region, cache_status, round(elapsed), user_agent, ip)
            
            file_type = get_file_type(filename)
            file_size = len(response.content)
            
            # For text files, show content; for others, show appropriate viewer
            if file_type == 'text' or content_type.startswith('text/'):
                content = response.text
            else:
                content = None  # Will trigger image/video/audio viewer
            
            return render_template('view.html',
                                 filename=filename,
                                 content=content,
                                 content_type=content_type,
                                 file_type=file_type,
                                 cache_status=cache_status,
                                 edge_region=edge_region,
                                 response_time=f"{elapsed:.0f}ms",
                                 location=location,
                                 file_size_str=get_file_size_str(file_size))
        else:
            return render_template('error.html',
                                 error=f"File not found (HTTP {response.status_code})",
                                 filename=filename), 404
                                 
    except Exception as e:
        return render_template('error.html', error=str(e), filename=filename), 500

@app.route('/download/<filename>')
def download_file(filename):
    """Download file - ONLY through GSLB"""
    location = detect_location(request)
    
    try:
        headers = {'X-Client-Location': location}
        response = requests.get(
            f"{GSLB_URL}/?file={filename}",
            headers=headers,
            stream=True,
            timeout=30
        )
        
        if response.status_code == 200:
            flask_response = Response(response.content, status=200)
            flask_response.headers['Content-Disposition'] = f'attachment; filename={filename}'
            flask_response.headers['X-Cache-Status'] = response.headers.get('X-Cache-Status', 'UNKNOWN')
            return flask_response
        else:
            return "File not found", 404
    except Exception as e:
        return str(e), 500

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    """Upload file - through GSLB's upload endpoint"""
    if request.method == 'POST':
        if 'file' not in request.files:
            return render_template('upload.html', error='No file selected')
        
        file = request.files['file']
        if file.filename == '':
            return render_template('upload.html', error='No file selected')
        
        filename = file.filename
        file_content = file.read()
        file_size = len(file_content)
        
        try:
            # Upload through GSLB (which forwards to internal origin)
            files = {'file': (filename, file_content)}
            response = requests.post(
                f"{GSLB_URL}/upload",
                files=files,
                timeout=30
            )
            
            if response.status_code in [200, 201]:
                result = response.json()
                is_update = result.get('is_update', False)
                
                # Refresh file cache
                refresh_file_cache()
                
                status = "Updated" if is_update else "Uploaded"
                log_upload(filename, file_size, status, "Auto-purge triggered" if is_update else "")
                
                return render_template('upload.html',
                                     success=True,
                                     filename=filename,
                                     is_update=is_update,
                                     file_size_str=get_file_size_str(file_size))
            else:
                log_upload(filename, file_size, "Failed", f"HTTP {response.status_code}")
                return render_template('upload.html', error=f'Upload failed: HTTP {response.status_code}')
                
        except Exception as e:
            log_upload(filename, file_size, "Failed", str(e))
            return render_template('upload.html', error=f'Upload failed: {str(e)}')
    
    return render_template('upload.html')

@app.route('/stats')
def stats():
    """Statistics - ALL data from GSLB only!"""
    
    # Get GSLB status (which includes all internal node info)
    gslb_status = {}
    try:
        resp = requests.get(f"{GSLB_URL}/status", timeout=5)
        if resp.status_code == 200:
            gslb_status = resp.json()
    except Exception as e:
        print(f"GSLB stats failed: {e}")
    
    # Extract edge node status from GSLB
    edge_nodes = []
    if gslb_status and 'nodes' in gslb_status:
        for region, node_data in gslb_status['nodes'].items():
            edge_nodes.append({
                'name': node_data.get('name', region.capitalize()),
                'region': region,
                'online': node_data.get('healthy', False),
                'status': node_data.get('status', 'Unknown'),
                'active_connections': node_data.get('details', {}).get('active', 0)
            })
    
    # Get GSLB statistics
    gslb_stats = {}
    try:
        resp = requests.get(f"{GSLB_URL}/stats", timeout=5)
        if resp.status_code == 200:
            gslb_stats = resp.json()
    except:
        pass
    
    # Calculate hit ratio from access logs
    total_hits = sum(1 for log in access_logs if log.get('cache_status') == 'HIT')
    total_requests = len(access_logs)
    hit_ratio = round((total_hits / total_requests * 100) if total_requests > 0 else 0, 2)
    
    return render_template('stats.html',
                         gslb_status=gslb_status,
                         gslb_stats=gslb_stats,
                         edge_nodes=edge_nodes,
                         access_logs=access_logs[:30],
                         upload_history=upload_history[:20],
                         total_hits=total_hits,
                         total_requests=total_requests,
                         hit_ratio=hit_ratio,
                         get_file_size_str=get_file_size_str)

@app.route('/health')
def health():
    """Health check - only checks GSLB"""
    gslb_ok = False
    try:
        resp = requests.get(f"{GSLB_URL}/health", timeout=2)
        gslb_ok = resp.status_code == 200
    except:
        pass
    
    return jsonify({
        'status': 'healthy' if gslb_ok else 'degraded',
        'service': 'web-app',
        'gslb_reachable': gslb_ok
    })

if __name__ == '__main__':
    print("=" * 70)
    print("🌐 CDN WEB APPLICATION - FINAL VERSION")
    print("=" * 70)
    print("📍 Access: http://localhost:5000")
    print("")
    print("🔒 Architecture:")
    print("   • Web App → GSLB (port 8080) ONLY!")
    print("   • No direct access to Origin or Edge nodes")
    print("   • All data comes through Traffic Manager")
    print("=" * 70)
    app.run(host='0.0.0.0', port=5000, debug=True)