# Plex Rating Sync

Plex-Rating-Sync is a Python script that synchronizes ratings between Plex and your music files' tags. It supports two-way synchronization with a preference for Plex ratings, ensuring your music library stays consistently rated across different platforms.

If you found this script useful, you can [![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-☕-yellow.svg)](https://www.buymeacoffee.com/Mythic82)

## How It Works

1. **Connection**: The script connects to your Plex server using the provided URL and token.

2. **Library Scanning**: It scans through your entire music library in Plex.

3. **File Matching**: For each track, it matches the Plex entry with the corresponding file on your local system using file paths.

4. **Rating Comparison**: The script compares the Plex rating with the rating stored in the file's tag.

5. **Synchronization**:
   - If Plex has a rating and the file doesn't, it updates the file tag.
   - If the file has a rating and Plex doesn't, it updates Plex.
   - If both have ratings but they differ, it prefers the Plex rating and updates the file tag.

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
- `PLEX_TOKEN`: Your Plex authentication token
- `PLEX_MUSIC_LIBRARY_NAME`: The name of your music library in Plex
- `LOG_LEVEL`: The desired logging level (e.g., 'INFO', 'DEBUG', 'ERROR')
- `TEST_MODE`: Set to True to run the script without making any changes (dry run)
- `PLEX_PATH_PREFIX`: The path prefix for your music files on the Plex server
- `HOST_PATH_PREFIX`: The corresponding path prefix on your local system

Make sure to set these variables correctly before running the script.

## Running the Script

1. Clone this repository or download the script.
2. Install the required libraries: `pip install plexapi mutagen`
3. Set the user variables at the top of the script.
4. Run the script: `python plex_rating_sync.py`

Remember to run in test mode first and review the logs before making any changes to your library!
