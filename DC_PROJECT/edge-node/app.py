"""
EDGE NODE - Internal Cache Server
Serves cached content, only accessible by Traffic Manager (internal network)
"""

from flask import Flask, request, jsonify, send_file
import requests
import os
import time
from threading import Lock
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [EDGE] - %(levelname)s - %(message)s')
logger = logging.getLogger('edge')

app = Flask(__name__)

# Configuration
CACHE_DIR = "/app/cache"
ORIGIN_URL = "http://origin-server:8084"  # Internal container name
REGION = os.environ.get('NODE_REGION', 'unknown')

# Create cache directory
os.makedirs(CACHE_DIR, exist_ok=True)

# Connection tracking
active_connections = 0
lock = Lock()

# Cache statistics
cache_stats = {"hits": 0, "misses": 0, "total": 0}

@app.route('/')
def home():
    return jsonify({
        "service": "CDN Edge Node",
        "region": REGION,
        "status": "internal"
    })

@app.route('/health')
def health():
    """Health check for Traffic Manager"""
    with lock:
        busy = active_connections > 10
        return jsonify({
            "status": "healthy",
            "region": REGION,
            "active_connections": active_connections,
            "busy": busy,
            "cache_hits": cache_stats['hits'],
            "cache_misses": cache_stats['misses']
        })

@app.route('/cache/<filename>', methods=['GET'])
def get_cached_file(filename):
    """Serve file from cache - ONLY called by Traffic Manager"""
    global active_connections
    
    with lock:
        active_connections += 1
    
    try:
        cache_path = os.path.join(CACHE_DIR, filename)
        
        # Check cache
        if os.path.exists(cache_path):
            logger.info(f"✅ CACHE HIT [{REGION}]: {filename}")
            time.sleep(0.1)  # Fast local delivery
            cache_stats['hits'] += 1
            cache_stats['total'] += 1
            
            response = send_file(cache_path)
            response.headers['X-Cache'] = 'HIT'
            response.headers['X-Edge-Region'] = REGION
            return response
        
        # Cache miss - fetch from origin
        logger.info(f"❌ CACHE MISS [{REGION}]: {filename}")
        cache_stats['misses'] += 1
        cache_stats['total'] += 1
        
        # Fetch from origin (internal)
        response = requests.get(f"{ORIGIN_URL}/files/{filename}", timeout=10)
        
        if response.status_code == 200:
            # Save to cache
            with open(cache_path, 'wb') as f:
                f.write(response.content)
            logger.info(f"💾 Cached [{REGION}]: {filename}")
            
            resp = send_file(cache_path)
            resp.headers['X-Cache'] = 'MISS'
            resp.headers['X-Edge-Region'] = REGION
            return resp
        else:
            return jsonify({"error": "File not found"}), 404
            
    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        with lock:
            active_connections -= 1

@app.route('/cache/<filename>', methods=['DELETE'])
def purge_cache(filename):
    """Purge file from cache - called by Purge Service"""
    cache_path = os.path.join(CACHE_DIR, filename)
    if os.path.exists(cache_path):
        os.remove(cache_path)
        logger.info(f"🗑️ PURGED [{REGION}]: {filename}")
        return jsonify({"status": "purged"})
    return jsonify({"status": "not_found"}), 404

@app.route('/cache/list', methods=['GET'])
def list_cache():
    """List cached files - internal only"""
    files = []
    for f in os.listdir(CACHE_DIR):
        filepath = os.path.join(CACHE_DIR, f)
        if os.path.isfile(filepath):
            files.append({"name": f, "size": os.path.getsize(filepath)})
    return jsonify({"region": REGION, "count": len(files), "files": files})

@app.route('/stats', methods=['GET'])
def get_stats():
    """Get cache statistics"""
    return jsonify({
        "region": REGION,
        "cache_stats": cache_stats,
        "hit_ratio": round(cache_stats['hits'] / max(cache_stats['total'], 1) * 100, 2)
    })

if __name__ == '__main__':
    logger.info("=" * 50)
    logger.info(f"EDGE NODE STARTING - Region: {REGION.upper()} (INTERNAL)")
    logger.info(f"Cache: {CACHE_DIR}")
    logger.info(f"Origin: {ORIGIN_URL}")
    logger.info("=" * 50)
    app.run(host='0.0.0.0', port=8081, debug=False)