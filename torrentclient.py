import libtorrent as lt
import time
import os

class TorrentClient:
    def __init__(self):
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
        
        print("Torrent client initialized. DHT enabled.")

    def download_chunks_only(self, torrent_file_path, save_path, num_pieces=5):
        """
        Download ONLY the first N pieces for malware scanning testing.
        Perfect for your chunk-level detection project!
        """
        
        # Load torrent info
        info = lt.torrent_info(torrent_file_path)
        
        params = {
            'save_path': save_path,
            'storage_mode': lt.storage_mode_t.storage_mode_sparse,
            'ti': info
        }
        
        handle = self.session.add_torrent(params)
        
        print(f"\n{'='*60}")
        print(f"Torrent: {info.name()}")
        print(f"Total size: {info.total_size() / (1024**2):.2f} MB")
        print(f"Total pieces: {info.num_pieces()}")
        print(f"Piece size: {info.piece_length() / 1024:.2f} KB")
        print(f"{'='*60}")
        
        # ✨ KEY FEATURE: Download ONLY first N pieces for malware detection testing
        total_pieces = info.num_pieces()
        num_pieces = min(num_pieces, total_pieces)  # Don't request more than available
        
        # Set all pieces to priority 0 (don't download)
        priorities = [0] * total_pieces
        
        # Set only first N pieces to priority 7 (highest)
        for i in range(num_pieces):
            priorities[i] = 7
        
        handle.prioritize_pieces(priorities)
        
        print(f"\n🎯 Downloading ONLY first {num_pieces} pieces ({num_pieces * info.piece_length() / 1024:.2f} KB)")
        print(f"   Perfect for testing your malware scanner!\n")
        
        # Wait for those specific pieces to download
        pieces_downloaded = set()
        
        try:
            while len(pieces_downloaded) < num_pieces:
                s = handle.status()
                
                # FIXED: Extended state list to avoid IndexError
                state_str = [
                    'queued', 'checking', 'downloading metadata',
                    'downloading', 'finished', 'seeding', 'allocating',
                    'checking fastresume', 'unknown'  # Added more states
                ]
                
                # Use min to prevent index out of range
                state_idx = min(s.state, len(state_str) - 1)
                state = state_str[state_idx]
                
                # Check which pieces we have
                if s.has_metadata:
                    for i in range(num_pieces):
                        if handle.have_piece(i) and i not in pieces_downloaded:
                            pieces_downloaded.add(i)
                            piece_hash = info.hash_for_piece(i)
                            print(f"✓ Piece {i}/{num_pieces-1} downloaded! Hash: {piece_hash}")
                
                progress_percent = (len(pieces_downloaded) / num_pieces) * 100
                download_speed_kb = s.download_rate / 1024
                
                print(f'\rProgress: {progress_percent:.1f}% | '
                      f'State: {state} | '
                      f'Peers: {s.num_peers} | '
                      f'Speed: {download_speed_kb:.1f} KB/s | '
                      f'Pieces: {len(pieces_downloaded)}/{num_pieces}   ', end='')
                
                time.sleep(0.5)
        
        except KeyboardInterrupt:
            print("\n\n⚠ Download stopped by user.")
            return None, pieces_downloaded

        print(f"\n\n{'='*60}")
        print(f"✓ Downloaded {len(pieces_downloaded)} chunks!")
        print(f"  You can now scan these pieces for malware patterns")
        print(f"{'='*60}\n")
        
        # Return info about downloaded pieces
        piece_info = {
            'file_name': info.name(),
            'save_path': save_path,
            'piece_length': info.piece_length(),
            'downloaded_pieces': list(pieces_downloaded),
            'total_pieces': total_pieces
        }
        
        return piece_info, pieces_downloaded

    def download_full_file(self, torrent_file_path, save_path):
        """Full download (original method, now fixed)"""
        
        info = lt.torrent_info(torrent_file_path)
        
        params = {
            'save_path': save_path,
            'storage_mode': lt.storage_mode_t.storage_mode_sparse,
            'ti': info
        }
        
        handle = self.session.add_torrent(params)
        print(f"Added torrent: {info.name()}")
        print(f"Total size: {info.total_size() / (1024**3):.2f} GB")
        print("Starting download...")
        
        try:
            while not handle.status().is_seeding:
                s = handle.status()
                
                # FIXED state list
                state_str = [
                    'queued', 'checking', 'downloading metadata',
                    'downloading', 'finished', 'seeding', 'allocating',
                    'checking fastresume', 'unknown'
                ]
                state_idx = min(s.state, len(state_str) - 1)
                
                progress_percent = s.progress * 100
                download_speed_mb = s.download_rate / (1024 * 1024)
                
                print(f'\rProgress: {progress_percent:.2f}% | '
                      f'Status: {state_str[state_idx]} | '
                      f'Peers: {s.num_peers} | '
                      f'Speed: {download_speed_mb:.2f} MB/s   ', end='')
                
                time.sleep(1)
        
        except KeyboardInterrupt:
            print("\n⚠ Download stopped by user.")
            return None

        print(f"\n✓ Download Complete!")
        
        if info.num_files() > 0:
            first_file = info.file_at(0)
            file_path = os.path.join(save_path, first_file.path)
        else:
            file_path = os.path.join(save_path, info.name())
        
        print(f"File saved: {file_path}")
        return file_path


if __name__ == "__main__":
    download_dir = os.path.join(os.getcwd(), "downloads")
    
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
        print(f"Created directory: {download_dir}")

    client = TorrentClient()
    
    # 🎯 OPTION 1: Test with tiny 4.8MB file from Internet Archive
    print("\n" + "="*60)
    print("DOWNLOAD SMALL TEST TORRENT (4.8MB)")
    print("Run this command first:")
    print("wget https://archive.org/download/tiny-iso-test/tiny-iso-test_archive.torrent")
    print("="*60)
    
    tiny_torrent = "tiny-iso-test_archive.torrent"
    
    if os.path.exists(tiny_torrent):
        # Download only first 5 chunks for malware scanning testing
        piece_info, downloaded_pieces = client.download_chunks_only(
            tiny_torrent, 
            download_dir, 
            num_pieces=5  # Download ONLY 5 pieces (small chunks)
        )
        
        if piece_info:
            print(f"\n🔬 NEXT STEP: Scan these pieces for malware:")
            print(f"   File: {download_dir}/{piece_info['file_name']}")
            print(f"   Piece size: {piece_info['piece_length'] / 1024:.2f} KB each")
            print(f"   Downloaded pieces: {piece_info['downloaded_pieces']}")
            print(f"\n   Now you can run your ML scanner on each piece!")
    else:
        print(f"\n❌ Torrent file not found: {tiny_torrent}")
        print("Download it with:")
        print(f"wget https://archive.org/download/tiny-iso-test/tiny-iso-test_archive.torrent")
        
        print("\n" + "="*60)
        print("OR use Ubuntu torrent:")
        print("wget https://releases.ubuntu.com/jammy/ubuntu-22.04.5-desktop-amd64.iso.torrent")
        print("="*60)
