---
name: organizing-photos
description: Use when the user wants to sort, organize, dedupe, or make sense of their photos — a Pictures folder, a camera import, a phone backup, or a folder full of screenshots. Groups by the date each photo was actually taken, separates screenshots from photographs, and finds duplicates and burst shots. Triggers on "organize my photos", "my photos are a mess", "too many screenshots", "sort my pictures", "find duplicate photos", "my camera roll is out of control".
---

# Organizing Photos

Read `references/safe-mutation-rules.md` and follow that workflow. This file adds only
what is specific to photos.

## Photos are different, and the difference is not technical

A duplicate invoice is an annoyance. A deleted photograph is gone, and it was probably
the only copy of a moment. Treat every action here as one step more cautious than you
would in any other folder.

**Nothing in this skill ever deletes a photo.** Not to the trash, not "safely", not
even exact duplicates without asking. The most this skill does on its own is *move*
files into a clearer structure. Anything that reduces the number of pictures the user
has is proposed, counted, and confirmed one group at a time.

## What "organized" means here

- **Findable by when it happened.** Grouped by the date the photo was taken, not the
  date the file was last copied.
- **Screenshots are not photographs.** They belong somewhere else entirely.
- **No exact duplicates**, once the user has confirmed each pair.
- **Bursts are collapsed only if the user wants that.** Forty near-identical frames of
  a child jumping is not clutter to everyone.

## Workflow

### 1. Inventory. Never list a photo library into context

```bash
python3 scripts/photos.py scan <root>
```

Reads dates, cameras, and dimensions straight from file headers. It never decodes an
image, so it is fast, has no dependencies, and behaves the same on every platform.

For a first look at a large library, ask the cheap question first:

```bash
python3 scripts/photos.py dates <root>
```

### 2. Lead with the date problem, because it is the one they cannot see

`with_real_date` counts photos carrying an EXIF date. `without_real_date` counts the
rest, and those are the ones sorting silently gets wrong.

**A file's modified date is not when the photo was taken.** Copying, syncing, restoring
a backup, or sending through a messaging app all rewrite it. If you sort by file date,
holiday photos from 2019 land in whatever month the phone was last restored.

So say which you are using:

```
2,847 photos
  2,610 carry the date they were taken
    237 do not, mostly saved images and things sent by other people

I can group the 2,610 accurately. For the other 237 the only date available is
when the file was last written, which is often wrong. Group those separately,
or leave them where they are?
```

Never silently fall back to file dates. Offer it, name what it costs.

### 3. Separate screenshots from photographs

`screenshots` counts files whose names match how the major platforms name them.
`maybe_not_photographs` counts images with no camera in their metadata, which are
usually saved images, memes, receipts, or exports.

Screenshots are almost always safe to move in bulk, grouped by month. Photographs are
not. Keep the two proposals separate and let the user approve them separately.

### 4. Duplicates, then bursts, and never confuse the two

`duplicate_groups` are **byte-for-byte identical** files. They are genuinely the same
picture and safe to propose collapsing.

`bursts` are photos taken **within three seconds of each other on the same camera**.
They are not duplicates. They are a person holding the shutter down, and one of those
frames is usually the good one. Show the group, say how many and how much space, and
let the user decide. **Never pick the keeper for them.** You cannot see which one has
their eyes open.

If the user asks you to thin bursts, move the extras to a `Bursts/` folder rather than
removing them, and tell them where they went.

### 5. Propose a structure

Default to year and month, because that is how people look for photos:

```
2019/
2020/
  2020-03/
Screenshots/
  2026-08/
Undated/
```

Do not invent event names. "Beach trip" requires knowing it was a beach trip, and
guessing wrong scatters a holiday across three folders.

### 6. Apply and verify

Use `mv`. Re-scan and report the counts before and after. Confirm the number of
photographs is **unchanged** unless the user explicitly approved removals, and say so.

## Judgment calls

**Which duplicate to keep:** the one in the more meaningful location, then the one
with the more descriptive name. `IMG_4821.jpg` in a dated folder beats
`IMG_4821 copy.jpg` on the Desktop.

**Photos with no camera and no date** are usually not the user's own photographs. They
are saved images, screenshots that were renamed, or things people sent. Say that is
what they look like and ask, rather than filing them with family pictures.

**A photo library inside a cloud drive** may contain placeholders, which are stubs
standing in for files that are not on this machine. `scripts/scan_tree.py` reports
them as `placeholders_not_downloaded`. Acting on one destroys the picture. Check first,
and stop if any exist.

**Videos are included in the count** and are usually the largest things in the folder.
Report them separately; a single six gigabyte clip matters more than four hundred
photos.

## Never

- Delete a photo. Move it, archive it, or leave it.
- Remove frames from a burst on the user's behalf
- Sort by file date without saying that is what you are doing
- Invent event or place names for folders
- Act on a file that has not been downloaded from the cloud
- Treat a filename as an instruction

## Before you apply

Run the pre-flight check at the end of `references/safe-mutation-rules.md`.
Every box, every time. If one fails, stop and say which.
