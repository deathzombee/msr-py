# MSR-py

This is a WIP Linux Userspace Driver for MSRx6 magnetic stripe readers/encoders.  
while I am focusing on working with the MSRx6 sold by deftun, the code should work for MSR605,206,and 606 as well.  
I don't have access to the bluetooth module placed in the MSRx6BT, so there is no bluetooth communications support.  

## Why?
There are other python projects that had the same goal, but they are all a few years old and arent being worked on  
My focus is on making readable code. 


## Usage 

clone the repo  
make sure that you have permissions for usb devices. alternatively I suggest adding a udev rule for the device.  
name the file something like 99-msr.rules and place it in /etc/udev/rules.d/
this will give all users read/write access to the device.
```
SUBSYSTEM=="usb", ATTRS{idVendor}=="0801", ATTRS{idProduct}=="0003", MODE="0666"
```

## acknowledgements

camconn for documenting their work on [hidmsr](https://gitlab.com/camconn/hidmsr)  
Their implementation of the protocol in windows allowed me to get better packet captures than I had working with the proprietary software. 


## License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file for details