# README

## Requirements

* Enable Cursor wake-up via CLI
    * If you are using Windows/MacOS Cursor:
        1. Open Cursor, press `Ctrl + Shift + P` (on Windows) or `Cmd + Shift + P` (on macOS).
        2. Type `Shell Command: Install 'cursor' command` and hit enter.
        3. Follow the prompts to complete the installation.
        
    * If you are using Linux Cursor:
        1. Add `alias cursor='<path-to-your-cursor-AppImage>'` to your `~/.bashrc` file.
        2. Run `source ~/.bashrc` to apply the changes.
    
    * If you are using Linux Cursor inside Docker container:
        1. Download Cursor app (AppImage) to host machine and extract to `squashfs-root`.
        2. Add the directory containing `squashfs-root` to `.config` as `CURSOR_APP_PATH`.
        3. Open your Cursor app and login to your account.
        4. Find your Cursor config dir and add it to `.config` as `CURSOR_CONFIG_PATH`.

    Now you can use the `cursor` command in your terminal to wake up Cursor.


* Disable Word Wrap
    1. Open `Preference > Settings` via `Ctrl + ,` or `Cmd + ,` (on macOS).
    2. Type `Editor: Word Warp` to fine the option.
    3. Set the option to `false`.
