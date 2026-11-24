# Super Folder Lock for Omarchy

Lock folders behind a password from the Omarchy shell. They lock themselves again when you step
away, leave the workspace or lock the screen.

> Early version (0.1.0). Full documentation is on its way.

## Two lock types

| | Hide (default) | Encrypt |
|---|---|---|
| How | The folder is moved out of sight on the same disk | A [gocryptfs](https://nuetzlich.net/gocryptfs/) vault |
| Folders with files | Yes | Only new or empty folders |
| Copies your files | Never | No |
| Protects the data on another computer | **No** | Yes |
| Recovery key | No | Yes, shown once |

While locked, a folder can disappear from its place or stay there empty: double-clicking it in Files
(Nautilus) then asks for its password.

## Limits

- **Hide is not encryption.** Anyone with your user session and Linux knowledge, or with the disk on
  another computer, can reach the files.
- A file that was already open when the folder locked can still be read by the program that opened it.
- While open, an encrypted folder shows up as a volume in the Files sidebar.
- With Encrypt, losing both the password and the recovery key means losing the files. With Hide there
  is no password recovery in the window, but the files stay on the disk.
- Lock a folder on an external disk before unplugging it.

## Install

Needs Omarchy with its Quickshell-based shell and Python 3. Encrypt also needs `gocryptfs`
(`omarchy pkg add gocryptfs`).

```
omarchy plugin add https://github.com/LeninZapata/omarchy-super-folder-lock --enable
```

Omarchy puts the icon in the middle of the bar. To move it to the tray drawer:

```
omarchy bar move leninzapata.super-folder-lock --section tray
```

The interface follows the Omarchy language (English and Spanish).

## License

MIT
