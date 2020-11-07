
# Packette v1.0
<img src="http://www.phys.hawaii.edu/~kcroker/packette/fp.png" width="50%"/>

_Chaotic good female fire elemental, carries and rips packets from sockets at blazing speed._

## Overview
packette is a highly robust UDP protocol and client suite for extremely rapid data capture and inspection.
The main tools are

* `packette` : L1 cache-optimized multiprocess C program which moves incoming packets 
from sockets to files, in order
* `packette-merge` :  (optional) integrates unordered packets into existing ordered streams
* `packette_stream.py` : provides a list-like API for Python 3 programs by indexing and caching the underlying OS streams.
* `packette_browse.py` : lightweight shell for inspection and visualization of packette data streams

## Packet structure

Coming soon.  For now, look in `packette.h`.

## Usage Examples

The typical usage is to start `packette` and then monitor the data stream.  
`packette` will dump data to a directory `rawdata` in the current working directory and will fail if this directory does not exist.
In its default operation, `packette` uses ncurses to display real-time statistics of packets-per-second (pps)
and bytes-per-second pushed to the OS.  
So, a typical usage is to start `packette` in one terminal window

```bash
   $ ./packette 10.0.6.254 -f testing
```
without any event count limits.  The IP adresss specifies the bind address, and the default port 1338 will be used.  
The flag `-f` sets the data stream prefix for files written into `rawdata`.
Any files that exist are overwritten.
Data, as it arrives, can then be inspected using `packette_browse.py`

```bash
   $ ./packette_browse.py rawdata/testing*
```

`packette_browse.py` implements a shell with TAB autocompletion, online help, and command/history editting.
An example shell command is as follows.
To graph the most recently arrived event's channels 0-31

```
   Event #7 @ 5 (packette) graph 0-31
```

Notice that the prompt gives the current event number and also its position with the stream.
The event number is determined by the data stream and board itself, where as the position within the 
stream is determined by receipt order at the client.
Underlying instructions can be sent to board control software.  
Consider the following 

```
   Event #7 @ 5 (packette) cmd -c 0x00000000000000ff -N 10 -r 500 10.0.6.212
   Event #7 @ 5 (packette) refresh
   Event #17 @ 17 (packette) graph 0-31
```

This example assumes use of packette with the Ultraltyics A2x series boards.  
It does the following:

1. set the channel mask and request 10 soft triggers at 500 Hz from an A2x board at IP 10.0.6.212
2. update the stream index and jump to the most recently received event
3. graph the first 32 channels

The final operation will only reflect the 8 channels of data present.
Individual channel data, including unmasked raw payloads, masks, and stop samples can be viewed with

```
   Event #7 @ 5 (packette) channel 5
```

The following example places an A2x series board into ADC test-pattern mode 'ramp', sends a single soft trigger, and graphs all channels:

```
   Event #7 @ 5 (packette) cmd -c 0xffffffffffffffff -N 1 --adcmode ramp 10.0.6.212
   Event #7 @ 5 (packette) refresh
   Event #8 @ 6 (packette) graph 0-63
```


