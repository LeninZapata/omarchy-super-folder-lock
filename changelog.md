# Changelog — Super Folder Lock

> What changed, by version (newest first; the last 10 are kept).

## 0.1.0 - 2026-11-24 10:40
---
- [feature] Hide: protect a folder with a password without copying, changing or deleting anything in it
- [feature] Encrypt: new or empty folders encrypted with gocryptfs, with a recovery key
- [feature] Folders lock themselves: idle, leaving the workspace, screen lock or a maximum time open; default rules and rules per folder
- [feature] Nothing is listed until the system password is entered (PAM); it is asked again after a while without use
- [feature] Double-click to open for folders that stay visible while locked, in Files (Nautilus)
- [feature] Folders on external disks stay on their disk
- [new] Remove protection, Remove from the list and Add back; none of them deletes files
- [new] Optional bar icon, launcher entry, shortcut and notifications; English and Spanish
- [fix] The window opens again after closing it with Esc
- [fix] The shortcut never takes over or releases a key that something else uses in any Hyprland submap; if Hyprland's bind list can't be read, nothing is touched
