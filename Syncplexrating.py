from plexapi.server import PlexServer
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, POPM, ID3NoHeaderError
import os
import logging

# ============================================================
# User Settable Variables
# ============================================================

# URL of the Plex server. Replace with your actual Plex server URL.
PLEX_URL = 'http://your-plex-server:32400'

# Plex token for authentication. Replace with your actual Plex token.
PLEX_TOKEN = 'your-plex-token'

# Name of the music library in Plex. Ensure this matches the name of your library in Plex.
PLEX_MUSIC_LIBRARY_NAME = 'YourMusicLibraryName'

# Logging level for the script.
LOG_LEVEL = 'INFO'

# Test mode flag. Set to True to run in test mode without making changes, or False to apply changes.
TEST_MODE = True

# Progress update frequency (display update after processing this many tracks)
PROGRESS_UPDATE_FREQUENCY = 50

# Number of worker threads/processes to use
MAX_WORKERS = 4

# Rating sync direction: 'PLEX' or 'FILE'
# 'PLEX': Plex ratings are considered master and will update file tags
# 'FILE': File ratings are considered master and will update Plex
MASTER_SOURCE = 'FILE'  # Options: 'PLEX' or 'FILE'

# ============================================================
# Path Translation
# ============================================================

# Prefix for the music path as seen by Plex. Adjust to match your Plex server's configuration.
PLEX_PATH_PREFIX = '/music/'

# Prefix for the music path on the local host. Adjust to match your local file system.
HOST_PATH_PREFIX = 'Y:\\Music\\MusicBee\\Music\\'

# Set up logging
logging.basicConfig(level=LOG_LEVEL, format='%(message)s')
logger = logging.getLogger(__name__)

# Suppress plexapi debug output
logging.getLogger('plexapi').setLevel(logging.WARNING)

# Validate settings
if MASTER_SOURCE not in ['PLEX', 'FILE']:
    logger.error(f"Invalid MASTER_SOURCE: {MASTER_SOURCE}. Must be either 'PLEX' or 'FILE'")
    sys.exit(1)

# Script mode description
SCRIPT_MODE = "AUDIO FILES ARE MASTER" if MASTER_SOURCE == 'FILE' else "PLEX IS MASTER"

# Counters and thread-safe lock
counters_lock = threading.Lock()
insync = 0
justsynced = 0
notag = 0
error = 0
not_found = 0
tracks_processed = 0
total_tracks = 0

# Time tracking
start_time = time.time()

# Cache for path translations to reduce redundant operations
@lru_cache(maxsize=1024)
def translate_path(plex_path):
    """
    Translate a Plex path to a local host path.
    Uses LRU cache to speed up repeated path translations.
    
    Handles conversion from Unix-style paths (used by Plex) to Windows-style paths.
    Correctly maintains the subdirectory structure after the prefix.
    """
    if not plex_path.startswith(PLEX_PATH_PREFIX):
        logger.warning(f"Path does not start with expected prefix: {plex_path}")
        return plex_path
        
    # Extract the part after the prefix
    relative_path = plex_path[len(PLEX_PATH_PREFIX):]
    
    # Convert forward slashes to backslashes for Windows
    if '\\' in HOST_PATH_PREFIX:  # Detect if we're on Windows
        relative_path = relative_path.replace('/', '\\')
    
    # Make sure HOST_PATH_PREFIX doesn't end with a slash or backslash
    host_prefix = HOST_PATH_PREFIX
    if host_prefix.endswith('\\') or host_prefix.endswith('/'):
        host_prefix = host_prefix[:-1]
    
    # Join with the correct separator
    if '\\' in HOST_PATH_PREFIX:  # Windows
        return f"{host_prefix}\\{relative_path}"
    else:  # Unix
        return f"{host_prefix}/{relative_path}"

# Cache rating conversions to reduce redundant calculations
@lru_cache(maxsize=100)
def plex_to_mp3_rating(plex_rating):
    """Convert Plex rating (0-10) to MP3 rating format with caching."""
    stars = round(plex_rating / 2)
    if stars == 0:
        return 0
    elif stars == 1:
        return 1
    elif stars == 2:
        return 64
    elif stars == 3:
        return 128
    elif stars == 4:
        return 196
    else:
        return 255

@lru_cache(maxsize=100)
def mp3_to_plex_rating(mp3_rating):
    """Convert MP3 rating to Plex rating (0-10) with caching."""
    if mp3_rating == 0:
        return 0
    elif mp3_rating == 1:
        return 2
    elif mp3_rating <= 64:
        return 4
    elif mp3_rating <= 128:
        return 6
    elif mp3_rating <= 196:
        return 8
    else:
        return 10

def get_rating(audiofile):
    """Get the rating from an audio file's tags."""
    try:
        popm = audiofile.tags.getall('POPM')
        # Take the first POPM tag we find, regardless of email field
        if popm and len(popm) > 0:
            return popm[0].rating
        return None
    except Exception as e:
        logger.error(f"Error getting rating: {str(e)}")
        return None

def set_rating(audiofile, rating):
    """Set the rating in an audio file's tags."""
    try:
        popm_frames = audiofile.tags.getall('POPM')
        
        if popm_frames and len(popm_frames) > 0:
            # Update the first existing POPM frame
            popm_frames[0].rating = rating
        else:
            # If no POPM frames exist, create a new one
            # Using 'MusicBee' as email to maintain compatibility with MusicBee
            popm = POPM(email='MusicBee', rating=rating, count=0)
            audiofile.tags.add(popm)
        
        audiofile.save()
    except Exception as e:
        logger.error(f"Error setting rating: {str(e)}")

def process_mp3(track, host_path):
    """Process an MP3 file to sync ratings with Plex."""
    global insync, justsynced, notag, error
    
    try:
        audiofile = MP3(host_path, ID3=ID3)
    except ID3NoHeaderError:
        with counters_lock:
            error += 1
        logger.error(f"Error: No ID3 tag found for {track.title}")
        return
    except Exception as e:
        with counters_lock:
            error += 1
        logger.error(f"Error loading MP3 file: {track.title} - {str(e)}")
        return

    current_rating = get_rating(audiofile)

    if MASTER_SOURCE == 'PLEX':
        # PLEX IS MASTER - Update file from Plex
        if isinstance(track.userRating, float):
            mp3_rating = plex_to_mp3_rating(track.userRating)
            
            if current_rating == mp3_rating:
                with counters_lock:
                    insync += 1
                logger.debug(f'Synchronized: {track.title} (MP3)')
            else:
                if not TEST_MODE:
                    set_rating(audiofile, mp3_rating)
                    
                    # Verify the change
                    audiofile = MP3(host_path, ID3=ID3)
                    new_rating = get_rating(audiofile)
                    
                    if new_rating == mp3_rating:
                        with counters_lock:
                            justsynced += 1
                        logger.debug(f'Updated and verified file: {track.title} with rating {mp3_rating}')
                    else:
                        with counters_lock:
                            error += 1
                        logger.error(f'Failed to update file: {track.title}. Expected {mp3_rating}, got {new_rating}')
                else:
                    logger.debug(f'Would update file: {track.title} with rating {mp3_rating}')
                    with counters_lock:
                        justsynced += 1  # Count as synced in test mode for reporting
        else:
            # Plex has no rating
            if current_rating is not None:
                # File has rating but Plex doesn't - unusual in Plex-master mode
                # We'll still update Plex for consistency
                plex_rating = mp3_to_plex_rating(current_rating)
                if not TEST_MODE:
                    track.rate(plex_rating)
                logger.debug(f'Backfilled Plex: {track.title} with rating {plex_rating}')
                with counters_lock:
                    justsynced += 1
            else:
                # No rating in either place
                with counters_lock:
                    notag += 1
    else:
        # FILE IS MASTER - Update Plex from file
        if current_rating is not None:
            # Convert file rating to Plex format
            plex_rating = mp3_to_plex_rating(current_rating)
            
            # Check if Plex rating matches
            if isinstance(track.userRating, float) and abs(track.userRating - plex_rating) < 0.1:
                # Ratings match, already in sync
                with counters_lock:
                    insync += 1
                logger.debug(f'Synchronized: {track.title} (MP3)')
            else:
                # Update Plex with file rating
                if not TEST_MODE:
                    track.rate(plex_rating)
                logger.debug(f'Would update Plex: {track.title} with rating {plex_rating}')
                with counters_lock:
                    justsynced += 1
        else:
            # File has no rating
            if isinstance(track.userRating, float):
                # If Plex has rating but file doesn't, remove Plex rating
                if not TEST_MODE:
                    track.rate(None)  # Set to null/none in Plex
                logger.debug(f'Would remove Plex rating: {track.title}')
                with counters_lock:
                    justsynced += 1
            else:
                # No rating in either place
                with counters_lock:
                    notag += 1

@lru_cache(maxsize=100)
def plex_to_flac_rating(plex_rating):
    """Convert Plex rating to FLAC rating format with caching."""
    return str(min(5, max(1, round(plex_rating / 2))))

@lru_cache(maxsize=100)
def flac_to_plex_rating(flac_rating):
    """Convert FLAC rating to Plex rating with caching."""
    return float(flac_rating) * 2

def process_flac(track, host_path):
    """Process a FLAC file to sync ratings with Plex."""
    global insync, justsynced, notag, error
    
    try:
        audiofile = FLAC(host_path)
    except Exception as e:
        with counters_lock:
            error += 1
        logger.error(f"Error loading FLAC file: {track.title} - {str(e)}")
        return

    # Get current rating from file
    current_rating = audiofile.get('RATING', [None])[0]
    
    if MASTER_SOURCE == 'PLEX':
        # PLEX IS MASTER - Update file from Plex
        if isinstance(track.userRating, float):
            plex_rating_converted = plex_to_flac_rating(track.userRating)
            
            if current_rating == plex_rating_converted:
                with counters_lock:
                    insync += 1
                logger.debug(f'Synchronized: {track.title} (FLAC)')
            else:
                if not TEST_MODE:
                    audiofile['RATING'] = [plex_rating_converted]
                    audiofile.save()
                    
                    # Verify the change
                    audiofile = FLAC(host_path)
                    new_rating = audiofile.get('RATING', [None])[0]
                    if new_rating == plex_rating_converted:
                        with counters_lock:
                            justsynced += 1
                        logger.debug(f'Updated and verified file: {track.title} with rating {plex_rating_converted}')
                    else:
                        with counters_lock:
                            error += 1
                        logger.error(f'Failed to update file: {track.title}. Expected {plex_rating_converted}, got {new_rating}')
                else:
                    logger.debug(f'Would update file: {track.title} with rating {plex_rating_converted}')
                    with counters_lock:
                        justsynced += 1  # Count as synced in test mode for reporting
        else:
            # Plex has no rating
            if current_rating is not None:
                # File has rating but Plex doesn't - unusual in Plex-master mode
                # We'll still update Plex for consistency
                plex_rating = flac_to_plex_rating(float(current_rating))
                if not TEST_MODE:
                    track.rate(plex_rating)
                logger.debug(f'Backfilled Plex: {track.title} with rating {plex_rating}')
                with counters_lock:
                    justsynced += 1
            else:
                # No rating in either place
                logger.debug(f'No rating found: {track.title} (FLAC)')
                with counters_lock:
                    notag += 1
    else:
        # FILE IS MASTER - Update Plex from file
        if current_rating is not None:
            # Convert file rating to Plex format
            plex_rating = flac_to_plex_rating(float(current_rating))
            
            # Check if Plex rating matches
            if isinstance(track.userRating, float) and abs(track.userRating - plex_rating) < 0.1:
                # Ratings match, already in sync
                with counters_lock:
                    insync += 1
                logger.debug(f'Synchronized: {track.title} (FLAC)')
            else:
                # Update Plex with file rating
                if not TEST_MODE:
                    track.rate(plex_rating)
                logger.debug(f'Would update Plex: {track.title} with rating {plex_rating}')
                with counters_lock:
                    justsynced += 1
        else:
            # File has no rating
            if isinstance(track.userRating, float):
                # If Plex has rating but file doesn't, remove Plex rating
                if not TEST_MODE:
                    track.rate(None)  # Set to null/none in Plex
                logger.debug(f'Would remove Plex rating: {track.title}')
                with counters_lock:
                    justsynced += 1
            else:
                # No rating in either place
                logger.debug(f'No rating found: {track.title} (FLAC)')
                with counters_lock:
                    notag += 1

def process_track(track_data):
    """Process a single track (for use with thread pool)."""
    global tracks_processed, not_found, error
    
    track, album_name = track_data
    
    try:
        host_path = translate_path(track.locations[0])
        
        if not os.path.exists(host_path):
            with counters_lock:
                not_found += 1
                tracks_processed += 1
            return
        
        if host_path.lower().endswith('.mp3'):
            process_mp3(track, host_path)
        elif host_path.lower().endswith('.flac'):
            process_flac(track, host_path)
        else:
            with counters_lock:
                error += 1
        
        with counters_lock:
            tracks_processed += 1
            
            # Only print progress from one thread at specified intervals
            if tracks_processed % PROGRESS_UPDATE_FREQUENCY == 0:
                print_progress()
                
    except Exception as e:
        logger.error(f"Error processing track {track.title} from album {album_name}: {str(e)}")
        with counters_lock:
            error += 1
            tracks_processed += 1

def print_progress():
    """Print progress information to the console."""
    global tracks_processed, total_tracks, start_time
    
    current_time = time.time()
    elapsed_time = current_time - start_time
    
    if total_tracks > 0:
        percent_complete = (tracks_processed / total_tracks) * 100
        
        # Estimate remaining time
        if tracks_processed > 0:
            time_per_track = elapsed_time / tracks_processed
            remaining_tracks = total_tracks - tracks_processed
            estimated_remaining_time = remaining_tracks * time_per_track
            
            # Format estimated remaining time
            remaining_hours = int(estimated_remaining_time // 3600)
            remaining_minutes = int((estimated_remaining_time % 3600) // 60)
            remaining_seconds = int(estimated_remaining_time % 60)
            
            time_str = f"{remaining_hours}h {remaining_minutes}m {remaining_seconds}s"
        else:
            time_str = "calculating..."
        
        logger.info(f"Progress: {tracks_processed}/{total_tracks} tracks processed ({percent_complete:.1f}%) - ETA: {time_str}")
        logger.info(f"Current stats: {insync} in sync, {justsynced} synced, {notag} no tags, {error} errors, {not_found} not found")
    else:
        logger.info(f"Progress: {tracks_processed} tracks processed")

def main():
    """Main execution function."""
    global total_tracks, tracks_processed, not_found, insync, justsynced, notag, error
    # Reset counters to ensure clean state when running
    tracks_processed = 0
    not_found = 0
    insync = 0
    justsynced = 0
    notag = 0
    error = 0
    
    # Connect to Plex
    logger.info("Connecting to Plex server...")
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)

    logger.info(f"Connected to Plex server: {plex.friendlyName}")
    logger.info(f"Accessing library: {PLEX_MUSIC_LIBRARY_NAME}")

    try:
        music_library = plex.library.section(PLEX_MUSIC_LIBRARY_NAME)
        albums = music_library.albums()
        
        # Count total tracks for progress tracking
        logger.info(f"Found {len(albums)} albums. Counting tracks...")
        
        # First pass to count total tracks for progress reporting
        for album in albums:
            total_tracks += len(album.tracks())
        
        logger.info(f"Starting to process {total_tracks} tracks using {MAX_WORKERS} worker threads" + 
               (" in TEST MODE" if TEST_MODE else " in ACTIVE MODE") + f" - {SCRIPT_MODE}")
        
        # Prepare track data for processing
        all_tracks = []
        for album in albums:
            album_name = album.title
            logger.info(f"Queuing album: '{album_name}' ({len(album.tracks())} tracks)")
            
            for track in album.tracks():
                all_tracks.append((track, album_name))
        
        # Process tracks using thread pool
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # Submit all tasks and wait for completion
            list(executor.map(process_track, all_tracks))
            
    except Exception as e:
        logger.error(f"Error accessing music library: {str(e)}")
        return 1
    
    # Final stats Output
    elapsed_time = time.time() - start_time
    hours = int(elapsed_time // 3600)
    minutes = int((elapsed_time % 3600) // 60)
    seconds = int(elapsed_time % 60)

    logger.info("\nFinal Summary:")
    logger.info(f"Total processing time: {hours}h {minutes}m {seconds}s")
    logger.info(f"{insync} files already in sync")
    logger.info(f"{justsynced} newly synced files")
    logger.info(f"{notag} files with no tags")
    logger.info(f"{error} files had errors")
    logger.info(f"{not_found} files not found")
    logger.info(f"Total files processed: {tracks_processed}")
    
    return 0

if __name__ == "__main__":
    main()