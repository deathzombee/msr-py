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

### Record tracks for MagSpoof

Only capture cards you own or are authorized to test. Connect the reader and
run:

```sh
python msr-cmd.py --output card.magspoof.c
```

Swipe once when prompted. The command reassembles multi-report USB messages,
parses each track by its declared byte length, validates character parity and
LRC, and writes a replacement `tracks[]` definition for MagSpoof. Card files
are created with mode `0600`, and existing files are not replaced unless
`--force` is supplied. Keep generated card files out of version control.

For ISO payment tracks, the command also identifies the three-digit service
code on Tracks 1 and 2, reports whether its first digit indicates ICC/EMV, and
warns if the two tracks disagree. This inspection is read-only: captured track
data is never changed.

For a neutral interchange format instead:

```sh
python msr-cmd.py --format json --output card.json
```

The standard MagSpoof firmware plays Tracks 1 and 2. Track 3 is preserved in
both formats, but using it requires selecting Track 3 in the firmware.

Run the protocol and decoder tests without reader hardware:

```sh
python -m unittest discover -s tests -v
```

## acknowledgements

camconn for documenting their work on [hidmsr](https://gitlab.com/camconn/hidmsr)  
Their implementation of the protocol in windows allowed me to get better packet captures than I had working with the proprietary software. 


## License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file for details
