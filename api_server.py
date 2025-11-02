from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import os
import threading
import time
import libtorrent as lt
from datetime import datetime
import hashlib

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend
socketio = SocketIO(app, cors_allowed_origins="*")

# Configuration
DOWNLOAD_FOLDER = os.path.join(os.getcwd(), "downloads")
UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Global state management
active_downloads = {}
scan_results = {}


# ============= TORRENT CLIENT CLASS =============
class TorrentDownloader:
    def __init__(self, download_id):
        self.download_id = download_id
        self.session = lt.session()
        
        settings = self.session.get_settings()
        settings['listen_interfaces'] = '0.0.0.0:6881'
        settings['enable_dht'] = True
        settings['enable_lsd'] = True
        settings['enable_upnp'] = True
        settings['enable_natpmp'] = True
        settings['announce_to_all_trackers'] = True
        settings['announce_to_all_tiers'] = True
        self.session.apply_settings(settings)

        self.session.add_dht_router("router.bittorrent.com", 6881)
        self.session.add_dht_router("router.utorrent.com", 6881)
        self.session.add_dht_router("dht.transmissionbt.com", 6881)
        self.session.start_dht()
        
        self.handle = None
        self.info = None
        self.stopped = False

    def download_chunks_with_scan(self, torrent_file_path, save_path, num_pieces=10):
        """Download chunks and emit progress via WebSocket"""
        
        try:
            self.info = lt.torrent_info(torrent_file_path)
            
            params = {
                'save_path': save_path,
                'storage_mode': lt.storage_mode_t.storage_mode_sparse,
                'ti': self.info
            }
            
            self.handle = self.session.add_torrent(params)
            
            total_pieces = self.info.num_pieces()
            num_pieces = min(num_pieces, total_pieces)
            
            # Prioritize only first N pieces
            priorities = [0] * total_pieces
            for i in range(num_pieces):
                priorities[i] = 7
            
            self.handle.prioritize_pieces(priorities)
            
            # Emit initial status
            socketio.emit('download_started', {
                'download_id': self.download_id,
                'name': self.info.name(),
                'total_size': self.info.total_size(),
                'total_pieces': total_pieces,
                'downloading_pieces': num_pieces,
                'piece_size': self.info.piece_length()
            })
            
            pieces_downloaded = set()
            
            while len(pieces_downloaded) < num_pieces and not self.stopped:
                s = self.handle.status()
                
                state_str = [
                    'queued', 'checking', 'downloading metadata',
                    'downloading', 'finished', 'seeding', 'allocating',
                    'checking fastresume', 'unknown'
                ]
                state_idx = min(s.state, len(state_str) - 1)
                
                # Check for newly downloaded pieces
                if s.has_metadata:
                    for i in range(num_pieces):
                        if self.handle.have_piece(i) and i not in pieces_downloaded:
                            pieces_downloaded.add(i)
                            
                            # 🔬 HOOK FOR ML MALWARE DETECTION
                            piece_hash = str(self.info.hash_for_piece(i))
                            scan_result = self.scan_piece(i, piece_hash)
                            
                            socketio.emit('piece_downloaded', {
                                'download_id': self.download_id,
                                'piece_index': i,
                                'piece_hash': piece_hash,
                                'scan_result': scan_result,
                                'progress': (len(pieces_downloaded) / num_pieces) * 100
                            })
                
                # Emit progress update
                progress_percent = (len(pieces_downloaded) / num_pieces) * 100
                socketio.emit('download_progress', {
                    'download_id': self.download_id,
                    'progress': progress_percent,
                    'state': state_str[state_idx],
                    'peers': s.num_peers,
                    'download_rate': s.download_rate,
                    'pieces_completed': len(pieces_downloaded),
                    'total_pieces': num_pieces
                })
                
                time.sleep(0.5)
            
            if not self.stopped:
                socketio.emit('download_complete', {
                    'download_id': self.download_id,
                    'pieces_downloaded': len(pieces_downloaded),
                    'file_path': os.path.join(save_path, self.info.name())
                })
                
            return {
                'success': True,
                'pieces_downloaded': len(pieces_downloaded),
                'file_name': self.info.name()
            }
            
        except Exception as e:
            socketio.emit('download_error', {
                'download_id': self.download_id,
                'error': str(e)
            })
            return {'success': False, 'error': str(e)}

    def scan_piece(self, piece_index, piece_hash):
        """
        🔬 MALWARE DETECTION HOOK
        Your teammate will replace this with ML model
        """
        # Placeholder for ML scanner
        # TODO: Integrate ML model here
        # Example:
        # piece_data = self.handle.read_piece(piece_index)
        # features = extract_features(piece_data)
        # prediction = ml_model.predict(features)
        # return {'malicious': prediction, 'confidence': confidence}
        
        return {
            'malicious': False,
            'confidence': 0.0,
            'scanner': 'placeholder',
            'timestamp': datetime.now().isoformat()
        }

    def stop(self):
        """Stop the download"""
        self.stopped = True
        if self.handle:
            self.session.remove_torrent(self.handle)


# ============= REST API ENDPOINTS =============

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'active_downloads': len(active_downloads),
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/upload-torrent', methods=['POST'])
def upload_torrent():
    """Upload .torrent file"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not file.filename.endswith('.torrent'):
        return jsonify({'error': 'File must be a .torrent file'}), 400
    
    # Save the torrent file
    filename = f"{hashlib.md5(file.filename.encode()).hexdigest()}.torrent"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    
    # Parse torrent info
    try:
        info = lt.torrent_info(filepath)
        torrent_data = {
            'torrent_id': filename.replace('.torrent', ''),
            'name': info.name(),
            'total_size': info.total_size(),
            'total_pieces': info.num_pieces(),
            'piece_size': info.piece_length(),
            'file_path': filepath
        }
        
        return jsonify({
            'success': True,
            'torrent': torrent_data
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'Invalid torrent file: {str(e)}'}), 400


@app.route('/api/start-download', methods=['POST'])
def start_download():
    """Start downloading torrent with chunk-level scanning"""
    data = request.json
    
    if not data or 'torrent_id' not in data:
        return jsonify({'error': 'torrent_id required'}), 400
    
    torrent_id = data['torrent_id']
    num_pieces = data.get('num_pieces', 10)  # Default to 10 pieces
    
    torrent_file = os.path.join(UPLOAD_FOLDER, f"{torrent_id}.torrent")
    
    if not os.path.exists(torrent_file):
        return jsonify({'error': 'Torrent file not found'}), 404
    
    # Generate unique download ID
    download_id = hashlib.md5(f"{torrent_id}_{datetime.now().isoformat()}".encode()).hexdigest()
    
    # Create downloader instance
    downloader = TorrentDownloader(download_id)
    active_downloads[download_id] = downloader
    
    # Start download in background thread
    def download_thread():
        result = downloader.download_chunks_with_scan(
            torrent_file,
            DOWNLOAD_FOLDER,
            num_pieces
        )
        # Clean up
        if download_id in active_downloads:
            del active_downloads[download_id]
    
    thread = threading.Thread(target=download_thread, daemon=True)
    thread.start()
    
    return jsonify({
        'success': True,
        'download_id': download_id,
        'message': 'Download started'
    }), 202


@app.route('/api/download-status/<download_id>', methods=['GET'])
def download_status(download_id):
    """Get download status"""
    if download_id not in active_downloads:
        return jsonify({'error': 'Download not found'}), 404
    
    downloader = active_downloads[download_id]
    
    if downloader.handle:
        s = downloader.handle.status()
        state_str = [
            'queued', 'checking', 'downloading metadata',
            'downloading', 'finished', 'seeding', 'allocating',
            'checking fastresume', 'unknown'
        ]
        state_idx = min(s.state, len(state_str) - 1)
        
        return jsonify({
            'download_id': download_id,
            'state': state_str[state_idx],
            'progress': s.progress * 100,
            'peers': s.num_peers,
            'download_rate': s.download_rate,
            'upload_rate': s.upload_rate
        })
    
    return jsonify({'error': 'Download not active'}), 400


@app.route('/api/stop-download/<download_id>', methods=['POST'])
def stop_download(download_id):
    """Stop a download"""
    if download_id not in active_downloads:
        return jsonify({'error': 'Download not found'}), 404
    
    downloader = active_downloads[download_id]
    downloader.stop()
    del active_downloads[download_id]
    
    return jsonify({
        'success': True,
        'message': 'Download stopped'
    })


@app.route('/api/scan-results/<download_id>', methods=['GET'])
def get_scan_results(download_id):
    """Get malware scan results for a download"""
    if download_id in scan_results:
        return jsonify({
            'download_id': download_id,
            'results': scan_results[download_id]
        })
    
    return jsonify({'error': 'No scan results found'}), 404


@app.route('/api/downloads', methods=['GET'])
def list_downloads():
    """List all active downloads"""
    downloads = []
    for download_id, downloader in active_downloads.items():
        if downloader.info:
            downloads.append({
                'download_id': download_id,
                'name': downloader.info.name(),
                'total_size': downloader.info.total_size()
            })
    
    return jsonify({'downloads': downloads})


# ============= WEBSOCKET EVENTS =============

@socketio.on('connect')
def handle_connect():
    print(f'Client connected: {request.sid}')
    emit('connection_response', {'status': 'connected'})


@socketio.on('disconnect')
def handle_disconnect():
    print(f'Client disconnected: {request.sid}')


@socketio.on('subscribe_download')
def handle_subscribe(data):
    """Client subscribes to download updates"""
    download_id = data.get('download_id')
    print(f'Client {request.sid} subscribed to download {download_id}')


# ============= RUN SERVER =============

if __name__ == '__main__':
    print("="*60)
    print("🚀 Torrent Malware Detection API Server")
    print("="*60)
    print(f"📁 Downloads: {DOWNLOAD_FOLDER}")
    print(f"📁 Uploads: {UPLOAD_FOLDER}")
    print("📡 WebSocket: Enabled for real-time updates")
    print("🔬 ML Integration: Ready (placeholder active)")
    print("="*60)
    print("\nAPI Endpoints:")
    print("  GET  /api/health")
    print("  POST /api/upload-torrent")
    print("  POST /api/start-download")
    print("  GET  /api/download-status/<id>")
    print("  POST /api/stop-download/<id>")
    print("  GET  /api/scan-results/<id>")
    print("  GET  /api/downloads")
    print("\nStarting server on http://localhost:5000")
    print("="*60 + "\n")
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
