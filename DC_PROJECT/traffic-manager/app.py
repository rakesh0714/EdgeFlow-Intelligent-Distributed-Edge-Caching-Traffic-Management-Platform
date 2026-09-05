"""
GSLB - Global Server Load Balancer (Traffic Manager)
Complete version with all endpoints needed for Web App
"""

from flask import Flask, request, jsonify, Response
import requests
import time
import logging
from datetime import datetime
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [GSLB] - %(levelname)s - %(message)s')
logger = logging.getLogger('gslb')

app = Flask(__name__)

# ==================== CONFIGURATION ====================

# Internal edge nodes (container names on Docker network)
EDGE_NODES = {
    "america": {
        "name": "North America",
        "url": "http://edge-node-a:8081",
        "port": 8081,
        "description": "Serves USA, Canada, Mexico, Brazil",
        "fallback": ["europe", "asia"]
    },
    "europe": {
        "name": "Europe",
        "url": "http://edge-node-b:8081",
        "port": 8082,
        "description": "Serves UK, Germany, France, Italy, Spain",
        "fallback": ["america", "asia"]
    },
    "asia": {
        "name": "Asia Pacific",
        "url": "http://edge-node-c:8081",
        "port": 8083,
        "description": "Serves Japan, China, India, Australia",
        "fallback": ["america", "europe"]
    }
}

# Internal origin URL
ORIGIN_URL = "http://origin-server:8084"

# Statistics
stats = {
    "total_requests": 0,
    "routing_decisions": {"america": 0, "europe": 0, "asia": 0},
    "fallback_used": 0,
    "errors": 0,
    "upload_count": 0
}

# File list cache (from origin)
files_cache = []
cache_timestamp = 0
CACHE_DURATION = 30

# ==================== HELPER FUNCTIONS ====================

def detect_location(request):
    """Detect user location from request headers"""
    custom_location = request.headers.get('X-Client-Location', '').lower()
    if custom_location and custom_location in EDGE_NODES:
        logger.info(f"📍 Location from header: {custom_location}")
        return custom_location
    
    accept_lang = request.headers.get('Accept-Language', '').lower()
    
    asian_langs = ['ja', 'zh', 'ko', 'th', 'vi', 'id', 'ms']
    for lang in asian_langs:
        if lang in accept_lang:
            logger.info(f"📍 Location from language: asia")
            return "asia"
    
    european_langs = ['de', 'fr', 'it', 'es', 'nl', 'sv', 'pl', 'ru']
    for lang in european_langs:
        if lang in accept_lang:
            logger.info(f"📍 Location from language: europe")
            return "europe"
    
    logger.info(f"📍 Default location: america")
    return "america"

def check_node_health(node_url):
    """Check if edge node is healthy"""
    try:
        response = requests.get(f"{node_url}/health", timeout=3)
        if response.status_code == 200:
            data = response.json()
            active_connections = data.get('active_connections', 0)
            is_busy = data.get('busy', False)
            return not is_busy, active_connections
        return False, 0
    except:
        return False, 0

def get_files_from_origin():
    """Get list of files from origin (internal)"""
    global files_cache, cache_timestamp
    
    current_time = time.time()
    if current_time - cache_timestamp < CACHE_DURATION and files_cache:
        return files_cache
    
    try:
        response = requests.get(f"{ORIGIN_URL}/list", timeout=5)
        if response.status_code == 200:
            data = response.json()
            files_cache = data.get('files', [])
            cache_timestamp = current_time
            logger.info(f"✅ Fetched {len(files_cache)} files from origin")
            return files_cache
    except Exception as e:
        logger.error(f"Error fetching files: {e}")
    
    # Fallback sample files
    files_cache = [
        {'name': 'welcome.txt', 'size': 42},
        {'name': 'sample.jpg', 'size': 1900},
        {'name': 'sample.mp4', 'size': 3800},
        {'name': 'sample.pdf', 'size': 2850}
    ]
    return files_cache

def forward_to_edge(edge_url, filename, client_location, edge_region):
    """Forward request to edge node"""
    target_url = f"{edge_url}/cache/{filename}"
    logger.info(f"🔄 Forwarding to {edge_region}: {target_url}")
    
    try:
        start_time = time.time()
        response = requests.get(target_url, timeout=30)
        elapsed = (time.time() - start_time) * 1000
        
        cache_status = response.headers.get('X-Cache', 'UNKNOWN')
        logger.info(f"📦 Response: {cache_status} ({elapsed:.0f}ms)")
        
        flask_response = Response(response.content, status=200)
        flask_response.headers['Content-Type'] = response.headers.get('Content-Type', 'text/plain')
        flask_response.headers['X-Cache-Status'] = cache_status
        flask_response.headers['X-Edge-Region'] = edge_region
        flask_response.headers['X-Response-Time'] = f"{elapsed:.0f}ms"
        
        return flask_response
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return Response(f"Error: {e}", status=500)

# ==================== MAIN ROUTES ====================

@app.route('/')
def route_request():
    """Main routing endpoint - routes to appropriate edge node"""
    stats['total_requests'] += 1
    
    filename = request.args.get('file', '')
    if not filename:
        return jsonify({
            "error": "No file specified",
            "usage": "/?file=<filename>"
        }), 400
    
    client_location = detect_location(request)
    logger.info(f"🌍 Client: {client_location.upper()} | File: {filename}")
    
    target = EDGE_NODES.get(client_location)
    if not target:
        stats['errors'] += 1
        return jsonify({"error": "Invalid location"}), 400
    
    is_healthy, connections = check_node_health(target['url'])
    
    if is_healthy:
        stats['routing_decisions'][client_location] += 1
        return forward_to_edge(target['url'], filename, client_location, client_location)
    
    # Try fallback
    logger.warning(f"⚠️ {target['name']} busy, trying fallback")
    for fallback_region in target['fallback']:
        fallback = EDGE_NODES.get(fallback_region)
        if fallback:
            is_healthy, _ = check_node_health(fallback['url'])
            if is_healthy:
                stats['fallback_used'] += 1
                stats['routing_decisions'][fallback_region] += 1
                
                response = forward_to_edge(fallback['url'], filename, client_location, fallback_region)
                response.headers['X-Fallback'] = f"From {target['name']}"
                return response
    
    stats['errors'] += 1
    return jsonify({"error": "All nodes unavailable"}), 503

@app.route('/upload', methods=['POST'])
def upload_file():
    """Upload file to origin (internal) - called by Web App"""
    if 'file' not in request.files:
        return jsonify({"error": "No file"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No filename"}), 400
    
    filename = file.filename
    file_content = file.read()
    
    try:
        # Forward to internal origin
        files = {'file': (filename, file_content)}
        response = requests.put(
            f"{ORIGIN_URL}/files/{filename}",
            files=files,
            timeout=30
        )
        
        if response.status_code in [200, 201]:
            result = response.json()
            stats['upload_count'] += 1
            
            # Clear file cache
            global files_cache, cache_timestamp
            files_cache = []
            cache_timestamp = 0
            
            logger.info(f"✅ Uploaded: {filename}")
            return jsonify({
                "status": "success",
                "filename": filename,
                "is_update": result.get('is_update', False),
                "size": result.get('new_size', len(file_content))
            })
        else:
            return jsonify({"error": f"Upload failed: HTTP {response.status_code}"}), response.status_code
            
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/files', methods=['GET'])
def list_files():
    """List all files - called by Web App to browse files"""
    files = get_files_from_origin()
    return jsonify({"files": files})

@app.route('/status')
def status():
    """Get status of all edge nodes - called by Web App stats page"""
    nodes_status = {}
    for region, config in EDGE_NODES.items():
        is_healthy, connections = check_node_health(config['url'])
        nodes_status[region] = {
            "name": config['name'],
            "url": config['url'],
            "healthy": is_healthy,
            "status": "Healthy" if is_healthy else "Unhealthy",
            "details": {
                "active": connections,
                "max": 10
            },
            "description": config['description']
        }
    
    return jsonify({
        "service": "GSLB Traffic Manager",
        "timestamp": datetime.now().isoformat(),
        "nodes": nodes_status,
        "statistics": stats
    })

@app.route('/stats', methods=['GET'])
def get_stats():
    """Get statistics - called by Web App stats page"""
    return jsonify({
        "service": "GSLB Traffic Manager",
        "statistics": stats,
        "edge_nodes": {
            region: {
                "name": config['name'],
                "healthy": check_node_health(config['url'])[0]
            }
            for region, config in EDGE_NODES.items()
        }
    })

@app.route('/health')
def health():
    """Health check - called by Web App"""
    return jsonify({
        "status": "healthy",
        "service": "traffic-manager",
        "port": 8080,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/info')
def info():
    """Get routing information"""
    return jsonify({
        "service": "GSLB Traffic Manager",
        "routing_logic": "Routes users to nearest edge node based on location",
        "regions": {
            region: {
                "name": config['name'],
                "url": config['url'],
                "description": config['description'],
                "fallback": config['fallback']
            }
            for region, config in EDGE_NODES.items()
        },
        "statistics": stats
    })

if __name__ == '__main__':
    logger.info("=" * 70)
    logger.info("🌍 GSLB TRAFFIC MANAGER - COMPLETE VERSION")
    logger.info("=" * 70)
    logger.info("📋 Endpoints:")
    logger.info("   GET  /?file=<name>  - Get file (routes to edge)")
    logger.info("   POST /upload        - Upload file to origin")
    logger.info("   GET  /files         - List all files")
    logger.info("   GET  /status        - Edge node status")
    logger.info("   GET  /stats         - Statistics")
    logger.info("   GET  /health        - Health check")
    logger.info("   GET  /info          - Routing info")
    logger.info("=" * 70)
    logger.info("🔗 Internal URLs:")
    logger.info(f"   Origin: {ORIGIN_URL}")
    for region, config in EDGE_NODES.items():
        logger.info(f"   {region.upper()}: {config['url']}")
    logger.info("=" * 70)
    
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)