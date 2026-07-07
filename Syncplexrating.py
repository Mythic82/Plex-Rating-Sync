"""
Sync track ratings between Plex and local MP3/FLAC files.

Direction of sync per track:
  - Plex has a rating         -> written to the file (unless CONFLICT_WINNER='file')
  - Only the file has a rating -> written to Plex
  - Neither has a rating       -> counted as 'no tag'

Run with TEST_MODE = True first to see what would change.
"""

import logging
import os
import sys
from collections import Counter
from datetime import datetime

from mutagen.flac import FLAC
from mutagen.id3 import ID3, ID3NoHeaderError, POPM
from mutagen.mp3 import MP3
from plexapi.server import PlexServer

# ============================================================
# User Settable Variables
# ============================================================

# URL of the Plex server. Replace with your actual Plex server URL.
PLEX_URL = 'http://your-plex-server:32400'

# Plex token for authentication. Replace with your actual Plex token.
PLEX_TOKEN = 'your-plex-token'

# Name of the music library in Plex. Ensure this matches the name of your library in Plex.
PLEX_MUSIC_LIBRARY_NAME = 'YourMusicLibraryName'

# Logging level for the script: DEBUG, INFO, WARNING, ERROR.
LOG_LEVEL = 'INFO'

# Optional log file. Everything printed to the console is also written here.
# Set to None to disable file logging.
LOG_FILE = 'sync_ratings.log'

# Test mode flag. Set to True to run in test mode without making changes,
# or False to apply changes.
TEST_MODE = True

# Conflict resolution: what to do when Plex AND the file both have a rating
# but they differ.
#   'plex'   -> the Plex rating wins and is written to the file (default)
#   'file'   -> the file rating wins and is written to Plex
#   'newest' -> whichever side changed most recently wins. Compares Plex's
#               lastRatedAt timestamp against the file's modification time.
#               Note: the file mtime updates when ANY tag is edited, not just
#               the rating, so a recently retagged file can win a conflict
#               even if its rating is old. If Plex has no lastRatedAt
#               timestamp, falls back to 'plex' (and logs the fallback).
# Every conflict (both ratings, timestamps if used, and which side won) is
# logged so nothing is overwritten silently.
CONFLICT_WINNER = 'plex'

# ============================================================
# Path Translation
# ============================================================

# Prefix for the music path as seen by Plex. Adjust to match your Plex server's configuration.
PLEX_PATH_PREFIX = '/Music/'

# Prefix for the music path on the local host. Adjust to match your local file system.
HOST_PATH_PREFIX = '/mnt/Music/'

# ============================================================
# Logging setup
# ============================================================

logger = logging.getLogger('syncplexrating')
logger.setLevel(LOG_LEVEL)

_console = logging.StreamHandler()
_console.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(_console)

if LOG_FILE:
    # A relative LOG_FILE is placed next to this script, regardless of the
    # directory the script is launched from (important for cron jobs).
    if not os.path.isabs(LOG_FILE):
        LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), LOG_FILE)
    _filehandler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    _filehandler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(_filehandler)

# Suppress plexapi debug output
logging.getLogger('plexapi').setLevel(logging.WARNING)

# ============================================================
# Rating conversion
# ============================================================

# One table drives both directions of the MP3 conversion so the two
# mappings can never drift out of sync. Values follow the common
# Windows / MediaMonkey POPM convention.
#
#   (plex rating 0-10, POPM byte 0-255)
RATING_MAP = [
    (0, 0),      # unrated
    (2, 1),      # 1 star
    (3, 32),     # 1.5 stars
    (4, 64),     # 2 stars
    (5, 96),     # 2.5 stars
    (6, 128),    # 3 stars
    (7, 162),    # 3.5 stars
    (8, 196),    # 4 stars
    (9, 225),    # 4.5 stars
    (10, 255),   # 5 stars
]


def plex_to_mp3_rating(plex_rating):
    """Convert a Plex rating (0-10 float) to the nearest POPM byte value.

    Nearest-match lookup means unexpected values (e.g. 7.3 set via the API)
    are rounded to the closest defined step instead of silently becoming
    5 stars.
    """
    # Ties round UP (e.g. Plex 1 / 0.5 stars sits exactly between the
    # 'unrated' and '1 star' steps) so a real rating is never erased.
    nearest = min(RATING_MAP, key=lambda pair: (abs(pair[0] - plex_rating), -pair[0]))
    if nearest[0] != plex_rating:
        if plex_rating == 1:
            # 0.5 stars has no POPM step of its own; stored as 1 star.
            logger.debug('Plex rating 0.5 stars stored as 1 star (POPM limit)')
        else:
            logger.warning(
                f'Unexpected Plex rating {plex_rating}, rounded to nearest '
                f'half-star ({nearest[0] / 2.0} stars)'
            )
    return nearest[1]


def mp3_to_plex_rating(mp3_rating):
    """Convert a POPM byte value (0-255) to the nearest Plex rating (0-10).

    Ties round up, matching the previous threshold-based behavior.
    """
    return min(RATING_MAP, key=lambda pair: (abs(pair[1] - mp3_rating), -pair[1]))[0]


def plex_to_flac_rating(plex_rating):
    """Convert Plex rating (0-10) to FLAC RATING tag (0-5 scale, half stars)."""
    if plex_rating == 0:
        return '0'
    return str(plex_rating / 2.0)


def flac_to_plex_rating(flac_rating):
    """Convert a FLAC RATING tag value to a Plex rating (0-10).

    Handles both common conventions:
      - 0-5 scale (what this script writes)
      - 0-100 scale (Winamp / foobar2000 style); detected when the value
        exceeds 10 and converted by dividing by 20.
    Returns None for non-numeric values.
    """
    try:
        rating_val = float(flac_rating)
    except (ValueError, TypeError):
        return None

    if rating_val < 0:
        return None

    if rating_val > 10:
        # Almost certainly a 0-100 scale tag written by another program.
        logger.warning(
            f'FLAC RATING value {rating_val} looks like a 0-100 scale tag; '
            f'converting as {rating_val}/100'
        )
        rating_val = rating_val / 20.0  # 0-100 -> 0-5
    elif rating_val > 5:
        # Between 5 and 10: ambiguous, but treat as already 0-10.
        return min(10.0, rating_val)

    return min(10.0, max(0.0, rating_val * 2.0))


# ============================================================
# MP3 tag helpers
# ============================================================

def get_mp3_rating(audiofile):
    """Return the POPM rating with a blank email, or None if absent."""
    try:
        for frame in audiofile.tags.getall('POPM'):
            if frame.email == '':
                return frame.rating
        return None
    except Exception as e:
        logger.error(f'Error getting rating: {e}')
        return None


def set_mp3_rating(audiofile, rating):
    """Write the POPM rating (blank email), creating the frame if needed."""
    try:
        popm = None
        for frame in audiofile.tags.getall('POPM'):
            if frame.email == '':
                popm = frame
                break

        if popm is None:
            audiofile.tags.add(POPM(email='', rating=rating, count=0))
        else:
            popm.rating = rating

        audiofile.save()
    except Exception as e:
        logger.error(f'Error setting rating: {e}')


# ============================================================
# Per-track processing
# ============================================================

def resolve_conflict(track, host_path):
    """Decide which side wins a rating conflict.

    Returns a tuple of (winner, detail) where winner is 'plex' or 'file'
    and detail is a short string for the conflict log line explaining
    how the decision was made.
    """
    if CONFLICT_WINNER in ('plex', 'file'):
        return CONFLICT_WINNER, f'configured winner: {CONFLICT_WINNER}'

    # CONFLICT_WINNER == 'newest'
    plex_rated_at = getattr(track, 'lastRatedAt', None)
    if plex_rated_at is None:
        return 'plex', "newest: no lastRatedAt from Plex, falling back to 'plex'"

    try:
        plex_ts = plex_rated_at.timestamp()
        file_ts = os.path.getmtime(host_path)
    except (OSError, OverflowError, ValueError) as e:
        return 'plex', f"newest: timestamp comparison failed ({e}), falling back to 'plex'"

    detail = (
        f'newest: Plex rated {plex_rated_at:%Y-%m-%d %H:%M:%S} vs '
        f'file modified {_fmt_ts(file_ts)}'
    )
    return ('file', detail) if file_ts > plex_ts else ('plex', detail)


def _fmt_ts(epoch_seconds):
    return datetime.fromtimestamp(epoch_seconds).strftime('%Y-%m-%d %H:%M:%S')


def update_plex_rating(track, plex_rating, stats, source_label):
    """Push a rating from a file up to Plex (with validation)."""
    stars = plex_rating / 2.0
    if not 0 <= plex_rating <= 10:
        logger.error(f'Invalid rating range for {track.title}: {stars} stars')
        stats['error'] += 1
        return

    if TEST_MODE:
        logger.info(f'Would update Plex: {track.title} to {stars} stars (from {source_label})')
    else:
        track.rate(plex_rating)
        logger.info(f'Updated Plex: {track.title} to {stars} stars (from {source_label})')
    stats['justsynced'] += 1


def process_mp3(track, host_path, stats):
    try:
        audiofile = MP3(host_path, ID3=ID3)
    except ID3NoHeaderError:
        logger.error(f'Error: No ID3 tag found for {track.title}')
        stats['error'] += 1
        return
    except Exception as e:
        logger.error(f'Error loading MP3 file: {track.title} - {e}')
        stats['error'] += 1
        return

    file_rating = get_mp3_rating(audiofile)
    plex_has_rating = isinstance(track.userRating, float)

    if plex_has_rating:
        target_rating = plex_to_mp3_rating(track.userRating)
        stars = track.userRating / 2.0

        if file_rating == target_rating:
            stats['insync'] += 1
            logger.debug(f'Synchronized: {track.title} (MP3) - {stars} stars')
            return

        # Both sides rated but they differ -> conflict.
        if file_rating is not None:
            winner, detail = resolve_conflict(track, host_path)
            file_stars = mp3_to_plex_rating(file_rating) / 2.0
            logger.info(
                f'Conflict: {track.title} - Plex {stars} stars vs file '
                f'{file_stars} stars (winner: {winner}; {detail})'
            )
            if winner == 'file':
                update_plex_rating(track, mp3_to_plex_rating(file_rating), stats, 'MP3')
                return

        # Plex wins (or file had no rating): write to the file.
        current_stars = (
            mp3_to_plex_rating(file_rating) / 2.0 if file_rating is not None else 'no rating'
        )
        if TEST_MODE:
            stats['justsynced'] += 1
            logger.info(f'Would update MP3: {track.title} to {stars} stars (currently {current_stars})')
            return

        set_mp3_rating(audiofile, target_rating)

        # Verify the change actually landed on disk.
        audiofile = MP3(host_path, ID3=ID3)
        if get_mp3_rating(audiofile) == target_rating:
            stats['justsynced'] += 1
            logger.info(f'Updated MP3: {track.title} to {stars} stars (was {current_stars})')
        else:
            stats['error'] += 1
            logger.error(f'Failed to update: {track.title}. Expected {stars} stars')

    elif file_rating is not None:
        # Only the file has a rating -> push it to Plex.
        update_plex_rating(track, mp3_to_plex_rating(file_rating), stats, 'MP3')

    else:
        stats['notag'] += 1


def process_flac(track, host_path, stats):
    try:
        audiofile = FLAC(host_path)
    except Exception as e:
        logger.error(f'Error loading FLAC file: {track.title} - {e}')
        stats['error'] += 1
        return

    raw_file_rating = audiofile.get('RATING', [None])[0]
    plex_has_rating = isinstance(track.userRating, float)

    if plex_has_rating:
        target_rating = plex_to_flac_rating(track.userRating)
        stars = track.userRating / 2.0

        file_rating_plex = flac_to_plex_rating(raw_file_rating) if raw_file_rating else None
        if raw_file_rating and file_rating_plex is None:
            logger.error(f'Invalid rating format in FLAC file {track.title}: {raw_file_rating}')
            stats['error'] += 1
            return

        if file_rating_plex is not None and file_rating_plex == track.userRating:
            stats['insync'] += 1
            logger.debug(f'Synchronized: {track.title} (FLAC) - {stars} stars')
            return

        # Both sides rated but they differ -> conflict.
        if file_rating_plex is not None:
            winner, detail = resolve_conflict(track, host_path)
            logger.info(
                f'Conflict: {track.title} - Plex {stars} stars vs file '
                f'{file_rating_plex / 2.0} stars (winner: {winner}; {detail})'
            )
            if winner == 'file':
                update_plex_rating(track, file_rating_plex, stats, 'FLAC')
                return

        # Plex wins (or file had no rating): write to the file.
        current_stars = file_rating_plex / 2.0 if file_rating_plex is not None else 'no rating'
        if TEST_MODE:
            stats['justsynced'] += 1
            logger.info(f'Would update FLAC: {track.title} to {stars} stars (currently {current_stars})')
            return

        audiofile['RATING'] = [target_rating]
        audiofile.save()

        # Verify the change actually landed on disk.
        audiofile = FLAC(host_path)
        if audiofile.get('RATING', [None])[0] == target_rating:
            stats['justsynced'] += 1
            logger.info(f'Updated FLAC: {track.title} to {stars} stars (was {current_stars})')
        else:
            stats['error'] += 1
            logger.error(f'Failed to update FLAC: {track.title}. Expected {stars} stars')

    elif raw_file_rating:
        # Only the file has a rating -> push it to Plex.
        plex_rating = flac_to_plex_rating(raw_file_rating)
        if plex_rating is None:
            logger.error(f'Non-numeric rating found in {track.title}: {raw_file_rating}')
            stats['error'] += 1
        else:
            update_plex_rating(track, plex_rating, stats, 'FLAC')

    else:
        logger.debug(f'No rating found: {track.title} (FLAC)')
        stats['notag'] += 1


# ============================================================
# Main
# ============================================================

def translate_path(plex_path):
    return plex_path.replace(PLEX_PATH_PREFIX, HOST_PATH_PREFIX)


def main():
    if CONFLICT_WINNER not in ('plex', 'file', 'newest'):
        logger.error(f"CONFLICT_WINNER must be 'plex', 'file' or 'newest', got '{CONFLICT_WINNER}'")
        sys.exit(1)

    try:
        plex = PlexServer(PLEX_URL, PLEX_TOKEN)
    except Exception as e:
        logger.error(f'Could not connect to Plex server at {PLEX_URL}: {e}')
        sys.exit(1)

    logger.info(f'Connected to Plex server: {plex.friendlyName}')
    logger.info(f'Accessing library: {PLEX_MUSIC_LIBRARY_NAME}')
    if TEST_MODE:
        logger.info('TEST MODE is ON - no changes will be made')

    try:
        music_library = plex.library.section(PLEX_MUSIC_LIBRARY_NAME)
        # One paginated fetch of all tracks instead of one request per album.
        tracks = music_library.searchTracks()
        logger.info(f'Found music library. Total tracks: {len(tracks)}')
    except Exception as e:
        logger.error(f'Error accessing music library: {e}')
        sys.exit(1)

    stats = Counter()
    skipped_extensions = Counter()

    for track in tracks:
        if not track.locations:
            logger.warning(f'No file location in Plex for: {track.title} - skipping')
            stats['not_found'] += 1
            continue

        host_path = translate_path(track.locations[0])

        if not os.path.exists(host_path):
            logger.debug(f'File not found on disk: {host_path}')
            stats['not_found'] += 1
            continue

        ext = os.path.splitext(host_path)[1].lower()
        if ext == '.mp3':
            process_mp3(track, host_path, stats)
        elif ext == '.flac':
            process_flac(track, host_path, stats)
        else:
            skipped_extensions[ext or '(no extension)'] += 1
            stats['skipped'] += 1
            logger.debug(f'Skipped unsupported file type {ext}: {track.title}')

    # Stats output
    logger.info('\nSummary:')
    logger.info(f"{stats['insync']} files already in sync")
    logger.info(f"{stats['justsynced']} newly synced files")
    logger.info(f"{stats['notag']} files with no tags")
    logger.info(f"{stats['error']} files had errors")
    logger.info(f"{stats['not_found']} files not found")
    logger.info(f"{stats['skipped']} files skipped (unsupported format)")
    for ext, count in skipped_extensions.most_common():
        logger.info(f'  {count} x {ext} - not touched, only MP3 and FLAC are supported')


if __name__ == '__main__':
    main()
