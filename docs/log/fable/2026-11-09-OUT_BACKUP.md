# Backing up out/ (proposal)

Status: a proposal. Nothing is set up yet, and the owner picks an option. Written 2026-11-09.

## Why

`out/` holds every result, painted clip and closed-loop transcript. It's ignored by git and exists only on this Mac's internal disk, so a dead disk or a bad `rm` loses all of it. On 2026-11-09 it held **45.0 G in 39,492 files**, and the disk was 82% full (734 of 926 GiB). `bodies/` is 31.7 G of that (see `docs/OUT_LAYOUT.md`). `models/` (weights) can be downloaded again and isn't covered here.

## What to exclude

Live state that's always mid-write and means nothing once restored:

    ops/gpu.lock
    ram/
    *.db-shm
    *.db-wal
    .DS_Store
    panel.log
    ops/panel_8765.log
    overnight/latest    (a symlink; rsync -a copies it as a link, which is fine, but don't follow it)

Optional, to save about 7 G: smoke and intermediate runs past their retention limit (`kokopelli/ops/out_report.py` lists them). I'd back these up anyway. They're cheap at this size, and backing up before any deletion is the point.

`life.db` and `demo.db` are SQLite. Copy them while the panel is stopped, or copy them with `sqlite3 out/life.db ".backup '/Volumes/X/life.db'"`. A plain file copy while the panel writes can give a torn database.

## Option A: external SSD with rsync snapshots (recommended)

Each night `rsync --link-dest` makes a dated folder that looks like a full copy. Unchanged files are hard links to the previous night's copy, so each snapshot only costs the files that changed.

    DEST=/Volumes/KokoBackup/out
    TODAY=$(date +%Y-%m-%d)
    rsync -a --delete --exclude-from=kokopelli/ops/out_backup_exclude.txt \
          --link-dest="$DEST/latest" out/ "$DEST/$TODAY/"
    ln -sfn "$TODAY" "$DEST/latest"

- macOS ships `openrsync`, which supports `--link-dest`, `--delete` and `--exclude-from` (checked with `rsync --help` on this Mac). Homebrew `rsync` 3.x adds `--info=progress2` if wanted.
- The trailing `/` on `out/` matters: it copies the contents, not a nested `out/out`.
- **Cost:** a 1 TB USB-C SSD, roughly $60-100 (my estimate, not checked against current prices). 1 TB holds today's 45 G about 20 times over, which leaves room for months of nightly snapshots.
- **Time (estimates, not measured):** the first copy is 45 G at 300-800 MB/s real-world over USB-C, so about 1-3 minutes of transfer plus per-file overhead for 39k files. Expect under 10 minutes. Nightly runs compare file sizes and times, then copy only what changed. Expect under a minute when little changed.
- **Restore:** copy the files back from a dated folder with Finder or `rsync -a`. No special software.
- **Weakness:** the SSD sits next to the Mac, so fire, theft or one spill takes out both. That's fine for "I deleted the wrong folder", not for "the house burned down".
- Could be a nightly `launchd` job or a line in the overnight routine. Run it after the queue goes idle, so it doesn't copy half-written clips.

## Option B: cloud with rclone (Backblaze B2 or similar)

    rclone sync out/ b2:kokopelli-out --exclude-from kokopelli/ops/out_backup_exclude.txt --fast-list --transfers 8
    # with versioning turned on in the bucket, deleted or overwritten files stay recoverable for N days

- Needs `rclone` (not installed; `brew install rclone`), a B2 account and a key. That's an outside service, so it's the owner's decision.
- **Cost (list prices as I know them, check before deciding):** B2 storage is about $6 per TB per month, so 45 G is about $0.30 a month. Restores beyond the free monthly egress allowance cost extra.
- **Time (estimates):** the first upload is 45 G, about 5 hours at 20 Mbit/s up or about 1 hour at 100 Mbit/s. Later syncs only send what changed.
- **Weakness:** restoring 45 G takes hours, and the first upload competes with GPU-queue jobs that pull weights. Schedule it at night with `--bwlimit`.
- Also protects against fire and theft.

## Option C: both (3-2-1)

Use A every night and B weekly. That gives three copies, on two kinds of media, with one off-site. It adds about $0.30 a month to option A's one-time cost. This is the standard advice, and it's my recommendation once `out/` holds results the project claims in reports.

## Not recommended

- **Time Machine for `out/`.** It works, but it backs up the whole disk on its own schedule. On a disk at 82% it also keeps local snapshots, which would take more of the space we're short of.
- **Git LFS or committing results.** 45 G of mostly binary frames is the wrong shape for git.
- **Deleting before backing up.** Any deletion from the retention candidate list should come after a backup exists.

## What the owner needs to decide

1. A, B or C (I'd pick A now and add B later).
2. Buy an SSD (A), or create a B2 account and key (B).
3. When it runs: nightly after the queue is idle, or by hand.
4. Then a small follow-up package adds `kokopelli/ops/out_backup_exclude.txt` (the list above) and a script. Neither exists yet, because this package only writes documents and the read-only report.
