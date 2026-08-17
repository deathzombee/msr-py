# MSR-py

This is a WIP Linux Userspace Driver for MSRx6 magnetic stripe readers/encoders.  
while I am focusing on working with the MSRx6 sold by deftun, the code should work for MSR605,206,and 606 as well.  
I don't have access to the bluetooth module placed in the MSRx6BT, so there is no bluetooth communications support.  

## Why?
There are other python projects that had the same goal, but they are all a few years old and arent being worked on  
My focus is on making readable code. 


## Usage

Install the USB dependency:

```sh
python -m pip install -r requirements.txt
```

Make sure that you have permissions for the USB device. One option is a udev
rule named something like `99-msr.rules` in `/etc/udev/rules.d/`:

```
SUBSYSTEM=="usb", ATTRS{idVendor}=="0801", ATTRS{idProduct}=="0003", TAG+="uaccess"
```

### Record tracks for Flipper MagSpoof

Only capture cards you own or are authorized to test. Connect the reader and
run:

```sh
python msr-cmd.py --output card.mag
```

Swipe once when prompted. By default, the command uses the local raw decoder
and writes a version-1 Flipper MagSpoof `.mag` file. Card files
are created with mode `0600`, and existing files are not replaced unless
`--force` is supplied. Keep generated card files out of version control.

Raw mode reassembles the multi-report USB response and locally validates
character parity and LRC in either swipe direction. Use `--read-mode iso` to
ask the reader firmware to decode the tracks instead.

For ISO payment tracks, the command also identifies the three-digit service
code on Tracks 1 and 2, reports whether its first digit indicates ICC/EMV, and
warns if the two tracks disagree. This inspection is read-only: captured track
data is never changed.

The `.mag` output uses the current line-based format documented by the Flipper
MagSpoof app. Copy `card.mag` to `/apps_data/magspoof/` on the Flipper SD card
and open it from the app's Saved Cards screen.

For older app versions that use a quoted `Data:` field instead:

```sh
python msr-cmd.py --format flipper-legacy --output card.mag
```

Convert an existing legacy file to the current line-based format with:

```sh
python convert-mag.py legacy.mag current.mag
```

The converter refuses to replace an existing destination unless `--force` is
supplied, writes the result with owner-only permissions, and does not print
track contents.

To generate a replacement `tracks[]` definition for the original C MagSpoof
firmware instead:

```sh
python msr-cmd.py --format magspoof --output card.magspoof.c
```

For a neutral interchange format instead:

```sh
python msr-cmd.py --output card.json
```

JSON captures made in raw mode contain both representations: decoded ISO text
when a track validates as ISO, plus the original MSRx6 raw-read bytes for every
present track. A track that is not ISO is still saved and can be written back;
its decode failure is reported without discarding the raw data. The file also
records the declared physical density, which defaults to the standard Track
1/2/3 values of `210,75,210` BPI. The reader does not auto-detect density. For a
different authorized format, specify all three densities while capturing:

```sh
python msr-cmd.py --output custom.json --bpi 75,75,210
```

Raw replay is format-agnostic: it preserves the captured magnetic bit pattern,
so it can reproduce ISO/ABA data as well as other encodings supported by the
writer's 75/210-BPI hardware. It does not infer the semantic fields of an
unknown format.

The standard MagSpoof firmware plays Tracks 1 and 2. Track 3 is preserved in
both formats, but using it requires selecting Track 3 in the firmware.

Run the protocol and decoder tests without reader hardware:

```sh
python -m unittest discover -s tests -v
```

### Write and verify a test card

Use only blank/erasable cards you own or are authorized to overwrite. Check the
coercivity printed on the card, then write a JSON capture made by `msr-cmd.py`:

```sh
python write-card.py original.json --coercivity high
```

Use `--coercivity low` for LoCo media. For a current JSON capture, `auto` mode
selects raw replay when raw data is present; older logical-only JSON files use
the ISO writer. The first prompted swipe writes the source tracks. After the
writer reports success, swipe the same card a second time for verification.
It reports only
`MATCH`/`DIFFERENT`, never the track contents. Exit code `0` means every track
matched, `1` means the device operation failed or the read-back differed, and
`2` means the command arguments or input capture were invalid.

Select a path explicitly when needed:

```sh
python write-card.py original.json --coercivity high --mode raw
python write-card.py original.json --coercivity high --mode iso
```

ISO mode sends logical characters and lets the writer generate sentinels,
parity, and LRC. Raw mode sets 8-bit passthrough, restores the saved density for
each track, converts the reader's raw byte orientation to the writer's required
orientation, and writes every captured track including Track 3. Raw read-back
is compared after normalizing the supported forward/reverse swipe packings.
Override saved densities with `--bpi 210,75,210` when intentionally targeting a
different format.

The source JSON file is read-only and is not modified. All three tracks are
part of verification: a source track must match, and a source track that is
absent must also be absent on the test card. Start with a blank or fully erased
test card if the capture does not contain all three tracks.

For a reused card, add `--erase-first`. This adds a separate initial swipe that
erases all three tracks before the write and verification swipes:

```sh
python write-card.py original.json --coercivity high --erase-first
```

To erase a card without writing it, select any combination of tracks (all
three are selected by default):

```sh
python erase-card.py --coercivity high
python erase-card.py --coercivity low --tracks 23
```

### Compare an original card with MagSpoof read-back

Capture the physical card and then the Flipper transmission through the same
isolated reader:

```sh
python msr-cmd.py --output original.json
python msr-cmd.py --output replay.json
python compare-captures.py original.json replay.json
```

The comparator reports `MATCH` or `DIFFERENT` for each track, the service-code
metadata, and the overall result. It never prints the track contents. Exit code
`0` means an exact logical match, `1` means a difference, and `2` means an input
file could not be read or validated.

## acknowledgements

camconn for documenting their work on [hidmsr](https://gitlab.com/camconn/hidmsr)  
Their implementation of the protocol in windows allowed me to get better packet captures than I had working with the proprietary software. 


## License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file for details
