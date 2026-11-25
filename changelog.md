# Changelog — Super Folder Lock

> What changed, by version (newest first; the last 10 are kept).

## 0.2.1 - 2026-11-25 01:19
---
- [fix] A visible locked folder no longer asks for its password on its own: when it locked while Files was showing it (for example on leaving its workspace), Files reading it again counted as a double-click

## 0.2.0 - 2026-11-24 11:20
---
- [update] Remove protection is now the only way to take a folder off the list: it becomes a normal folder again, in its place
- [delete] "Remove from the list", which left a folder locked without showing it anywhere. An entry can only be removed alone when its files no longer exist
- [update] Add back finds the folder by its password, so with several folders outside the list any of them can be added back (before, only the first one)
- [update] Clearer rule names: "No keyboard or mouse for" (was "Computer idle") and "Show the folder after unlocking it" (was "Open in file manager"), which now has its own "When opening" group
- [update] New marketplace preview: a folder with its photos and the same folder locked
- [update] The new folder form explains what each lock type is for, and why Encrypt needs a new or empty folder
- [fix] The window opens small at the password prompt and grows to the list once it is passed
- [fix] The hint text of the password fields is readable in every theme: it takes the theme's muted color or a softened text color, whichever reads better
- [fix] The window opens again after closing it with Esc
- [fix] The shortcut never takes over or releases a key that something else uses in any Hyprland submap; if Hyprland's bind list can't be read, nothing is touched

## 0.1.0 - 2026-11-24 00:21
---
- [feature] Hide: protect a folder with a password without copying, changing or deleting anything in it
- [feature] Encrypt: new or empty folders encrypted with gocryptfs, with a recovery key
- [feature] Folders lock themselves: idle, leaving the workspace, screen lock or a maximum time open; default rules and rules per folder
- [feature] Nothing is listed until the system password is entered (PAM); it is asked again after a while without use
- [feature] Double-click to open for folders that stay visible while locked, in Files (Nautilus)
- [feature] Folders on external disks stay on their disk
- [new] Remove protection and Add back; neither deletes files
- [new] Optional bar icon, launcher entry, shortcut and notifications; English and Spanish
