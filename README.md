# Plex Rating Sync

Plex Rating Sync is a Python script that synchronizes ratings between Plex and your music files' tags. It supports bidirectional synchronization with configurable mastering, allowing you to choose whether Plex ratings or file tags are considered the source of truth.

## Disclaimer

This repository is a fork of [Mythic82/Plex-Rating-Sync](https://github.com/Mythic82/Plex-Rating-Sync). The core concept and initial implementation were created by [Mythic82](https://github.com/Mythic82). My contributions include performance optimizations, bidirectional sync capabilities, progress tracking, and various usability improvements. Credit for the original concept and base implementation belongs to the original author.

If you find this tool useful, please consider starring the original repository at [Mythic82/Plex-Rating-Sync](https://github.com/Mythic82/Plex-Rating-Sync).

## Enhancements in this Fork

- **Multithreaded Processing**: Significantly faster execution using concurrent processing
- **Bidirectional Sync**: Configure whether Plex or local files are the source of truth
- **Enhanced Path Handling**: Improved path translation between Plex and local file systems
- **Caching**: Reduced redundant operations with LRU caching
- **Detailed Progress Tracking**: Real-time updates with percentage completion and ETA
- **Improved Tag Compatibility**: Better support for various music players' rating tags (including MusicBee)
- **Comprehensive Error Handling**: More robust processing with better error reporting

## How It Works

1. **Connection**: The script connects to your Plex server using the provided URL and token.

2. **Library Scanning**: It scans through your entire music library in Plex.

3. **File Matching**: For each track, it matches the Plex entry with the corresponding file on your local system using file paths.

4. **Rating Comparison**: The script compares the Plex rating with the rating stored in the file's tag.

5. **Synchronization** (based on selected master source):
   - **When Plex is master**: Plex ratings update file tags; if a file has a rating but Plex doesn't, it will optionally backfill Plex
   - **When File is master**: File ratings update Plex; if a file has no rating but Plex does, the Plex rating is removed

6. **Verification**: After each update, it verifies that the change was applied successfully.

7. **Logging**: The script logs all actions and any errors encountered during the process.

## Requirements

- Python 3.6 or higher
- `plexapi` library
- `mutagen` library
- Access to your Plex server and the ability to read/write to your music files

## Suggested Usage

It's recommended to run this script periodically (e.g., weekly or monthly) to ensure your music file tags always reflect your Plex ratings. This practice is beneficial if you ever decide to use a different media player or music management software, as your ratings will be stored directly in the music files.

You could set up a cron job (on Linux/Mac) or a scheduled task (on Windows) to run the script automatically at your preferred interval.

## User-Settable Variables

At the beginning of the script, you'll find several variables you can adjust:

- `PLEX_URL`: The URL of your Plex server (e.g., 'http://192.168.1.100:32400')
- `PLEX_TOKEN`: Your Plex authentication token ([How to find](https://www.ryananddebi.com/2019/08/26/plex-how-to-create-smart-auto-updating-music-playlists/))
- `PLEX_MUSIC_LIBRARY_NAME`: The name of your music library in Plex
- `LOG_LEVEL`: The desired logging level (e.g., 'INFO', 'DEBUG', 'ERROR')
- `TEST_MODE`: Set to True to run the script without making any changes (dry run)
- `PROGRESS_UPDATE_FREQUENCY`: How often to display progress updates (# of tracks)
- `MAX_WORKERS`: Number of concurrent threads to use (adjust based on your system)
- `MASTER_SOURCE`: Set to 'PLEX' or 'FILE' to determine which ratings take precedence
- `PLEX_PATH_PREFIX`: The path prefix for your music files on the Plex server
- `HOST_PATH_PREFIX`: The corresponding path prefix on your local system

***Make sure to set these variables correctly before running the script.***

## Running the Script

1. Clone this repository or download the script.
2. Install the required libraries: `pip install plexapi mutagen`
3. Set the user variables at the top of the script.
4. Run the script: `python plex_rating_sync.py`

## Best Practices

- Always run in test mode first (`TEST_MODE = True`) and review the logs before making changes
- Start with a small library section for initial testing before running on your full collection
- Consider the appropriate `MASTER_SOURCE` setting for your workflow:
   - Use `PLEX` if you primarily rate music in Plex and want those ratings in your files
   - Use `FILE` if you use another music player (like MusicBee) and want Plex to reflect those ratings
- Adjust `MAX_WORKERS` based on your system capabilities (higher values for faster systems)
- Set up a periodic scheduled task to keep your ratings in sync

## Understanding the Output

The script provides detailed progress information during execution:

```
Progress: 5000/48317 tracks processed (10.3%) - ETA: 0h 52m 31s
Current stats: 213 in sync, 854 synced, 3812 no tags, 2 errors, 119 not found
```
- **In sync**: Tracks where ratings already match between Plex and file
- **Synced**: Tracks that would be/were updated to match the master source
- **No tags**: Tracks with no ratings in either Plex or file
- **Errors**: Issues encountered during processing
- **Not found**: Tracks in Plex that couldn't be matched to local files

