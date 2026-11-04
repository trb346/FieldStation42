#!/bin/bash

SOURCE="/media/helium/media/FieldStation"
TARGET="$HOME/workspace/FieldStation42/catalog"

# 1. Mirror the nested folder structure and symlink all video files
find "$SOURCE" -mindepth 2 -type f \( -name "*.mp4" -o -name "*.webm" -o -name "*.mkv" -o -name "*.avi" \) | while read -r file; do
    # Extract path relative to SOURCE (e.g., Fox/King of the Hill/Season 1/ep1.mkv)
    rel_path="${file#$SOURCE/}"
    
    # Get the raw channel directory (e.g., Fox) and the path underneath it
    raw_channel="${rel_path%%/*}"
    inner_path="${rel_path#*/}"
    
    # Lowercase channel name for FieldStation42 (e.g., fox)
    channel="${raw_channel,,}"
    
    # Categorize based on special folders or default to "shows"
    case "$inner_path" in
        *[C|c]ommercial*) category="commercial" ;;
        *[B|b]ump*)       category="bump" ;;
        *)                category="shows" ;;
    esac

    # Preserve full subfolder structure under the category
    target_dir="$TARGET/$channel/$category/$(dirname "$inner_path")"
    target_file="$target_dir/$(basename "$file")"
    
    # Safely build directory structure and create/update symlink
    mkdir -p "$target_dir"
    ln -s -f "$file" "$target_file"
done

# 2. Clean up broken/dead symlinks if source files are moved or deleted
find "$TARGET" -type l ! -exec test -e {} \; -delete