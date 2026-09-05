"""
ORIGIN SERVER - Internal Only with Auto-Purge
Stores original files, triggers purge when files are updated
"""

from flask import Flask, request, jsonify, send_file
import os
import time
import logging
import requests
import threading

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [ORIGIN] - %(levelname)s - %(message)s')
logger = logging.getLogger('origin')

app = Flask(__name__)

# Storage path (internal)
STORAGE_PATH = "/app/data"
os.makedirs(STORAGE_PATH, exist_ok=True)

# Purge Service URL (internal)
PURGE_SERVICE_URL = "http://purge-service:8085"

# Configuration
AUTO_PURGE_ENABLED = True  # Set to False to disable auto-purge

# Create sample files
def create_sample_files():
    samples = {
        "welcome.txt": "Welcome to our CDN!\nThis is a test file.",
        "sample.jpg": "Fake image data - " * 50,
        "sample.mp4": "Fake video data - " * 100,
        "sample.pdf": "Fake PDF content - " * 75
    }
    
    for filename, content in samples.items():
        filepath = os.path.join(STORAGE_PATH, filename)
        if not os.path.exists(filepath):
            with open(filepath, 'w') as f:
                f.write(content)
            logger.info(f"Created: {filename}")

def trigger_purge(filename, async_mode=True):
    """
    Trigger purge for a file when it's updated
    """
    if not AUTO_PURGE_ENABLED:
        logger.info(f"Auto-purge disabled, skipping purge for: {filename}")
        return
    
    def purge_call():
        try:
            purge_url = f"{PURGE_SERVICE_URL}/purge/{filename}"
            logger.info(f"📢 Triggering auto-purge for: {filename}")
            response = requests.post(purge_url, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"✅ Auto-purge successful: {result.get('successful_nodes', 0)}/{result.get('total_nodes', 0)} nodes")
            else:
                logger.warning(f"⚠️ Auto-purge returned status: {response.status_code}")
        except Exception as e:
            logger.error(f"❌ Auto-purge failed: {e}")
    
    if async_mode:
        # Don't block the upload response
        thread = threading.Thread(target=purge_call)
        thread.start()
        logger.info(f"Auto-purge triggered asynchronously for: {filename}")
    else:
        # Blocking mode (slower but guaranteed)
        purge_call()

@app.route('/')
def home():
    return "Origin Server - Internal CDN Backend with Auto-Purge"

@app.route('/health')
def health():
    """Health check for internal monitoring"""
    return jsonify({
        "status": "healthy",
        "service": "origin-server",
        "files": len(os.listdir(STORAGE_PATH)),
        "auto_purge": AUTO_PURGE_ENABLED,
        "purge_service": PURGE_SERVICE_URL
    })

@app.route('/files/<filename>', methods=['GET'])
def get_file(filename):
    """Serve file - ONLY called by Edge Nodes (internal)"""
    logger.info(f"📤 Internal request: {filename}")
    time.sleep(2)  # Simulate backbone delay
    
    filepath = os.path.join(STORAGE_PATH, filename)
    if os.path.exists(filepath):
        return send_file(filepath)
    return jsonify({"error": "File not found"}), 404

@app.route('/files/<filename>', methods=['PUT'])
def upload_file(filename):
    """
    Upload file - for admin use only
    Triggers auto-purge to invalidate old cache
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file"}), 400
    
    file = request.files['file']
    filepath = os.path.join(STORAGE_PATH, filename)
    
    # Check if this is an update (file already exists)
    is_update = os.path.exists(filepath)
    old_size = os.path.getsize(filepath) if is_update else 0
    old_modified = os.path.getmtime(filepath) if is_update else None
    
    # Save the file
    file.save(filepath)
    new_size = os.path.getsize(filepath)
    new_modified = os.path.getmtime(filepath)
    
    logger.info(f"📥 Uploaded: {filename}")
    logger.info(f"   Update: {is_update}")
    logger.info(f"   Size: {old_size} → {new_size} bytes")
    
    # TRIGGER AUTO-PURGE if this is an update
    if is_update:
        logger.info(f"📢 File updated! Triggering auto-purge for: {filename}")
        trigger_purge(filename, async_mode=True)
    else:
        logger.info(f"📝 New file created (no purge needed): {filename}")
    
    return jsonify({
        "status": "uploaded",
        "filename": filename,
        "is_update": is_update,
        "old_size": old_size,
        "new_size": new_size,
        "size_diff": new_size - old_size,
        "auto_purge_triggered": is_update,
        "timestamp": time.time()
    })

@app.route('/files/<filename>', methods=['DELETE'])
def delete_file(filename):
    """
    Delete file - triggers purge to remove from all caches
    """
    filepath = os.path.join(STORAGE_PATH, filename)
    
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    
    # Get file info before deletion
    file_size = os.path.getsize(filepath)
    os.remove(filepath)
    
    logger.info(f"🗑️ Deleted: {filename} ({file_size} bytes)")
    
    # Trigger purge to remove from all edge caches
    trigger_purge(filename, async_mode=True)
    
    return jsonify({
        "status": "deleted",
        "filename": filename,
        "size": file_size,
        "auto_purge_triggered": True
    })

@app.route('/list', methods=['GET'])
def list_files():
    """List files - internal use only"""
    files = []
    for f in os.listdir(STORAGE_PATH):
        filepath = os.path.join(STORAGE_PATH, f)
        if os.path.isfile(filepath):
            files.append({
                "name": f, 
                "size": os.path.getsize(filepath),
                "modified": os.path.getmtime(filepath)
            })
    return jsonify({
        "count": len(files), 
        "files": files,
        "auto_purge": AUTO_PURGE_ENABLED
    })

@app.route('/config', methods=['GET'])
def get_config():
    """Get origin server configuration"""
    return jsonify({
        "storage_path": STORAGE_PATH,
        "auto_purge_enabled": AUTO_PURGE_ENABLED,
        "purge_service_url": PURGE_SERVICE_URL,
        "backbone_delay_seconds": 2
    })

@app.route('/config/purge', methods=['POST'])
def toggle_purge():
    """Toggle auto-purge on/off (admin endpoint)"""
    global AUTO_PURGE_ENABLED
    
    data = request.get_json()
    if data and 'enabled' in data:
        AUTO_PURGE_ENABLED = bool(data['enabled'])
    
    return jsonify({
        "auto_purge_enabled": AUTO_PURGE_ENABLED,
        "message": f"Auto-purge {'enabled' if AUTO_PURGE_ENABLED else 'disabled'}"
    })

if __name__ == '__main__':
    create_sample_files()
    logger.info("=" * 60)
    logger.info("ORIGIN SERVER STARTING (INTERNAL ONLY)")
    logger.info(f"Storage: {STORAGE_PATH}")
    logger.info(f"Auto-Purge: {'ENABLED' if AUTO_PURGE_ENABLED else 'DISABLED'}")
    logger.info(f"Purge Service: {PURGE_SERVICE_URL}")
    logger.info("=" * 60)
    app.run(host='0.0.0.0', port=8084, debug=False)