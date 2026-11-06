#!/bin/bash

SOURCE="/media/helium/media/FieldStation"
TARGET="$HOME/workspace/FieldStation42/catalog"

# 1. Pre-create root channel directories along with "commercials" and "bump" subdirectories
find "$SOURCE" -mindepth 1 -maxdepth 1 -type d | while read -r chan_dir; do
    raw_channel="$(basename "$chan_dir")"
    channel="${raw_channel,,}"
    
    # Ensure root channel folder exists in the target catalog
    mkdir -p "$TARGET/$channel"
    
    # Pre-create "commercials" and "bump" subdirectories at root for all channels
    mkdir -p "$TARGET/$channel/commercials"
    mkdir -p "$TARGET/$channel/bumps"
done

# 2. Mirror nested folder structure under "shows" and symlink ALL files
find "$SOURCE" -mindepth 2 -type f | while read -r file; do
    # Extract path relative to SOURCE (e.g., Fox/King of the Hill/Season 1/ep1.mkv)
    rel_path="${file#$SOURCE/}"
     
    # Get the raw channel directory (e.g., Fox or commercials) and path underneath
    raw_channel="${rel_path%%/*}"
    inner_path="${rel_path#*/}"
     
    # Lowercase channel name for FieldStation42 (e.g., fox, commercials)
    channel="${raw_channel,,}"
     
    # Everything in a channel folder goes directly under "shows"
    target_dir="$TARGET/$channel/shows/$(dirname "$inner_path")"
    target_file="$target_dir/$(basename "$file")"
     
    # Safely build target directory structure and create/update symlink
    mkdir -p "$target_dir"
    ln -s -f "$file" "$target_file"
done

# 3. Clean up broken/dead symlinks if source files were removed or renamed
find -L "$TARGET" -type l -delete
