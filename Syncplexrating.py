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

# ============================================================
# Path Translation
# ============================================================

# Prefix for the music path as seen by Plex. Adjust to match your Plex server's configuration.
PLEX_PATH_PREFIX = '/Music/'

# Prefix for the music path on the local host. Adjust to match your local file system.
HOST_PATH_PREFIX = '/mnt/Music/'

# Set up logging
logging.basicConfig(level=LOG_LEVEL, format='%(message)s')
logger = logging.getLogger(__name__)

# Suppress plexapi debug output
logging.getLogger('plexapi').setLevel(logging.WARNING)

# Counters
insync = 0
justsynced = 0
notag = 0
error = 0
not_found = 0

def translate_path(plex_path):
    return plex_path.replace(PLEX_PATH_PREFIX, HOST_PATH_PREFIX)

def plex_to_mp3_rating(plex_rating):
    """Convert Plex rating (0-10) to MP3 POPM rating - Compatible with existing files"""
    if plex_rating == 0:
        return 0
    elif plex_rating == 1:  # 0.5 stars
        return 1
    elif plex_rating == 2:  # 1 star
        return 1
    elif plex_rating == 3:  # 1.5 stars  
        return 32
    elif plex_rating == 4:  # 2 stars
        return 64
    elif plex_rating == 5:  # 2.5 stars
        return 96
    elif plex_rating == 6:  # 3 stars
        return 128
    elif plex_rating == 7:  # 3.5 stars
        return 162
    elif plex_rating == 8:  # 4 stars
        return 196
    elif plex_rating == 9:  # 4.5 stars
        return 225
    else:  # 5 stars (10)
        return 255

def mp3_to_plex_rating(mp3_rating):
    """Convert MP3 POPM rating to Plex rating - Compatible with existing files"""
    if mp3_rating == 0:
        return 0
    elif mp3_rating == 1:
        return 2  # 1 star
    elif mp3_rating <= 32:
        return 3  # 1.5 stars
    elif mp3_rating <= 64:
        return 4  # 2 stars
    elif mp3_rating <= 96:
        return 5  # 2.5 stars
    elif mp3_rating <= 128:
        return 6  # 3 stars
    elif mp3_rating <= 162:
        return 7  # 3.5 stars
    elif mp3_rating <= 196:
        return 8  # 4 stars
    elif mp3_rating <= 225:
        return 9  # 4.5 stars
    else:
        return 10  # 5 stars

def plex_to_flac_rating(plex_rating):
    """Convert Plex rating (0-10) to FLAC rating (0-5 with decimals)"""
    if plex_rating == 0:
        return '0'
    else:
        # Convert to 0-5 scale with half-star precision
        flac_rating = plex_rating / 2.0
        return str(flac_rating)

def flac_to_plex_rating(flac_rating):
    """Convert FLAC rating to Plex rating (0-10) with validation"""
    try:
        rating_val = float(flac_rating)
        # Convert from 0-5 scale to 0-10 scale
        plex_rating = rating_val * 2.0
        # Ensure the result is within Plex's valid range (0-10)
        return min(10.0, max(0.0, plex_rating))
    except (ValueError, TypeError):
        # Handle non-numeric ratings
        return None

def get_rating(audiofile):
    try:
        popm = audiofile.tags.getall('POPM')
        for pop in popm:
            if pop.email == '':  # Check for a blank email
                return pop.rating
        return None
    except Exception as e:
        logger.error(f"Error getting rating: {str(e)}")
        return None

def set_rating(audiofile, rating):
    try:
        popm_frames = audiofile.tags.getall('POPM')
        
        # Check if a POPM frame with a blank email already exists
        pomp = None
        for frame in popm_frames:
            if frame.email == '':  # Check for a blank email
                pomp = frame
                break
        
        if pomp is None:
            # If no existing frame, create a new one with a blank email
            pomp = POPM(email='', rating=rating, count=0)
            audiofile.tags.add(pomp)
        else:
            # Update the existing frame
            pomp.rating = rating
        
        audiofile.save()
    except Exception as e:
        logger.error(f"Error setting rating: {str(e)}")

def process_mp3(track, host_path):
    global insync, justsynced, notag, error
    
    try:
        audiofile = MP3(host_path, ID3=ID3)
    except ID3NoHeaderError:
        logger.error(f"Error: No ID3 tag found for {track.title}")
        error += 1
        return
    except Exception as e:
        logger.error(f"Error loading MP3 file: {track.title} - {str(e)}")
        error += 1
        return

    current_rating = get_rating(audiofile)

    if isinstance(track.userRating, float):
        mp3_rating = plex_to_mp3_rating(track.userRating)
        stars = track.userRating / 2.0
        
        if current_rating == mp3_rating:
            insync += 1
            logger.debug(f'Synchronized: {track.title} (MP3) - {stars} stars')
        else:
            current_stars = mp3_to_plex_rating(current_rating) / 2.0 if current_rating is not None else "no rating"
            if not TEST_MODE:
                set_rating(audiofile, mp3_rating)
                
                # Verify the change
                audiofile = MP3(host_path, ID3=ID3)
                new_rating = get_rating(audiofile)
                
                if new_rating == mp3_rating:
                    justsynced += 1
                    logger.info(f'Updated MP3: {track.title} to {stars} stars')
                else:
                    error += 1
                    logger.error(f'Failed to update: {track.title}. Expected {stars} stars')
            else:
                justsynced += 1
                logger.info(f'Would update MP3: {track.title} to {stars} stars (currently {current_stars})')
    else:
        if current_rating is not None:
            plex_rating = mp3_to_plex_rating(current_rating)
            stars = plex_rating / 2.0
            # Validate rating is within Plex's acceptable range
            if 0 <= plex_rating <= 10:
                if not TEST_MODE:
                    track.rate(plex_rating)
                    logger.info(f'Updated Plex: {track.title} to {stars} stars')
                else:
                    logger.info(f'Would update Plex: {track.title} to {stars} stars (from MP3)')
                justsynced += 1
            else:
                logger.error(f'Invalid rating range for {track.title}: {stars} stars')
                error += 1
        else:
            notag += 1

def process_flac(track, host_path):
    global insync, justsynced, notag, error
    
    try:
        audiofile = FLAC(host_path)
    except Exception as e:
        logger.error(f"Error loading FLAC file: {track.title} - {str(e)}")
        error += 1
        return

    if isinstance(track.userRating, float):
        plex_rating_converted = plex_to_flac_rating(track.userRating)
        stars = track.userRating / 2.0
        
        current_rating = audiofile.get('RATING', [None])[0]
        
        # Compare as floats to handle decimal precision
        try:
            current_rating_float = float(current_rating) if current_rating else None
            plex_rating_float = float(plex_rating_converted)
            
            if current_rating_float == plex_rating_float:
                insync += 1
                logger.debug(f'Synchronized: {track.title} (FLAC) - {stars} stars')
            else:
                current_stars = current_rating_float if current_rating_float is not None else "no rating"
                if not TEST_MODE:
                    audiofile['RATING'] = [plex_rating_converted]
                    audiofile.save()
                    
                    # Verify the change
                    audiofile = FLAC(host_path)
                    new_rating = audiofile.get('RATING', [None])[0]
                    if new_rating == plex_rating_converted:
                        justsynced += 1
                        logger.info(f'Updated FLAC: {track.title} to {stars} stars')
                    else:
                        error += 1
                        logger.error(f'Failed to update FLAC: {track.title}. Expected {stars} stars')
                else:
                    justsynced += 1
                    logger.info(f'Would update FLAC: {track.title} to {stars} stars (currently {current_stars})')
        except (ValueError, TypeError):
            logger.error(f'Invalid rating format in FLAC file {track.title}: {current_rating}')
            error += 1
            
    else:
        current_rating = audiofile.get('RATING', [None])[0]
        if current_rating:
            # Add error handling for non-numeric ratings
            try:
                plex_rating = flac_to_plex_rating(current_rating)
                if plex_rating is not None:
                    stars = plex_rating / 2.0
                    # Validate rating is within Plex's acceptable range
                    if 0 <= plex_rating <= 10:
                        if not TEST_MODE:
                            track.rate(plex_rating)
                            logger.info(f'Updated Plex: {track.title} to {stars} stars')
                        else:
                            logger.info(f'Would update Plex: {track.title} to {stars} stars (from FLAC)')
                        justsynced += 1
                    else:
                        logger.error(f'Invalid rating range for {track.title}: {stars} stars')
                        error += 1
                else:
                    logger.error(f'Non-numeric rating found in {track.title}: {current_rating}')
                    error += 1
            except Exception as e:
                logger.error(f'Error processing rating for {track.title}: {str(e)}')
                error += 1
        else:
            logger.debug(f'No rating found: {track.title} (FLAC)')
            notag += 1

# Connect to Plex
plex = PlexServer(PLEX_URL, PLEX_TOKEN)

logger.info(f"Connected to Plex server: {plex.friendlyName}")
logger.info(f"Accessing library: {PLEX_MUSIC_LIBRARY_NAME}")

try:
    music_library = plex.library.section(PLEX_MUSIC_LIBRARY_NAME)
    logger.info(f"Found music library. Total albums: {len(music_library.albums())}")
except Exception as e:
    logger.error(f"Error accessing music library: {str(e)}")
    exit(1)

for album in music_library.albums():
    for track in album.tracks():
        host_path = translate_path(track.locations[0])
        
        if not os.path.exists(host_path):
            not_found += 1
            continue

        if host_path.lower().endswith('.mp3'):
            process_mp3(track, host_path)
        elif host_path.lower().endswith('.flac'):
            process_flac(track, host_path)
        else:
            error += 1

# Stats Output
logger.info("\nSummary:")
logger.info(f"{insync} files already in sync")
logger.info(f"{justsynced} newly synced files")
logger.info(f"{notag} files with no tags")
logger.info(f"{error} files had errors")
logger.info(f"{not_found} files not found (suppressed)")