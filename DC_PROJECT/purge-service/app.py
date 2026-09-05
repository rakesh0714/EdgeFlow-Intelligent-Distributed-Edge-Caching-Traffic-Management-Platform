"""
PURGE SERVICE - Cache Invalidation Controller
Broadcasts delete commands to all edge nodes when content updates
"""

from flask import Flask, request, jsonify
import requests
import threading
import time
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [PURGE] - %(levelname)s - %(message)s')
logger = logging.getLogger('purge')

app = Flask(__name__)

# ==================== CONFIGURATION ====================

# Internal edge nodes (same network as all other services)
EDGE_NODES = [
    {"name": "America", "url": "http://edge-node-a:8081"},
    {"name": "Europe", "url": "http://edge-node-b:8081"},
    {"name": "Asia", "url": "http://edge-node-c:8081"}
]

# Statistics
stats = {
    "total_purges": 0,
    "successful_purges": 0,
    "failed_purges": 0,
    "last_purge": None,
    "purge_history": []
}

# ==================== HELPER FUNCTIONS ====================

def purge_single_node(node_url, node_name, filename):
    """
    Send DELETE request to a single edge node
    Returns: (success, status_code, message)
    """
    try:
        purge_url = f"{node_url}/cache/{filename}"
        logger.info(f"🧹 Purging {filename} from {node_name} ({purge_url})")
        
        response = requests.delete(purge_url, timeout=5)
        
        if response.status_code in [200, 404]:
            # 200 = deleted, 404 = not in cache (still success)
            logger.info(f"✅ {node_name}: {response.status_code}")
            return True, response.status_code, "success"
        else:
            logger.warning(f"⚠️ {node_name}: HTTP {response.status_code}")
            return False, response.status_code, f"HTTP {response.status_code}"
            
    except requests.exceptions.Timeout:
        logger.error(f"❌ {node_name}: Timeout")
        return False, None, "timeout"
    except requests.exceptions.ConnectionError:
        logger.error(f"❌ {node_name}: Connection error")
        return False, None, "connection_error"
    except Exception as e:
        logger.error(f"❌ {node_name}: {str(e)}")
        return False, None, str(e)

def broadcast_purge(filename, async_mode=True):
    """
    Broadcast purge to all edge nodes
    async_mode=True: Send to all nodes simultaneously (fan-out)
    async_mode=False: Send sequentially
    """
    results = []
    
    if async_mode:
        # FAN-OUT: Send to all nodes simultaneously
        threads = []
        results_lock = threading.Lock()
        
        def purge_thread(node):
            success, status, message = purge_single_node(node['url'], node['name'], filename)
            with results_lock:
                results.append({
                    "node": node['name'],
                    "url": node['url'],
                    "success": success,
                    "status_code": status,
                    "message": message
                })
        
        # Create and start threads
        for node in EDGE_NODES:
            thread = threading.Thread(target=purge_thread, args=(node,))
            thread.start()
            threads.append(thread)
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
    else:
        # Sequential mode (slower but simpler)
        for node in EDGE_NODES:
            success, status, message = purge_single_node(node['url'], node['name'], filename)
            results.append({
                "node": node['name'],
                "url": node['url'],
                "success": success,
                "status_code": status,
                "message": message
            })
    
    return results

def update_stats(results, filename):
    """Update purge statistics"""
    stats['total_purges'] += 1
    stats['last_purge'] = {
        "filename": filename,
        "timestamp": datetime.now().isoformat(),
        "results": results
    }
    
    successful = sum(1 for r in results if r['success'])
    stats['successful_purges'] += successful
    stats['failed_purges'] += len(results) - successful
    
    # Keep last 10 purges in history
    stats['purge_history'].insert(0, {
        "filename": filename,
        "timestamp": datetime.now().isoformat(),
        "successful": successful,
        "total": len(results)
    })
    stats['purge_history'] = stats['purge_history'][:10]

# ==================== API ENDPOINTS ====================

@app.route('/')
def home():
    """Service information"""
    return jsonify({
        "service": "Purge Service",
        "description": "Cache invalidation controller for CDN",
        "version": "1.0.0",
        "endpoints": {
            "POST /purge/<filename>": "Purge single file from all edge nodes",
            "POST /purge/batch": "Purge multiple files",
            "POST /purge/all": "Purge entire cache (all nodes)",
            "GET /status": "Get service status",
            "GET /stats": "Get purge statistics",
            "GET /health": "Health check"
        }
    })

@app.route('/health')
def health():
    """Health check for monitoring"""
    return jsonify({
        "status": "healthy",
        "service": "purge-service",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/status')
def status():
    """Get status of all edge nodes"""
    nodes_status = []
    
    for node in EDGE_NODES:
        try:
            response = requests.get(f"{node['url']}/health", timeout=2)
            if response.status_code == 200:
                data = response.json()
                nodes_status.append({
                    "name": node['name'],
                    "url": node['url'],
                    "healthy": True,
                    "region": data.get('region', 'unknown'),
                    "cache_stats": data.get('cache_stats', {})
                })
            else:
                nodes_status.append({
                    "name": node['name'],
                    "url": node['url'],
                    "healthy": False,
                    "error": f"HTTP {response.status_code}"
                })
        except Exception as e:
            nodes_status.append({
                "name": node['name'],
                "url": node['url'],
                "healthy": False,
                "error": str(e)
            })
    
    return jsonify({
        "service": "purge-service",
        "timestamp": datetime.now().isoformat(),
        "nodes": nodes_status,
        "statistics": stats
    })

@app.route('/stats')
def get_stats():
    """Get purge statistics"""
    return jsonify({
        "service": "purge-service",
        "statistics": stats
    })

@app.route('/purge/<filename>', methods=['POST'])
def purge_file(filename):
    """
    Purge a single file from all edge nodes
    POST /purge/welcome.txt
    """
    logger.info(f"📢 PURGE REQUEST: {filename}")
    
    # Broadcast to all edge nodes (fan-out)
    start_time = time.time()
    results = broadcast_purge(filename, async_mode=True)
    elapsed = (time.time() - start_time) * 1000
    
    # Update statistics
    update_stats(results, filename)
    
    # Count successes
    successful = sum(1 for r in results if r['success'])
    total = len(results)
    
    response = {
        "status": "completed",
        "filename": filename,
        "successful_nodes": successful,
        "total_nodes": total,
        "all_success": successful == total,
        "results": results,
        "elapsed_ms": round(elapsed, 2)
    }
    
    logger.info(f"✅ Purge complete: {successful}/{total} nodes ({elapsed:.0f}ms)")
    
    return jsonify(response)

@app.route('/purge/batch', methods=['POST'])
def purge_batch():
    """
    Purge multiple files
    POST /purge/batch
    Body: {"files": ["file1.txt", "file2.jpg", "file3.mp4"]}
    """
    data = request.get_json()
    
    if not data or 'files' not in data:
        return jsonify({"error": "Missing 'files' array in request body"}), 400
    
    files = data['files']
    if not isinstance(files, list):
        return jsonify({"error": "'files' must be an array"}), 400
    
    logger.info(f"📢 BATCH PURGE: {len(files)} files")
    
    results = {}
    for filename in files:
        results[filename] = broadcast_purge(filename, async_mode=True)
        update_stats(results[filename], filename)
    
    return jsonify({
        "status": "batch_completed",
        "total_files": len(files),
        "results": results
    })

@app.route('/purge/all', methods=['POST'])
def purge_all():
    """
    Purge entire cache from all edge nodes
    POST /purge/all
    """
    logger.info("📢 PURGE ALL: Clearing entire cache from all nodes")
    
    results = []
    
    for node in EDGE_NODES:
        try:
            purge_url = f"{node['url']}/cache"
            response = requests.delete(purge_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                results.append({
                    "node": node['name'],
                    "url": node['url'],
                    "success": True,
                    "files_removed": data.get('count', 0)
                })
                logger.info(f"✅ {node['name']}: Purged all ({data.get('count', 0)} files)")
            else:
                results.append({
                    "node": node['name'],
                    "url": node['url'],
                    "success": False,
                    "error": f"HTTP {response.status_code}"
                })
        except Exception as e:
            results.append({
                "node": node['name'],
                "url": node['url'],
                "success": False,
                "error": str(e)
            })
    
    stats['total_purges'] += 1
    stats['last_purge'] = {
        "filename": "ALL_FILES",
        "timestamp": datetime.now().isoformat(),
        "results": results
    }
    
    successful = sum(1 for r in results if r['success'])
    
    return jsonify({
        "status": "completed",
        "action": "purge_all",
        "successful_nodes": successful,
        "total_nodes": len(results),
        "all_success": successful == len(results),
        "results": results
    })

@app.route('/cache/status', methods=['GET'])
def cache_status():
    """Get cache status from all edge nodes"""
    results = []
    
    for node in EDGE_NODES:
        try:
            response = requests.get(f"{node['url']}/cache/list", timeout=5)
            if response.status_code == 200:
                data = response.json()
                results.append({
                    "node": node['name'],
                    "url": node['url'],
                    "cached_files": data.get('count', 0),
                    "files": data.get('files', [])
                })
            else:
                results.append({
                    "node": node['name'],
                    "url": node['url'],
                    "error": f"HTTP {response.status_code}"
                })
        except Exception as e:
            results.append({
                "node": node['name'],
                "url": node['url'],
                "error": str(e)
            })
    
    return jsonify({
        "timestamp": datetime.now().isoformat(),
        "nodes": results
    })

# ==================== WEBHOOK ENDPOINT (Optional) ===================//

@app.route('/webhook/origin', methods=['POST'])
def origin_webhook():
    """
    Webhook endpoint that origin server can call when content updates
    Automatically purges the updated file
    """
    data = request.get_json()
    
    if not data or 'filename' not in data:
        return jsonify({"error": "Missing filename"}), 400
    
    filename = data['filename']
    event = data.get('event', 'updated')
    
    logger.info(f"📢 Webhook received: {filename} ({event})")
    
    # Automatically purge the updated file
    results = broadcast_purge(filename, async_mode=True)
    update_stats(results, filename)
    
    successful = sum(1 for r in results if r['success'])
    
    return jsonify({
        "status": "webhook_processed",
        "event": event,
        "filename": filename,
        "purge_result": {
            "successful_nodes": successful,
            "total_nodes": len(results)
        }
    })

# ==================== MAIN ====================

if __name__ == '__main__':
    logger.info("=" * 70)
    logger.info("🧹 PURGE SERVICE - Cache Invalidation Controller")
    logger.info("=" * 70)
    logger.info("Edge Nodes:")
    for node in EDGE_NODES:
        logger.info(f"   • {node['name']}: {node['url']}")
    logger.info("")
    logger.info("Endpoints:")
    logger.info("   POST /purge/<filename>  - Purge single file")
    logger.info("   POST /purge/batch       - Purge multiple files")
    logger.info("   POST /purge/all         - Purge entire cache")
    logger.info("   GET  /status            - Node status")
    logger.info("   GET  /stats             - Purge statistics")
    logger.info("   GET  /cache/status      - Cache contents")
    logger.info("   POST /webhook/origin    - Auto-purge on update")
    logger.info("=" * 70)
    
    app.run(host='0.0.0.0', port=8085, debug=False)